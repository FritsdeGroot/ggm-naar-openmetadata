#!/usr/bin/env python3
"""
Laadt GGM-objecttypen (uit ggm_objecttypen.json) als OpenMetadata GlossaryTerms,
gekoppeld aan het bijbehorende Domain. Gefaseerd per domein draaibaar.

Vereisten:
    pip install requests --break-system-packages

Configuratie via omgevingsvariabelen:
    OM_HOST       - basis-URL van je OpenMetadata-instantie
    OM_JWT_TOKEN  - JWT-token van een bot/service-account met rechten op
                    Glossary, GlossaryTerm en Domain (Create/EditAll/ViewAll)

Gebruik:
    # Lijst van beschikbare domeinen tonen
    python3 ggm_objecttypen_naar_openmetadata.py --list

    # Eén domein laden
    python3 ggm_objecttypen_naar_openmetadata.py --domein "Sociaal domein"

    # Alle domeinen laden (gefaseerd, alle in een keer)
    python3 ggm_objecttypen_naar_openmetadata.py --alle

Het Domain-FQN waaraan gekoppeld wordt, moet overeenkomen met de
hoofddomeinen die al eerder via ggm_naar_openmetadata_domains.py zijn
aangemaakt (zie DOMAIN_FQN_OVERRIDES hieronder voor naamcorrecties).
"""

import sys
import os
import json
import argparse
from datetime import datetime
import requests

from om_ggm_metadata import (
    ensure_custom_properties, haal_alle_termen, TermIndex,
    hernoem_term, werk_ggm_metadata_bij, TERM_FIELDS,
)


GLOSSARY_NAME = "GGM_Objecttypen"
GLOSSARY_DISPLAY_NAME = "GGM Objecttypen"
GLOSSARY_DESCRIPTION = (
    "Objecttypen (entiteiten) uit het Gemeentelijk Gegevensmodel (GGM), "
    "met hun definitie en attributen. Bron: "
    "https://github.com/Gemeente-Delft/Gemeentelijk-Gegevensmodel"
)

CLASSIFICATION_NAME = "GGM_Hoofddomein"
CLASSIFICATION_DISPLAY_NAME = "GGM Hoofddomein"
CLASSIFICATION_DESCRIPTION = (
    "Classificatie naar het GGM-hoofdbeleidsdomein (IV3-niveau), "
    "ter aanvulling op de fijnmazigere Domain-koppeling per (sub)domein."
)

# Extra hernoemingen voor termen die in een eerdere run al een gedisambigueerde
# naam kregen, maar waarvan die suffix in een latere versie van
# ggm_naam_disambiguatie.json is gewijzigd (bv. doordat een collisiegroep
# is uitgebreid). Format: oude_naam_in_openmetadata -> nieuwe_naam.
EXTRA_RENAMES = {
    "Aanvraag (Erfgoed)": "Aanvraag (Erfgoed - Archief)",
}

# Termen die als relict van een eerdere disambiguatie-/opschoonronde zijn
# blijven hangen en niet meer overeenkomen met enige huidige naam
# (de juiste opvolger bestaat al onder een andere naam, dus hernoemen
# zou een naamcollisie geven). Worden bij de correctie-pass verwijderd.
OBSOLETE_TERMS = [
    "Aanvraag (Inkomen)",  # voorganger van 'Aanvraag (Inkomen - Diensten)' /
                            # 'Aanvraag (Inkomen - Reden aanvraag)', beide al aanwezig
    # Oude namen met '/' of '.' -- de schone opvolgers ("... of ...") zijn al
    # apart aangemaakt, dus deze oude duplicaten zijn overtollig.
    "Deelplan/Veld",
    "Domein/Taakveld",
    "Fase/Oplevering",
    "OntbindingHuwelijk/geregistreerdPartnerschap",
    "Periodiek dienst Bijz. bijstand",
    "Rijbewijs /Certificaat",
    # Oude namen MET trailing spatie (vóór whitespace-opschoning aangemaakt).
    # De gestripte versie zonder spatie is later apart aangemaakt en is de
    # correcte/huidige naam; deze met-spatie-varianten zijn overtollig.
    "Aandachtspunt ",
    "CMDB-item ",
    "Historisch Persoon ",
    "Ontwikkelwens ",
    "Reiskosten naar het werk ",
    "VoorlopigeVoorziening ",
    # Diagram-artefacten uit een oudere extractie (v1.0.0-bronbestand met 959
    # objecttypen): legenda-placeholders uit 'Diagram RSGB > Tekenwijze' en
    # hulpvlakken uit 'Diagrammen intern gebruik'. Geen echte objecttypen,
    # geen attributen; extract_ggm.py filtert ze al uit (Diagram-packages).
    "ObjecttypeA", "ObjecttypeB", "ObjecttypeC", "ObjecttypeD",
    "ObjecttypeE", "ObjecttypeF", "ObjecttypeG",
    "DetailleringAdressenGebouwenEnTerreinen", "DetailleringKadastraleOnroerendZaken",
    "DetailleringSubjecten", "DetailleringWOZObjecttypen", "OverigImgeo",
    # NB: "Fractie" en "Rol" stonden hier tot en met v1.0.0 als "losse termen uit
    # een testrun", maar het zijn bestaande GGM-objecttypen (Afval resp. HR).
    # Ze zijn verwijderd uit deze lijst; zie ook de beveiliging in main().
]

# Als de domeinnaam in ggm_objecttypen.json niet exact overeenkomt met de
# Domain-FQN zoals eerder aangemaakt via ggm_naar_openmetadata_domains.py,
# kan hier een mapping worden opgegeven. Standaard wordt de naam 1-op-1
# gebruikt als FQN.
DOMAIN_FQN_OVERRIDES = {
    # "Sociaal domein": "Sociaal domein",
}

