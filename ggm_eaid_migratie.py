#!/usr/bin/env python3
"""
Eenmalige migratie v1.0.0 -> v1.1.0: koppel de EA-GUID (ggmEaId) en de overige
GGM-herkomstmetadata aan termen die al in OpenMetadata staan.

Standaard is dit een DROOGLOOP: er wordt niets gewijzigd, alleen gerapporteerd
hoe elk GGM-element aan een bestaande term gekoppeld zou worden:

  eaid     term heeft al de juiste ggmEaId
  naam     term gevonden op naam, krijgt de EAID erbij
  nieuw    geen bestaande term; wordt bij de volgende laadrun aangemaakt
  conflict naam bestaat, maar draagt de EAID van een ander GGM-element

plus de termen in OpenMetadata waarvoor GEEN GGM-element meer bestaat
(bijvoorbeeld het verschil tussen de 959 termen uit v1.0.0 en de 947
objecttypen die extract_ggm.py uit GGM 2.5.1 haalt).

Met --uitvoeren worden bij de gematchte termen alleen de custom properties,
GEMMA-link en synoniemen gezet. Omschrijvingen, domains, tags en relaties
blijven ongemoeid; nieuwe termen worden niet aangemaakt. Daarvoor is de gewone
laadrun (ggm_objecttypen_naar_openmetadata.py) bedoeld.

Gebruik:
    python3 ggm_eaid_migratie.py --versie v2.5.1                # droogloop
    python3 ggm_eaid_migratie.py --versie v2.5.1 --uitvoeren    # echt migreren

Vereist dezelfde omgevingsvariabelen als het laadscript (OM_HOST, OM_JWT_TOKEN).
"""

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime

from ggm_objecttypen_naar_openmetadata import (
    GLOSSARY_NAME, get_session, load_disambiguation_map, resolve_term_name,
    clean_attribute_name, load_attributen, resolve_data_pad,
)
from om_ggm_metadata import (
    ensure_custom_properties, haal_alle_termen, TermIndex, werk_ggm_metadata_bij,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--versie", required=True, help="GGM-versie, bijv. v2.5.1 (datamap data/<versie>/)")
    parser.add_argument("--release", default=None, help="Waarde voor ggmRelease/ggmEersteRelease (default: --versie)")
    parser.add_argument("--uitvoeren", action="store_true", help="Werkelijk wijzigen (default: droogloop)")
    parser.add_argument("--glossary", default=GLOSSARY_NAME, help=f"Naam van de glossary (default: {GLOSSARY_NAME})")
    parser.add_argument("--zonder-attributen", action="store_true", help="Alleen objecttypen migreren")
    args = parser.parse_args()
    release = args.release or args.versie

    with open(resolve_data_pad(args.versie, "ggm_objecttypen.json"), encoding="utf-8") as f:
        objecttypen = json.load(f)
    if not any(o.get("ea_id") for o in objecttypen):
        sys.exit("ggm_objecttypen.json bevat geen ea_id. Draai eerst extract_ggm.py (v1.1.0).")
    disamb = load_disambiguation_map(resolve_data_pad(args.versie, "ggm_naam_disambiguatie.json"))
    attributen_map = {} if args.zonder_attributen else \
        load_attributen(resolve_data_pad(args.versie, "ggm_attributen.json"))

    session = get_session()
    resp = session.get(f"{session.base_url}/api/v1/glossaries/name/{args.glossary}")
    resp.raise_for_status()
    glossary = resp.json()

    if args.uitvoeren:
        nieuw = ensure_custom_properties(session)
        if nieuw:
            print(f"Custom properties aangemaakt: {', '.join(nieuw)}")

    termen = haal_alle_termen(session, glossary["id"])
    index = TermIndex(termen)
    print(f"{len(termen)} termen in {args.glossary}, waarvan {len(index.op_eaid)} al met ggmEaId.\n")

    uitkomst = Counter()
    regels = []
    gematcht_ids = set()

    def verwerk(item, parent_naam, naam, soort):
        term, hoe = index.zoek(item.get("ea_id"), parent_naam, naam)
        hoe = hoe or "nieuw"
        if hoe == "eaid" and term["name"] != naam:
            hoe = "eaid (hernoemd in GGM)"
        uitkomst[(soort, hoe)] += 1
        regel = {"soort": soort, "uitkomst": hoe, "ea_id": item.get("ea_id"),
                 "verwachte_naam": naam, "parent": parent_naam}
        if term is not None:
            gematcht_ids.add(term["id"])
            regel["fqn"] = term.get("fullyQualifiedName")
            if args.uitvoeren and hoe in ("naam", "eaid"):
                status, term, _ = werk_ggm_metadata_bij(session, term, item, release)
                index.voeg_toe(term)
                regel["status"] = status.strip(" +") or "ongewijzigd"
        regels.append(regel)
        return term

    for obj in objecttypen:
        term_naam = resolve_term_name(obj, disamb)
        verwerk(obj, None, term_naam, "objecttype")
        for attr in attributen_map.get((obj["naam"], tuple(obj["pad"])), []):
            naam = f"{term_naam} {clean_attribute_name(attr['naam'])}"
            verwerk(attr, term_naam, naam, "attribuut")

    zonder_ggm = [
        {"fqn": t.get("fullyQualifiedName"), "parent": (t.get("parent") or {}).get("name"),
         "ggmEaId": (t.get("extension") or {}).get("ggmEaId")}
        for t in termen if t["id"] not in gematcht_ids
    ]

    print("Resultaat" + (" (UITGEVOERD)" if args.uitvoeren else " (droogloop, niets gewijzigd)") + ":")
    for (soort, hoe), n in sorted(uitkomst.items()):
        print(f"  {soort:<11} {hoe:<24} {n:>6}")
    n_top = sum(1 for z in zonder_ggm if not z["parent"])
    print(f"  Termen in OpenMetadata zonder GGM-element: {len(zonder_ggm)} "
          f"({n_top} objecttypen, {len(zonder_ggm) - n_top} attributen)")
    fouten = [r for r in regels if "FOUT" in (r.get("status") or "")]
    if fouten:
        print(f"  FOUTEN bij bijwerken: {len(fouten)} (zie rapport)")

    map_ = os.path.join("data", args.versie)
    os.makedirs(map_, exist_ok=True)
    pad = os.path.join(map_, f"migratie_eaid_{'uitgevoerd' if args.uitvoeren else 'droog'}_"
                             f"{datetime.now():%Y%m%d_%H%M%S}.json")
    with open(pad, "w", encoding="utf-8") as f:
        json.dump({
            "release": release, "uitgevoerd": args.uitvoeren,
            "samenvatting": {f"{s}|{h}": n for (s, h), n in uitkomst.items()},
            "zonder_ggm_element": zonder_ggm,
            "dubbele_eaid_in_openmetadata": [list(x) for x in index.dubbele_eaid],
            "regels": regels,
        }, f, ensure_ascii=False, indent=2)
    print(f"\nRapport: {pad}")


if __name__ == "__main__":
    main()
