# Repository Guidelines

## Project Structure & Module Organization

Root Python scripts implement the translation pipeline; shared parsing and serialization belong in `gnosia_common.py`. A C# helper patches runtime grammar. `parches/*.parche` is the versioned translation source of truth. Editorial, terminology, and layout rules live in the Markdown and JSON guides.

`out/`, `work/`, and `tmp/` are ignored local artifacts.

## Original Content Firewall — Absolute Rule

No original or extracted game content may enter the repository or Git history. This includes source-language text, textures, sprites, audio, screenshots, serialized blobs, assets, DLLs, fixtures, and reports containing any of them. Keep such material only in ignored local directories.

Represent every conversion as a minimal hash/ID-addressed patch or delta containing only contributor-authored replacements. Never include original-side payload, contextual source lines, or recoverable texture data; ordinary unified diffs are unsuitable when their removed/context lines expose game content. Before staging, inspect modified and untracked files for leaks.

## Game Asset Safety

Treat `../Gnosia_Data/` as read-only during development and build only in `tmp/`. Publish solely with `instalar.bash`, which verifies source hashes, preserves canonical backups, and journals installation. Never overwrite backups or bypass unknown-file guards.

## Build, Test, and Development Commands

Set up Python with:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Run `python aplicar_parches.py`, edit only `texts[1]` under `work/entities/`, then persist changes with `python exportar_parches.py`. Check them with:

```bash
python auditar_traduccion.py --work-manifest work/manifest.json
python auditar_consistencia.py --report-dir tmp/qa_consistencia
python cobertura_traduccion.py --details
```

Use `bash instalar.bash --build-only` to build and validate, `bash instalar.bash` to install, and `bash instalar.bash --restore` to recover originals.

## Coding Style & Naming Conventions

Use four-space indentation, UTF-8, type hints, `pathlib.Path`, and future annotations in Python. Use `snake_case` for functions and variables, `PascalCase` for classes, and `UPPER_SNAKE_CASE` for constants. Keep CLI parsing in `parse_args()` and return integer exit codes from `main()`. Match surrounding PEP 8-style code.

Preserve patch lines as `<hash>:<id>:<translation>`, including placeholders, escapes, and line breaks.

## Testing Guidelines

There is no unit-test framework or coverage threshold. Treat audit scripts and `validar.py` round trips as integration tests; usable builds require `hard_fail=0`. Audit both materialized text and runtime-generated grammar without recording source literals in reports.

## Commit & Pull Request Guidelines

History uses short Spanish subjects without Conventional Commit prefixes. Keep commits focused. PRs should identify affected entities or code paths, list validation results, and link issues. Include screenshots only when they contain no original game content.
