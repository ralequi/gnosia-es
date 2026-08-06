# Repository Guidelines

## Project Structure & Module Organization

Root Python scripts implement the pipeline; put shared code in `gnosia_common.py`. `parches/*.parche` is the source of truth. Markdown/JSON files define terminology and layout rules.

`out/`, `work/`, and `tmp/` are ignored local artifacts.

## Original Content Firewall — Absolute Rule

No original or extracted game content may enter the repository or Git history: text, textures, audio, screenshots, binaries, fixtures, or revealing reports. Keep it in ignored directories.

Store only hash/ID-addressed patches containing contributor-owned replacements. Never include original payload, context, recoverable textures, or unified diffs exposing game content. Inspect changes before staging.

## Game Asset Safety

Treat `../Gnosia_Data/` as read-only and build only in `tmp/`. Publish with `instalar.bash`, which verifies hashes, preserves backups, and journals installation. Never overwrite backups or bypass unknown-file guards. Steam Deck mode may stream verified originals between owned installations; never stage them, saves, or backups in repository paths.

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

Keep caps structural: 82 visible `CharaText` notes allow 59 logical characters; 52 visible `ScenarioBaseText` command names allow 19. Translate the role-request action as `Instar a declararse`; related copy describes declaring a role, never physical movement. Exclude filler, dialogue, and duplicate hashes in other entities.

## Testing Guidelines

There is no unit-test framework or coverage threshold. Treat audits and `validar.py` round trips as integration tests; usable builds require `hard_fail=0`. Audit materialized text and runtime grammar without recording source literals in reports.

## Commit & Pull Request Guidelines

History uses short Spanish subjects without Conventional Commit prefixes. Keep commits focused. PRs should identify affected entities or code paths, list validation results, and link issues. Include screenshots only when they contain no original game content.
