#!/usr/bin/env python3
"""
GGM-herkomstmetadata op OpenMetadata GlossaryTerms (sinds v1.1.0).

Verantwoordelijk voor:
  - het (idempotent) aanmaken van de custom properties op het entiteittype
    glossaryTerm (ensure_custom_properties);
  - het gepagineerd ophalen van alle termen van een glossary en het bouwen van
    een index op EAID en op (parent, naam) (TermIndex);
  - het bijwerken van extension, references (GEMMA-link) en synoniemen van één
    term in één JSON Patch (werk_ggm_metadata_bij).

Custom properties (alle op glossaryTerm):
  ggmEaId           EA-GUID uit de GGM-XMI; matchsleutel bij herladen
  ggmRelease        GGM-release waaruit de term het laatst is geladen
  ggmEersteRelease  eerste GGM-release waarin de pipeline deze EAID zag
                    (wordt eenmalig gezet en nooit overschreven)
  ggmInhoudHash     hash over de GGM-inhoud (definitie, toelichting, attributen);
                    wijzigt alleen bij inhoudelijke wijziging in het GGM
  ggmToelichting    toelichting uit het GGM (markdown)
  ggmAuteur         auteur volgens EA (informatief)
  gemmaType         type van het gekoppelde GEMMA-object (bijv. business-object)

De velden van EA zelf (version, modified) worden bewust NIET overgenomen: in
GGM 2.5.0 zijn die voor vrijwel alle objecttypen tegelijk gewijzigd door een
bulkbewerking, waardoor ze geen betrouwbaar wijzigingssignaal zijn.
"""

import json
import time

CUSTOM_PROPERTIES = [
    ("ggmEaId", "string",
     "Enterprise Architect-GUID van dit element in de GGM-XMI. Blijft gelijk bij "
     "hernoemen en is de matchsleutel bij het herladen van nieuwe GGM-versies."),
    ("ggmRelease", "string",
     "GGM-release waaruit deze term het laatst is geladen (bijv. v2.5.1)."),
    ("ggmEersteRelease", "string",
     "Eerste GGM-release waarin de pipeline dit element (op EAID) zag. Wordt "
     "eenmalig gezet. Bij migratie van v1.0.0-termen is dit de migratierelease."),
    ("ggmInhoudHash", "string",
     "Hash over de GGM-inhoud van dit element (definitie, toelichting, "
     "attributen/type/waardelijst). Wijzigt alleen bij een inhoudelijke wijziging "
     "in het GGM en is het signaal om classificaties opnieuw te beoordelen."),
    ("ggmToelichting", "markdown",
     "Toelichting uit het GGM (tagged value 'Toelichting')."),
    ("ggmAuteur", "string",
     "Auteur van het element volgens Enterprise Architect (informatief)."),
    ("gemmaType", "string",
     "Type van het gekoppelde GEMMA-object (bijv. business-object)."),
]

GGM_EXTENSION_KEYS = [naam for naam, _, _ in CUSTOM_PROPERTIES]
GEMMA_REFERENCE_PREFIX = "GEMMA: "

TERM_FIELDS = "parent,extension,references,synonyms,relatedTerms,domains,tags"


# ==============================================================================
# Custom properties
# ==============================================================================

def ensure_custom_properties(session):
    """Maak ontbrekende custom properties aan op glossaryTerm. Idempotent.
    Vereist rechten op het 'type'-resource (Create/EditAll)."""
    base = session.base_url
    resp = session.get(f"{base}/api/v1/metadata/types/name/glossaryTerm",
                       params={"fields": "customProperties"})
    resp.raise_for_status()
    term_type = resp.json()
    bestaand = {cp["name"] for cp in (term_type.get("customProperties") or [])}

    resp = session.get(f"{base}/api/v1/metadata/types",
                       params={"category": "field", "limit": 100})
    resp.raise_for_status()
    veldtypen = {t["name"]: t["id"] for t in resp.json().get("data", [])}

    aangemaakt = []
    for naam, veldtype, omschrijving in CUSTOM_PROPERTIES:
        if naam in bestaand:
            continue
        if veldtype not in veldtypen:
            raise RuntimeError(f"Veldtype '{veldtype}' niet gevonden in OpenMetadata "
                               f"(beschikbaar: {sorted(veldtypen)})")
        payload = {
            "name": naam,
            "description": omschrijving,
            "propertyType": {"id": veldtypen[veldtype], "type": "type"},
        }
        r = session.put(f"{base}/api/v1/metadata/types/{term_type['id']}", json=payload)
        if not r.ok:
            raise RuntimeError(f"Aanmaken custom property '{naam}' mislukt: "
                               f"{r.status_code} {r.text}")
        aangemaakt.append(naam)
    return aangemaakt


