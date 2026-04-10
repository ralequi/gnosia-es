from __future__ import annotations

import argparse
import math
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from gnosia_common import (  # noqa: E402
    OUTPUT_DIR,
    TMP_DIR,
    decode_corpus_text,
    ensure_dir,
    load_entities_from_manifest,
    read_json,
    write_json,
)

PHASE1_ENTITIES = {
    "OthersText",
    "ScreenText",
    "ScenarioBaseText",
    "ScenarioTutorialText",
    "CharaText",
    "ScenarioSetsuText",
}

UNCHANGED_ALLOWED = {
    "Gnosia",
    "Takashi",
    "LeVi",
    "Yu... Yuri...ko?",
    "Allacosia",
    "Agh...!",
    "Base 52",
    "Chipie",
    "Kukrushka",
    "Kanaan\n579",
    "Manan",
    "Setsu",
    "Jonas",
    "Raqio",
    "SQ",
    "Gina",
    "Stella",
    "Yuriko",
    "Otome",
    "Shigemichi",
    "Comet",
    "Sha-Ming",
    "Remnan",
    "SQ",
    "Ad astra per aspera.",
    "AC",
    "Bug",
    "Doctor",
    "dammy",
    "Hangar",
    "Hmph...",
    "Loop",
    "Setsu CS",
    "N/A",
    "OK",
    "No",
    "???",
    "Ah...",
    "Aaah...!",
    "Manual",
    "Mm...",
    "Sushi",
    "Ramen",
    "Uuugh... *Sniff*",
    "Yuriko CS",
    "Zzz... zzz...",
}

PUNCT_ONLY_RE = re.compile(r"^[\s\W_]+$", re.UNICODE)
PLACEHOLDER_RE = re.compile(r"\{[^}]+\}")
LOOP_KEY_DUMP_RE = re.compile(
    r"^RL:[A-Z].*\n(?:[a-z,]+\n)?(?:D\d:.*\n)*(?:-+Loop\d+-+\nRL:[A-Z].*\n(?:[a-z,]+\n)?(?:D\d:.*\n)*)*$"
)
GLOSSARY_PATH = SCRIPT_DIR / "glosario_v1.json"
LAYOUT_RULES_PATH = SCRIPT_DIR / "layout_rules.json"
ENGLISH_LEFTOVER_RE = re.compile(
    r"\b(Engineer|Guardian Angel|Crew Member Data|Data Reference|Load|Save|Proceed|Goodnight|warp)\b"
)
STYLIZATION_RE = re.compile(r"(s[uú]{2,}per|voo+y|superconfuso|supersospechoso)", re.IGNORECASE)
CHOICE_RESPONSE_RE = re.compile(
    r"^You (replied|answered|nodded|complained|asked|told|explained|affirmed|exchanged)\b"
)
CHOICE_OPTION_WHITELIST = {
    ("ScenarioTutorialText", "loop1"): {6, 10, 14, 22, 28, 32, 36, 84, 87, 90, 95, 98, 101},
}
CHARATEXT_INTERNAL_NAME_RE = re.compile(r"\b(Cipi|Kukulsika|Rakio|Remnant|ShaMin)\b")
CHARATEXT_NEUTRALITY_RE = re.compile(r"\b(?:no binari[eo]|nobinarie|elle|amigue|compañere|misme)\b", re.IGNORECASE)


def load_glossary() -> dict[str, object]:
    return read_json(GLOSSARY_PATH)


def load_layout_rules() -> dict[str, object]:
    return read_json(LAYOUT_RULES_PATH)


def load_glossary_map(glossary: dict[str, object]) -> dict[str, str]:
    flattened: dict[str, str] = {}
    for section in ("roles", "acciones", "estado_y_ui"):
        flattened.update(glossary.get(section, {}))
    return flattened


GLOSSARY = load_glossary()
GLOSSARY_MAP = load_glossary_map(GLOSSARY)
ASCII_FALLBACK_PATTERNS = GLOSSARY.get("ascii_fallbacks", {})
LAYOUT_RULES = load_layout_rules()


def parse_entity_sheet_key(key: str) -> tuple[str, str]:
    try:
        entity_name, sheet_name = key.split("/", 1)
    except ValueError as exc:
        raise ValueError(f"Invalid Entity/Sheet key in {LAYOUT_RULES_PATH}: {key!r}") from exc
    return entity_name, sheet_name


def parse_entity_sheet_param_key(key: str) -> tuple[str, str, int]:
    try:
        entity_name, tail = key.split("/", 1)
        sheet_name, param_index_raw = tail.rsplit("#", 1)
        return entity_name, sheet_name, int(param_index_raw)
    except ValueError as exc:
        raise ValueError(f"Invalid Entity/Sheet#Param key in {LAYOUT_RULES_PATH}: {key!r}") from exc


