# Repository Guidelines

## Project Structure & Module Organization

Root scripts are the pipeline; shared Python belongs in `gnosia_common.py`, and `parches/*.parche` is the source of truth. Markdown/JSON define terminology and layout.

`out/`, `work/`, and `tmp/` are ignored artifacts.

## Translation Prerequisites

Before any repository change, read `README.md`, `GUIA_EDITORIAL.md`, and `VOCES_PERSONAJES.md`. Their workflow, terminology, style, and voices are mandatory. Preserve documented voices; resolve conflicts before editing.

## Original Content Firewall — Absolute Rule

Never commit original or extracted game content: text, textures, audio, screenshots, binaries, fixtures, or revealing reports. Keep it in ignored directories.

Store only hash/ID-addressed patches with contributor-owned replacements. Never include original payload, context, recoverable textures, or unified diffs exposing game content. Inspect changes before staging.

## Game Asset Safety

Treat `../Gnosia_Data/` as read-only; build only in `tmp/`. Publish with `instalar.bash`, which verifies hashes, preserves backups, and journals installation. Never overwrite backups or bypass unknown-file guards. Steam Deck mode may stream verified originals between owned installations; keep them, saves, and backups outside repository paths.

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

Use `bash instalar.bash --build-only` to validate, `bash instalar.bash` to install, and `bash instalar.bash --restore` to recover. Add `--steam-deck USER@HOST` for the same remote actions.

## Coding Style & Naming Conventions

Use four-space indentation, UTF-8, type hints, and `pathlib.Path` in Python. Use `snake_case` for functions and variables, `PascalCase` for classes, and `UPPER_SNAKE_CASE` for constants. Keep CLI parsing in `parse_args()` and integer exit codes from `main()`.

Preserve patch lines as `<hash>:<id>:<translation>`, including placeholders, escapes, and line breaks.

Keep structural caps: `CharaText` notes 82×59; command-list labels 47×19; `ScenarioBaseText` commands 52×20. Use short label `Instar a proclamar`; prose uses `proclamarse`, never physical movement. Exclude filler, dialogue, and duplicate hashes elsewhere.

## Testing Guidelines

No unit-test framework or coverage threshold exists. Treat audits and `validar.py` round trips as integration tests; builds require `hard_fail=0`. Never record source literals in reports.

## Commit & Pull Request Guidelines

History uses short Spanish subjects without Conventional Commit prefixes. Keep commits focused. PRs should identify affected entities/code paths, list validation, and link issues. Screenshots must contain no original game content.