MAX_ATTRS_IN_DESCRIPTION = 30  # voorkom extreem lange beschrijvingen


def load_path_mapping(path):
    with open(path, "r", encoding="utf-8") as f:
        mapping = json.load(f)
    mapping.pop("_comment", None)
    return mapping


def load_disambiguation_map(path):
    """Laad de naam-disambiguatiemapping. Keys zijn JSON-strings van
    [oorspronkelijke_naam, padlijst]; values zijn de gedisambigueerde naam."""
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    result = {}
    for key, new_name in raw.items():
        orig_name, pad = json.loads(key)
        result[(orig_name, tuple(pad))] = new_name
    return result


def resolve_term_name(objecttype, disambiguation_map):
    key = (objecttype["naam"], tuple(objecttype["pad"]))
    return disambiguation_map.get(key, objecttype["naam"])


def path_key(pad):
    """Reduceer een XMI-packagepad tot maximaal 3 betekenisvolle segmenten
    (zonder 'Model ...' en 'Diagram')."""
    segs = [p for p in pad if not p.startswith("Model") and p != "Diagram"]
    return segs[:3]


def resolve_subdomain_fqn(pad, path_mapping):
    """Zoek de laagste matchende Domain-FQN voor dit objecttype-pad
    via langste-prefix-matching in path_mapping."""
    segs = path_key(pad)
    for i in range(len(segs), 0, -1):
        candidate = " > ".join(segs[:i])
        if candidate in path_mapping:
            return path_mapping[candidate]
    return None


def get_session():
    host = os.environ.get("OM_HOST")
    token = os.environ.get("OM_JWT_TOKEN")
    if not host or not token:
        sys.exit("Stel OM_HOST en OM_JWT_TOKEN als omgevingsvariabelen in.")

    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    })
    session.base_url = host.rstrip("/")
    return session


def build_relations_text(relaties, disambiguation_map):
    """Bouw de '**Relaties:**'-sectie voor de beschrijving van een objecttype,
    op basis van de uml:Association-data uit de XMI (ggm_relaties_per_object.json)."""
    if not relaties:
        return None
    lines = []
    for r in relaties:
        rel_naam = r["naam"] or "heeft relatie met"
        mult = r.get("mult")
        target_name = resolve_term_name(r["object"], disambiguation_map)
        if mult:
            lines.append(f"- {rel_naam} ({mult}) {target_name}")
        else:
            lines.append(f"- {rel_naam} {target_name}")
    return "**Relaties:**\n" + "\n".join(lines)


