from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
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

CHARATEXT_COMMENT_LABELS = {
    "Takashi": "Takashi",
    "Cipi": "Chipie (Cipi)",
    "Comet": "Comet",
    "Gina": "Gina",
    "Jonas": "Jonas",
    "Kukulsika": "Kukrushka (Kukulsika)",
    "Otome": "Otome",
    "Rakio": "Raqio (Rakio)",
    "Remnant": "Remnan (Remnant)",
    "Setsu": "Setsu",
    "ShaMin": "Sha-Ming (ShaMin)",
    "Shigemichi": "Shigemichi",
    "SQ": "SQ",
    "Stella": "Stella",
    "Yuriko": "Yuriko",
}


@dataclass(frozen=True)
class ManualCommentBlock:
    order: int
    sheet_name: str
    anchor_key: tuple[str, int]
    lines: tuple[str, ...]


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


def load_manual_comment_blocks(
    patch_path: Path,
    target_index: dict[tuple[str, int], dict[str, object]],
) -> list[ManualCommentBlock]:
    if not patch_path.exists():
        return []

    blocks: list[ManualCommentBlock] = []
    pending_comments: list[str] = []
    order = 0
    for line_number, raw_line in enumerate(patch_path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            pending_comments.append(raw_line.rstrip("\n"))
            continue

        hash_key, duplicate_id, _ = parse_patch_line(
            raw_line,
            patch_path=patch_path,
            line_number=line_number,
        )
        key = (hash_key, duplicate_id)
        target = target_index.get(key)
        if target is None:
            raise SystemExit(f"Unresolved patch key in {patch_path}:{line_number}: {hash_key}:{duplicate_id}")
        if pending_comments:
            blocks.append(
                ManualCommentBlock(
                    order=order,
                    sheet_name=str(target["sheet_name"]),
                    anchor_key=key,
                    lines=tuple(pending_comments),
                )
            )
            order += 1
            pending_comments = []

    return blocks


def comment_label(entity_name: str, sheet_name: str) -> str:
    if entity_name == "CharaText":
        return CHARATEXT_COMMENT_LABELS.get(sheet_name, sheet_name)
    return sheet_name


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
    existing_comments_by_entity: dict[str, list[ManualCommentBlock]] = {}
    for path_id, source_entity in sorted(source_by_path.items()):
        patch_path = patch_dir / patch_filename(source_entity.entity_name)
        if not patch_path.exists():
            continue
        existing_comments_by_entity[source_entity.entity_name] = load_manual_comment_blocks(
            patch_path,
            build_patch_target_index(source_entity),
        )

    for existing in patch_dir.glob("*.parche"):
        existing.unlink()

    written_files = 0
    written_entries = 0
    for path_id, source_entity in sorted(source_by_path.items()):
        work_entity = work_by_path.get(path_id)
        if work_entity is None:
            raise SystemExit(f"Missing work entity for path_id={path_id}")

        targets = build_patch_target_index(source_entity)
        translated_entries: list[dict[str, object]] = []
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
            translated_entries.append(
                {
                    "key": (hash_key, duplicate_id),
                    "sheet_name": str(target["sheet_name"]),
                    "sheet_index": int(target["sheet_index"]),
                    "param_index": int(target["param_index"]),
                    "line": f"{hash_key}:{duplicate_id}:{payload}",
                }
            )

        if not translated_entries:
            continue

        present_keys = {entry["key"] for entry in translated_entries}
        comments = existing_comments_by_entity.get(source_entity.entity_name, [])
        anchored_blocks: dict[tuple[str, int], list[ManualCommentBlock]] = {}
        orphan_blocks_by_sheet: dict[str, list[ManualCommentBlock]] = {}
        for block in comments:
            if block.anchor_key in present_keys:
                anchored_blocks.setdefault(block.anchor_key, []).append(block)
            else:
                orphan_blocks_by_sheet.setdefault(block.sheet_name, []).append(block)

        lines: list[str] = []
        emitted_comment_orders: set[int] = set()
        seen_sheet_names: set[str] = set()
        for entry in translated_entries:
            sheet_name = str(entry["sheet_name"])
            key = entry["key"]
            is_first_for_sheet = sheet_name not in seen_sheet_names

            if is_first_for_sheet:
                for block in sorted(orphan_blocks_by_sheet.get(sheet_name, []), key=lambda item: item.order):
                    if block.order in emitted_comment_orders:
                        continue
                    lines.extend(block.lines)
                    emitted_comment_orders.add(block.order)

            anchored_for_key = [
                block
                for block in sorted(anchored_blocks.get(key, []), key=lambda item: item.order)
                if block.order not in emitted_comment_orders
            ]
            if anchored_for_key:
                for block in anchored_for_key:
                    lines.extend(block.lines)
                    emitted_comment_orders.add(block.order)
            elif is_first_for_sheet and not orphan_blocks_by_sheet.get(sheet_name):
                lines.append(f"# {comment_label(source_entity.entity_name, sheet_name)}")

            lines.append(str(entry["line"]))
            seen_sheet_names.add(sheet_name)

        patch_path = patch_dir / patch_filename(source_entity.entity_name)
        patch_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        written_files += 1
        written_entries += len(translated_entries)

    print(f"Patch files written: {written_files}")
    print(f"Translated entries exported: {written_entries}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
