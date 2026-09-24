#!/usr/bin/env python3
"""
Hulpfuncties voor het uitlezen van Enterprise Architect-metadata uit de GGM-XMI.

De GGM-XMI bevat naast het UML-model (uml:Model) twee plekken met aanvullende
metadata die extract_ggm.py tot en met v1.0.0 niet (volledig) gebruikte:

1. De EA-extensie (<xmi:Extension><elements><element ...>) met per element:
   - <properties documentation="..." stereotype="..."/>  -> definitie, stereotype
   - <project author= version= created= modified=/>     -> herkomst
   - <tags><tag name= value=/></tags>                   -> tagged values
   en per attribuut (<attributes><attribute xmi:idref=...>) dezelfde <tags>.

2. Profieltoepassingen direct onder de root, bijv.
   <thecustomprofile:GEMMA-URL base_Class="EAID_..." GEMMA-URL="https://..."/>
   <MIM:Objecttype base_Class="EAID_..." Toelichting="..."/>

Tagged values komen in het GGM onder meerdere spellingen voor
(`GEMMA url`, `GEMMA-URL`, `GEMMA_url`; `Toelichting`, `toelichting`).
`canonieke_tagnaam` voegt die samen. Bij verschillende, niet-lege waarden voor
dezelfde canonieke naam wint de spelling met een koppelteken (`GEMMA-naam`),
omdat die overeenkomt met wat gemeentelijkgegevensmodel.nl toont. Alle
afwijkingen worden verzameld als conflict, zodat ze teruggemeld kunnen worden
aan het GGM-team.
"""

import hashlib
import json
import re
from collections import defaultdict


# ==============================================================================
# Tagnamen normaliseren
# ==============================================================================

def canonieke_tagnaam(naam):
    """'GEMMA-URL', 'GEMMA_url', 'GEMMA url ' -> 'gemma url'."""
    if not naam:
        return None
    n = naam.strip().lower().replace("-", " ").replace("_", " ")
    return " ".join(n.split()) or None


def _prioriteit(originele_naam):
    """Lagere waarde = hogere prioriteit. Koppelteken-spelling wint."""
    return 0 if "-" in originele_naam else 1


def _local(tag):
    return tag.split("}")[-1]


def _attr(elem, suffix):
    """Haal een attribuut op ongeacht namespace-prefix (xmi:id, xmi:idref, ...)."""
    for k, v in elem.attrib.items():
        if k == suffix or k.endswith("}" + suffix):
            return v
    return None


# ==============================================================================
# Verzamelen
# ==============================================================================

class TagVerzameling:
    """Verzamelt per element-id alle (originele_naam, waarde)-paren en lost ze op
    tot één waarde per canonieke naam."""

    def __init__(self):
        self._raw = defaultdict(lambda: defaultdict(list))  # id -> canon -> [(orig, val)]

    def voeg_toe(self, element_id, originele_naam, waarde):
        if not element_id or not originele_naam:
            return
        if waarde is None:
            return
        waarde = waarde.strip()
        if not waarde:
            return
        canon = canonieke_tagnaam(originele_naam)
        if canon:
            self._raw[element_id][canon].append((originele_naam.strip(), waarde))

    def oplossen(self):
        """Retourneert (waarden, conflicten).
        waarden:    id -> {canon: waarde}
        conflicten: lijst van {element_id, tag, waarden: [{spelling, waarde}], gekozen}
        """
        waarden = {}
        conflicten = []
        for element_id, per_canon in self._raw.items():
            opgelost = {}
            for canon, kandidaten in per_canon.items():
                kandidaten = sorted(kandidaten, key=lambda kv: _prioriteit(kv[0]))
                gekozen = kandidaten[0][1]
                opgelost[canon] = gekozen
                uniek = {v for _, v in kandidaten}
                if len(uniek) > 1:
                    conflicten.append({
                        "element_id": element_id,
                        "tag": canon,
                        "waarden": [{"spelling": o, "waarde": v} for o, v in kandidaten],
                        "gekozen": gekozen,
                    })
            waarden[element_id] = opgelost
        return waarden, conflicten