# ==============================================================================
# Termen ophalen en indexeren
# ==============================================================================

def haal_alle_termen(session, glossary_id, fields=TERM_FIELDS, toon_voortgang=True, paginagrootte=500):
    """Haal ALLE termen van een glossary op, gepagineerd (v1.0.0 haalde er
    maximaal 1000 op, terwijl GGM_Objecttypen er ruim 5.000 bevat).
    Toont per pagina hoeveel termen al binnen zijn en hoe lang dat duurde."""
    termen = []
    after = None
    while True:
        params = {"glossary": glossary_id, "limit": paginagrootte, "fields": fields}
        if after:
            params["after"] = after
        t = time.monotonic()
        resp = session.get(f"{session.base_url}/api/v1/glossaryTerms", params=params)
        resp.raise_for_status()
        body = resp.json()
        termen.extend(body.get("data", []))
        paging = body.get("paging") or {}
        after = paging.get("after")
        if toon_voortgang:
            totaal = paging.get("total")
            print(f"  … {len(termen)}" + (f"/{totaal}" if totaal else "")
                  + f" termen opgehaald ({time.monotonic() - t:.1f}s voor deze pagina)")
        if not after:
            break
    return termen


def _parent_naam(term):
    p = term.get("parent")
    return p.get("name") if p else None


class TermIndex:
    """Index op bestaande termen: op ggmEaId en op (parentnaam, naam)."""

    def __init__(self, termen):
        self.op_eaid = {}
        self.op_naam = {}
        self.dubbele_eaid = []
        for t in termen:
            self.voeg_toe(t)

    def voeg_toe(self, term):
        eaid = (term.get("extension") or {}).get("ggmEaId")
        if eaid:
            if eaid in self.op_eaid and self.op_eaid[eaid]["id"] != term["id"]:
                self.dubbele_eaid.append((eaid, self.op_eaid[eaid]["fullyQualifiedName"],
                                          term["fullyQualifiedName"]))
            self.op_eaid[eaid] = term
        self.op_naam[(_parent_naam(term), term["name"])] = term

    def verwijder(self, term):
        eaid = (term.get("extension") or {}).get("ggmEaId")
        if eaid and self.op_eaid.get(eaid, {}).get("id") == term["id"]:
            del self.op_eaid[eaid]
        key = (_parent_naam(term), term["name"])
        if self.op_naam.get(key, {}).get("id") == term["id"]:
            del self.op_naam[key]

    def zoek(self, ea_id, parent_naam, naam):
        """Retourneert (term, hoe): hoe = 'eaid' | 'naam' | None.
        Een naam-match op een term die al een ANDERE EAID draagt telt niet:
        dan is de naam hergebruikt door een ander GGM-element."""
        if ea_id and ea_id in self.op_eaid:
            return self.op_eaid[ea_id], "eaid"
        term = self.op_naam.get((parent_naam, naam))
        if term is not None:
            bestaande = (term.get("extension") or {}).get("ggmEaId")
            if ea_id and bestaande and bestaande != ea_id:
                return None, "conflict"
            return term, "naam"
        return None, None


# ==============================================================================
# Patchen
# ==============================================================================

def _patch(session, term_id, ops):
    return session.patch(
        f"{session.base_url}/api/v1/glossaryTerms/{term_id}",
        data=json.dumps(ops),
        headers={"Content-Type": "application/json-patch+json"},
    )


def hernoem_term(session, term, nieuwe_naam):
    """Hernoem een term (name + displayName). Retourneert de bijgewerkte term of
    raise bij fout."""
    ops = [
        {"op": "replace", "path": "/name", "value": nieuwe_naam},
        {"op": "replace", "path": "/displayName", "value": nieuwe_naam},
    ]
    r = _patch(session, term["id"], ops)
    if not r.ok:
        raise RuntimeError(f"{r.status_code}: {r.text}")
    nieuw = r.json()
    # PATCH-respons bevat niet altijd alle velden; neem ze over van het origineel
    for k in ("extension", "references", "synonyms", "relatedTerms", "domains", "tags", "parent"):
        nieuw.setdefault(k, term.get(k))
    return nieuw