def load_relaties(path):
    """Laad ggm_relaties_per_object.json: per objecttype een lijst relaties
    (naam, multipliciteit, doel-objecttype), afgeleid uit uml:Association in de XMI."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    by_key = {}
    for r in data:
        by_key[(r["naam"], tuple(r["pad"]))] = r["relaties"]
    return by_key


def build_description(objecttype, relaties=None, disambiguation_map=None):
    """Bouw de glossary-term-beschrijving: definitie + attributenlijst + relaties."""
    desc = objecttype["definitie"] or objecttype["naam"]

    attrs = [a for a in objecttype["attributen"] if a["naam"]]
    if attrs:
        lines = []
        for a in attrs[:MAX_ATTRS_IN_DESCRIPTION]:
            type_str = f": {a['type']}" if a["type"] else ""
            lines.append(f"- {a['naam']}{type_str}")
        if len(attrs) > MAX_ATTRS_IN_DESCRIPTION:
            lines.append(f"- ... en {len(attrs) - MAX_ATTRS_IN_DESCRIPTION} meer")
        desc += "\n\n**Attributen:**\n" + "\n".join(lines)

    if relaties:
        relations_text = build_relations_text(relaties, disambiguation_map or {})
        if relations_text:
            desc += "\n\n" + relations_text

    return desc


def get_or_create_glossary(session):
    url = f"{session.base_url}/api/v1/glossaries/name/{GLOSSARY_NAME}"
    resp = session.get(url)
    if resp.status_code == 200:
        return resp.json()

    payload = {
        "name": GLOSSARY_NAME,
        "displayName": GLOSSARY_DISPLAY_NAME,
        "description": GLOSSARY_DESCRIPTION,
    }
    url = f"{session.base_url}/api/v1/glossaries"
    resp = session.post(url, json=payload)
    resp.raise_for_status()
    print(f"Glossary '{GLOSSARY_NAME}' aangemaakt.")
    return resp.json()


def get_or_create_classification(session):
    url = f"{session.base_url}/api/v1/classifications/name/{CLASSIFICATION_NAME}"
    resp = session.get(url)
    if resp.status_code == 200:
        return resp.json()

    payload = {
        "name": CLASSIFICATION_NAME,
        "displayName": CLASSIFICATION_DISPLAY_NAME,
        "description": CLASSIFICATION_DESCRIPTION,
    }
    url = f"{session.base_url}/api/v1/classifications"
    resp = session.post(url, json=payload)
    resp.raise_for_status()
    print(f"Classification '{CLASSIFICATION_NAME}' aangemaakt.")
    return resp.json()


def get_or_create_tag(session, classification_name, tag_name, description=None):
    tag_fqn = f"{classification_name}.{tag_name}"
    url = f"{session.base_url}/api/v1/tags/name/{tag_fqn}"
    resp = session.get(url)
    if resp.status_code == 200:
        return tag_fqn

    payload = {
        "name": tag_name,
        "displayName": tag_name,
        "description": description or tag_name,
        "classification": classification_name,
    }
    url = f"{session.base_url}/api/v1/tags"
    resp = session.post(url, json=payload)
    resp.raise_for_status()
    return tag_fqn


def ensure_hoofddomein_tags(session, hoofddomeinen):
    """Maak de classification en alle benodigde hoofddomein-tags vast aan."""
    get_or_create_classification(session)
    tag_fqns = {}
    for naam in hoofddomeinen:
        tag_fqns[naam] = get_or_create_tag(
            session, CLASSIFICATION_NAME, naam,
            description=f"Objecttypen die behoren tot het GGM-hoofddomein '{naam}'.",
        )
    return tag_fqns


def build_attribute_description(attr):
    """Bouw de beschrijving voor een attribuut-child-term: type + definitie + waardelijst."""
    parts = []
    if attr.get("type"):
        parts.append(f"**Type:** {attr['type']}")
    if attr.get("definitie"):
        parts.append(attr["definitie"])
    waardelijst = attr.get("waardelijst")
    if waardelijst:
        lines = ["**Toegestane waarden:**"] + [f"- {w}" for w in waardelijst]
        parts.append("\n".join(lines))
    return "\n\n".join(parts) if parts else (attr["naam"])


def resolve_related_term_fqn(glossary_fqn, attr, disambiguation_map):
    """Bepaal de FQN van het objecttype waarnaar dit attribuut verwijst (indien aanwezig),
    rekening houdend met eventuele naamdisambiguatie."""
    ref = attr.get("verwijst_naar_objecttype")
    if not ref:
        return None
    key = (ref["naam"], tuple(ref["pad"]))
    resolved_name = disambiguation_map.get(key, ref["naam"])
    return f"{glossary_fqn}.{resolved_name}"


def clean_attribute_name(name):
    """Defensieve opschoning van attribuutnamen: '/' en '.' conflicteren met
    FQN-scheidingstekens in OpenMetadata (zie bekende foutpatronen objecttypen)."""
    cleaned = name.replace("/", " of ").replace(".", "")
    cleaned = " ".join(cleaned.split())  # whitespace normaliseren
    return cleaned


def update_description_if_changed(session, term, new_description):
    """Patch /description als deze afwijkt van de huidige waarde.
    Retourneert een statussuffix (leeg, ' + omschrijving bijgewerkt', of foutmelding)."""
    current = term.get("description")
    if current == new_description:
        return ""

    patch = [{
        "op": "replace" if current is not None else "add",
        "path": "/description",
        "value": new_description,
    }]
    patch_url = f"{session.base_url}/api/v1/glossaryTerms/{term['id']}"
    patch_resp = session.patch(
        patch_url, data=json.dumps(patch),
        headers={"Content-Type": "application/json-patch+json"},
    )
    if patch_resp.ok:
        return " + omschrijving bijgewerkt"
    return f" + FOUT bij omschrijving-update {patch_resp.status_code}: {patch_resp.text}"


def zoek_bestaande_term(session, index, ggm_item, parent_naam, gewenste_naam, own_fqn, rapport,
                        verwachte_parent_id=None):
    """Zoek een bestaande term: eerst op EAID (ggmEaId), dan op naam.

    Wordt de term op EAID gevonden onder een andere naam, dan is het element in
    het GGM hernoemd en wordt de term hernoemd (met behoud van tags, eigen
    aanpassingen en classificaties). Retourneert (term | None, statussuffix).
    Zonder index (bijv. oude bronbestanden zonder ea_id) valt de functie terug
    op het v1.0.0-gedrag: een GET op FQN."""
    if index is None:
        resp = session.get(f"{session.base_url}/api/v1/glossaryTerms/name/{own_fqn}",
                           params={"fields": TERM_FIELDS})
        return (resp.json(), "") if resp.status_code == 200 else (None, "")

    ea_id = (ggm_item or {}).get("ea_id")
    term, hoe = index.zoek(ea_id, parent_naam, gewenste_naam)

    if hoe == "conflict":
        bestaand = index.op_naam.get((parent_naam, gewenste_naam))
        melding = {
            "fqn": own_fqn, "ea_id_ggm": ea_id,
            "ea_id_in_openmetadata": (bestaand.get("extension") or {}).get("ggmEaId"),
        }
        if rapport is not None:
            rapport["eaid_conflicten"].append(melding)
        return None, (f"FOUT: naam al in gebruik door ander GGM-element "
                      f"({melding['ea_id_in_openmetadata']}); handmatig beoordelen")

    if term is None:
        return None, ""

    if hoe == "eaid" and verwachte_parent_id:
        huidige_parent = (term.get("parent") or {}).get("id")
        if huidige_parent and huidige_parent != verwachte_parent_id:
            if rapport is not None:
                rapport["verplaatst"].append({"ea_id": ea_id, "fqn_openmetadata": term.get("fullyQualifiedName"),
                                              "verwacht_fqn": own_fqn})
            return None, ("FOUT: attribuut is in het GGM naar een ander objecttype verplaatst; "
                          "handmatig beoordelen (zie runrapport)")

    suffix = ""
    if hoe == "eaid" and term["name"] != gewenste_naam:
        oude_naam = term["name"]
        index.verwijder(term)
        try:
            term = hernoem_term(session, term, gewenste_naam)
        except RuntimeError as e:
            index.voeg_toe(term)
            return None, f"FOUT bij hernoemen (EAID) '{oude_naam}' -> '{gewenste_naam}': {e}"
        index.voeg_toe(term)
        if rapport is not None:
            rapport["hernoemd_via_eaid"].append({"ea_id": ea_id, "van": oude_naam, "naar": gewenste_naam})
        suffix = f" + hernoemd via EAID (was '{oude_naam}')"
    elif hoe == "naam" and ea_id and not (term.get("extension") or {}).get("ggmEaId"):
        suffix = " + EAID gekoppeld"
    return term, suffix


def pas_ggm_metadata_toe(session, term, ggm_item, index, release, rapport, own_fqn, status):
    """Zet ggmEaId/ggmRelease/ggmInhoudHash/... , GEMMA-link en synoniemen."""
    if not ggm_item or (not ggm_item.get("ea_id") and not ggm_item.get("inhoud_hash")):
        return status, term
    suffix, term, gewijzigd = werk_ggm_metadata_bij(session, term, ggm_item, release)
    if index is not None:
        index.voeg_toe(term)
    if rapport is not None:
        if ggm_item.get("ea_id"):
            rapport["_geziene_eaids"].add(ggm_item["ea_id"])
        if gewijzigd:
            rapport["inhoud_gewijzigd"].append({"ea_id": ggm_item.get("ea_id"), "fqn": own_fqn})
    return status + suffix, term


def get_or_create_attribute_term(session, glossary_fqn, parent_fqn, parent_display_name, attr_name, description, related_term_fqn=None, forceer_omschrijving=False,
                                 ggm_item=None, index=None, release=None, rapport=None, parent_id=None):
    """Maak (of vind) een attribuut als child glossary term onder een objecttype-term.

    De OpenMetadata-naam-validatie voor GlossaryTerm.name is glossary-breed (niet per FQN),
    waardoor generieke attribuutnamen als 'naam', 'titel', 'code' globaal botsen zodra ze
    bij meerdere objecttypen voorkomen. Conform de OpenMetadata best practice voor
    contextrijke termnamen (bv. 'User Phone Number' vs. 'Business Phone Number') wordt de
    term-naam daarom '<Objecttype> <Attribuut>' (bv. 'Raadslid naam'), wat zowel uniek is
    als de PII-relevante context meegeeft. FQN blijft GGM_Objecttypen.<Objecttype>.<naam>."""
    attr_name = clean_attribute_name(attr_name)
    combined_name = f"{parent_display_name} {attr_name}"
    own_fqn = f"{parent_fqn}.{combined_name}"

    term, status = zoek_bestaande_term(
        session, index, ggm_item, parent_display_name, combined_name, own_fqn, rapport,
        verwachte_parent_id=parent_id,
    )
    if status and status.startswith("FOUT"):
        return own_fqn, status
    if term is not None:
        status = "bestaat al" + (status or "")
        if forceer_omschrijving:
            status += update_description_if_changed(session, term, description)
    else:
        payload = {
            "name": combined_name,
            "displayName": combined_name,
            "description": description,
            "glossary": glossary_fqn,
            "parent": parent_fqn,
        }
        url = f"{session.base_url}/api/v1/glossaryTerms"
        resp = session.post(url, json=payload)
        if not resp.ok:
            return own_fqn, f"FOUT bij aanmaken {resp.status_code}: {resp.text}"
        term = resp.json()
        status = "aangemaakt"

    status, term = pas_ggm_metadata_toe(session, term, ggm_item, index, release, rapport, own_fqn, status)

    if related_term_fqn:
        related = term.get("relatedTerms") or []
        related_fqns = {
            r.get("fullyQualifiedName") or r.get("term", {}).get("fullyQualifiedName")
            for r in related
        }
        if related_term_fqn not in related_fqns:
            check = session.get(f"{session.base_url}/api/v1/glossaryTerms/name/{related_term_fqn}")
            if check.status_code == 200:
                target_id = check.json().get("id")
                related_ref = {"relationType": "relatedTo", "term": {"id": target_id, "type": "glossaryTerm"}}
                patch = [{
                    "op": "add" if not related else "replace",
                    "path": "/relatedTerms",
                    "value": related + [related_ref],
                }]
                patch_url = f"{session.base_url}/api/v1/glossaryTerms/{term['id']}"
                patch_resp = session.patch(
                    patch_url, data=json.dumps(patch),
                    headers={"Content-Type": "application/json-patch+json"},
                )
                if patch_resp.ok:
                    status += " + relatedTerm gekoppeld"
                else:
                    status += f" + FOUT bij relatedTerm {patch_resp.status_code}: {patch_resp.text}"

    return own_fqn, status


def load_attributen(path):
    """Laad ggm_attributen.json: lijst van {naam, pad, attributen} per objecttype."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    by_key = {}
    for r in data:
        by_key[(r["naam"], tuple(r["pad"]))] = r["attributen"]
    return by_key