CHOICE_WIDTH_CAPS = {
    parse_entity_sheet_key(key): int(value)
    for key, value in LAYOUT_RULES.get("choice_width_caps", {}).items()
}
UI_LABEL_WIDTH_CAPS = {
    parse_entity_sheet_param_key(key): int(value)
    for key, value in LAYOUT_RULES.get("ui_label_caps", {}).items()
}
TEXTBOX_CAPS = {
    parse_entity_sheet_param_key(key): {
        "line_width": int(value["line_width"]),
        "max_lines": int(value["max_lines"]),
    }
    for key, value in LAYOUT_RULES.get("textbox_caps", {}).items()
}


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
        default=TMP_DIR / "audit",
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


def placeholder_sets(*texts: str) -> tuple[set[str], set[str]]:
    required = set(PLACEHOLDER_RE.findall(texts[1]))
    allowed = set()
    for text in texts:
        allowed.update(PLACEHOLDER_RE.findall(text))
    return required, allowed

    if entity_name == "CharaText":
        if "\n" not in source_text and len(source_text) <= 24:
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


def is_allowed_unchanged(text: str) -> bool:
    stripped = text.strip()
    if stripped in UNCHANGED_ALLOWED:
        return True
    if stripped.startswith("RL:") and "---------------Loop" in stripped:
        return True
    core = stripped.strip(" \t\r\n.!?¿¡…\"'“”()[]{}")
    if core in UNCHANGED_ALLOWED:
        return True
    return bool(LOOP_KEY_DUMP_RE.match(stripped))


