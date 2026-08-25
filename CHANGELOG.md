# Changelog

All notable changes to this project are documented here.
This project follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [1.0.0] — 2026-08-25

Initial public release. Complete pipeline for loading GGM v2.5.1 into
OpenMetadata Community Edition.

### Added

#### Domain structure
- `ggm_naar_openmetadata_domains.py`: loads 49 (sub)domains as OpenMetadata
  Domains with parent hierarchy, sourced from GGM mkdocs.yml navigation
- `ggm_domeinen_naar_skos.py`: generates `ggm_domeinen_skos.jsonld` (SKOS
  concept scheme) from GGM mkdocs.yml + domain definitions
- `ggm_domeinen_skos.jsonld`: SKOS concept scheme for 49 GGM domains
- `ggm_definities.json`: domain definitions derived from GGM README.md

#### Objecttypes (glossary terms)
- `ggm_objecttypen_naar_openmetadata.py`: main script for loading 959 objecttypes
  as GlossaryTerms in glossary `GGM_Objecttypen`, each linked to their lowest
  (sub)domain and tagged with their main domain
- `ggm_objecttypen.json`: 959 cleaned objecttypes with name, definition, path,
  attributes and domain
- `ggm_pad_naar_domain.json`: mapping from XMI package path to OpenMetadata
  Domain FQN
- `ggm_naam_disambiguatie.json`: disambiguation of 136 objecttypes with
  non-unique names (e.g. `Pand (BAG)` vs `Pand (RSGB)`)
- Classification `GGM_Hoofddomein` with 12 main domain tags
- Idempotent correction pass: `rename_old_style_attribute_terms`,
  `rename_top_level_term`, `delete_term` for OBSOLETE_TERMS and EXTRA_RENAMES

#### Attributes (child glossary terms)
- `ggm_attributen.json`: 4534 attributes across 824 objecttypes, with name,
  type, definition, value list (for `uml:Enumeration` types) and objecttype
  reference (for `uml:Class` types)
- `--met-attributen` flag: loads attributes as child GlossaryTerms under each
  objecttype using `"<Objecttype> <Attribute>"` naming convention
- `--forceer-omschrijving` flag: updates descriptions of existing terms when
  changed (for GGM version updates)
- 510 attributes with allowed value lists (from 156 unique Enumerations)
- 98 attributes with `relatedTerms` links to referenced objecttype terms
  (e.g. `geboorteland` → `Land`)

#### Relations between objecttypes
- `ggm_relaties_per_object.json`: 425 relations (from `uml:Association`) across
  384 objecttypes, with association name and normalized multiplicities
- `--met-relaties` flag: adds `**Relaties:**` section to objecttype description
  and `relatedTerms` links between related objecttype terms
- Multiplicity normalization: EA encoding `0..-1` / `1..-1` → `0..*` / `1..*`

### Architecture decisions

- **`"<Objecttype> <Attribute>"` naming for child terms**: OpenMetadata's
  `GlossaryTerm.name` validation is glossary-wide (not per FQN), causing generic
  attribute names like `naam` or `status` to conflict after the first objecttype.
  Contextual names (`Raadslid naam`, `Pand (BAG) status`) are both unique and
  aligned with [OpenMetadata best practices](https://docs.open-metadata.org/latest/how-to-guides/data-governance/glossary/best-practices)
  for PII-sensitive tagging.
- **Relations as description + relatedTerms**: chosen over child terms (same
  name-uniqueness issue) and bare relatedTerms (loses association name and
  multiplicity).
- **`rename_top_level_term` wrapper**: prevents disambiguation renames from
  accidentally targeting attribute child terms that share a name with an
  objecttype (e.g. attribute `Vergadering.locatie` being mistaken for objecttype
  `locatie`).

### Known limitations

- 135 objecttypes have no attributes in the XMI (abstract/marker classes or
  specialisations that inherit attributes via association, not `ownedAttribute`)
- 35 attribute→objecttype references are ambiguous (multiple objecttypes with the
  same name in different domains, e.g. `Leverancier`) and are intentionally left
  uncoupled to avoid incorrect `relatedTerms` links
- 657 of the 1084 `uml:Association` elements do not connect two recognized
  objecttypes (they reference Enumerations, PrimitiveTypes or EA helper classes
  such as `ProxyConnector`) and are excluded
- `uml:AssociationClass` (6 elements, e.g. `Historische Rol`) and `uml:DataType`
  (11 elements, e.g. `Geldbedrag`) are not yet loaded
- Requires OpenMetadata 2.x — the relatedTerms API changed significantly between 1.x and 2.x: payload format is now `{"relationType": "relatedTo", "term": {"id": "<uuid>", "type": "glossaryTerm"}}`, the target term UUID must be resolved via a GET before patching, and `relationType` must be one of: relatedTo, synonym, antonym, broader, narrower, partOf, hasPart, calculatedFrom, usedToCalculate, seeAlso
- `relatedTerms` links to objecttypes in a domain loaded later in the same run
  may be missing after the first `--alle` run; a second identical run is
  self-healing

---

## [Unreleased]

### To investigate
- **947 vs 959 objecttypen**: `extract_ggm.py` genereert ~947 objecttypen terwijl de
  oorspronkelijke handmatige extractie 959 opleverde. De 12 ontbrekende objecttypen zijn
  nog niet geïdentificeerd — vergelijking van beide `ggm_objecttypen.json`-bestanden is
  nodig om te bepalen of dit een filteringsverschil is in `extract_ggm.py` (bijv.
  `DIAGRAM_PREFIX_PATTERN` of `clean_naam`) of een verschil in de XMI-versie die is
  gebruikt.

### Possible future additions
- Support for `uml:AssociationClass` and `uml:DataType` elements
- Automated PII/AVG classification layer aligned with Woo information categories
- Support for OpenMetadata's Data Product entity type