def domain_exists(session, domain_fqn):
    url = f"{session.base_url}/api/v1/domains/name/{domain_fqn}"
    resp = session.get(url)
    if resp.status_code == 200:
        return resp.json()
    return None


def get_or_create_term(session, glossary_fqn, name, description, domain=None, tag_fqn=None, forceer_omschrijving=False, related_term_fqns=None,
                       ggm_item=None, index=None, release=None, rapport=None):
    own_fqn = f"{glossary_fqn}.{name}"

    term, zoekstatus = zoek_bestaande_term(session, index, ggm_item, None, name, own_fqn, rapport)
    if zoekstatus and zoekstatus.startswith("FOUT"):
        return own_fqn, zoekstatus, None
    if term is not None:
        already_existed = True
    else:
        payload = {
            "name": name,
            "displayName": name,
            "description": description,
            "glossary": glossary_fqn,
        }
        url = f"{session.base_url}/api/v1/glossaryTerms"
        resp = session.post(url, json=payload)
        if not resp.ok:
            return own_fqn, f"FOUT bij aanmaken {resp.status_code}: {resp.text}", None
        term = resp.json()
        already_existed = False

    status = "bestaat al" if already_existed else "aangemaakt"
    status += zoekstatus or ""

    if already_existed and forceer_omschrijving:
        status += update_description_if_changed(session, term, description)

    status, term = pas_ggm_metadata_toe(session, term, ggm_item, index, release, rapport, own_fqn, status)

    if domain:
        current_domains = term.get("domains") or []
        current_fqns = {d.get("fullyQualifiedName") for d in current_domains}
        if domain["fullyQualifiedName"] not in current_fqns:
            domain_ref = {
                "id": domain["id"],
                "type": "domain",
                "name": domain["name"],
                "fullyQualifiedName": domain["fullyQualifiedName"],
            }
            patch = [{
                "op": "add" if not current_domains else "replace",
                "path": "/domains",
                "value": [domain_ref],
            }]
            patch_url = f"{session.base_url}/api/v1/glossaryTerms/{term['id']}"
            patch_resp = session.patch(
                patch_url, data=json.dumps(patch),
                headers={"Content-Type": "application/json-patch+json"},
            )
            if patch_resp.ok:
                status += " + domain gekoppeld"
            else:
                status += f" + FOUT bij domain-koppeling {patch_resp.status_code}: {patch_resp.text}"

    if tag_fqn:
        current_tags = term.get("tags") or []
        current_tag_fqns = {t.get("tagFQN") for t in current_tags}
        if tag_fqn not in current_tag_fqns:
            new_tag = {"tagFQN": tag_fqn, "source": "Classification", "labelType": "Manual", "state": "Confirmed"}
            patch = [{
                "op": "add" if not current_tags else "replace",
                "path": "/tags",
                "value": current_tags + [new_tag],
            }]
            patch_url = f"{session.base_url}/api/v1/glossaryTerms/{term['id']}"
            patch_resp = session.patch(
                patch_url, data=json.dumps(patch),
                headers={"Content-Type": "application/json-patch+json"},
            )
            if patch_resp.ok:
                status += " + tag toegevoegd"
            else:
                status += f" + FOUT bij tag {patch_resp.status_code}: {patch_resp.text}"

    if related_term_fqns:
        related = term.get("relatedTerms") or []
        related_fqns = {
            r.get("fullyQualifiedName") or r.get("term", {}).get("fullyQualifiedName")
            for r in related
        }

        # Controleer per doelterm of deze al bestaat — OpenMetadata geeft een
        # 500 (null UUID) als de doelterm nog niet bestaat bij de PATCH.
        # Sla niet-bestaande doeltermen over; een volgende run is zelf-herstellend.
        nieuwe = []
        for fqn in related_term_fqns:
            if fqn in related_fqns or fqn == own_fqn:
                continue
            check = session.get(f"{session.base_url}/api/v1/glossaryTerms/name/{fqn}")
            if check.status_code == 200:
                target_id = check.json().get("id")
                nieuwe.append({"relationType": "relatedTo", "term": {"id": target_id, "type": "glossaryTerm"}})

        if nieuwe:
            patch = [{
                "op": "add" if not related else "replace",
                "path": "/relatedTerms",
                "value": related + nieuwe,
            }]
            patch_url = f"{session.base_url}/api/v1/glossaryTerms/{term['id']}"
            patch_resp = session.patch(
                patch_url, data=json.dumps(patch),
                headers={"Content-Type": "application/json-patch+json"},
            )
            if patch_resp.ok:
                status += f" + {len(nieuwe)} relatedTerm(s) gekoppeld"
            else:
                status += f" + FOUT bij relatedTerms {patch_resp.status_code}: {patch_resp.text}"

    return own_fqn, status, term.get("id")