def is_translatable(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if is_allowed_unchanged(text):
        return False
    if PUNCT_ONLY_RE.match(text) and not PLACEHOLDER_RE.search(text):
        return False
    return any(char.isalpha() for char in stripped)


def line_count(text: str) -> int:
    return text.count("\n") + 1


def max_line_length(text: str) -> int:
    return max((len(line) for line in text.split("\n")), default=0)


def rendered_textbox_lines(text: str, *, line_width: int) -> int:
    total = 0
    for line in text.split("\n"):
        total += max(1, math.ceil(len(line) / line_width))
    return total


def is_choice_option(
    entity_name: str,
    sheet_name: str,
    param_index: int,
    source_sheet,
) -> bool:
    if param_index in CHOICE_OPTION_WHITELIST.get((entity_name, sheet_name), set()):
        return True

    source_text = decode_corpus_text(source_sheet.params[param_index][1]).strip()
    if line_count(source_text) > 2 or max_line_length(source_text) > 30:
        return False

    next_index = param_index + 1
    if next_index >= len(source_sheet.params):
        return False

    next_source = decode_corpus_text(source_sheet.params[next_index][1]).strip()
    return bool(CHOICE_RESPONSE_RE.match(next_source))


def choice_width_cap(entity_name: str, sheet_name: str, source_text: str, source_sheet) -> int:
    explicit = CHOICE_WIDTH_CAPS.get((entity_name, sheet_name))
    if explicit is not None:
        return explicit

    widths = []
    for param_index, source_param in enumerate(source_sheet.params):
        candidate = decode_corpus_text(source_param[1])
        if is_choice_option(entity_name, sheet_name, param_index, source_sheet):
            widths.append(max_line_length(candidate))
    if widths:
        return max(widths)
    return max_line_length(source_text)


def needs_dialogue_reflow_review(entity_name: str, tier: str, source_text: str, work_text: str) -> bool:
    if tier not in {"B", "C"}:
        return False
    if entity_name not in {"ScreenText", "ScenarioBaseText", "ScenarioTutorialText"}:
        return False

    source_max = max_line_length(source_text)
    work_max = max_line_length(work_text)
    source_lines = line_count(source_text)
    work_lines = line_count(work_text)

    if work_lines != source_lines:
        return True
    if work_max > max(source_max + 8, math.ceil(source_max * 1.15)):
        return True
    return False


def editorial_reasons(entity_name: str, tier: str, source_text: str, work_text: str) -> list[str]:
    reasons: list[str] = []
    decoded_source = decode_corpus_text(source_text)
    decoded_work = decode_corpus_text(work_text)
    lower_work = decoded_work.lower()

    expected_glossary = GLOSSARY_MAP.get(decoded_source)
    if expected_glossary is not None and decoded_work != expected_glossary:
        reasons.append("glossary_mismatch")

    for ascii_term in ASCII_FALLBACK_PATTERNS:
        if re.search(rf"\b{re.escape(ascii_term)}\b", lower_work):
            reasons.append("ascii_fallback")
            break

    if work_text != source_text and ENGLISH_LEFTOVER_RE.search(decoded_work):
        reasons.append("english_leftover")

    if STYLIZATION_RE.search(decoded_work):
        reasons.append("stylization_review")

    if needs_dialogue_reflow_review(entity_name, tier, decoded_source, decoded_work):
        reasons.append("dialogue_reflow_review")

    return reasons


def voice_doc_reasons(entity_name: str, sheet_name: str, source_text: str, work_text: str) -> list[str]:
    if entity_name != "CharaText":
        return []

    decoded_source = decode_corpus_text(source_text)
    decoded_work = decode_corpus_text(work_text)
    reasons: list[str] = []

    if CHARATEXT_INTERNAL_NAME_RE.search(decoded_work):
        reasons.append("name_consistency_review")

    if sheet_name in {"Setsu", "Rakio"} and CHARATEXT_NEUTRALITY_RE.search(decoded_work):
        reasons.append("voice_doc_mismatch")

    if sheet_name == "Kukulsika" and decoded_source.strip().startswith("("):
        stripped = decoded_work.strip()
        if stripped and not stripped.startswith("("):
            reasons.append("voice_doc_mismatch")

    if sheet_name == "Otome" and "*Squeak" in decoded_source and "Chii" not in decoded_work:
        reasons.append("voice_doc_mismatch")

    return reasons


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
                source_display = decode_corpus_text(source_text)
                work_display = decode_corpus_text(work_text)
                tier = classify_tier(source_entity.entity_name, source_sheet.name, source_display)
                if tier is None:
                    continue

                summary[f"tier_{tier}"] += 1
                required_placeholders, allowed_placeholders = placeholder_sets(
                    decode_corpus_text(source_param[0]),
                    source_display,
                    decode_corpus_text(source_param[2]),
                )
                translated_placeholders = set(PLACEHOLDER_RE.findall(work_display))
                source_len = len(source_display)
                work_len = len(work_display)

                status = "ok"
                reasons: list[str] = []
                if (
                    not required_placeholders.issubset(translated_placeholders)
                    or not translated_placeholders.issubset(allowed_placeholders)
                ):
                    status = "hard_fail"
                    reasons.append("placeholder_mismatch")

                if is_choice_option(source_entity.entity_name, source_sheet.name, param_index, source_sheet):
                    if line_count(work_display) > line_count(source_display):
                        status = "hard_fail"
                        reasons.append("choice_linecount_overflow")
                    if max_line_length(work_display) > choice_width_cap(
                        source_entity.entity_name,
                        source_sheet.name,
                        source_display,
                        source_sheet,
                    ):
                        status = "hard_fail"
                        reasons.append("choice_width_overflow")

                ui_cap = UI_LABEL_WIDTH_CAPS.get(
                    (source_entity.entity_name, source_sheet.name, param_index)
                )
                if ui_cap is not None and max_line_length(work_display) > ui_cap:
                    status = "hard_fail"
                    reasons.append("ui_label_overflow")

                textbox_cap = TEXTBOX_CAPS.get(
                    (source_entity.entity_name, source_sheet.name, param_index)
                )
                if textbox_cap is not None:
                    rendered_lines = rendered_textbox_lines(
                        work_display,
                        line_width=int(textbox_cap["line_width"]),
                    )
                    if rendered_lines > int(textbox_cap["max_lines"]):
                        status = "hard_fail"
                        reasons.append("textbox_linecount_overflow")

                budget = max_len_for_tier(source_len, tier)
                if work_len > budget:
                    if status != "hard_fail":
                        status = "review"
                    reasons.append("over_budget")

                if status != "hard_fail" and work_text == source_text and is_translatable(source_display):
                    status = "review"
                    reasons.append("unchanged_translatable")

                if status != "hard_fail":
                    for reason in editorial_reasons(
                        source_entity.entity_name,
                        tier,
                        source_text,
                        work_text,
                    ):
                        if reason not in reasons:
                            reasons.append(reason)
                    for reason in voice_doc_reasons(
                        source_entity.entity_name,
                        source_sheet.name,
                        source_text,
                        work_text,
                    ):
                        if reason not in reasons:
                            reasons.append(reason)
                    if reasons and status == "ok":
                        status = "review"

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
                        "source_display_text": source_display,
                        "translated_display_text": work_display,
                    }
                )

    report_dir = ensure_dir(args.report_dir)
    write_json(report_dir / "audit.json", {"summary": summary, "entries": report_entries})

    lines = [
        "GNOSIA translation audit",
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
