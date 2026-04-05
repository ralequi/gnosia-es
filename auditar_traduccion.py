from __future__ import annotations

import argparse
import math
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from gnosia_common import OUTPUT_DIR, TMP_DIR, ensure_dir, load_entities_from_manifest, write_json  # noqa: E402

PHASE1_ENTITIES = {
    "OthersText",
    "ScreenText",
    "ScenarioBaseText",
    "ScenarioTutorialText",
}

UNCHANGED_ALLOWED = {
    "Gnosia",
    "Takashi",
    "LeVi",
    "Kukrushka",
    "Manan",
    "SQ",
    "Ad astra per aspera.",
    "AC",
    "Bug",
    "N/A",
    "OK",
    "???",
}

PUNCT_ONLY_RE = re.compile(r"^[\s\W_]+$", re.UNICODE)
PLACEHOLDER_RE = re.compile(r"\{[^}]+\}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit translated work corpus against the extracted snapshot.")
    parser.add_argument(
        "--source-manifest",
        type=Path,
        default=OUTPUT_DIR / "manifest.json",
        help="Snapshot manifest with the original English slot.",
    )
    parser.add_argument(
        "--work-manifest",
        type=Path,
        default=SCRIPT_DIR / "work" / "manifest.json",
        help="Tracked work manifest to audit.",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=TMP_DIR / "audit_phase1",
        help="Directory for JSON and text audit reports.",
    )
    return parser.parse_args()


def classify_tier(entity_name: str, sheet_name: str, source_text: str) -> str | None:
    if entity_name not in PHASE1_ENTITIES:
        return None

    stripped = source_text.strip()
    if not stripped:
        return None
    if PUNCT_ONLY_RE.match(source_text) and not PLACEHOLDER_RE.search(source_text):
        return None

    if entity_name == "OthersText":
        if sheet_name in {"setting", "savedata", "script_parser"} and "\n" not in source_text and len(source_text) <= 24:
            return "A"
        return "B"

    if entity_name == "ScreenText":
        if "\n" not in source_text and len(source_text) <= 32:
            return "A"
        return "B"

    if entity_name == "ScenarioBaseText":
        if "\n" not in source_text and len(source_text) <= 24:
            return "A"
        return "B"

    if entity_name == "ScenarioTutorialText":
        if "\n" not in source_text and len(source_text) <= 12:
            return "A"
        return "C"

    return None


def max_len_for_tier(source_len: int, tier: str) -> int:
    if tier == "A":
        return source_len
    if tier == "B":
        return math.ceil(source_len * 1.10)
    if tier == "C":
        return math.ceil(source_len * 1.25)
    raise ValueError(f"Unknown tier: {tier}")


def is_translatable(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if stripped in UNCHANGED_ALLOWED:
        return False
    if PUNCT_ONLY_RE.match(text) and not PLACEHOLDER_RE.search(text):
        return False
    return any(char.isalpha() for char in stripped)


def main() -> int:
    args = parse_args()
    source_manifest, source_entities = load_entities_from_manifest(args.source_manifest)
    work_manifest, work_entities = load_entities_from_manifest(args.work_manifest)

    del source_manifest
    del work_manifest

    source_map = {entity.path_id: entity for entity in source_entities}
    work_map = {entity.path_id: entity for entity in work_entities}

    report_entries: list[dict[str, object]] = []
    summary = {
        "ok": 0,
        "review": 0,
        "hard_fail": 0,
        "tier_A": 0,
        "tier_B": 0,
        "tier_C": 0,
    }

    for path_id, source_entity in sorted(source_map.items()):
        work_entity = work_map[path_id]
        for sheet_index, source_sheet in enumerate(source_entity.sheets):
            work_sheet = work_entity.sheets[sheet_index]
            for param_index, source_param in enumerate(source_sheet.params):
                source_text = source_param[1]
                work_text = work_sheet.params[param_index][1]
                tier = classify_tier(source_entity.entity_name, source_sheet.name, source_text)
                if tier is None:
                    continue

                summary[f"tier_{tier}"] += 1
                placeholders_source = PLACEHOLDER_RE.findall(source_text)
                placeholders_work = PLACEHOLDER_RE.findall(work_text)
                newline_source = source_text.count("\n")
                newline_work = work_text.count("\n")
                source_len = len(source_text)
                work_len = len(work_text)

                status = "ok"
                reasons: list[str] = []
                if placeholders_source != placeholders_work:
                    status = "hard_fail"
                    reasons.append("placeholder_mismatch")
                if newline_source != newline_work:
                    status = "hard_fail"
                    reasons.append("newline_mismatch")

                budget = max_len_for_tier(source_len, tier)
                if work_len > budget:
                    if tier == "A":
                        status = "hard_fail"
                    elif status != "hard_fail":
                        status = "review"
                    reasons.append("over_budget")

                if status != "hard_fail" and work_text == source_text and is_translatable(source_text):
                    status = "review"
                    reasons.append("unchanged")

                summary[status] += 1
                report_entries.append(
                    {
                        "path_id": path_id,
                        "entity_name": source_entity.entity_name,
                        "sheet_name": source_sheet.name,
                        "param_index": param_index,
                        "tier": tier,
                        "status": status,
                        "reasons": reasons,
                        "source_len": source_len,
                        "translated_len": work_len,
                        "budget": budget,
                        "source_text": source_text,
                        "translated_text": work_text,
                    }
                )

    report_dir = ensure_dir(args.report_dir)
    write_json(report_dir / "audit.json", {"summary": summary, "entries": report_entries})

    lines = [
        "GNOSIA phase-1 translation audit",
        f"ok={summary['ok']} review={summary['review']} hard_fail={summary['hard_fail']}",
        f"tier_A={summary['tier_A']} tier_B={summary['tier_B']} tier_C={summary['tier_C']}",
        "",
        "Findings:",
    ]
    findings = [entry for entry in report_entries if entry["status"] != "ok"]
    for entry in findings[:200]:
        lines.append(
            f"[{entry['status']}] {entry['entity_name']}/{entry['sheet_name']}#{entry['param_index']:04d} "
            f"tier={entry['tier']} budget={entry['budget']} "
            f"src={entry['source_len']} dst={entry['translated_len']} "
            f"reasons={','.join(entry['reasons']) or '-'}"
        )
        lines.append(f"  EN: {entry['source_text']}")
        lines.append(f"  ES: {entry['translated_text']}")
    (report_dir / "audit.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(
        "Audit complete:",
        f"ok={summary['ok']}",
        f"review={summary['review']}",
        f"hard_fail={summary['hard_fail']}",
    )
    print(f"Report: {report_dir / 'audit.txt'}")
    return 0 if summary["hard_fail"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