def list_all_glossary_terms(session, glossary_id):
    """Haal alle terms van een glossary op als naam->term dict.
    Sinds v1.1.0 gepagineerd: v1.0.0 haalde maximaal 1000 termen op, waardoor
    de correctie-pass bij >5.000 termen een deel van de glossary miste."""
    by_name = {}
    for term in haal_alle_termen(session, glossary_id, fields="domains,tags,parent,extension"):
        by_name[term["name"]] = term
    return by_name


def rename_term(session, glossary_id, terms_by_name, old_name, new_name):
    """Hernoem een reeds bestaande glossary term (correctie voor disambiguatie).
    Gebruikt een vooraf opgehaalde naam->term-lookup i.p.v. de FQN-name-route,
    omdat namen met '/' of '.' de FQN-lookup laten falen."""
    term = terms_by_name.get(old_name)
    if term is None:
        return None  # term bestaat niet (onder deze naam), niets te hernoemen

    if term["name"] == new_name:
        return "al correct"

    patch = [
        {"op": "replace", "path": "/name", "value": new_name},
        {"op": "replace", "path": "/displayName", "value": new_name},
    ]
    patch_url = f"{session.base_url}/api/v1/glossaryTerms/{term['id']}"
    patch_resp = session.patch(
        patch_url, data=json.dumps(patch),
        headers={"Content-Type": "application/json-patch+json"},
    )
    if patch_resp.ok:
        # houd de lokale lookup-cache in sync
        terms_by_name.pop(old_name, None)
        new_term = patch_resp.json()
        terms_by_name[new_name] = new_term
        return "hernoemd"
    return f"FOUT {patch_resp.status_code}: {patch_resp.text}"


def rename_top_level_term(session, glossary_id, terms_by_name, old_name, new_name):
    """Wrapper om rename_term die alleen top-level objecttype-termen (zonder parent)
    hernoemt. Voorkomt dat een attribuut-child-term die toevallig dezelfde naam
    draagt (bv. 'locatie' als attribuut van 'Vergadering') per ongeluk wordt
    hernoemd in plaats van het bedoelde objecttype."""
    term = terms_by_name.get(old_name)
    if term is None or term.get("parent"):
        return None
    return rename_term(session, glossary_id, terms_by_name, old_name, new_name)