def verzamel_ea_metadata(root):
    """Lees EA-extensie en profieltoepassingen uit.

    Retourneert een dict met:
      elementen:  id -> {documentatie, stereotype, auteur, ea_versie,
                         aangemaakt, gewijzigd, tags: {canon: waarde}}
                  (classes, packages, enumeraties, ...)
      attributen: id -> {documentatie, stereotype, tags: {canon: waarde}}
      conflicten: lijst van tag-conflicten (zie TagVerzameling.oplossen)
    """
    tags = TagVerzameling()
    elementen = {}
    attributen = {}

    # --- 1. EA-extensie -------------------------------------------------------
    for elem in root.iter():
        if _local(elem.tag) != "element":
            continue
        eid = _attr(elem, "idref")
        if not eid:
            continue
        info = {"naam": elem.get("name"), "ea_type": _attr(elem, "type")}
        props = elem.find("properties")
        if props is not None:
            info["documentatie"] = (props.get("documentation") or "").strip() or None
            info["stereotype"] = props.get("stereotype") or None
        proj = elem.find("project")
        if proj is not None:
            info["auteur"] = proj.get("author") or None
            info["ea_versie"] = proj.get("version") or None
            info["aangemaakt"] = proj.get("created") or None
            info["gewijzigd"] = proj.get("modified") or None
        # Tags van het element zelf (alleen directe <tags>, niet die van attributen)
        t = elem.find("tags")
        if t is not None:
            for tag in t.findall("tag"):
                tags.voeg_toe(eid, tag.get("name"), tag.get("value"))
        elementen[eid] = info

        # Attributen van dit element
        attrs = elem.find("attributes")
        if attrs is not None:
            for a in attrs.findall("attribute"):
                aid = _attr(a, "idref")
                if not aid:
                    continue
                ainfo = {}
                doc = a.find("documentation")
                if doc is not None:
                    ainfo["documentatie"] = (doc.get("value") or "").strip() or None
                st = a.find("stereotype")
                if st is not None:
                    ainfo["stereotype"] = st.get("stereotype") or None
                at = a.find("tags")
                if at is not None:
                    for tag in at.findall("tag"):
                        tags.voeg_toe(aid, tag.get("name"), tag.get("value"))
                attributen[aid] = ainfo

    # --- 2. Profieltoepassingen (base_Class, base_Property, ...) ---------------
    for elem in root:
        if _local(elem.tag) in ("Model", "Extension", "Documentation"):
            continue
        base_id = None
        for k, v in elem.attrib.items():
            if _local(k).startswith("base_"):
                base_id = v
                break
        if not base_id:
            continue
        for k, v in elem.attrib.items():
            lk = _local(k)
            if lk.startswith("base_") or lk.startswith("__EA"):
                continue
            tags.voeg_toe(base_id, lk, v)

    waarden, conflicten = tags.oplossen()
    for eid, tv in waarden.items():
        if eid in elementen:
            elementen[eid]["tags"] = tv
        elif eid in attributen:
            attributen[eid]["tags"] = tv
        else:
            # Profieltoepassing op een element dat niet in de extensie staat
            elementen.setdefault(eid, {})["tags"] = tv
    for d in list(elementen.values()) + list(attributen.values()):
        d.setdefault("tags", {})

    return {"elementen": elementen, "attributen": attributen, "conflicten": conflicten}


# ==============================================================================
# Afgeleide velden
# ==============================================================================

def splits_synoniemen(waarde):
    if not waarde:
        return []
    delen = re.split(r"[;,\n]", waarde)
    return [d.strip() for d in delen if d.strip()]


def gemma_info(tagwaarden):
    """Bundel de GEMMA-tagged values tot één dict (of None als er geen URL is)."""
    url = tagwaarden.get("gemma url")
    info = {
        "url": url,
        "naam": tagwaarden.get("gemma naam"),
        "type": tagwaarden.get("gemma type"),
        "guid": tagwaarden.get("gemma guid"),
    }
    info = {k: v for k, v in info.items() if v}
    return info or None


def inhoud_hash(data):
    """Stabiele, korte hash over een JSON-serialiseerbare structuur.
    Gebruikt om inhoudelijke wijzigingen tussen GGM-releases te detecteren,
    los van EA's eigen version/modified-velden (die bij bulkbewerkingen
    massaal wijzigen, zie CHANGELOG v1.1.0)."""
    s = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def objecttype_hash(obj, attributen):
    """Hash over wat een objecttype inhoudelijk definieert: definitie,
    toelichting en de set attributen (naam + type). De naam zelf telt niet
    mee; hernoemingen worden via de EAID apart gedetecteerd."""
    return inhoud_hash({
        "definitie": obj.get("definitie"),
        "toelichting": obj.get("toelichting"),
        "attributen": sorted((a.get("naam") or "", a.get("type") or "") for a in attributen),
    })


def attribuut_hash(attr):
    return inhoud_hash({
        "type": attr.get("type"),
        "definitie": attr.get("definitie"),
        "toelichting": attr.get("toelichting"),
        "waardelijst": attr.get("waardelijst"),
    })
