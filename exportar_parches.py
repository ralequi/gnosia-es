from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from gnosia_common import (  # noqa: E402
    OUTPUT_DIR,
    PATCH_DIR,
    WORK_DIR,
    build_patch_target_index,
    decode_corpus_text,
    ensure_dir,
    escape_patch_text,
    load_entities_from_manifest,
    patch_filename,
    summarize_entities,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export translated EN-overrides as hash-based patch files.")
    parser.add_argument(
        "--source-manifest",
        type=Path,
        default=OUTPUT_DIR / "manifest.json",
        help="Manifest with the extracted source snapshot.",
    )
    parser.add_argument(
        "--work-manifest",
        type=Path,
        default=WORK_DIR / "manifest.json",
        help="Manifest with the local translated work corpus.",
    )
    parser.add_argument(
        "--patch-dir",
        type=Path,
        default=PATCH_DIR,
        help="Destination directory for *.parche files.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_manifest, source_entities = load_entities_from_manifest(args.source_manifest)
    work_manifest, work_entities = load_entities_from_manifest(args.work_manifest)

    del source_manifest
    del work_manifest

    if summarize_entities(source_entities) != summarize_entities(work_entities):
        raise SystemExit("Source and work corpora do not share the same structure.")

    source_by_path = {entity.path_id: entity for entity in source_entities}
    work_by_path = {entity.path_id: entity for entity in work_entities}

    patch_dir = ensure_dir(args.patch_dir)
    for existing in patch_dir.glob("*.parche"):
        existing.unlink()

    written_files = 0
    written_entries = 0
    for path_id, source_entity in sorted(source_by_path.items()):
        work_entity = work_by_path.get(path_id)
        if work_entity is None:
            raise SystemExit(f"Missing work entity for path_id={path_id}")

        targets = build_patch_target_index(source_entity)
        lines: list[str] = []
        for (hash_key, duplicate_id), target in sorted(
            targets.items(),
            key=lambda item: (item[1]["sheet_index"], item[1]["param_index"]),
        ):
            sheet_index = int(target["sheet_index"])
            param_index = int(target["param_index"])
            source_text = source_entity.sheets[sheet_index].params[param_index][1]
            work_text = work_entity.sheets[sheet_index].params[param_index][1]
            if work_text == source_text:
                continue
            logical_text = decode_corpus_text(work_text)
            payload = escape_patch_text(logical_text)
            lines.append(f"{hash_key}:{duplicate_id}:{payload}")

        if not lines:
            continue

        patch_path = patch_dir / patch_filename(source_entity.entity_name)
        patch_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        written_files += 1
        written_entries += len(lines)

    print(f"Patch files written: {written_files}")
    print(f"Translated entries exported: {written_entries}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