def rename_old_style_attribute_terms(session, glossary_id, terms_by_name):
    """Eenmalige correctie: child-terms die zijn aangemaakt vóór de invoering van de
    '<Objecttype> <Attribuut>'-naamgeving (toen attribuutnamen nog kaal waren, bv.
    'naam' onder 'Raadslid') worden hernoemd naar '<Objecttype> <Attribuut>'.
    Retourneert het aantal hernoemingen."""
    n_renamed = 0
    # Itereer over een snapshot van de items, want terms_by_name wijzigt tijdens het renamen
    for name, term in list(terms_by_name.items()):
        parent = term.get("parent")
        if not parent:
            continue
        parent_name = parent.get("name")
        if name.startswith(f"{parent_name} "):
            continue  # al in nieuwe stijl

        new_name = f"{parent_name} {name}"
        if new_name in terms_by_name:
            print(f"  WAARSCHUWING: kan '{name}' (parent '{parent_name}') niet hernoemen "
                  f"naar '{new_name}': bestaat al.")
            continue

        result = rename_term(session, glossary_id, terms_by_name, name, new_name)
        if result == "hernoemd":
            print(f"  Hernoemd (attribuut, oude stijl): '{name}' -> '{new_name}'")
            n_renamed += 1
        elif result and result.startswith("FOUT"):
            print(f"  FOUT bij hernoemen attribuut '{name}' -> '{new_name}': {result}")
    return n_renamed


def delete_term(session, terms_by_name, name):
    """Verwijder een verouderde/overtollige glossary term op naam.
    OBSOLETE_TERMS betreft uitsluitend top-level objecttype-termen; een
    attribuut-child-term met dezelfde naam (heeft een 'parent') wordt
    overgeslagen om te voorkomen dat per ongeluk een attribuut wordt
    verwijderd."""
    term = terms_by_name.get(name)
    if term is None or term.get("parent"):
        return None  # bestaat niet (meer), of is een attribuut-child -> niets te verwijderen

    url = f"{session.base_url}/api/v1/glossaryTerms/{term['id']}"
    resp = session.delete(url, params={"hardDelete": "true"})
    if resp.ok or resp.status_code == 404:
        terms_by_name.pop(name, None)
        return "verwijderd"
    return f"FOUT {resp.status_code}: {resp.text}"


def schrijf_runrapport(rapport, index, versie, alle_domeinen):
    """Schrijf een runrapport met hernoemingen, inhoudelijke wijzigingen,
    conflicten en (bij --alle) verweesde termen: termen met een ggmEaId die in
    deze GGM-release niet meer voorkomen. Die worden NIET automatisch
    verwijderd; er kunnen classificaties en eigen aanpassingen aan hangen."""
    gezien = rapport.pop("_geziene_eaids")
    if alle_domeinen:
        rapport["verweesd"] = sorted(
            [{"ea_id": eaid, "fqn": t.get("fullyQualifiedName")}
             for eaid, t in index.op_eaid.items() if eaid not in gezien],
            key=lambda x: x["fqn"] or "",
        )
    else:
        rapport["verweesd"] = "alleen bepaald bij --alle"
    rapport["afgerond"] = datetime.now().isoformat(timespec="seconds")
    map_ = os.path.join("data", versie) if versie else "."
    os.makedirs(map_, exist_ok=True)
    pad = os.path.join(map_, f"run_ggm_metadata_{datetime.now():%Y%m%d_%H%M%S}.json")
    with open(pad, "w", encoding="utf-8") as f:
        json.dump(rapport, f, ensure_ascii=False, indent=2)
    n_verweesd = len(rapport["verweesd"]) if isinstance(rapport["verweesd"], list) else "n.v.t."
    print(f"Runrapport: {pad}")
    print(f"  {len(rapport['hernoemd_via_eaid'])} hernoemd via EAID, "
          f"{len(rapport['inhoud_gewijzigd'])} inhoudelijk gewijzigd, "
          f"{len(rapport['eaid_conflicten'])} conflicten, "
          f"{len(rapport['verplaatst'])} verplaatst, {n_verweesd} verweesd")


def resolve_data_pad(versie, bestandsnaam, override=None):
    """Bepaal het pad naar een bronbestand.
    - Als 'override' is opgegeven (expliciet --argument), gebruik die.
    - Als 'versie' is opgegeven, gebruik data/<versie>/<bestandsnaam>.
    - Anders: bestandsnaam in de huidige map (legacy / lokaal gebruik)."""
    if override is not None:
        return override
    if versie:
        return os.path.join("data", versie, bestandsnaam)
    return bestandsnaam


def zet_glossary(naam):
    """Gebruik een andere glossary dan GGM_Objecttypen (bijv. om te testen)."""
    global GLOSSARY_NAME, GLOSSARY_DISPLAY_NAME
    GLOSSARY_NAME = naam
    GLOSSARY_DISPLAY_NAME = naam.replace("_", " ")


