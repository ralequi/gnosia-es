from __future__ import annotations

import argparse
import fnmatch
import hashlib
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
    iter_patch_targets,
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
    "ScenarioSQText",
    "ScenarioYurikoText",
    "ScenarioWithoutText",
    "ScenarioEndingText",
    "ScenarioGinaText",
    "ScenarioCometText",
    "ScenarioCipiText",
    "ScenarioOtomeText",
    "ScenarioJonasText",
    "ScenarioKukulText",
    "ScenarioRERSText",
    "ScenarioRakioText",
    "ScenarioRamnantText",
    "ScenarioShaminText",
    "ScenarioSigeText",
    "ScenarioStellaText",
}

UNCHANGED_ALLOWED = {
    "Gnosia",
    "Takashi",
    "LeVi",
    "Yu... Yuri...ko?",
    "Allacosia",
    "Agh...!",
    "Aaah...",
    "Base 52",
    "Bobobobobobobobobobobobobobobobobobobobobobo\nbobobobobobobobobobobobobobobobobobobo\nbobobobobobobobobobobobobo",
    "Chipie",
    "G-guh...",
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
    "...Guh...",
    "...!\nAh... {0}...",
    "Sushi",
    "Ramen",
    "Ah... {0}...",
    "Hm-hmmm♪\nHm, hm-hmmm...♪",
    "Laaa la-la-laaa, laaa la-la-laaa...",
    "Uuugh...",
    "Uuuh, uuugh...",
    "Uuugh... *Sniff*",
    "Yuriko CS",
    "Stella CS",
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


def load_fixed_length_caps() -> dict[tuple[str, str, int], dict[str, object]]:
    groups = LAYOUT_RULES.get("fixed_length_caps", {})
    if not isinstance(groups, dict):
        raise ValueError(f"fixed_length_caps must be an object in {LAYOUT_RULES_PATH}")

    caps: dict[tuple[str, str, int], dict[str, object]] = {}
    for group_name, raw_group in groups.items():
        if not re.fullmatch(r"[a-z][a-z0-9_]*", str(group_name)):
            raise ValueError(f"Invalid fixed-length group name in {LAYOUT_RULES_PATH}: {group_name!r}")
        if not isinstance(raw_group, dict):
            raise ValueError(f"Fixed-length group {group_name!r} must be an object")

        max_chars = int(raw_group.get("max_chars", 0))
        expected_count = int(raw_group.get("expected_count", 0))
        target_sha256 = str(raw_group.get("target_sha256", ""))
        if max_chars <= 0 or expected_count <= 0:
            raise ValueError(f"Fixed-length group {group_name!r} needs positive limits")
        if not re.fullmatch(r"[0-9a-f]{64}", target_sha256):
            raise ValueError(f"Fixed-length group {group_name!r} needs a target_sha256")

        group_targets: list[tuple[str, str, int]] = []
        param_ranges = raw_group.get("param_ranges", {})
        if not isinstance(param_ranges, dict):
            raise ValueError(f"param_ranges for {group_name!r} must be an object")
        for key, bounds in param_ranges.items():
            entity_name, sheet_name = parse_entity_sheet_key(str(key))
            if not isinstance(bounds, list) or len(bounds) != 2:
                raise ValueError(f"Invalid parameter range for {key!r} in {LAYOUT_RULES_PATH}")
            start, end = (int(bound) for bound in bounds)
            if start < 0 or end < start:
                raise ValueError(f"Invalid parameter range for {key!r} in {LAYOUT_RULES_PATH}")
            group_targets.extend(
                (entity_name, sheet_name, param_index)
                for param_index in range(start, end + 1)
            )

        param_indices = raw_group.get("param_indices", {})
        if not isinstance(param_indices, dict):
            raise ValueError(f"param_indices for {group_name!r} must be an object")
        for key, indices in param_indices.items():
            entity_name, sheet_name = parse_entity_sheet_key(str(key))
            if not isinstance(indices, list):
                raise ValueError(f"Invalid parameter indices for {key!r} in {LAYOUT_RULES_PATH}")
            for raw_index in indices:
                param_index = int(raw_index)
                if param_index < 0:
                    raise ValueError(f"Invalid parameter index for {key!r} in {LAYOUT_RULES_PATH}")
                group_targets.append((entity_name, sheet_name, param_index))

        if len(group_targets) != expected_count or len(set(group_targets)) != expected_count:
            raise ValueError(
                f"Fixed-length group {group_name!r} must resolve to "
                f"{expected_count} unique targets, got {len(set(group_targets))}"
            )
        for target in group_targets:
            if target in caps:
                raise ValueError(f"Fixed-length target configured more than once: {target!r}")
            caps[target] = {
                "group": str(group_name),
                "max_chars": max_chars,
                "target_sha256": target_sha256,
            }
    return caps


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
FLOW_LINE_CAPS = {
    parse_entity_sheet_key(key): {"line_width": int(value["line_width"])}
    for key, value in LAYOUT_RULES.get("flow_line_caps", {}).items()
}
FIXED_LENGTH_CAPS = load_fixed_length_caps()
GENERIC_TEXTBOX_CAPS = LAYOUT_RULES.get("generic_textbox_caps", {})
GENERIC_TEXTBOX_ENTITY_PATTERNS = [
    str(pattern) for pattern in GENERIC_TEXTBOX_CAPS.get("entity_patterns", [])
]
GENERIC_TEXTBOX_LINE_WIDTH = int(GENERIC_TEXTBOX_CAPS.get("line_width", 0) or 0)
GENERIC_TEXTBOX_MAX_LINES = int(GENERIC_TEXTBOX_CAPS.get("max_lines", 0) or 0)
TEXT_REPORT_REVIEW_LIMIT = 200


def validate_fixed_length_cap_targets(source_entities) -> None:
    available = {
        (entity.entity_name, sheet.name, param_index)
        for entity in source_entities
        for sheet in entity.sheets
        for param_index in range(len(sheet.params))
    }
    missing = sorted(set(FIXED_LENGTH_CAPS) - available)
    if missing:
        formatted = ", ".join(
            f"{entity_name}/{sheet_name}#{param_index}"
            for entity_name, sheet_name, param_index in missing
        )
        raise ValueError(f"Fixed-length targets missing from source manifest: {formatted}")

    patch_keys = {
        (entity.entity_name, str(target["sheet_name"]), int(target["param_index"])): (
            f"{entity.entity_name}:{target['hash']}:{target['id']}"
        )
        for entity in source_entities
        for target in iter_patch_targets(entity)
    }
    missing_patch_keys = sorted(set(FIXED_LENGTH_CAPS) - set(patch_keys))
    if missing_patch_keys:
        raise ValueError(f"Fixed-length targets have no patch identity: {missing_patch_keys!r}")

    groups: dict[str, list[str]] = {}
    checksums: dict[str, str] = {}
    for location, cap in FIXED_LENGTH_CAPS.items():
        group_name = str(cap["group"])
        groups.setdefault(group_name, []).append(patch_keys[location])
        checksums[group_name] = str(cap["target_sha256"])
    for group_name, keys in groups.items():
        actual = hashlib.sha256("\n".join(sorted(keys)).encode("utf-8")).hexdigest()
        if actual != checksums[group_name]:
            raise ValueError(
                f"Fixed-length group {group_name!r} no longer matches its structural targets"
            )


def fixed_length_overflow_detail(
    entity_name: str,
    sheet_name: str,
    param_index: int,
    text: str,
) -> dict[str, object] | None:
    cap = FIXED_LENGTH_CAPS.get((entity_name, sheet_name, param_index))
    if cap is None or len(text) <= int(cap["max_chars"]):
        return None
    return {
        "reason": f"{cap['group']}_length_overflow",
        "max_chars": int(cap["max_chars"]),
        "char_count": len(text),
    }


def summarize_layout_details(details: list[dict[str, object]]) -> str:
    metric_names = (
        "max_chars",
        "char_count",
        "line_width",
        "max_lines",
        "rendered_lines",
    )
    summaries = []
    for detail in details:
        reason = str(detail.get("reason", "layout"))
        metrics = ",".join(
            f"{name}={detail[name]}" for name in metric_names if name in detail
        )
        summaries.append(f"{reason}({metrics})" if metrics else reason)
    return ";".join(summaries)


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


def visual_line_length(line: str, *, line_width: int) -> int:
    if len(line) == line_width + 1 and line.endswith(" "):
        return line_width
    return len(line)


def rendered_textbox_lines(text: str, *, line_width: int) -> int:
    total = 0
    for line in text.split("\n"):
        total += max(1, math.ceil(visual_line_length(line, line_width=line_width) / line_width))
    return total


def overflowing_lines(text: str, *, line_width: int) -> list[dict[str, object]]:
    lines: list[dict[str, object]] = []
    for index, line in enumerate(text.split("\n"), start=1):
        visual_length = visual_line_length(line, line_width=line_width)
        if visual_length > line_width:
            lines.append(
                {
                    "line_index": index,
                    "line_length": len(line),
                    "visual_length": visual_length,
                    "line_width": line_width,
                    "line_text": line,
                }
            )
    return lines


def textbox_layout_detail(
    *,
    reason: str,
    text: str,
    line_width: int,
    max_lines: int | None = None,
) -> dict[str, object]:
    detail: dict[str, object] = {
        "reason": reason,
        "line_width": line_width,
        "rendered_lines": rendered_textbox_lines(text, line_width=line_width),
        "overflowing_lines": overflowing_lines(text, line_width=line_width),
    }
    if max_lines is not None:
        detail["max_lines"] = max_lines
    return detail


def entity_matches_any_pattern(entity_name: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(entity_name, pattern) for pattern in patterns)


def generic_textbox_cap_applies(
    entity_name: str,
    source_text: str,
    *,
    has_choice_cap: bool,
    has_ui_cap: bool,
    has_explicit_textbox_cap: bool,
    has_flow_line_cap: bool,
) -> bool:
    if (
        not GENERIC_TEXTBOX_LINE_WIDTH
        or not GENERIC_TEXTBOX_MAX_LINES
        or not GENERIC_TEXTBOX_ENTITY_PATTERNS
    ):
        return False
    if has_choice_cap or has_ui_cap or has_explicit_textbox_cap or has_flow_line_cap:
        return False
    if is_allowed_unchanged(source_text):
        return False
    if not entity_matches_any_pattern(entity_name, GENERIC_TEXTBOX_ENTITY_PATTERNS):
        return False
    source_rendered_lines = rendered_textbox_lines(
        source_text,
        line_width=GENERIC_TEXTBOX_LINE_WIDTH,
    )
    return source_rendered_lines <= GENERIC_TEXTBOX_MAX_LINES


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

    validate_fixed_length_cap_targets(source_entities)

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
        source_targets = {
            (int(target["sheet_index"]), int(target["param_index"])): target
            for target in iter_patch_targets(source_entity)
        }
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
                layout_details: list[dict[str, object]] = []
                if (
                    not required_placeholders.issubset(translated_placeholders)
                    or not translated_placeholders.issubset(allowed_placeholders)
                ):
                    status = "hard_fail"
                    reasons.append("placeholder_mismatch")

                fixed_length_detail = fixed_length_overflow_detail(
                    source_entity.entity_name,
                    source_sheet.name,
                    param_index,
                    work_display,
                )
                if fixed_length_detail is not None:
                    status = "hard_fail"
                    reasons.append(str(fixed_length_detail["reason"]))
                    layout_details.append(fixed_length_detail)

                has_choice_cap = is_choice_option(
                    source_entity.entity_name,
                    source_sheet.name,
                    param_index,
                    source_sheet,
                )
                if has_choice_cap:
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
                has_ui_cap = ui_cap is not None
                if ui_cap is not None and max_line_length(work_display) > ui_cap:
                    status = "hard_fail"
                    reasons.append("ui_label_overflow")

                textbox_cap = TEXTBOX_CAPS.get(
                    (source_entity.entity_name, source_sheet.name, param_index)
                )
                has_explicit_textbox_cap = textbox_cap is not None
                if textbox_cap is not None:
                    rendered_lines = rendered_textbox_lines(
                        work_display,
                        line_width=int(textbox_cap["line_width"]),
                    )
                    if rendered_lines > int(textbox_cap["max_lines"]):
                        status = "hard_fail"
                        reasons.append("textbox_linecount_overflow")
                        layout_details.append(
                            textbox_layout_detail(
                                reason="textbox_linecount_overflow",
                                text=work_display,
                                line_width=int(textbox_cap["line_width"]),
                                max_lines=int(textbox_cap["max_lines"]),
                            )
                        )

                flow_cap = FLOW_LINE_CAPS.get((source_entity.entity_name, source_sheet.name))
                has_flow_line_cap = flow_cap is not None
                if flow_cap is not None:
                    flow_width = int(flow_cap["line_width"])
                    flow_overflows = overflowing_lines(work_display, line_width=flow_width)
                    if flow_overflows:
                        status = "hard_fail"
                        reasons.append("flow_line_width_overflow")
                        layout_details.append(
                            {
                                "reason": "flow_line_width_overflow",
                                "line_width": flow_width,
                                "overflowing_lines": flow_overflows,
                            }
                        )

                if generic_textbox_cap_applies(
                    source_entity.entity_name,
                    source_display,
                    has_choice_cap=has_choice_cap,
                    has_ui_cap=has_ui_cap,
                    has_explicit_textbox_cap=has_explicit_textbox_cap,
                    has_flow_line_cap=has_flow_line_cap,
                ):
                    generic_width = GENERIC_TEXTBOX_LINE_WIDTH
                    generic_max_lines = GENERIC_TEXTBOX_MAX_LINES
                    generic_rendered_lines = rendered_textbox_lines(
                        work_display,
                        line_width=generic_width,
                    )
                    generic_overflows = overflowing_lines(work_display, line_width=generic_width)
                    if generic_rendered_lines > generic_max_lines:
                        status = "hard_fail"
                        reasons.append("generic_textbox_linecount_overflow")
                        layout_details.append(
                            textbox_layout_detail(
                                reason="generic_textbox_linecount_overflow",
                                text=work_display,
                                line_width=generic_width,
                                max_lines=generic_max_lines,
                            )
                        )
                    if generic_overflows:
                        if status != "hard_fail":
                            status = "review"
                        reasons.append("generic_textbox_line_width_overflow")
                        layout_details.append(
                            {
                                "reason": "generic_textbox_line_width_overflow",
                                "line_width": generic_width,
                                "max_lines": generic_max_lines,
                                "rendered_lines": generic_rendered_lines,
                                "overflowing_lines": generic_overflows,
                            }
                        )

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
                report_entry = {
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
                if layout_details:
                    report_entry["layout_details"] = layout_details
                patch_target = source_targets.get((sheet_index, param_index))
                if patch_target is not None:
                    report_entry["patch_hash"] = str(patch_target["hash"])
                    report_entry["patch_id"] = int(patch_target["id"])
                report_entries.append(report_entry)

    report_dir = ensure_dir(args.report_dir)
    write_json(report_dir / "audit.json", {"summary": summary, "entries": report_entries})

    lines = [
        "GNOSIA translation audit",
        f"ok={summary['ok']} review={summary['review']} hard_fail={summary['hard_fail']}",
        f"tier_A={summary['tier_A']} tier_B={summary['tier_B']} tier_C={summary['tier_C']}",
        "",
        "Findings:",
    ]
    hard_fail_findings = [
        entry for entry in report_entries if entry["status"] == "hard_fail"
    ]
    review_findings = [entry for entry in report_entries if entry["status"] == "review"]
    shown_review_findings = review_findings[:TEXT_REPORT_REVIEW_LIMIT]
    lines.extend(
        [
            f"hard_fail shown={len(hard_fail_findings)}/{len(hard_fail_findings)}",
            f"review shown={len(shown_review_findings)}/{len(review_findings)}",
            "",
        ]
    )
    for entry in hard_fail_findings + shown_review_findings:
        patch_identity = ""
        if "patch_hash" in entry:
            patch_identity = f" patch={entry['patch_hash']}:{entry['patch_id']}"
        layout_summary = ""
        if "layout_details" in entry:
            layout_summary = f" layout={summarize_layout_details(entry['layout_details'])}"
        lines.append(
            f"[{entry['status']}] {entry['entity_name']}/{entry['sheet_name']}#{entry['param_index']:04d} "
            f"tier={entry['tier']} tier_budget={entry['budget']} "
            f"src={entry['source_len']} dst={entry['translated_len']} "
            f"reasons={','.join(entry['reasons']) or '-'}{patch_identity}{layout_summary}"
        )
        lines.append(f"  EN: {entry['source_text']}")
        lines.append(f"  ES: {entry['translated_text']}")
    omitted_reviews = len(review_findings) - len(shown_review_findings)
    if omitted_reviews:
        lines.extend(
            [
                "",
                f"{omitted_reviews} review findings omitted; see audit.json for all entries.",
            ]
        )
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
