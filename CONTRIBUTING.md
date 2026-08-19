# Bijdragen

Bedankt voor je interesse in dit project. Bijdragen zijn welkom van gemeenten,
data governance-consultants en iedereen die werkt met het Gemeentelijk
Gegevensmodel (GGM) of OpenMetadata.

---

## Hoe kun je bijdragen?

### Bugs melden en vragen stellen

[Open een issue](../../issues) voor:
- Fouten of onverwacht gedrag in de scripts
- Onjuiste mappings in de JSON-bronbestanden (verkeerd domein, ontbrekende
  definitie, foutieve disambiguatie-suffix)
- Vragen over het aanpassen van de pipeline voor een andere gemeente of
  GGM-versie

Voeg bij een bug graag toe:
- Het commando dat je hebt gedraaid (inclusief vlaggen)
- De relevante outputregels (met name regels met `FOUT`)
- Je OpenMetadata-versie
- Je Python-versie (`python3 --version`)

### Verbeteringen en nieuwe functies

Open eerst een issue om je idee te bespreken voordat je een pull request
indient. Zo voorkom je dubbel werk en kun je afstemmen of de wijziging past
binnen de scope van het project.

Goede kandidaten voor bijdragen:
- **Extractiescripts verfijnen**: `extract_ggm.py` genereert de JSON-bronbestanden
  automatisch, maar bij een nieuwe GGM-versie kunnen er aanpassingen nodig zijn
  aan de extractielogica of de databereiniging
- **Nieuwe GGM-versie**: bijgewerkte handmatige bronbestanden (`ggm_definities.json`,
  `ggm_pad_naar_domain.json`, `ggm_naam_disambiguatie.json`) voor een nieuwe
  GGM-release in een nieuwe `data/vX.Y.Z/`-map
- **Gemeente-specifieke aanpassingen**: voorbeelden van `DOMAIN_FQN_OVERRIDES`
  of gefilterde objecttype-sets voor een specifieke gemeente
- **OpenMetadata-versiecompatibiliteit**: fixes of notities voor nieuwere
  OM-versies
- **PII-/classificatielaag**: koppeling van GGM-attributen aan AVG-categorieën
  of Woo-informatiecategorieën

### Documentatie

Correcties in de README, CHANGELOG of scriptdocstrings zijn altijd welkom.

---

## Lokaal aan de slag

```bash
git clone https://github.com/FritsdeGroot/ggm-naar-openmetadata-.git
cd ggm-naar-openmetadata-
pip install requests --break-system-packages
```

Omgevingsvariabelen instellen:
```bash
export OM_HOST="http://<jouw-openmetadata-host>:8585"
export OM_JWT_TOKEN="<jouw-bot-token>"
```

Bronbestanden genereren voor de versie die je wilt testen:
```bash
python3 extract_ggm.py --versie v2.5.1
```

Test altijd eerst op een klein domein voordat je `--alle` draait:
```bash
python3 ggm_objecttypen_naar_openmetadata.py --versie v2.5.1 --domein "Economie" --met-attributen --met-relaties
```

---

## Checklist voor een pull request

- [ ] Scripts zijn getest tegen een draaiende OpenMetadata-instantie voor de
      betreffende domeinen (ook een lokale Docker CE-instantie volstaat)
- [ ] Gewijzigde JSON-bronbestanden zijn gevalideerd met `python3 -c
      "import json; json.load(open('bestand.json'))"`
- [ ] De sectie `[Unreleased]` in `CHANGELOG.md` is bijgewerkt met een korte
      omschrijving van de wijziging
- [ ] Geen XMI-bestanden, logbestanden of `*_raw.json`-tussenbestanden meegecommit
      (zie `.gitignore`)
- [ ] Commit-berichten zijn in het Engels en beschrijven *wat* er is gewijzigd
      en *waarom*

---

## Aanpassen voor een andere gemeente

Deze pipeline is ontwikkeld op basis van GGM v2.5.1 van Gemeente Delft. Voor
een andere gemeente met dezelfde GGM-versie:

1. Zet een eigen OpenMetadata-instantie op en stel `OM_HOST` en `OM_JWT_TOKEN` in
2. Genereer de bronbestanden: `python3 extract_ggm.py --versie v2.5.1`
3. De handmatige bronbestanden in `data/v2.5.1/` zijn GGM-versie-specifiek en
   gemeente-onafhankelijk — die kun je ongewijzigd hergebruiken
4. Controleer of gemeente-specifieke domeinnaaminstellingen nodig zijn in
   `DOMAIN_FQN_OVERRIDES` (in `ggm_objecttypen_naar_openmetadata.py`)
5. Draai de pipeline zoals beschreven in de README

Voor een **nieuwe GGM-versie**, zie de sectie "Bij een nieuwe GGM-versie" in
de README.

---

## Codestijl

- Python: volg de bestaande stijl (PEP 8, beschrijvende variabelenamen in het
  Nederlands waar consistent met het domein, Engels elders)
- JSON-bestanden: opgemaakt met `indent=2` en `ensure_ascii=False`
- Commit-berichten: Engels

---

## Licentie

Door een pull request in te dienen ga je ermee akkoord dat je bijdrage wordt
gepubliceerd onder de [EUPL 1.2](LICENSE).