def main():
    parser = argparse.ArgumentParser(
        description="Laad GGM-objecttypen als glossary terms in OpenMetadata.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Voorbeelden:
  # Eenvoudigst: versie opgeven, alle paden worden automatisch bepaald
  python3 ggm_objecttypen_naar_openmetadata.py --versie v2.5.1 --alle --met-attributen --met-relaties

  # Specifiek domein testen
  python3 ggm_objecttypen_naar_openmetadata.py --versie v2.5.1 --domein "Economie"

  # Individuele padoverride (overschrijft --versie voor dat bestand)
  python3 ggm_objecttypen_naar_openmetadata.py --versie v2.5.1 --alle --mapping mijn_mapping.json
        """,
    )
    parser.add_argument("--versie", help="GGM-versie (bijv. v2.5.1) — bepaalt automatisch de datamap data/<versie>/")
    parser.add_argument("--data", default=None, help="Pad naar ggm_objecttypen.json (overschrijft --versie)")
    parser.add_argument("--mapping", default=None, help="Pad naar ggm_pad_naar_domain.json (overschrijft --versie)")
    parser.add_argument("--namen", default=None, help="Pad naar ggm_naam_disambiguatie.json (overschrijft --versie)")
    parser.add_argument("--attributen", default=None, help="Pad naar ggm_attributen.json (overschrijft --versie)")
    parser.add_argument("--met-attributen", action="store_true", help="Laad ook attributen als child glossary terms onder elk objecttype")
    parser.add_argument("--relaties", default=None, help="Pad naar ggm_relaties_per_object.json (overschrijft --versie)")
    parser.add_argument("--met-relaties", action="store_true", help="Voeg relaties tussen objecttypen (uit uml:Association) toe aan de beschrijving en als relatedTerms")
    parser.add_argument("--forceer-omschrijving", action="store_true", help="Werk bij reeds bestaande termen de omschrijving bij als deze afwijkt van de berekende waarde (objecttypen en attributen)")
    parser.add_argument("--domein", help="Naam van het te laden hoofddomein (exact zoals in ggm_objecttypen.json)")
    parser.add_argument("--alle", action="store_true", help="Laad alle hoofddomeinen")
    parser.add_argument("--list", action="store_true", help="Toon beschikbare hoofddomeinen en stop")
    parser.add_argument("--glossary", default=None,
                        help=f"Naam van de glossary (default: {GLOSSARY_NAME}). Handig om naast een "
                             "bestaande glossary te testen, bijv. --glossary GGM_Objecttypen_test")
    parser.add_argument("--release", default=None, help="Waarde voor ggmRelease (default: de waarde van --versie)")
    parser.add_argument("--zonder-ggm-metadata", action="store_true",
                        help="Sla EAID-matching en GGM-herkomstmetadata over (gedrag van v1.0.0)")
    args = parser.parse_args()

    v = args.versie
    if args.glossary:
        zet_glossary(args.glossary)

    pad_objecttypen  = resolve_data_pad(v, "ggm_objecttypen.json",          args.data)
    pad_mapping      = resolve_data_pad(v, "ggm_pad_naar_domain.json",       args.mapping)
    pad_namen        = resolve_data_pad(v, "ggm_naam_disambiguatie.json",    args.namen)
    pad_attributen   = resolve_data_pad(v, "ggm_attributen.json",            args.attributen)
    pad_relaties     = resolve_data_pad(v, "ggm_relaties_per_object.json",   args.relaties)

    if v:
        print(f"GGM-versie: {v}  (datamap: data/{v}/)\n")

    with open(pad_objecttypen, "r", encoding="utf-8") as f:
        objecttypen = json.load(f)

    hoofddomeinen = sorted(set(o["domein"] for o in objecttypen))

    if args.list:
        print("Beschikbare hoofddomeinen:")
        for d in hoofddomeinen:
            n = sum(1 for o in objecttypen if o["domein"] == d)
            print(f"  {d!r}  ({n} objecttypen)")
        return

    if not args.domein and not args.alle:
        parser.error("Geef --domein \"<naam>\", --alle, of --list op.")

    if args.domein and args.domein not in hoofddomeinen:
        sys.exit(f"Onbekend hoofddomein: {args.domein!r}. Gebruik --list voor de beschikbare namen.")

    te_laden = [args.domein] if args.domein else hoofddomeinen

    path_mapping = load_path_mapping(pad_mapping)
    disambiguation_map = load_disambiguation_map(pad_namen)

    attributen_map = {}
    if args.met_attributen:
        attributen_map = load_attributen(pad_attributen)
        total_attrs = sum(len(v) for v in attributen_map.values())
        print(f"Attributenbestand geladen: {len(attributen_map)} objecttypen, {total_attrs} attributen.\n")

    relaties_map = {}
    if args.met_relaties:
        relaties_map = load_relaties(pad_relaties)
        total_rel = sum(len(v) for v in relaties_map.values())
        print(f"Relatiebestand geladen: {len(relaties_map)} objecttypen, {total_rel} relatie-regels.\n")

    session = get_session()
    glossary = get_or_create_glossary(session)
    glossary_fqn = glossary["fullyQualifiedName"]
    glossary_id = glossary["id"]
    print(f"Glossary FQN: {glossary_fqn}")

    tag_fqns = ensure_hoofddomein_tags(session, hoofddomeinen)
    print(f"Classification '{CLASSIFICATION_NAME}' met {len(tag_fqns)} hoofddomein-tags klaar.\n")

    # Correctie-pass: hernoem/verwijder reeds geladen termen die een correctie nodig hebben
    print("Controleren op reeds geladen termen die hernoemd of verwijderd moeten worden...")
    terms_by_name = list_all_glossary_terms(session, glossary_id)
    n_renamed = 0
    n_deleted = 0

    for old_name, new_name in EXTRA_RENAMES.items():
        result = rename_top_level_term(session, glossary_id, terms_by_name, old_name, new_name)
        if result == "hernoemd":
            print(f"  Hernoemd (extra): '{old_name}' -> '{new_name}'")
            n_renamed += 1
        elif result and result.startswith("FOUT"):
            print(f"  FOUT bij hernoemen '{old_name}' -> '{new_name}': {result}")

    for (orig_name, pad), new_name in disambiguation_map.items():
        if orig_name == new_name:
            continue
        result = rename_top_level_term(session, glossary_id, terms_by_name, orig_name, new_name)
        if result == "hernoemd":
            print(f"  Hernoemd: '{orig_name}' -> '{new_name}'  [{' > '.join(pad)}]")
            n_renamed += 1
        elif result and result.startswith("FOUT"):
            print(f"  FOUT bij hernoemen '{orig_name}' -> '{new_name}': {result}")

    huidige_namen = {resolve_term_name(o, disambiguation_map) for o in objecttypen}
    for obsolete_name in OBSOLETE_TERMS:
        # Beveiliging: verwijder nooit een term die (nog) een GGM-objecttype is
        # of een GGM-EAID draagt; daar kunnen classificaties aan hangen.
        term = terms_by_name.get(obsolete_name)
        if obsolete_name in huidige_namen or (term and (term.get("extension") or {}).get("ggmEaId")):
            if term:
                print(f"  OVERGESLAGEN: '{obsolete_name}' staat in OBSOLETE_TERMS maar is een "
                      f"bestaand GGM-objecttype; niet verwijderd.")
            continue
        result = delete_term(session, terms_by_name, obsolete_name)
        if result == "verwijderd":
            print(f"  Verwijderd (overtollig): '{obsolete_name}'")
            n_deleted += 1
        elif result and result.startswith("FOUT"):
            print(f"  FOUT bij verwijderen '{obsolete_name}': {result}")

    if args.met_attributen:
        n_renamed += rename_old_style_attribute_terms(session, glossary_id, terms_by_name)

    print(f"{n_renamed} term(en) hernoemd, {n_deleted} term(en) verwijderd.\n")

    # GGM-herkomstmetadata (v1.1.0): custom properties + EAID-index
    index = None
    release = args.release or v
    rapport = None
    heeft_eaid = any(o.get("ea_id") for o in objecttypen)
    if args.zonder_ggm_metadata:
        print("GGM-metadata overgeslagen (--zonder-ggm-metadata).\n")
    elif not heeft_eaid:
        print("WAARSCHUWING: ggm_objecttypen.json bevat geen ea_id (gegenereerd met extract_ggm.py < v1.1.0).")
        print("             Draai extract_ggm.py opnieuw; nu wordt op naam gematcht zoals in v1.0.0.\n")
    else:
        if not release:
            sys.exit("Geef --versie of --release op; die waarde wordt vastgelegd in ggmRelease.")
        nieuw = ensure_custom_properties(session)
        print(f"Custom properties op glossaryTerm: {', '.join(nieuw) + ' aangemaakt' if nieuw else 'aanwezig'}.")
        alle_termen = haal_alle_termen(session, glossary_id)
        index = TermIndex(alle_termen)
        print(f"Index: {len(alle_termen)} bestaande termen, {len(index.op_eaid)} met ggmEaId.")
        if index.dubbele_eaid:
            print(f"  WAARSCHUWING: {len(index.dubbele_eaid)} EAID's komen op meer dan één term voor (zie runrapport).")
        print()
        rapport = {
            "release": release,
            "gestart": datetime.now().isoformat(timespec="seconds"),
            "hernoemd_via_eaid": [], "inhoud_gewijzigd": [], "eaid_conflicten": [],
            "verplaatst": [], "_geziene_eaids": set(),
            "dubbele_eaid_in_openmetadata": [list(x) for x in index.dubbele_eaid],
        }

    # Cache van opgehaalde Domain-objecten per FQN (voorkomt herhaalde lookups)
    domain_cache = {}

    def lookup_domain(fqn):
        if fqn not in domain_cache:
            domain_cache[fqn] = domain_exists(session, fqn)
        return domain_cache[fqn]

    for hoofddomein in te_laden:
        items = [o for o in objecttypen if o["domein"] == hoofddomein]
        print(f"=== Hoofddomein: {hoofddomein} ({len(items)} objecttypen) ===")
        tag_fqn = tag_fqns.get(hoofddomein)

        for obj in items:
            subdomain_fqn = resolve_subdomain_fqn(obj["pad"], path_mapping)
            domain_fqn = DOMAIN_FQN_OVERRIDES.get(subdomain_fqn, subdomain_fqn) if subdomain_fqn else hoofddomein

            domain = lookup_domain(domain_fqn)
            if not domain:
                print(f"  WAARSCHUWING: Domain '{domain_fqn}' niet gevonden, term wordt zonder domain-koppeling aangemaakt.")

            obj_relaties = relaties_map.get((obj["naam"], tuple(obj["pad"])), []) if args.met_relaties else []
            description = build_description(obj, obj_relaties, disambiguation_map)
            term_name = resolve_term_name(obj, disambiguation_map)

            related_term_fqns = None
            if obj_relaties:
                related_term_fqns = []
                for r in obj_relaties:
                    target_name = resolve_term_name(r["object"], disambiguation_map)
                    related_term_fqns.append(f"{glossary_fqn}.{target_name}")

            fqn, status, term_id = get_or_create_term(
                session, glossary_fqn, term_name, description, domain, tag_fqn,
                args.forceer_omschrijving, related_term_fqns,
                ggm_item=obj, index=index, release=release, rapport=rapport,
            )
            print(f"  [{status}] {fqn}  (domain: {domain_fqn})")
            if status.startswith("FOUT"):
                continue

            if args.met_attributen:
                attrs = attributen_map.get((obj["naam"], tuple(obj["pad"])), [])
                n_ok = 0
                n_err = 0
                for attr in attrs:
                    attr_desc = build_attribute_description(attr)
                    related_fqn = resolve_related_term_fqn(glossary_fqn, attr, disambiguation_map)
                    attr_fqn, attr_status = get_or_create_attribute_term(
                        session, glossary_fqn, fqn, term_name, attr["naam"], attr_desc, related_fqn, args.forceer_omschrijving,
                        ggm_item=attr, index=index, release=release, rapport=rapport, parent_id=term_id,
                    )
                    if "hernoemd via EAID" in attr_status or "INHOUD GEWIJZIGD" in attr_status:
                        print(f"    [{attr_status}] {attr_fqn}")
                    if attr_status.startswith("FOUT"):
                        n_err += 1
                        print(f"    [{attr_status}] {attr_fqn}")
                    else:
                        n_ok += 1
                if attrs:
                    print(f"    -> {n_ok} attributen ok" + (f", {n_err} fouten" if n_err else ""))

        print()

    if rapport is not None:
        schrijf_runrapport(rapport, index, v, alle_domeinen=bool(args.alle))

    print("Klaar.")


if __name__ == "__main__":
    main()