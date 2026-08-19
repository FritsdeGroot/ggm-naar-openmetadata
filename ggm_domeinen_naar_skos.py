#!/usr/bin/env python3
"""
Zet het GGM-domeinen SKOS-conceptenschema (JSON-LD) om naar een CSV
geschikt voor OpenMetadata's Glossary Bulk Import.

OpenMetadata CSV-kolommen (zie docs.open-metadata.org -> Glossary -> Import):
    parent,name,displayName,description,synonyms,relatedTerms,references,tags

Hiërarchie wordt opgebouwd via de 'parent'-kolom, met dot-notatie
t.o.v. de glossary-root (bijv. "Sociaal domein.Werk").

Gebruik:
    python3 ggm_skos_naar_openmetadata_csv.py ggm_domeinen_skos.jsonld ggm_glossary.csv
"""

import sys
import json
import csv
import os


def load_definitions(path):
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def build_index(graph):
    """Index concepten op @id, en bepaal kinderen per concept."""
    by_id = {}
    children = {}
    scheme_id = None

    for node in graph:
        if node.get("@type") == "skos:ConceptScheme":
            scheme_id = node["@id"]
            continue
        if node.get("@type") == "skos:Concept":
            by_id[node["@id"]] = node

    for node in by_id.values():
        broader = node.get("skos:broader")
        parent_id = broader["@id"] if broader else None  # None = top concept
        children.setdefault(parent_id, []).append(node)

    return by_id, children, scheme_id


def get_label(node, parent_label=None):
    label = node["skos:prefLabel"]
    name = label["@value"] if isinstance(label, dict) else label
    # Disambigueer als subdomein-naam gelijk is aan de naam van het hoofddomein
    # (bijv. hoofddomein "Onderwijs" -> subdomein "Onderwijs").
    if parent_label is not None and name == parent_label:
        name = f"{name} (subdomein)"
    return name


def walk(node_id, by_id, children, parent_path, parent_label, definitions, rows, missing):
    node = by_id[node_id]
    name = get_label(node, parent_label)
    slug = node_id.rstrip("/").split("/")[-1]

    description = definitions.get(slug)
    if not description:
        description = node.get("dct:description")
        if isinstance(description, dict):
            description = description.get("@value", "")
    if not description:
        # description is verplicht in OpenMetadata; gebruik de naam als fallback
        description = name
        missing.append(name)

    rows.append({
        "parent": parent_path,           # leeg = root-niveau van de glossary
        "name*": name,
        "displayName": name,
        "description": description,
        "synonyms": "",
        "relatedTerms": "",
        "references": "",
        "tags": "",
        "reviewers": "",
        "owner": "",
        "glossaryStatus": "Approved",
        "color": "",
        "iconURL": "",
        "extension": "",
    })

    own_path = f"{parent_path}.{name}" if parent_path else name

    for child in children.get(node_id, []):
        walk(child["@id"], by_id, children, own_path, name, definitions, rows, missing)


def main():
    if len(sys.argv) not in (3, 4):
        print(f"Gebruik: {sys.argv[0]} <input.jsonld> <output.csv> [definities.json]")
        sys.exit(1)

    input_path, output_path = sys.argv[1], sys.argv[2]
    definitions_path = sys.argv[3] if len(sys.argv) == 4 else None
    definitions = load_definitions(definitions_path)

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    graph = data["@graph"]
    by_id, children, scheme_id = build_index(graph)

    rows = []
    missing = []
    # top concepten (geen skos:broader) starten op root-niveau (parent = "")
    for top_node in children.get(None, []):
        walk(top_node["@id"], by_id, children, "", None, definitions, rows, missing)

    fieldnames = ["parent", "name*", "displayName", "description",
                   "synonyms", "relatedTerms", "references", "tags",
                   "reviewers", "owner", "glossaryStatus", "color",
                   "iconURL", "extension"]

    # Volledig bestand (handig voor referentie / archief, niet voor directe import
    # als de OpenMetadata-instantie parent-afhankelijkheden binnen 1 bulk niet oplost)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # Splits per niveau (bepaald aan de hand van het aantal punten in 'parent')
    levels = {}
    for row in rows:
        depth = row["parent"].count(".") + 1 if row["parent"] else 0
        levels.setdefault(depth, []).append(row)

    base, ext = os.path.splitext(output_path)
    for depth in sorted(levels):
        level_path = f"{base}_niveau{depth + 1}{ext}"
        with open(level_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(levels[depth])
        print(f"  Niveau {depth + 1}: {len(levels[depth])} term(en) -> {level_path}")

    print(f"Klaar: {len(rows)} glossary terms in totaal (volledig bestand: {output_path})")
    if missing:
        print(f"Let op: geen definitie gevonden voor {len(missing)} term(en), naam gebruikt als fallback:")
        for m in missing:
            print(f"  - {m}")


if __name__ == "__main__":
    main()