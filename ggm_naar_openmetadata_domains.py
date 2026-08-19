#!/usr/bin/env python3
"""
Laadt de GGM-domeinstructuur (SKOS JSON-LD) via de OpenMetadata REST API
als Domains (en sub-domains).

Vereisten:
    pip install requests --break-system-packages

Configuratie via omgevingsvariabelen:
    OM_HOST       - basis-URL van je OpenMetadata-instantie, bv. https://openmetadata.mijn-org.nl
    OM_JWT_TOKEN  - JWT-token van een bot/service-account (Settings > Bots in de UI)

Gebruik:
    export OM_HOST="https://openmetadata.mijn-org.nl"
    export OM_JWT_TOKEN="ey....."
    python3 ggm_naar_openmetadata_domains.py ggm_domeinen_skos.jsonld ggm_definities.json
"""

import sys
import os
import json
import argparse
import requests


# Domeintype voor alle GGM-(sub)domeinen. Opties volgens OpenMetadata-schema:
# "Aggregate", "Consumer-aligned", "Source-aligned"
DOMAIN_TYPE = "Aggregate"


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


def load_definitions(path):
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def build_index(graph):
    """Index concepten op @id en bepaal kinderen per (parent) concept."""
    by_id = {}
    children = {}

    for node in graph:
        if node.get("@type") == "skos:Concept":
            by_id[node["@id"]] = node

    for node in by_id.values():
        broader = node.get("skos:broader")
        parent_id = broader["@id"] if broader else None
        children.setdefault(parent_id, []).append(node)

    return by_id, children


def get_label(node, parent_label=None):
    label = node["skos:prefLabel"]
    name = label["@value"] if isinstance(label, dict) else label
    # Domains vereisen unieke naam per niveau, maar niet globaal, dus
    # disambiguatie is hier strikt genomen niet nodig. We doen het toch
    # voor consistentie met de glossary-variant en duidelijkheid in de UI.
    if parent_label is not None and name == parent_label:
        name = f"{name} (subdomein)"
    return name


def get_or_create_domain(session, name, description, parent_fqn=None):
    """
    Maak een Domain aan (of hergebruik een bestaande met dezelfde FQN).
    Geeft de FQN van het domain terug.
    """
    own_fqn = f"{parent_fqn}.{name}" if parent_fqn else name

    # Check of het domain al bestaat (idempotent herdraaien)
    url = f"{session.base_url}/api/v1/domains/name/{own_fqn}"
    resp = session.get(url)
    if resp.status_code == 200:
        print(f"  Domain '{own_fqn}' bestaat al, overslaan.")
        return own_fqn

    payload = {
        "name": name,
        "displayName": name,
        "description": description,
        "domainType": DOMAIN_TYPE,
    }
    if parent_fqn:
        payload["parent"] = parent_fqn

    url = f"{session.base_url}/api/v1/domains"
    resp = session.post(url, json=payload)
    if not resp.ok:
        print(f"  FOUT bij aanmaken '{own_fqn}': {resp.status_code} {resp.text}")
        resp.raise_for_status()

    print(f"  Domain '{own_fqn}' aangemaakt.")
    return own_fqn


def walk(session, node_id, by_id, children, parent_fqn, parent_label, definitions):
    node = by_id[node_id]
    name = get_label(node, parent_label)
    slug = node_id.rstrip("/").split("/")[-1]

    description = definitions.get(slug)
    if not description:
        description = name  # fallback

    own_fqn = get_or_create_domain(session, name, description, parent_fqn)

    for child in children.get(node_id, []):
        walk(session, child["@id"], by_id, children, own_fqn, name, definitions)


def main():
    parser = argparse.ArgumentParser(
        description="Laad de GGM-domeinstructuur als OpenMetadata Domains.",
        epilog="Voorbeeld: python3 ggm_naar_openmetadata_domains.py --versie v2.5.1",
    )
    parser.add_argument("--versie", help="GGM-versie (bijv. v2.5.1) — bepaalt automatisch de datamap data/<versie>/")
    parser.add_argument("--skos", default=None, help="Pad naar ggm_domeinen_skos.jsonld (overschrijft --versie)")
    parser.add_argument("--definities", default=None, help="Pad naar ggm_definities.json (overschrijft --versie)")
    args = parser.parse_args()

    v = args.versie

    def resolve(bestandsnaam, override):
        if override is not None:
            return override
        if v:
            return os.path.join("data", v, bestandsnaam)
        return bestandsnaam

    skos_path = resolve("ggm_domeinen_skos.jsonld", args.skos)
    definitions_path = resolve("ggm_definities.json", args.definities)

    if v:
        print(f"GGM-versie: {v}  (datamap: data/{v}/)\n")

    definitions = load_definitions(definitions_path)

    with open(skos_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    by_id, children = build_index(data["@graph"])

    session = get_session()

    print("Domains aanmaken...\n")

    for top_node in children.get(None, []):
        walk(session, top_node["@id"], by_id, children, None, None, definitions)

    print("\nKlaar.")


if __name__ == "__main__":
    main()
    