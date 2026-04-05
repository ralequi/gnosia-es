from __future__ import annotations

import argparse
import re
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
    create_work_corpus_from_manifest,
    decode_corpus_text,
    encode_text_like_source_style,
    entity_to_dict,
    load_entities_from_manifest,
    summarize_entities,
    unescape_patch_text,
    write_json,
)

PLACEHOLDER_RE = re.compile(r"\{[^}]+\}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Materialize work/ from out/ plus *.parche files.")
    parser.add_argument(
        "--source-manifest",
        type=Path,
        default=OUTPUT_DIR / "manifest.json",
        help="Manifest with the extracted source snapshot.",
    )
    parser.add_argument(
        "--patch-dir",
        type=Path,
        default=PATCH_DIR,
        help="Directory containing *.parche files.",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=WORK_DIR,
        help="Destination work directory to regenerate.",
    )
    return parser.parse_args()


def parse_patch_line(line: str, *, patch_path: Path, line_number: int) -> tuple[str, int, str]:
    parts = line.split(":", 2)
    if len(parts) != 3:
        raise ValueError(f"{patch_path}:{line_number}: expected hash:id:traduccion")
    hash_key, duplicate_id_raw, payload = parts
    if not hash_key:
        raise ValueError(f"{patch_path}:{line_number}: empty hash")
    try:
        duplicate_id = int(duplicate_id_raw)
    except ValueError as exc:
        raise ValueError(f"{patch_path}:{line_number}: invalid id {duplicate_id_raw!r}") from exc
    if duplicate_id < 0:
        raise ValueError(f"{patch_path}:{line_number}: id must be >= 0")
    return hash_key, duplicate_id, payload


def placeholder_sets(*texts: str) -> tuple[set[str], set[str]]:
    decoded = [decode_corpus_text(text) for text in texts]
    required = set(PLACEHOLDER_RE.findall(decoded[1]))
    allowed = set()
    for text in decoded:
        allowed.update(PLACEHOLDER_RE.findall(text))
    return required, allowed


def main() -> int:
    args = parse_args()
    create_work_corpus_from_manifest(
        source_manifest_path=args.source_manifest,
        work_dir=args.work_dir,
        force=True,
    )

    source_manifest, source_entities = load_entities_from_manifest(args.source_manifest)
    work_manifest, work_entities = load_entities_from_manifest(args.work_dir / "manifest.json")

    del source_manifest

    if summarize_entities(source_entities) != summarize_entities(work_entities):
        raise SystemExit("Source and work corpora do not share the same structure.")

    source_by_name = {entity.entity_name: entity for entity in source_entities}
    work_by_name = {entity.entity_name: entity for entity in work_entities}

    applied_entries = 0
    touched_entities: set[str] = set()
    for patch_path in sorted(args.patch_dir.glob("*.parche")):
        entity_name = patch_path.stem
        source_entity = source_by_name.get(entity_name)
        work_entity = work_by_name.get(entity_name)
        if source_entity is None or work_entity is None:
            raise SystemExit(f"Patch file does not map to a known entity: {patch_path.name}")

        target_index = build_patch_target_index(source_entity)
        seen_keys: set[tuple[str, int]] = set()
        for line_number, raw_line in enumerate(patch_path.read_text(encoding="utf-8").splitlines(), start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            hash_key, duplicate_id, payload = parse_patch_line(
                raw_line,
                patch_path=patch_path,
                line_number=line_number,
            )
            key = (hash_key, duplicate_id)
            if key in seen_keys:
                raise SystemExit(f"Duplicate patch key in {patch_path}:{line_number}: {hash_key}:{duplicate_id}")
            seen_keys.add(key)

            target = target_index.get(key)
            if target is None:
                raise SystemExit(f"Unresolved patch key in {patch_path}:{line_number}: {hash_key}:{duplicate_id}")

            logical_translation = unescape_patch_text(payload)
            sheet_index = int(target["sheet_index"])
            param_index = int(target["param_index"])
            source_text = source_entity.sheets[sheet_index].params[param_index][1]
            required_placeholders, allowed_placeholders = placeholder_sets(
                source_entity.sheets[sheet_index].params[param_index][0],
                source_text,
                source_entity.sheets[sheet_index].params[param_index][2],
            )
            translated_placeholders = set(PLACEHOLDER_RE.findall(logical_translation))

            if (
                not required_placeholders.issubset(translated_placeholders)
                or not translated_placeholders.issubset(allowed_placeholders)
            ):
                raise SystemExit(
                    f"{patch_path}:{line_number}: placeholder mismatch for {entity_name} "
                    f"{target['sheet_name']}#{param_index}"
                )
            work_entity.sheets[sheet_index].params[param_index][1] = encode_text_like_source_style(
                source_text=source_text,
                logical_text=logical_translation,
            )
            applied_entries += 1
            touched_entities.add(entity_name)

    entity_by_path = {entity.path_id: entity for entity in work_entities}
    for entry in work_manifest["entities"]:
        entity = entity_by_path[int(entry["path_id"])]
        write_json(args.work_dir / entry["file"], entity_to_dict(entity))

    print(f"Work corpus regenerated at: {args.work_dir}")
    print(f"Patches applied: {applied_entries}")
    print(f"Entities touched: {len(touched_entities)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
