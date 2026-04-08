from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from auditar_traduccion import is_translatable  # noqa: E402
from gnosia_common import OUTPUT_DIR, WORK_DIR, decode_corpus_text, load_entities_from_manifest, write_json  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Report translation coverage by entity and optionally by sheet."
    )
    parser.add_argument(
        "--source-manifest",
        type=Path,
        default=OUTPUT_DIR / "manifest.json",
        help="Snapshot manifest with the extracted source corpus.",
    )
    parser.add_argument(
        "--work-manifest",
        type=Path,
        default=WORK_DIR / "manifest.json",
        help="Work manifest with the currently materialized translation corpus.",
    )
    parser.add_argument(
        "--entity",
        action="append",
        default=[],
        help="Restrict output to one or more entity names. Can be used multiple times.",
    )
    parser.add_argument(
        "--details",
        action="store_true",
        help="Also show coverage by sheet.",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        help="Optional JSON output path.",
    )
    return parser.parse_args()


def coverage_percent(translated: int, total: int) -> float:
    if total == 0:
        return 100.0
    return (translated / total) * 100.0


def empty_bucket() -> dict[str, object]:
    return {
        "total": 0,
        "translated": 0,
        "remaining": 0,
        "remaining_entries": [],
    }


def add_remaining_entry(
    bucket: dict[str, object],
    *,
    entity_name: str,
    sheet_name: str,
    param_index: int,
    source_text: str,
) -> None:
    entries: list[dict[str, object]] = bucket["remaining_entries"]  # type: ignore[assignment]
    entries.append(
        {
            "entity_name": entity_name,
            "sheet_name": sheet_name,
            "param_index": param_index,
            "source_text": source_text,
        }
    )


def finalize_bucket(bucket: dict[str, object]) -> None:
    bucket["remaining"] = int(bucket["total"]) - int(bucket["translated"])
    bucket["percent"] = round(
        coverage_percent(int(bucket["translated"]), int(bucket["total"])),
        2,
    )


def print_bucket(name: str, bucket: dict[str, object], *, indent: str = "") -> None:
    print(
        f"{indent}{name:<24} "
        f"{bucket['percent']:>6.2f}%  "
        f"{bucket['translated']:>4}/{bucket['total']:<4}  "
        f"pendientes={bucket['remaining']}"
    )


def main() -> int:
    args = parse_args()
    requested_entities = set(args.entity)

    _, source_entities = load_entities_from_manifest(args.source_manifest)
    _, work_entities = load_entities_from_manifest(args.work_manifest)

    source_map = {entity.path_id: entity for entity in source_entities}
    work_map = {entity.path_id: entity for entity in work_entities}

    totals = empty_bucket()
    entity_report: list[dict[str, object]] = []

    for path_id, source_entity in sorted(source_map.items()):
        if requested_entities and source_entity.entity_name not in requested_entities:
            continue

        work_entity = work_map[path_id]
        entity_bucket = empty_bucket()
        sheet_report: list[dict[str, object]] = []

        for sheet_index, source_sheet in enumerate(source_entity.sheets):
            work_sheet = work_entity.sheets[sheet_index]
            sheet_bucket = empty_bucket()

            for param_index, source_param in enumerate(source_sheet.params):
                source_text = decode_corpus_text(source_param[1])
                if not is_translatable(source_text):
                    continue

                work_text = decode_corpus_text(work_sheet.params[param_index][1])
                translated = work_text != source_text

                for bucket in (totals, entity_bucket, sheet_bucket):
                    bucket["total"] = int(bucket["total"]) + 1
                    if translated:
                        bucket["translated"] = int(bucket["translated"]) + 1

                if not translated:
                    add_remaining_entry(
                        sheet_bucket,
                        entity_name=source_entity.entity_name,
                        sheet_name=source_sheet.name,
                        param_index=param_index,
                        source_text=source_text,
                    )
                    add_remaining_entry(
                        entity_bucket,
                        entity_name=source_entity.entity_name,
                        sheet_name=source_sheet.name,
                        param_index=param_index,
                        source_text=source_text,
                    )
                    add_remaining_entry(
                        totals,
                        entity_name=source_entity.entity_name,
                        sheet_name=source_sheet.name,
                        param_index=param_index,
                        source_text=source_text,
                    )

            finalize_bucket(sheet_bucket)
            if int(sheet_bucket["total"]) > 0:
                sheet_report.append(
                    {
                        "sheet_name": source_sheet.name,
                        **sheet_bucket,
                    }
                )

        finalize_bucket(entity_bucket)
        entity_report.append(
            {
                "entity_name": source_entity.entity_name,
                "path_id": source_entity.path_id,
                **entity_bucket,
                "sheets": sheet_report,
            }
        )

    finalize_bucket(totals)

    print("GNOSIA translation coverage")
    print_bucket("TOTAL", totals)
    print("")
    print("Por entidad:")
    for entity in entity_report:
        print_bucket(str(entity["entity_name"]), entity)
        if args.details:
            for sheet in entity["sheets"]:  # type: ignore[index]
                print_bucket(str(sheet["sheet_name"]), sheet, indent="  ")

    if args.json_out is not None:
        write_json(
            args.json_out,
            {
                "summary": totals,
                "entities": entity_report,
                "source_manifest": str(args.source_manifest),
                "work_manifest": str(args.work_manifest),
            },
        )
        print("")
        print(f"JSON: {args.json_out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
