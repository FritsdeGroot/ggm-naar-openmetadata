#!/usr/bin/env python3
"""
Extraheert alle JSON-bronbestanden voor de GGM-naar-OpenMetadata-pipeline
direct uit de officiële GGM-repository van Gemeente Delft op GitHub.

Genereert:
    ggm_objecttypen.json          959 objecttypen met naam, definitie, pad, attributen
    ggm_attributen.json           4534 attributen met type, definitie, waardelijst en referenties
    ggm_relaties_per_object.json  425 relaties (uml:Association) per objecttype
    ggm_domeinen_skos.jsonld      SKOS-domeinstructuur (vereist ook mkdocs.yml)

Vereisten:
    pip install requests --break-system-packages

Gebruik:
    # Standaard (laatste bekende stabiele versie)
    python3 extract_ggm.py

    # Specifieke versie-tag uit de GGM-repo
    python3 extract_ggm.py --versie v2.5.1

    # Specifieke branch
    python3 extract_ggm.py --branch master

    # Uitvoermap opgeven
    python3 extract_ggm.py --uitvoer ./data

    # Alleen XMI downloaden, niet opnieuw genereren
    python3 extract_ggm.py --alleen-downloaden
"""

import sys
import os
import json
import html
import re
import argparse
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("Installeer requests: pip install requests --break-system-packages")

try:
    import yaml
except ImportError:
    sys.exit("Installeer pyyaml: pip install pyyaml --break-system-packages")


# ==============================================================================
# GGM-repository configuratie
# ==============================================================================

GGM_REPO_OWNER = "Gemeente-Delft"
GGM_REPO_NAME = "Gemeentelijk-Gegevensmodel"
GGM_DEFAULT_VERSIE = "master"

def xmi_paden_voor_versie(versie):
    """Geeft de te proberen XMI-paden voor een specifieke versie/branch.
    Het GGM slaat XMI-bestanden op in een versie-submap, bijv. v2.5.1/."""
    return [
        f"{versie}/Gemeentelijk Gegevensmodel XMI2.1.xml",   # meest voorkomend
        f"{versie}/Gemeentelijk_Gegevensmodel.xml",           # alternatieve naam
        "Gemeentelijk Gegevensmodel XMI2.1.xml",              # root (oudere versies)
        "model/Gemeentelijk Gegevensmodel XMI2.1.xml",        # model-submap
    ]

GGM_MKDOCS_PAD = "mkdocs.yml"


# ==============================================================================
# Databereiniging (namen van objecttypen en attributen)
# ==============================================================================

REVERSE_CLEAN = {
    "Gezinsmigrant en Overige migrant\n": "Gezinsmigrant en Overige migrant",
    "Periodiek dienst Bijz. bijstand": "Periodiek dienst Bijzondere bijstand",
    "Rijbewijs /Certificaat": "Rijbewijs of Certificaat",
    "Deelplan/Veld": "Deelplan of Veld",
    "Fase/Oplevering": "Fase of Oplevering",
    "Domein/Taakveld": "Domein of Taakveld",
    "OntbindingHuwelijk/geregistreerdPartnerschap": "OntbindingHuwelijk of geregistreerdPartnerschap",
}

# Objecttypen die beginnen met een diagram-prefex (EA-ruis)
DIAGRAM_PREFIX_PATTERN = re.compile(r"^Diagram", re.IGNORECASE)


def clean_naam(naam):
    """Opschonen van objecttype/attribuutnamen uit de XMI."""
    if not naam:
        return None
    naam = naam.strip()
    # Verwijder EA-package-prefix (::)
    if "::" in naam:
        naam = naam.split("::")[-1].strip()
    # Vervang / en . in namen
    naam = naam.replace("/", " of ").replace(".", "")
    naam = " ".join(naam.split())
    return REVERSE_CLEAN.get(naam, naam) or None


