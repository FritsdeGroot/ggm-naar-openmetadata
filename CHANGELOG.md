# Changelog

Alle noemenswaardige wijzigingen aan dit project worden in dit bestand vastgelegd.

Het formaat is gebaseerd op [Keep a Changelog](https://keepachangelog.com/nl/1.1.0/)
en dit project volgt [Semantic Versioning](https://semver.org/lang/nl/).

## [Unreleased]

## [1.0.0] - 2026-09-24

Eerste openbare release. Volledige pipeline voor het laden van GGM v2.5.1 in
OpenMetadata Community Edition.

### Toegevoegd

#### Domeinstructuur
- `ggm_naar_openmetadata_domains.py`: laadt 49 (sub)domeinen als OpenMetadata
  Domains met parent-hiërarchie, ontleend aan de GGM mkdocs.yml-navigatie
- `ggm_domeinen_naar_skos.py`: genereert `ggm_domeinen_skos.jsonld` (SKOS
  concept scheme) uit de GGM mkdocs.yml + domeindefinities
- `ggm_domeinen_skos.jsonld`: SKOS concept scheme voor 49 GGM-domeinen
- `ggm_definities.json`: domeindefinities afgeleid uit de GGM README.md

#### Objecttypen (glossary terms)
- `ggm_objecttypen_naar_openmetadata.py`: hoofdscript voor het laden van 959
  objecttypen als GlossaryTerms in glossary `GGM_Objecttypen`, elk gekoppeld aan
  hun laagste (sub)domein en getagd met hun hoofddomein
- `ggm_objecttypen.json`: 959 opgeschoonde objecttypen met naam, definitie, pad,
  attributen en domein
- `ggm_pad_naar_domain.json`: mapping van XMI-packagepad naar OpenMetadata
  Domain FQN
- `ggm_naam_disambiguatie.json`: disambiguatie van 136 objecttypen met
  niet-unieke namen (bijv. `Pand (BAG)` vs `Pand (RSGB)`)
- Classification `GGM_Hoofddomein` met 12 hoofddomein-tags
- Idempotente correctieronde: `rename_old_style_attribute_terms`,
  `rename_top_level_term`, `delete_term` voor OBSOLETE_TERMS en EXTRA_RENAMES

#### Attributen (child glossary terms)
- `ggm_attributen.json`: 4534 attributen verdeeld over 824 objecttypen, met naam,
  type, definitie, waardelijst (voor `uml:Enumeration`-types) en
  objecttype-referentie (voor `uml:Class`-types)
- `--met-attributen`-vlag: laadt attributen als child GlossaryTerms onder elk
  objecttype volgens de naamconventie `"<Objecttype> <Attribute>"`
- `--forceer-omschrijving`-vlag: werkt beschrijvingen van bestaande terms bij
  wanneer deze zijn gewijzigd (voor GGM-versie-updates)
- 510 attributen met toegestane waardelijsten (uit 156 unieke Enumerations)
- 98 attributen met `relatedTerms`-koppelingen naar gerefereerde
  objecttype-terms (bijv. `geboorteland` → `Land`)

#### Relaties tussen objecttypen
- `ggm_relaties_per_object.json`: 425 relaties (uit `uml:Association`) over 384
  objecttypen, met associatienaam en genormaliseerde multipliciteiten
- `--met-relaties`-vlag: voegt een `**Relaties:**`-sectie toe aan de
  objecttype-beschrijving en `relatedTerms`-koppelingen tussen gerelateerde
  objecttype-terms
- Multipliciteitsnormalisatie: EA-codering `0..-1` / `1..-1` → `0..*` / `1..*`

### Ontwerpkeuzes

- **`"<Objecttype> <Attribute>"`-naamgeving voor child terms**: OpenMetadata's
  `GlossaryTerm.name`-validatie geldt glossary-breed (niet per FQN), waardoor
  generieke attribuutnamen als `naam` of `status` na het eerste objecttype
  botsen. Contextuele namen (`Raadslid naam`, `Pand (BAG) status`) zijn zowel
  uniek als in lijn met de [OpenMetadata best practices](https://docs.open-metadata.org/latest/how-to-guides/data-governance/glossary/best-practices)
  voor PII-gevoelige tagging.
- **Relaties als beschrijving + relatedTerms**: gekozen boven child terms
  (dezelfde naam-uniciteitskwestie) en kale relatedTerms (verliest associatienaam
  en multipliciteit).
- **`rename_top_level_term`-wrapper**: voorkomt dat disambiguatie-hernoemingen
  per ongeluk attribuut-child-terms raken die een naam delen met een objecttype
  (bijv. attribuut `Vergadering.locatie` dat wordt aangezien voor objecttype
  `locatie`).

### Bekende beperkingen

- 135 objecttypen hebben geen attributen in de XMI (abstracte/marker-classes of
  specialisaties die attributen erven via associatie, niet via `ownedAttribute`)
- 35 attribuut→objecttype-referenties zijn ambigu (meerdere objecttypen met
  dezelfde naam in verschillende domeinen, bijv. `Leverancier`) en worden bewust
  ongekoppeld gelaten om onjuiste `relatedTerms`-koppelingen te voorkomen
- 657 van de 1084 `uml:Association`-elementen verbinden geen twee herkende
  objecttypen (ze verwijzen naar Enumerations, PrimitiveTypes of EA-hulpclasses
  zoals `ProxyConnector`) en worden uitgesloten
- `uml:AssociationClass` (6 elementen, bijv. `Historische Rol`) en `uml:DataType`
  (11 elementen, bijv. `Geldbedrag`) worden nog niet geladen
- Vereist OpenMetadata 2.x — de relatedTerms-API is tussen 1.x en 2.x ingrijpend
  gewijzigd: het payload-formaat is nu `{"relationType": "relatedTo", "term": {"id": "<uuid>", "type": "glossaryTerm"}}`,
  de doel-term-UUID moet via een GET worden opgehaald vóór het patchen, en
  `relationType` moet een van de volgende zijn: relatedTo, synonym, antonym,
  broader, narrower, partOf, hasPart, calculatedFrom, usedToCalculate, seeAlso
- `relatedTerms`-koppelingen naar objecttypen in een domein dat later in dezelfde
  run wordt geladen, kunnen ontbreken na de eerste `--alle`-run; een tweede
  identieke run is zelfherstellend
- `extract_ggm.py` regenereert momenteel ~947 objecttypen, terwijl de
  meegeleverde `ggm_objecttypen.json` (en deze release) er 959 bevat. De 12
  ontbrekende objecttypen zijn nog niet geïdentificeerd; vergelijking van beide
  `ggm_objecttypen.json`-outputs is nodig om te bepalen of dit een
  filteringsverschil is in `extract_ggm.py` (bijv. `DIAGRAM_PREFIX_PATTERN` of
  `clean_naam`) of een verschil in de gebruikte XMI-versie.

[Unreleased]: https://github.com/FritsdeGroot/ggm-naar-openmetadata-/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/FritsdeGroot/ggm-naar-openmetadata-/releases/tag/v1.0.0
