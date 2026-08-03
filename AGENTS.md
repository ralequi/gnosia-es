# Repository Guidelines

## Project Structure & Module Organization

This repository contains Python tooling and versioned Spanish translation patches for GNOSIA. Root-level scripts each cover one pipeline stage; shared parsing, serialization, and path helpers belong in `gnosia_common.py`. `parches/*.parche` is the versioned source of truth for translations. Editorial rules live in `GUIA_EDITORIAL.md`, character guidance in `VOCES_PERSONAJES.md`, and fixed terminology in `glosario_v1.json`. `layout_rules.json` defines UI constraints.

`out/`, `work/`, and `tmp/` contain extracted, editable, or generated artifacts. They are ignored and must never be committed, nor should original `.assets` files or copyrighted game text be added to Git.

## Build, Test, and Development Commands

Create the environment with:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Run `python extractor.py` once against a legally obtained game asset. Use `python aplicar_parches.py` to recreate `work/` from `out/`, edit only `texts[1]` in `work/entities/*.json`, then run `python exportar_parches.py` to persist changes. Check quality with:

```bash
python auditar_traduccion.py --work-manifest work/manifest.json
python auditar_consistencia.py --report-dir tmp/qa_consistencia
python cobertura_traduccion.py --details
```

Build blobs with `python reconstructor.py --manifest work/manifest.json --out-dir tmp/work_reconstructed`. See `README.md` for the complete repack and `validar.py --mode edited` commands, which require paths to local game assets.

## Coding Style & Naming Conventions

Use four-space indentation, UTF-8, type hints, `pathlib.Path`, and `from __future__ import annotations`. Follow existing Python naming: `snake_case` for functions and variables, `PascalCase` for dataclasses, and `UPPER_SNAKE_CASE` for constants. Keep CLI parsing in `parse_args()` and return integer exit codes from `main()`. No formatter or linter is configured; match the surrounding PEP 8-style code.

Preserve patch lines as `<hash>:<id>:<translation>` and retain placeholders (`{0}`), escapes, and line breaks exactly.

## Testing Guidelines

There is no unit-test framework or coverage threshold. Treat the audit scripts and `validar.py` round-trip checks as integration tests. A usable translation must report `hard_fail=0`. If adding isolated tests, place `test_*.py` files under `tests/` and document any new test dependency.

## Commit & Pull Request Guidelines

History uses short Spanish, sentence-style subjects such as `pequeñas mejoras`; no Conventional Commit prefixes are used. Keep commits focused on one tool or translation group. PRs should describe affected entities, list commands run and audit results, link relevant issues, and include screenshots for visible UI changes. Never attach original game assets or reports containing source-game text.