def clean_definitie(text):
    """Opschonen van HTML-opmaak in attribuut/objecttype-definities."""
    if not text:
        return None
    t = html.unescape(text)
    t = re.sub(r"</?(ul|ol)[^>]*>", "", t, flags=re.IGNORECASE)
    t = re.sub(r"<li[^>]*>\s*", "\n- ", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*</li>", "\n", t, flags=re.IGNORECASE)
    t = re.sub(r"</?(font|b|i|u)[^>]*>", "", t, flags=re.IGNORECASE)
    t = re.sub(r"<[^>]+>", "", t)
    t = t.replace("\t", "")
    lines = [ln.rstrip() for ln in t.split("\n")]
    out = []
    prev_empty = False
    for ln in lines:
        if ln == "":
            if prev_empty:
                continue
            prev_empty = True
        else:
            prev_empty = False
        out.append(ln)
    return "\n".join(out).strip() or None


def normalize_mult(m):
    """Normaliseer EA-multipliciteit (0..-1 → 0..*  etc.)."""
    if not m:
        return None
    parts = m.strip().split("..")
    if len(parts) != 2:
        return None
    lo, hi = parts
    try:
        lo_i, hi_i = int(lo), int(hi)
    except ValueError:
        return None
    if lo_i < 0 or (hi_i < 0 and hi_i != -1):
        return None
    if lo_i == 0 and hi_i == 0:
        return None
    hi_str = "*" if hi_i == -1 else str(hi_i)
    return f"{lo_i}..{hi_str}"


def slugify(text):
    import re
    text = text.strip().lower()
    for old, new in {"ë":"e","é":"e","è":"e","ï":"i","ü":"u","ç":"c","&":"en"}.items():
        text = text.replace(old, new)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return re.sub(r"-+", "-", text).strip("-")


def build_skos(mkdocs_path):
    """Genereer SKOS-conceptenschema uit de mkdocs.yml-navigatiestructuur."""
    GGM_BASE = "https://www.gemeentelijkgegevensmodel.nl/"
    SCHEME_URI = GGM_BASE + "id/conceptscheme/ggm-domeinen"

    with open(mkdocs_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    def find_domeinen(nav):
        for item in nav:
            if isinstance(item, dict):
                for key, value in item.items():
                    if key.strip().lower() == "beschrijving domeinen":
                        return value
        raise ValueError("Sectie 'Beschrijving Domeinen' niet gevonden in mkdocs.yml nav.")

    def walk(nav_items, parent_id, parent_uri, concepts, top_concepts, level=1):
        for item in nav_items:
            if isinstance(item, str):
                continue
            for label, value in item.items():
                if label.strip().lower() == "inleiding":
                    continue
                slug = slugify(label)
                cid = f"{parent_id}--{slug}" if parent_id else slug
                curi = f"{GGM_BASE}id/concept/{cid}"
                concept = {"@id": curi, "@type": "skos:Concept",
                           "skos:inScheme": {"@id": SCHEME_URI},
                           "skos:prefLabel": {"@value": label, "@language": "nl"},
                           "ggm:niveau": level}
                if parent_uri is None:
                    concept["skos:topConceptOf"] = {"@id": SCHEME_URI}
                    top_concepts.append({"@id": curi})
                else:
                    concept["skos:broader"] = {"@id": parent_uri}
                concepts.append(concept)
                if isinstance(value, list) and any(isinstance(v, dict) for v in value):
                    walk(value, cid, curi, concepts, top_concepts, level + 1)

    concepts, top_concepts = [], []
    walk(find_domeinen(data["nav"]), None, None, concepts, top_concepts)
    return {
        "@context": {"skos": "http://www.w3.org/2004/02/skos/core#",
                     "dct": "http://purl.org/dc/terms/",
                     "ggm": "https://www.gemeentelijkgegevensmodel.nl/id/def/"},
        "@graph": [{"@id": SCHEME_URI, "@type": "skos:ConceptScheme",
                    "skos:hasTopConcept": top_concepts}] + concepts,
    }


# ==============================================================================
# Downloaden uit GitHub
# ==============================================================================

def github_raw_url(owner, repo, ref, path):
    encoded = path.replace(" ", "%20")
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{encoded}"


def download_bestand(url, doel, label=""):
    print(f"  Downloaden {label or doel} ...")
    r = requests.get(url, timeout=120)
    if r.status_code == 404:
        return False
    r.raise_for_status()
    Path(doel).write_bytes(r.content)
    size_kb = len(r.content) // 1024
    print(f"    → {doel} ({size_kb} KB)")
    return True


def download_xmi(ref, uitvoer):
    xmi_pad = uitvoer / "ggm_xmi.xml"
    for pad in xmi_paden_voor_versie(ref):
        url = github_raw_url(GGM_REPO_OWNER, GGM_REPO_NAME, ref, pad)
        if download_bestand(url, xmi_pad, f"GGM XMI-export ({pad})"):
            return xmi_pad
    sys.exit(
        "XMI-bestand niet gevonden in de repository. Controleer de --versie/--branch "
        "of gebruik --xmi om een lokaal bestand op te geven."
    )


def download_mkdocs(ref, uitvoer):
    mkdocs_pad = uitvoer / "ggm_mkdocs.yml"
    url = github_raw_url(GGM_REPO_OWNER, GGM_REPO_NAME, ref, GGM_MKDOCS_PAD)
    if not download_bestand(url, mkdocs_pad, "mkdocs.yml (domeinnavigatie)"):
        print("  WAARSCHUWING: mkdocs.yml niet gevonden — ggm_domeinen_skos.jsonld wordt niet gegenereerd.")
        return None
    return mkdocs_pad


# ==============================================================================
# XMI-extractie helpers
# ==============================================================================

def get_id(elem):
    for k, v in elem.attrib.items():
        if k.endswith("}id") or k == "id":
            return v
    return None


def get_type(elem):
    for k, v in elem.attrib.items():
        if k.endswith("}type") or k == "type":
            return v
    return None


def parse_xmi(xmi_pad):
    """Parse de volledige XMI en retourneer de root."""
    print(f"  Parsen {xmi_pad} ...")
    return ET.parse(xmi_pad).getroot()


# ==============================================================================
# Stap 1: Objecttypen extraheren
# ==============================================================================

def extraheer_objecttypen(root):
    """
    Extraheer alle uml:Class-elementen (objecttypen) uit de XMI,
    inclusief GEMMA-definitie en attribuutlijst (naam + type).
    Filtert ruis (Diagram-packages, null-namen, etc.).
    """
    # GEMMA_definitie per class-id
    class_def = {}
    for elem in root.iter():
        tag = elem.tag.split("}")[-1]
        if tag == "GEMMA_definitie":
            base = elem.get("base_Class")
            d = elem.get("GEMMA_definitie")
            if base and d:
                class_def[base] = d

    objecttypen = []

    def walk(elem, pad):
        tag = elem.tag.split("}")[-1]
        if tag != "packagedElement":
            for child in elem:
                walk(child, pad)
            return
        etype = get_type(elem)
        naam = elem.get("name")
        cls_id = get_id(elem)
        if etype == "uml:Package":
            new_pad = pad + [naam] if naam else pad
            for child in elem:
                walk(child, new_pad)
        elif etype == "uml:Class":
            # Filter ruis
            if not naam:
                return
            if any(DIAGRAM_PREFIX_PATTERN.match(seg) for seg in pad):
                return
            cleaned = clean_naam(naam)
            if not cleaned:
                return
            # Attributen (naam + type uit ownedAttribute)
            attrs = []
            for oa in elem.findall("ownedAttribute"):
                a_naam = clean_naam(oa.get("name"))
                if not a_naam:
                    continue
                # type uit directe ownedAttribute (override van <properties type=...>)
                a_type = None
                t_elem = oa.find("type")
                if t_elem is not None:
                    a_type = t_elem.get("href", "").split("#")[-1] or None
                attrs.append({"naam": a_naam, "type": a_type})
            # Bepaal hoofddomein (eerste segment na 'Delfts Gemeentelijk Gegevensmodel')
            norm_pad = [p for p in pad if p != "Delfts Gemeentelijk Gegevensmodel"]
            domein = norm_pad[0] if norm_pad else "Onbekend"
            # Verwijder domein-nummer-prefix (bijv. "1 Bestuur" → "Bestuur" voor weergave)
            domein_display = re.sub(r"^\d+\s+", "", domein)
            objecttypen.append({
                "naam": cleaned,
                "definitie": clean_definitie(class_def.get(cls_id)),
                "pad": norm_pad,
                "attributen": attrs,
                "domein": domein_display,
            })

    walk(root, [])
    return objecttypen


def deduplicate_objecttypen(objecttypen):
    """
    Verwijder echte duplicaten (zelfde naam+pad) en geef een waarschuwing
    bij naamcollisies (zelfde naam, ander pad).
    """
    seen = {}
    result = []
    for o in objecttypen:
        key = (o["naam"], tuple(o["pad"]))
        if key in seen:
            continue
        seen[key] = True
        result.append(o)

    naam_cnt = Counter(o["naam"].lower() for o in result)
    collisies = [naam for naam, cnt in naam_cnt.items() if cnt > 1]
    if collisies:
        print(f"  WAARSCHUWING: {len(collisies)} naamcollisies gevonden (zelfde naam, ander domein/pad).")
        print("  Voeg een disambiguatie-suffix toe in ggm_naam_disambiguatie.json voor:")
        for naam in collisies[:10]:
            items = [o for o in result if o["naam"].lower() == naam]
            print(f"    '{items[0]['naam']}' ({len(items)}x): " +
                  " | ".join(" > ".join(o["pad"]) for o in items))
        if len(collisies) > 10:
            print(f"    ... en {len(collisies) - 10} meer.")

    return result


# ==============================================================================
# Stap 2: Attributen extraheren (met definitie, waardelijst, objecttype-referentie)
# ==============================================================================

def extraheer_attributen(root, objecttypen):
    """
    Extraheer per objecttype de attributen met definitie (uit <documentation value=...>),
    type (uit <properties type=...>), waardelijst (als type een Enumeration is)
    en objecttype-referentie (als type een bestaand objecttype is).
    """
    # Stap A: attr_id → (doc_value, type_value) uit <attribute> blokken
    attr_doc = {}
    for elem in root.iter():
        tag = elem.tag.split("}")[-1]
        if tag == "attribute":
            attr_id = None
            for k, v in elem.attrib.items():
                if k.endswith("idref"):
                    attr_id = v
            doc = elem.find("documentation")
            doc_val = doc.get("value") if doc is not None else None
            props = elem.find("properties")
            type_val = props.get("type") if props is not None else None
            if attr_id:
                attr_doc[attr_id] = (doc_val, type_val)

    # Stap B: alle Enumerations → naam (lower) → literals
    enums = {}
    for elem in root.iter():
        tag = elem.tag.split("}")[-1]
        if tag == "packagedElement" and get_type(elem) == "uml:Enumeration":
            naam = elem.get("name")
            if naam:
                literals = [c.get("name") for c in elem
                            if c.tag.split("}")[-1] == "ownedLiteral" and c.get("name")]
                enums[naam.lower()] = literals

    # Stap C: objecttype-namen (voor referentie-matching)
    obj_by_lower = defaultdict(list)
    for o in objecttypen:
        obj_by_lower[o["naam"].lower()].append(o)

    # Stap D: per class, attributen koppelen aan attr_doc via ownedAttribute-id
    # Bouw class-id → objecttype-index mapping
    pad_naam_naar_idx = {}
    for i, o in enumerate(objecttypen):
        pad_naam_naar_idx[(o["naam"], tuple(o["pad"]))] = i

    # Walk om per class de ownedAttribute-ids te vinden
    class_attrs_raw = {}  # (naam, norm_pad) → lijst van (attr_naam, attr_id)

    def walk_attrs(elem, pad):
        tag = elem.tag.split("}")[-1]
        if tag != "packagedElement":
            for child in elem:
                walk_attrs(child, pad)
            return
        etype = get_type(elem)
        naam = elem.get("name")
        if etype == "uml:Package":
            new_pad = pad + [naam] if naam else pad
            for child in elem:
                walk_attrs(child, new_pad)
        elif etype == "uml:Class":
            if not naam:
                return
            cleaned = clean_naam(naam)
            if not cleaned:
                return
            norm_pad = tuple(p for p in pad if p != "Delfts Gemeentelijk Gegevensmodel")
            attrs_raw = []
            seen_in_class = set()
            for oa in elem.findall("ownedAttribute"):
                oa_id = get_id(oa)
                a_naam = oa.get("name")
                if not a_naam:
                    continue
                # Dedupliceer association-ends (geen type/doc)
                info = attr_doc.get(oa_id, (None, None))
                dupe_key = a_naam.lower()
                if info == (None, None) and dupe_key in seen_in_class:
                    continue
                seen_in_class.add(dupe_key)
                attrs_raw.append((a_naam, oa_id))
            class_attrs_raw[(cleaned, norm_pad)] = attrs_raw

    walk_attrs(root, [])

    # Stap E: bouw de finale attributen-dataset
    result = []
    for o in objecttypen:
        key = (o["naam"], tuple(o["pad"]))
        attrs_raw = class_attrs_raw.get(key, [])
        attrs = []
        for a_naam, oa_id in attrs_raw:
            cleaned_naam = clean_naam(a_naam)
            if not cleaned_naam:
                continue
            doc_val, type_val = attr_doc.get(oa_id, (None, None))
            definitie = clean_definitie(doc_val)
            waardelijst = None
            verwijst_naar = None
            if type_val:
                if type_val.lower() in enums and enums[type_val.lower()]:
                    waardelijst = enums[type_val.lower()]
                candidates = obj_by_lower.get(type_val.lower(), [])
                if len(candidates) == 1:
                    verwijst_naar = {"naam": candidates[0]["naam"], "pad": candidates[0]["pad"]}
            attr = {"naam": cleaned_naam, "type": type_val, "definitie": definitie}
            if waardelijst:
                attr["waardelijst"] = waardelijst
            if verwijst_naar:
                attr["verwijst_naar_objecttype"] = verwijst_naar
            attrs.append(attr)
        result.append({"naam": o["naam"], "pad": o["pad"], "attributen": attrs})

    total = sum(len(r["attributen"]) for r in result)
    with_def = sum(1 for r in result for a in r["attributen"] if a.get("definitie"))
    with_wl = sum(1 for r in result for a in r["attributen"] if a.get("waardelijst"))
    with_ref = sum(1 for r in result for a in r["attributen"] if a.get("verwijst_naar_objecttype"))
    print(f"    {total} attributen ({with_def} met definitie, {with_wl} met waardelijst, "
          f"{with_ref} met objecttype-referentie)")
    return result


# ==============================================================================
# Stap 3: Relaties extraheren (uml:Association)
# ==============================================================================

def extraheer_relaties(root, objecttypen):
    """
    Extraheer uml:Association-elementen en koppel ze aan bekende objecttypen.
    Retourneert een per-objecttype gegroepeerde lijst van relaties.
    """
    # class-id → (naam, norm_pad)
    class_info = {}

    def walk_classes(elem, pad):
        tag = elem.tag.split("}")[-1]
        if tag != "packagedElement":
            for child in elem:
                walk_classes(child, pad)
            return
        etype = get_type(elem)
        naam = elem.get("name")
        if etype == "uml:Package":
            new_pad = pad + [naam] if naam else pad
            for child in elem:
                walk_classes(child, new_pad)
        elif etype == "uml:Class":
            cls_id = get_id(elem)
            if cls_id and naam:
                cleaned = clean_naam(naam)
                if cleaned:
                    norm_pad = tuple(p for p in pad if p != "Delfts Gemeentelijk Gegevensmodel")
                    class_info[cls_id] = (cleaned, norm_pad)

    walk_classes(root, [])

    # Bouw lookup (naam, pad) → objecttype
    obj_keys = {(o["naam"], tuple(o["pad"])) for o in objecttypen}

    associations = []
    for elem in root.iter():
        tag = elem.tag.split("}")[-1]
        if tag != "packagedElement" or get_type(elem) != "uml:Association":
            continue
        naam = elem.get("name")
        ends = []
        for oe in elem.findall("ownedEnd"):
            t = oe.find("type")
            tid = None
            if t is not None:
                for k, v in t.attrib.items():
                    if k.endswith("idref"):
                        tid = v
            lower = oe.find("lowerValue")
            upper = oe.find("upperValue")
            mult = None
            if lower is not None and upper is not None:
                mult = normalize_mult(f"{lower.get('value')}..{upper.get('value')}")
            ends.append({"class_id": tid, "mult": mult})
        if len(ends) != 2:
            continue
        a_info = class_info.get(ends[0]["class_id"])
        b_info = class_info.get(ends[1]["class_id"])
        if not a_info or not b_info:
            continue
        if a_info not in obj_keys or b_info not in obj_keys:
            continue
        associations.append({
            "naam": naam,
            "a": {"naam": a_info[0], "pad": list(a_info[1]), "mult": ends[0]["mult"]},
            "b": {"naam": b_info[0], "pad": list(b_info[1]), "mult": ends[1]["mult"]},
        })

    # Groepeer per objecttype (beide perspectieven)
    per_object = defaultdict(list)
    for assoc in associations:
        a_key = (assoc["a"]["naam"], tuple(assoc["a"]["pad"]))
        b_key = (assoc["b"]["naam"], tuple(assoc["b"]["pad"]))
        per_object[a_key].append({
            "naam": assoc["naam"],
            "mult": assoc["b"]["mult"],
            "object": {"naam": assoc["b"]["naam"], "pad": assoc["b"]["pad"]},
        })
        if a_key != b_key:
            per_object[b_key].append({
                "naam": assoc["naam"],
                "mult": assoc["a"]["mult"],
                "object": {"naam": assoc["a"]["naam"], "pad": assoc["a"]["pad"]},
            })
        else:
            per_object[a_key].append({
                "naam": assoc["naam"],
                "mult": assoc["a"]["mult"],
                "object": {"naam": assoc["a"]["naam"], "pad": assoc["a"]["pad"]},
            })

    out = [{"naam": naam, "pad": list(pad), "relaties": rel}
           for (naam, pad), rel in per_object.items()]
    total_rel = sum(len(r["relaties"]) for r in out)
    print(f"    {len(associations)} relaties, {len(out)} objecttypen betrokken, "
          f"{total_rel} relatie-regels totaal")
    return out


# ==============================================================================
# Hoofdprogramma
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Extraheert JSON-bronbestanden voor de GGM-naar-OpenMetadata-pipeline "
                    "direct uit de GGM-repository op GitHub."
    )
    parser.add_argument("--versie", default=GGM_DEFAULT_VERSIE,
                        help=f"GGM versie-tag of branch (default: {GGM_DEFAULT_VERSIE})")
    parser.add_argument("--branch", help="Branch-naam (alternatief voor --versie)")
    parser.add_argument("--uitvoer", default=None,
                        help="Uitvoermap voor de gegenereerde bestanden (default: data/<versie>/)")
    parser.add_argument("--alleen-downloaden", action="store_true",
                        help="Alleen de XMI downloaden, geen JSON-bestanden genereren")
    parser.add_argument("--xmi", help="Gebruik een lokaal XMI-bestand i.p.v. te downloaden")
    args = parser.parse_args()

    ref = args.branch or args.versie
    # Standaard uitvoermap: data/<versie>/ zodat bestanden per versie worden bewaard
    uitvoer = Path(args.uitvoer) if args.uitvoer else Path("data") / ref
    uitvoer.mkdir(parents=True, exist_ok=True)

    print(f"\nGGM-extractie — versie/branch: {ref}")
    print(f"Uitvoermap: {uitvoer.resolve()}\n")

    # --- Downloaden ---
    if args.xmi:
        xmi_pad = Path(args.xmi)
        print(f"Lokale XMI: {xmi_pad}")
    else:
        print("Stap 1: Downloaden uit GitHub ...")
        xmi_pad = download_xmi(ref, uitvoer)

    if args.alleen_downloaden:
        print("\nKlaar (alleen-downloaden modus).")
        return

    print(f"\nStap 2: Parsen en extraheren ...")

    # --- SKOS domeinstructuur ---
    print("  Domeinstructuur (SKOS) ...")
    mkdocs_pad = download_mkdocs(ref, uitvoer)
    if mkdocs_pad:
        try:
            skos = build_skos(str(mkdocs_pad))
            skos_pad = uitvoer / "ggm_domeinen_skos.jsonld"
            skos_pad.write_text(json.dumps(skos, ensure_ascii=False, indent=2), encoding="utf-8")
            n_concepts = len([n for n in skos["@graph"] if n.get("@type") == "skos:Concept"])
            print(f"  → {skos_pad} ({n_concepts} concepten)")
        except Exception as e:
            print(f"  WAARSCHUWING: SKOS-generatie mislukt: {e}")
    else:
        print("  SKOS overgeslagen (geen mkdocs.yml).")

    # --- Parsen ---
    root = parse_xmi(xmi_pad)

    # --- Objecttypen ---
    print("  Objecttypen ...")
    objecttypen_raw = extraheer_objecttypen(root)
    objecttypen = deduplicate_objecttypen(objecttypen_raw)
    pad = uitvoer / "ggm_objecttypen.json"
    pad.write_text(json.dumps(objecttypen, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  → {pad} ({len(objecttypen)} objecttypen)")

    # --- Attributen ---
    print("  Attributen ...")
    attributen = extraheer_attributen(root, objecttypen)
    pad = uitvoer / "ggm_attributen.json"
    pad.write_text(json.dumps(attributen, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  → {pad}")

    # --- Relaties ---
    print("  Relaties ...")
    relaties = extraheer_relaties(root, objecttypen)
    pad = uitvoer / "ggm_relaties_per_object.json"
    pad.write_text(json.dumps(relaties, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  → {pad}")

    print("\nKlaar.")
    print("\nVolgende stap: controleer naamcollisies en update ggm_naam_disambiguatie.json")
    print("indien er objecttypen zijn met dezelfde naam in verschillende domeinen,")
    print("daarna: python3 ggm_naar_openmetadata_domains.py")
    print("        python3 ggm_objecttypen_naar_openmetadata.py --alle --met-attributen --met-relaties")


if __name__ == "__main__":
    main()