def gewenste_extensie(item, release, bestaande_ext):
    """Bepaal de gewenste waarden van de GGM-custom-properties voor één
    objecttype of attribuut (zoals in ggm_objecttypen.json / ggm_attributen.json)."""
    bestaande_ext = bestaande_ext or {}
    ea = item.get("ea") or {}
    gemma = item.get("gemma") or {}
    return {
        "ggmEaId": item.get("ea_id"),
        "ggmRelease": release,
        "ggmEersteRelease": bestaande_ext.get("ggmEersteRelease") or release,
        "ggmInhoudHash": item.get("inhoud_hash"),
        "ggmToelichting": item.get("toelichting"),
        "ggmAuteur": ea.get("auteur"),
        "gemmaType": gemma.get("type"),
    }


def werk_ggm_metadata_bij(session, term, item, release):
    """Werk extension, GEMMA-reference en synoniemen van één term bij.

    Retourneert (status_suffix, bijgewerkte_term, inhoud_gewijzigd):
      inhoud_gewijzigd is True als er al een ggmInhoudHash stond die afwijkt
      van de nieuwe (d.w.z. het GGM-element is inhoudelijk gewijzigd).
    """
    ops = []
    ext = term.get("extension") or {}
    gewenst = gewenste_extensie(item, release, ext)

    oude_hash = ext.get("ggmInhoudHash")
    inhoud_gewijzigd = bool(oude_hash and gewenst["ggmInhoudHash"]
                            and oude_hash != gewenst["ggmInhoudHash"])

    # --- extension (alleen onze eigen sleutels aanraken) ---
    if not ext:
        waarden = {k: v for k, v in gewenst.items() if v}
        if waarden:
            ops.append({"op": "add", "path": "/extension", "value": waarden})
    else:
        for k, v in gewenst.items():
            if v and ext.get(k) != v:
                ops.append({"op": "add", "path": f"/extension/{k}", "value": v})
            elif not v and k in ext and k in GGM_EXTENSION_KEYS and k != "ggmEersteRelease":
                ops.append({"op": "remove", "path": f"/extension/{k}"})

    # --- GEMMA-reference ---
    gemma = item.get("gemma") or {}
    url = gemma.get("url")
    refs = list(term.get("references") or [])
    eigen = [r for r in refs if (r.get("name") or "").startswith(GEMMA_REFERENCE_PREFIX)]
    overig = [r for r in refs if r not in eigen]
    gewenste_refs = overig[:]
    if url:
        gewenste_refs.append({
            "name": f"{GEMMA_REFERENCE_PREFIX}{gemma.get('naam') or gemma.get('type') or 'bedrijfsobject'}",
            "endpoint": url,
        })
    if [(r.get("name"), r.get("endpoint")) for r in gewenste_refs] != \
       [(r.get("name"), r.get("endpoint")) for r in refs]:
        ops.append({"op": "add", "path": "/references", "value": gewenste_refs})

    # --- synoniemen (alleen toevoegen; handmatig toegevoegde blijven staan) ---
    huidig = list(term.get("synonyms") or [])
    nieuw = [s for s in (item.get("synoniemen") or []) if s not in huidig]
    if nieuw:
        ops.append({"op": "add", "path": "/synonyms", "value": huidig + nieuw})

    if not ops:
        return "", term, inhoud_gewijzigd

    r = _patch(session, term["id"], ops)
    if not r.ok:
        return f" + FOUT bij GGM-metadata {r.status_code}: {r.text}", term, inhoud_gewijzigd
    bijgewerkt = r.json()
    bijgewerkt.setdefault("parent", term.get("parent"))
    for k in ("relatedTerms", "domains", "tags"):
        bijgewerkt.setdefault(k, term.get(k))
    delen = []
    if any(o["path"].startswith("/extension") for o in ops):
        delen.append("herkomst")
    if any(o["path"] == "/references" for o in ops):
        delen.append("GEMMA-link")
    if any(o["path"] == "/synonyms" for o in ops):
        delen.append("synoniemen")
    suffix = " + " + ", ".join(delen) + " bijgewerkt"
    if inhoud_gewijzigd:
        suffix += " [INHOUD GEWIJZIGD in GGM]"
    return suffix, bijgewerkt, inhoud_gewijzigd
