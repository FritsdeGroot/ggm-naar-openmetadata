# Contributing

Thank you for your interest in this project. Contributions are welcome from
municipalities, data governance consultants, and anyone working with the
Gemeentelijk Gegevensmodel (GGM) or OpenMetadata.

---

## Ways to contribute

### Bug reports and questions

Please [open an issue](../../issues) for:
- Errors or unexpected behaviour in the scripts
- Incorrect mappings in the JSON source files (wrong domain, missing definition,
  incorrect disambiguation suffix)
- Questions about adapting the pipeline to a different municipality or GGM version

When reporting a bug, include:
- The command you ran (with flags)
- The relevant output lines (especially any `FOUT`-lines)
- Your OpenMetadata version
- Your Python version (`python3 --version`)

### Improvements and new features

Open an issue to discuss your idea before submitting a pull request. This helps
avoid duplicate effort and ensures the change fits the project's scope.

Good candidates for contributions:
- **Extraction scripts**: scripts to regenerate `ggm_objecttypen.json`,
  `ggm_attributen.json` and `ggm_relaties_per_object.json` from a new GGM XMI
  export are not yet in this repository — this is the most useful missing piece
- **New GGM version**: updated JSON source files for a newer GGM release
- **Municipality-specific overrides**: examples of `DOMAIN_FQN_OVERRIDES` or
  filtered objecttype sets for a specific municipality
- **OpenMetadata version compatibility**: fixes or notes for newer OM versions
- **PII/classification layer**: mapping GGM attributes to AVG categories or
  Woo information categories

### Documentation

Corrections to the README, CHANGELOG or inline script docstrings are always
welcome, including translations to Dutch.

---

## Development setup

```bash
git clone https://github.com/<your-org>/<this-repo>.git
cd <this-repo>
pip install requests --break-system-packages
```

Copy the environment variables to your shell:
```bash
export OM_HOST="http://<your-openmetadata-host>:8585"
export OM_JWT_TOKEN="<your-bot-token>"
```

Test against a single small domain before running `--alle`:
```bash
python3 ggm_objecttypen_naar_openmetadata.py --domein "Economie" --met-attributen --met-relaties
```

---

## Pull request checklist

- [ ] Scripts are tested against a running OpenMetadata instance (even a local
      Docker CE instance) for the affected domains
- [ ] JSON source files that change are validated with Python's `json.load()`
- [ ] The CHANGELOG.md `[Unreleased]` section is updated with a short description
      of the change
- [ ] No XMI files, log files or `*_raw.json` intermediates are committed
      (see `.gitignore`)
- [ ] Commit messages are in English and describe *what* changed and *why*

---

## Adapting to a different municipality

This pipeline was developed for Gemeente Delft's GGM v2.5.1. To use it for
another municipality with the same GGM version:

1. Set up a fresh OpenMetadata instance and configure `OM_HOST` / `OM_JWT_TOKEN`
2. All JSON source files are GGM-version-specific and municipality-independent —
   they can be reused as-is
3. Check whether municipality-specific domain name overrides are needed in
   `DOMAIN_FQN_OVERRIDES` (in `ggm_objecttypen_naar_openmetadata.py`)
4. Run the pipeline as described in the README

To use it with a **new GGM version**, see the "New GGM version" section in the
README and the extraction scripts (once available in the `extract/` directory).

---

## Code style

- Python: follow the existing style (PEP 8, descriptive variable names in Dutch
  where consistent with the domain, English elsewhere)
- JSON files: formatted with `indent=2`, `ensure_ascii=False`
- Commit language: English

---

## Licence

By submitting a pull request, you agree that your contribution will be licensed
under the [EUPL 1.2](LICENSE).
