# Changelog

Alle noemenswaardige wijzigingen aan dit project worden in dit bestand vastgelegd.

Het formaat is gebaseerd op [Keep a Changelog](https://keepachangelog.com/nl/1.1.0/)
en dit project volgt [Semantic Versioning](https://semver.org/lang/nl/).

## [Unreleased]

## [1.1.0] - 2026-10-01

Getest op een lege OpenMetadata 2.0.2-omgeving: eerste lading ~17 min (~14.100 API-aanroepen), herlading zonder wijzigingen ~10 s, 0 fouten. Eén run volstaat; OpenMetadata toont relaties tweezijdig.

### Toegevoegd

- **EAID als matchsleutel**: `extract_ggm.py` neemt per objecttype en attribuut
  de Enterprise Architect-GUID (`ea_id`) op. Het laadscript zoekt bestaande
  termen eerst op `ggmEaId` en pas daarna op naam; is een element in het GGM
  hernoemd, dan wordt de term hernoemd met behoud van tags, classificaties en
  eigen aanpassingen.
- **Custom properties op glossaryTerm** (`om_ggm_metadata.py`): `ggmEaId`,
  `ggmRelease`, `ggmEersteRelease`, `ggmInhoudHash`, `ggmToelichting`,
  `ggmAuteur`, `gemmaType`. Worden idempotent aangemaakt bij de eerste run.
- **GEMMA-link** in het standaardveld References (naam `GEMMA: <naam>`) voor 502
  objecttypen; **synoniemen** uit het GGM in Synonyms (alleen toevoegen).
- **Inhoud-hash** per objecttype en attribuut, als betrouwbaar wijzigingssignaal.
  EA's eigen `version`/`modified` zijn daarvoor ongeschikt: in GGM 2.5.0 zijn ze
  voor 951 van de 953 objecttypen tegelijk gewijzigd door een bulkbewerking.
- **Runrapport** `data/<versie>/run_ggm_metadata_<tijd>.json`: hernoemingen via
  EAID, inhoudelijk gewijzigde elementen, naamconflicten, verplaatste attributen
  en (bij `--alle`) verweesde termen. Verweesde termen worden niet verwijderd.
- **Extractierapport** `ggm_extractie_rapport.json`: uitgesloten classes,
  duplicaten, definitiebron, attributen zonder EAID (265) en tagged-value-
  conflicten tussen spellingen (130, bijv. `GEMMA naam` vs `GEMMA-naam`).
- `ggm_modellen.json`: EA-packages met hun documentatie (korte domeindefinities).
- `ggm_xmi_metadata.py`: leest EA-extensie en profieltoepassingen uit en voegt
  tagspellingen samen (`GEMMA url`/`GEMMA-URL`/`GEMMA_url`).
- `ggm_eaid_migratie.py`: eenmalige migratie van v1.0.0-termen, standaard als
  droogloop.
- **Voortgang en hartslag** (`voortgang.py`): fasen met tijdstempel, een
  prefix per objecttype (`[ 123/947  13% | 05:12 | nog ~31m]`), een
  hartslagregel na 60 seconden zonder uitvoer (fase, positie, aantal
  API-aanroepen, eventueel lang lopende aanroep) en aan het eind de duur en
  het aantal API-aanroepen per fase. Uitvoer wordt per regel doorgegeven, ook
  bij `| tee`.
- API-aanroepen krijgen een time-out (10 s verbinden, 180 s lezen); GET-aanroepen
  worden bij 502/503/504 of een verbroken verbinding tot drie keer herhaald.
- `--glossary <naam>`: laden in een andere glossary, bijv. om naast een
  bestaande te testen. `--release`, `--zonder-ggm-metadata`.

### Gewijzigd

- **Definitiebron objecttypen**: de EA-documentatie is leidend (dit toont ook
  gemeentelijkgegevensmodel.nl), met terugval op `GEMMA definitie`.
- `list_all_glossary_terms` haalt alle termen gepagineerd op (was maximaal 1000).
- Bestaande termen worden één keer opgehaald voor zowel de correctie-pass als
  de EAID-index (was twee keer); pagina's van 500 termen met voortgang per pagina.

### Opgelost

- `extract_ggm.py` las alleen `GEMMA definitie`, waardoor opnieuw gegenereerde
  bronbestanden 546 van de 947 objecttypen zonder definitie opleverden. Met
  `--forceer-omschrijving` zou dat bestaande definities overschrijven. Nu nog 9
  objecttypen zonder definitie (ontbreekt in het GGM zelf).
- `OBSOLETE_TERMS` bevatte `Fractie` en `Rol`, bestaande GGM-objecttypen (Afval,
  HR). Verwijderd, en een term met `ggmEaId` of een actuele GGM-naam wordt nooit
  meer door de correctie-pass verwijderd.
- `clean_naam` zocht `REVERSE_CLEAN` pas op na het verwijderen van `/` en `.`,
  waardoor o.a. `Periodiek dienst Bijz. bijstand` niet werd omgezet.
- Verschil 947 vs 959 objecttypen (bekende beperking v1.0.0) verklaard: de 12
  extra termen zijn diagram-artefacten uit een oudere extractie
  (`ObjecttypeA`–`G`, `Detaillering...`, `OverigImgeo`). Toegevoegd aan
  `OBSOLETE_TERMS`.

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

[Unreleased]: https://github.com/FritsdeGroot/ggm-naar-openmetadata-/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/FritsdeGroot/ggm-naar-openmetadata-/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/FritsdeGroot/ggm-naar-openmetadata-/releases/tag/v1.0.0
