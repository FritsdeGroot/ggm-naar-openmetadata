# GGM naar OpenMetadata

Scripts om het **Gemeentelijk Gegevensmodel (GGM)** van [Gemeente Delft](https://github.com/Gemeente-Delft/Gemeentelijk-Gegevensmodel) te laden in een **self-hosted OpenMetadata Community Edition**-omgeving via de REST API.

Het resultaat is een doorzoekbare, domeingestructureerde **data-glossary** met:
- **~947 objecttypen** als Glossary Terms, elk gekoppeld aan hun (sub)domein en hoofddomein-tag (exact aantal afhankelijk van de GGM-versie en extractie)
- **~4500 attributen** als child Glossary Terms (met type, definitie en eventuele waardelijst)
- **425 relaties** tussen objecttypen (uit `uml:Association`) in de beschrijving en als klikbare `relatedTerms`
- **49 domeinen** als OpenMetadata Domains (hiërarchisch, conform de GGM-packagestructuur)

> **Achtergrond**: dit project is onderdeel van de aanpak om een gemeentelijke metadata-/MCP-voorziening te bouwen die GGM-objecttypen, AVG-/PII-classificaties en Woo-informatiecategorieën met elkaar verbindt. De data-glossary vormt daarvoor de basislaag.

---

## Vereisten

- Python 3.9+
- `pip install requests --break-system-packages`
- Self-hosted OpenMetadata Community Edition versie 2.x (getest op 2.0). Let op: versie 1.x wordt niet ondersteund — de relatedTerms API is gewijzigd tussen 1.x en 2.x.
- Een bot/service-account met `Create`/`EditAll`/`ViewAll`-rechten op: Domain, Glossary, GlossaryTerm, Classification en Tag

---

## Snel aan de slag

```bash
# 0. Repository ophalen
git clone https://github.com/FritsdeGroot/ggm-naar-openmetadata-.git
cd ggm-naar-openmetadata-

# 1. Bronbestanden genereren uit de GGM-repo → opgeslagen in data/v2.5.1/
python3 extract_ggm.py --versie v2.5.1

# 2. Omgevingsvariabelen instellen
export OM_HOST="http://<jouw-openmetadata-ip>:8585"
export OM_JWT_TOKEN="<jwt-token-van-de-bot>"

# 3. Domeinstructuur laden
python3 ggm_naar_openmetadata_domains.py --versie v2.5.1

# 4. Objecttypen, attributen en relaties laden
python3 ggm_objecttypen_naar_openmetadata.py --versie v2.5.1 --alle --met-attributen --met-relaties
```

> Gebruik altijd `http://` als je OpenMetadata-instantie geen TLS gebruikt. Een `https://`-URL op een plain-HTTP-poort geeft een `SSL: RECORD_LAYER_FAILURE`-fout bij de eerste API-aanroep.

---

## Repository-structuur

```
ggm-naar-openmetadata/
│
├── extract_ggm.py                        # Downloadt GGM XMI → genereert JSON-bronbestanden
├── ggm_naar_openmetadata_domains.py      # Laadt domeinstructuur als OpenMetadata Domains
├── ggm_objecttypen_naar_openmetadata.py  # Hoofdscript: objecttypen + attributen + relaties
├── ggm_domeinen_naar_skos.py             # Genereert SKOS-domeinschema uit mkdocs.yml
│
└── data/
    └── v2.5.1/                           # Handmatig bijgehouden bestanden per GGM-versie
        ├── ggm_definities.json           # Domeindefinities (afgeleid uit GGM README.md)
        ├── ggm_pad_naar_domain.json      # XMI-packagepad → OpenMetadata Domain FQN
        └── ggm_naam_disambiguatie.json   # 136 disambiguaties voor niet-unieke objecttypenamen
```

> **Gegenereerde bestanden** (`ggm_objecttypen.json`, `ggm_attributen.json`,
> `ggm_relaties_per_object.json`, `ggm_domeinen_skos.jsonld`) worden door
> `extract_ggm.py` ook in `data/v2.5.1/` geplaatst, maar staan in `.gitignore`
> — ze zijn altijd te reproduceren vanuit de officiële GGM-repo.

---

## Bestandsoverzicht

### Scripts

| Bestand | Functie |
|---|---|
| `extract_ggm.py` | Downloadt de GGM XMI en genereert alle JSON-bronbestanden in `data/<versie>/` |
| `ggm_naar_openmetadata_domains.py` | Laadt de domeinstructuur als OpenMetadata Domains |
| `ggm_objecttypen_naar_openmetadata.py` | Hoofdscript: objecttypen, attributen en relaties laden |
| `ggm_domeinen_naar_skos.py` | Genereert `ggm_domeinen_skos.jsonld` uit de GGM mkdocs.yml |

### Bronbestanden in `data/<versie>/`

| Bestand | In repo? | Inhoud |
|---|---|---|
| `ggm_definities.json` | ✅ ja | Domeindefinities (handmatig bijgehouden) |
| `ggm_pad_naar_domain.json` | ✅ ja | XMI-packagepad → OpenMetadata Domain FQN (handmatig bijgehouden) |
| `ggm_naam_disambiguatie.json` | ✅ ja | 136 disambiguaties voor niet-unieke objecttypenamen (handmatig bijgehouden) |
| `ggm_objecttypen.json` | ❌ gegenereerd | ~947 objecttypen met naam, definitie, pad, attributen en domein (exact aantal afhankelijk van GGM-versie) |
| `ggm_attributen.json` | ❌ gegenereerd | ~4500 attributen met type, definitie, waardelijst en objecttype-referenties |
| `ggm_relaties_per_object.json` | ❌ gegenereerd | 425 relaties (uit `uml:Association`), per objecttype gegroepeerd |
| `ggm_domeinen_skos.jsonld` | ❌ gegenereerd | SKOS-conceptenschema van de volledige domeinstructuur |

---

## extract_ggm.py — opties

```bash
# Versie-tag (genereert naar data/v2.5.1/)
python3 extract_ggm.py --versie v2.5.1

# Branch
python3 extract_ggm.py --branch master

# Aangepaste uitvoermap
python3 extract_ggm.py --versie v2.5.1 --uitvoer ./mijn-data

# Lokaal XMI-bestand gebruiken (geen download)
python3 extract_ggm.py --versie v2.5.1 --xmi /pad/naar/model.xml

# Alleen downloaden, niet genereren
python3 extract_ggm.py --versie v2.5.1 --alleen-downloaden
```

---

## ggm_objecttypen_naar_openmetadata.py — alle opties

| Vlag | Beschrijving |
|---|---|
| `--versie <tag>` | GGM-versie — bepaalt automatisch `data/<versie>/` als datamap |
| `--list` | Toon beschikbare hoofddomeinen en stop |
| `--domein <naam>` | Laad één specifiek hoofddomein |
| `--alle` | Laad alle domeinen |
| `--met-attributen` | Laad attributen als child glossary terms |
| `--met-relaties` | Voeg relaties toe aan beschrijving + relatedTerms |
| `--forceer-omschrijving` | Werk beschrijving bij bij bestaande termen als deze is gewijzigd |
| `--data` | Pad naar `ggm_objecttypen.json` (overschrijft `--versie`) |
| `--mapping` | Pad naar `ggm_pad_naar_domain.json` (overschrijft `--versie`) |
| `--namen` | Pad naar `ggm_naam_disambiguatie.json` (overschrijft `--versie`) |
| `--attributen` | Pad naar `ggm_attributen.json` (overschrijft `--versie`) |
| `--relaties` | Pad naar `ggm_relaties_per_object.json` (overschrijft `--versie`) |

> **Tip**: schrijf de output weg voor controle achteraf:
> ```bash
> python3 ggm_objecttypen_naar_openmetadata.py --versie v2.5.1 --alle \
>   --met-attributen --met-relaties 2>&1 | tee run_$(date +%Y%m%d_%H%M%S).log
> grep -c "FOUT" run_*.log
> ```

Alle scripts zijn **idempotent**: opnieuw draaien is veilig.

---

## Bij een nieuwe GGM-versie

```bash
# Stap 1: genereer bronbestanden voor nieuwe versie (in data/v2.6.0/)
python3 extract_ggm.py --versie v2.6.0

# Stap 2: kopieer handmatige bestanden als startpunt en pas aan waar nodig
cp data/v2.5.1/ggm_definities.json        data/v2.6.0/
cp data/v2.5.1/ggm_pad_naar_domain.json   data/v2.6.0/
cp data/v2.5.1/ggm_naam_disambiguatie.json data/v2.6.0/
# → controleer naamcollisie-waarschuwingen uit stap 1
# → controleer ggm_pad_naar_domain.json op nieuwe packagepaden
# → update ggm_naam_disambiguatie.json voor nieuwe/gewijzigde collisies

# Stap 3: laad alles opnieuw
python3 ggm_naar_openmetadata_domains.py --versie v2.6.0
python3 ggm_objecttypen_naar_openmetadata.py --versie v2.6.0 \
  --alle --met-attributen --met-relaties --forceer-omschrijving
```

---

## Naamconventies

**Objecttypen** met een niet-unieke naam krijgen een subdomein-suffix:
`Pand (BAG)`, `Pand (RSGB)`, `Aanvraag (Inkomen - Diensten)` etc.

**Attribuut-child terms** gebruiken `"<Objecttype> <Attribuut>"` als naam
(bijv. `Raadslid naam`, `Pand (BAG) status`) — conform de
[OpenMetadata best practice](https://docs.open-metadata.org/latest/how-to-guides/data-governance/glossary/best-practices)
voor contextrijke termnamen. OpenMetadata's naam-validatie voor GlossaryTerm is
glossary-breed (niet per FQN), waardoor kale attribuutnamen als `naam`
of `status` na het eerste objecttype globaal conflicteren.

---

## Bronnen

- [Gemeentelijk Gegevensmodel (GGM) — Gemeente Delft](https://github.com/Gemeente-Delft/Gemeentelijk-Gegevensmodel)
- [OpenMetadata documentatie](https://docs.open-metadata.org)
- [OpenMetadata Glossary best practices](https://docs.open-metadata.org/latest/how-to-guides/data-governance/glossary/best-practices)
- [GEMMA — VNG Realisatie](https://www.gemmaonline.nl)

---

## Licentie

[EUPL 1.2](LICENSE)

Dit project is geen officieel product van Gemeente Delft of VNG. Het GGM zelf valt onder de licentievoorwaarden van de [GGM-repository](https://github.com/Gemeente-Delft/Gemeentelijk-Gegevensmodel).