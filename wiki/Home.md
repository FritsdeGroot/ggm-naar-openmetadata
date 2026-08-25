# GGM naar OpenMetadata — Beheerhandleiding

Scripts en bronbestanden om het **Gemeentelijk Gegevensmodel (GGM)** te laden in een self-hosted **OpenMetadata Community Edition**-omgeving via de REST API.

---

## Inhoudsopgave

| Hoofdstuk | Onderwerp |
|---|---|
| [1. Overzicht](1.-Overzicht) | Het laadproces in vier stappen |
| [2. Bestandsoverzicht](2.-Bestandsoverzicht) | Scripts en bronbestanden |
| [3. Scenario A — Nieuwe gemeente](3.-Scenario-A-Nieuwe-gemeente) | Zelfde GGM-versie, nieuwe omgeving |
| [4. Scenario B — Nieuwe GGM-versie](4.-Scenario-B-Nieuwe-GGM-versie) | Bijwerken naar een nieuwe GGM-release |
| [5. Validatie](5.-Validatie) | Controleer het resultaat na elke run |
| [6. Hulpcommando's](6.-Hulpcommandos) | OpenMetadata API-commando's |
| [7. Bekende foutpatronen](7.-Bekende-foutpatronen) | Fouten en oplossingen |
| [8. Naamconventies](8.-Naamconventies) | Objecttypen, attributen en disambiguatie |
| [9. Attributenlaag](9.-Attributenlaag) | Child glossary terms per objecttype |
| [10. Relaties tussen objecttypen](10.-Relaties-tussen-objecttypen) | uml:Association als relatedTerms |
| [11. Checklist](11.-Checklist) | Snelle samenvatting per scenario |

---

## Vereisten

- Python 3.9+
- `sudo apt-get install python3-yaml` of `pip install pyyaml --break-system-packages`
- `pip install requests --break-system-packages`
- Self-hosted **OpenMetadata 2.x** Community Edition  
  ⚠️ Versie 1.x wordt **niet** ondersteund — de `relatedTerms` API is gewijzigd tussen 1.x en 2.x
- Een bot/service-account met `Create`/`EditAll`/`ViewAll`-rechten op: Domain, Glossary, GlossaryTerm, Classification en Tag

## Snel starten

```bash
git clone https://github.com/FritsdeGroot/ggm-naar-openmetadata-.git
cd ggm-naar-openmetadata-

python3 extract_ggm.py --versie v2.5.1

export OM_HOST="http://<jouw-openmetadata-ip>:8585"
export OM_JWT_TOKEN="<jwt-token-van-de-bot>"

python3 ggm_naar_openmetadata_domains.py --versie v2.5.1
python3 ggm_objecttypen_naar_openmetadata.py --versie v2.5.1 --alle --met-attributen --met-relaties
```
