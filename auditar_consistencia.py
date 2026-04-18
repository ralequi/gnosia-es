from __future__ import annotations

import argparse
import hashlib
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from gnosia_common import (  # noqa: E402
    OUTPUT_DIR,
    TMP_DIR,
    WORK_DIR,
    decode_corpus_text,
    ensure_dir,
    iter_patch_targets,
    load_entities_from_manifest,
    write_json,
)


REPORT_DEFAULT_DIR = TMP_DIR / "qa_consistencia"

PLACEHOLDER_RE = re.compile(r"\{[0-9]+\}")
PERSON_PLACEHOLDER_RE = re.compile(r"\{[0-2]\}")
ARTICLE_BEFORE_PLACEHOLDER_RE = re.compile(
    r"\b(?:el|la|los|las|un|una|unos|unas|al|del)\s+\{[0-9]+\}",
    re.IGNORECASE,
)
GENDERED_AROUND_PLACEHOLDER_RE = re.compile(
    r"(?:\{[0-9]+\}\s+(?:está|fue|ha sido|era|es)\s+"
    r"(?:infectad[oa]s?|enviad[oa]s?|eliminad[oa]s?|congelad[oa]s?|"
    r"confirmad[oa]s?|segur[oa]s?|human[oa]s?|culpable|sospechos[oa]s?))|"
    r"(?:(?:infectad[oa]s?|enviad[oa]s?|eliminad[oa]s?|congelad[oa]s?|"
    r"confirmad[oa]s?|segur[oa]s?|human[oa]s?|sospechos[oa]s?)\s+\{[0-9]+\})",
    re.IGNORECASE,
)
SOURCE_GENDER_NUMBER_ROLE_RE = re.compile(
    r"\b(?:he|she|him|her|his|hers|they|them|their|theirs|"
    r"human|humans|person|people|crew|member|members|role|claim|claims|"
    r"Doctor|Engineer|Guardian Angel|AC Follower|Bug|Gnosia|alive|dead|"
    r"cold sleep|put into|sent to|infected|suspicious|safe)\b|"
    r"\{[0-9]+\}",
    re.IGNORECASE,
)
SPANISH_AGREEMENT_RISK_RE = re.compile(
    r"\b(?:el|la|los|las|un|una|unos|unas|al|del)\s+\{[0-9]+\}|"
    r"\{[0-9]+\}\s+(?:es|era|está|fue|ha sido)\s+"
    r"(?:human[oa]s?|infectad[oa]s?|sospechos[oa]s?|segur[oa]s?|"
    r"congelad[oa]s?|enviad[oa]s?|eliminad[oa]s?)|"
    r"(?:human[oa]s?|infectad[oa]s?|sospechos[oa]s?|segur[oa]s?|"
    r"congelad[oa]s?|enviad[oa]s?|eliminad[oa]s?)\s+\{[0-9]+\}",
    re.IGNORECASE,
)
FEMININE_GNOSIA_ARTICLE_RE = re.compile(r"\b(?:la|las|una|unas)\s+Gnosia\b", re.IGNORECASE)
GNOSIA_PLURALIZED_RE = re.compile(r"\bGnosias\b", re.IGNORECASE)
BARE_COLLECTIVE_GNOSIA_RE = re.compile(
    r"\b(?:lo|eso|tema|asunto|caso|problema|amenaza)\s+de\s+Gnosia\b",
    re.IGNORECASE,
)
NEUTRAL_SENSITIVE_ENTITIES = {"ScenarioSetsuText", "ScenarioRakioText"}
NEUTRAL_SENSITIVE_CHARA_SHEETS = {"Setsu", "Rakio", "Raqio"}
VOICE_VARIANT_ENTITY = "CharaText"
LOW_SIGNAL_DUPLICATE_EN = {
    "Continue",
    "Scenario Preload",
    "Explain Situation",
    "Don't answer",
    "Refuse",
    "Register conversation",
    "Conversation",
    "Reserve Ending",
    "Ending",
    "Main Console",
    "Win",
    "Free talk",
}


@dataclass(frozen=True)
class CorpusEntry:
    entity_name: str
    path_id: int
    sheet_name: str
    sheet_index: int
    param_index: int
    patch_hash: str
    patch_id: int
    jp: str
    en: str
    zh: str
    es: str

    @property
    def location(self) -> str:
        return f"{self.entity_name}/{self.sheet_name}#{self.param_index}"

    @property
    def patch_key(self) -> str:
        return f"{self.patch_hash}:{self.patch_id}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "QA editorial: detecta duplicados divergentes, pérdida de matiz y "
            "riesgos de género/número en placeholders."
        )
    )
    parser.add_argument(
        "--source-manifest",
        type=Path,
        default=OUTPUT_DIR / "manifest.json",
        help="Manifest con el snapshot original extraído.",
    )
    parser.add_argument(
        "--work-manifest",
        type=Path,
        default=WORK_DIR / "manifest.json",
        help="Manifest materializado con la traducción actual.",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=REPORT_DEFAULT_DIR,
        help="Directorio de salida para reportes QA.",
    )
    parser.add_argument(
        "--max-examples",
        type=int,
        default=8,
        help="Máximo de ejemplos por hallazgo en reportes compactos.",
    )
    return parser.parse_args()


def stable_source_key(jp: str, en: str, zh: str) -> str:
    return hashlib.md5((jp + "\0" + en + "\0" + zh).encode("utf-8")).hexdigest()


def short_text(text: str, *, limit: int = 220) -> str:
    normalized = text.replace("\n", "\\n")
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1] + "…"


def entry_ref(entry: CorpusEntry) -> dict[str, Any]:
    return {
        "location": entry.location,
        "patch_key": entry.patch_key,
        "en": entry.en,
        "es": entry.es,
    }


def load_parallel_entries(source_manifest: Path, work_manifest: Path) -> list[CorpusEntry]:
    _, source_entities = load_entities_from_manifest(source_manifest)
    _, work_entities = load_entities_from_manifest(work_manifest)
    work_by_path = {entity.path_id: entity for entity in work_entities}

    entries: list[CorpusEntry] = []
    for source_entity in source_entities:
        work_entity = work_by_path[source_entity.path_id]
        target_by_index = {
            (int(target["sheet_index"]), int(target["param_index"])): target
            for target in iter_patch_targets(source_entity)
        }
        for sheet_index, source_sheet in enumerate(source_entity.sheets):
            work_sheet = work_entity.sheets[sheet_index]
            for param_index, source_param in enumerate(source_sheet.params):
                if len(source_param) < 3:
                    continue
                target = target_by_index[(sheet_index, param_index)]
                jp = decode_corpus_text(source_param[0])
                en = decode_corpus_text(source_param[1])
                zh = decode_corpus_text(source_param[2])
                es = decode_corpus_text(work_sheet.params[param_index][1])
                entries.append(
                    CorpusEntry(
                        entity_name=source_entity.entity_name,
                        path_id=source_entity.path_id,
                        sheet_name=source_sheet.name,
                        sheet_index=sheet_index,
                        param_index=param_index,
                        patch_hash=str(target["hash"]),
                        patch_id=int(target["id"]),
                        jp=jp,
                        en=en,
                        zh=zh,
                        es=es,
                    )
                )
    return entries


def grouped(entries: list[CorpusEntry], key_fn) -> dict[str, list[CorpusEntry]]:
    groups: dict[str, list[CorpusEntry]] = defaultdict(list)
    for entry in entries:
        groups[str(key_fn(entry))].append(entry)
    return groups


def all_same(values: list[str]) -> bool:
    return len(set(values)) <= 1


def is_low_signal_duplicate_text(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if len(stripped) <= 3:
        return True
    if stripped in {"...", "No", "Sí", "OK", "Gnosia", "Bug", "Doctor", "dammy"}:
        return True
    return False


def is_neutral_sensitive_context(entry: CorpusEntry) -> bool:
    if entry.entity_name in NEUTRAL_SENSITIVE_ENTITIES:
        return True
    return entry.entity_name == VOICE_VARIANT_ENTITY and entry.sheet_name in NEUTRAL_SENSITIVE_CHARA_SHEETS


def source_has_gender_number_role_signal(text: str) -> bool:
    return bool(SOURCE_GENDER_NUMBER_ROLE_RE.search(text))


def spanish_has_agreement_risk(text: str) -> bool:
    return bool(SPANISH_AGREEMENT_RISK_RE.search(text))


def duplicate_divergence_findings(entries: list[CorpusEntry], *, max_examples: int) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    groups = grouped(entries, lambda entry: stable_source_key(entry.jp, entry.en, entry.zh))
    for source_key, group in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0])):
        if len(group) < 2:
            continue
        translations = sorted({entry.es for entry in group})
        if len(translations) <= 1:
            continue
        all_chara = all(entry.entity_name == VOICE_VARIANT_ENTITY for entry in group)
        low_signal_ui_marker = group[0].en.strip() in LOW_SIGNAL_DUPLICATE_EN
        status = "review" if all_chara or low_signal_ui_marker else "high"
        reasons = ["same_jp_en_zh_divergent_es"]
        if all_chara:
            reasons.append("voice_variant_possible")
        if low_signal_ui_marker:
            reasons.append("generic_ui_or_marker_variant_possible")
        findings.append(
            {
                "status": status,
                "reasons": reasons,
                "source_key": source_key,
                "entry_count": len(group),
                "translation_count": len(translations),
                "source_en": group[0].en,
                "translations": translations[:max_examples],
                "examples": [entry_ref(entry) for entry in group[:max_examples]],
            }
        )
    return findings


def patch_hash_divergence_findings(entries: list[CorpusEntry], *, max_examples: int) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    groups = grouped(entries, lambda entry: entry.patch_hash)
    for patch_hash, group in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0])):
        if len(group) < 2:
            continue
        translations = sorted({entry.es for entry in group})
        source_ens = sorted({entry.en for entry in group})
        if len(translations) <= 1:
            continue
        if all(entry.entity_name == VOICE_VARIANT_ENTITY for entry in group):
            continue
        findings.append(
            {
                "status": "review",
                "reasons": ["same_jp_zh_divergent_es"],
                "patch_hash": patch_hash,
                "entry_count": len(group),
                "english_variant_count": len(source_ens),
                "translation_count": len(translations),
                "source_en_samples": source_ens[:max_examples],
                "translations": translations[:max_examples],
                "examples": [entry_ref(entry) for entry in group[:max_examples]],
            }
        )
    return findings


def collapsed_translation_findings(entries: list[CorpusEntry], *, max_examples: int) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    groups = grouped(entries, lambda entry: entry.es)
    for es_text, group in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0])):
        if len(group) < 2 or is_low_signal_duplicate_text(es_text):
            continue
        source_keys = {stable_source_key(entry.jp, entry.en, entry.zh) for entry in group}
        source_ens = sorted({entry.en for entry in group})
        if len(source_keys) <= 1 or len(source_ens) <= 1:
            continue
        if len(es_text) < 12 and len(group) > 12:
            continue
        findings.append(
            {
                "status": "review",
                "reasons": ["same_es_multiple_sources"],
                "entry_count": len(group),
                "source_variant_count": len(source_keys),
                "translation": es_text,
                "source_en_samples": source_ens[:max_examples],
                "examples": [entry_ref(entry) for entry in group[:max_examples]],
            }
        )
    return findings


def placeholder_risk_findings(entries: list[CorpusEntry], *, max_examples: int) -> list[dict[str, Any]]:
    del max_examples
    findings: list[dict[str, Any]] = []
    for entry in entries:
        if not PERSON_PLACEHOLDER_RE.search(entry.es):
            continue
        reasons: list[str] = []
        if ARTICLE_BEFORE_PLACEHOLDER_RE.search(entry.es):
            reasons.append("article_before_placeholder")
        if GENDERED_AROUND_PLACEHOLDER_RE.search(entry.es):
            reasons.append("gendered_placeholder_context")
        if not reasons:
            continue
        status = "review"
        if is_neutral_sensitive_context(entry):
            status = "high"
            reasons.append("neutral_sensitive_context")
        findings.append(
            {
                "status": status,
                "reasons": reasons,
                "location": entry.location,
                "patch_key": entry.patch_key,
                "source_en": entry.en,
                "translation": entry.es,
            }
        )
    return findings


def same_es_source_variants_gender_number_findings(
    entries: list[CorpusEntry],
    *,
    max_examples: int,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    groups = grouped(entries, lambda entry: entry.es)
    for es_text, group in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0])):
        if len(group) < 2 or is_low_signal_duplicate_text(es_text):
            continue
        source_keys = {stable_source_key(entry.jp, entry.en, entry.zh) for entry in group}
        source_ens = sorted({entry.en for entry in group})
        if len(source_keys) <= 1 or len(source_ens) <= 1:
            continue
        if not any(source_has_gender_number_role_signal(source) for source in source_ens):
            continue

        reasons = ["same_es_source_variants_gender_number"]
        status = "review"
        if spanish_has_agreement_risk(es_text):
            status = "high"
            reasons.append("spanish_agreement_risk")
        if any(is_neutral_sensitive_context(entry) for entry in group):
            status = "high"
            reasons.append("neutral_sensitive_context")
        findings.append(
            {
                "status": status,
                "reasons": reasons,
                "entry_count": len(group),
                "source_variant_count": len(source_keys),
                "english_variant_count": len(source_ens),
                "translation": es_text,
                "source_en_samples": source_ens[:max_examples],
                "examples": [entry_ref(entry) for entry in group[:max_examples]],
            }
        )
    return findings


def same_jp_or_zh_en_variants_findings(
    entries: list[CorpusEntry],
    *,
    max_examples: int,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    language_specs = (("jp", lambda entry: entry.jp), ("zh", lambda entry: entry.zh))
    for language, key_fn in language_specs:
        groups = grouped(entries, key_fn)
        for source_text, group in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0])):
            if len(group) < 2 or not source_text.strip():
                continue
            source_ens = sorted({entry.en for entry in group})
            if len(source_ens) <= 1:
                continue
            dedupe_key = (language, hashlib.md5(source_text.encode("utf-8")).hexdigest())
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            translations = sorted({entry.es for entry in group})
            reasons = [f"same_{language}_en_variants"]
            status = "review"
            if len(translations) == 1 and any(source_has_gender_number_role_signal(source) for source in source_ens):
                status = "high"
                reasons.append("english_matiz_collapsed_in_es")
            findings.append(
                {
                    "status": status,
                    "reasons": reasons,
                    "language": language,
                    "source_hash": dedupe_key[1],
                    "entry_count": len(group),
                    "english_variant_count": len(source_ens),
                    "translation_count": len(translations),
                    "source_en_samples": source_ens[:max_examples],
                    "translations": translations[:max_examples],
                    "examples": [entry_ref(entry) for entry in group[:max_examples]],
                }
            )
    return findings


def placeholder_agreement_risk_findings(entries: list[CorpusEntry]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for entry in entries:
        if not PERSON_PLACEHOLDER_RE.search(entry.es):
            continue
        reasons: list[str] = []
        if ARTICLE_BEFORE_PLACEHOLDER_RE.search(entry.es):
            reasons.append("article_before_placeholder")
        if GENDERED_AROUND_PLACEHOLDER_RE.search(entry.es):
            reasons.append("gendered_placeholder_context")
        if spanish_has_agreement_risk(entry.es):
            reasons.append("spanish_agreement_risk")
        if not reasons:
            continue

        status = "high" if is_neutral_sensitive_context(entry) else "review"
        if status == "high":
            reasons.append("neutral_sensitive_context")
        findings.append(
            {
                "status": status,
                "reasons": sorted(set(reasons)),
                "location": entry.location,
                "patch_key": entry.patch_key,
                "source_en": entry.en,
                "translation": entry.es,
            }
        )
    return findings


def gnosia_article_findings(entries: list[CorpusEntry]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for entry in entries:
        reasons: list[str] = []
        if GNOSIA_PLURALIZED_RE.search(entry.es):
            reasons.append("gnosia_pluralized_with_s")
        if FEMININE_GNOSIA_ARTICLE_RE.search(entry.es):
            reasons.append("feminine_article_before_gnosia")
        if BARE_COLLECTIVE_GNOSIA_RE.search(entry.es):
            reasons.append("bare_collective_gnosia")
        if not reasons:
            continue
        findings.append(
            {
                "status": "review",
                "reasons": reasons,
                "location": entry.location,
                "patch_key": entry.patch_key,
                "source_en": entry.en,
                "translation": entry.es,
            }
        )
    return findings


def source_identity_matrix(entries: list[CorpusEntry]) -> list[dict[str, Any]]:
    exact_groups = [group for group in grouped(entries, lambda entry: stable_source_key(entry.jp, entry.en, entry.zh)).values() if len(group) > 1]
    jp_zh_groups = [group for group in grouped(entries, lambda entry: entry.patch_hash).values() if len(group) > 1]
    same_es_groups = [group for group in grouped(entries, lambda entry: entry.es).values() if len(group) > 1]

    rows = [
        {
            "metric": "same_jp_en_zh_groups",
            "group_count": len(exact_groups),
            "divergent_es_groups": sum(1 for group in exact_groups if len({entry.es for entry in group}) > 1),
        },
        {
            "metric": "same_jp_zh_groups",
            "group_count": len(jp_zh_groups),
            "english_variant_groups": sum(1 for group in jp_zh_groups if len({entry.en for entry in group}) > 1),
            "collapsed_es_groups": sum(
                1
                for group in jp_zh_groups
                if len({entry.en for entry in group}) > 1 and len({entry.es for entry in group}) == 1
            ),
        },
        {
            "metric": "same_es_groups",
            "group_count": len(same_es_groups),
            "source_variant_groups": sum(
                1
                for group in same_es_groups
                if len({stable_source_key(entry.jp, entry.en, entry.zh) for entry in group}) > 1
            ),
        },
    ]
    return [
        {
            "status": "review",
            "reasons": ["source_identity_matrix"],
            "entry_count": len(entries),
            "summary_rows": rows,
        }
    ]


def summarize_findings(sections: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "section_counts": {name: len(items) for name, items in sections.items()},
        "status_counts": {},
    }
    status_counts: dict[str, int] = defaultdict(int)
    for items in sections.values():
        for item in items:
            status_counts[str(item.get("status", "unknown"))] += 1
    summary["status_counts"] = dict(sorted(status_counts.items()))
    return summary


def render_text_report(sections: dict[str, list[dict[str, Any]]], summary: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("GNOSIA QA de consistencia")
    lines.append("========================")
    lines.append("")
    lines.append("Resumen")
    lines.append("-------")
    for section, count in summary["section_counts"].items():
        lines.append(f"- {section}: {count}")
    lines.append(f"- estados: {summary['status_counts']}")
    lines.append("")

    for section, items in sections.items():
        lines.append(section)
        lines.append("-" * len(section))
        if not items:
            lines.append("Sin hallazgos.")
            lines.append("")
            continue
        for index, item in enumerate(items[:50], start=1):
            status = item.get("status", "review")
            reasons = ",".join(item.get("reasons", []))
            lines.append(f"{index}. [{status}] {reasons}")
            if "location" in item:
                lines.append(f"   {item['location']} {item.get('patch_key', '')}")
                lines.append(f"   EN: {short_text(str(item.get('source_en', '')))}")
                lines.append(f"   ES: {short_text(str(item.get('translation', '')))}")
            else:
                if "summary_rows" in item:
                    for row in item["summary_rows"]:
                        lines.append(f"   {row}")
                    continue
                lines.append(f"   entradas={item.get('entry_count')} variantes={item.get('translation_count', item.get('source_variant_count'))}")
                if "source_en" in item:
                    lines.append(f"   EN: {short_text(str(item['source_en']))}")
                if "translations" in item:
                    for translation in item["translations"][:4]:
                        lines.append(f"   ES: {short_text(str(translation))}")
                if "source_en_samples" in item:
                    for source in item["source_en_samples"][:4]:
                        lines.append(f"   EN sample: {short_text(str(source))}")
                    lines.append(f"   ES: {short_text(str(item.get('translation', '')))}")
                for example in item.get("examples", [])[:4]:
                    lines.append(f"   - {example['location']} {example['patch_key']}: {short_text(str(example['es']))}")
        if len(items) > 50:
            lines.append(f"... {len(items) - 50} hallazgos más en JSON.")
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    entries = load_parallel_entries(args.source_manifest, args.work_manifest)

    sections = {
        "same_jp_en_zh_divergent_es": duplicate_divergence_findings(
            entries,
            max_examples=args.max_examples,
        ),
        "same_jp_zh_divergent_es": patch_hash_divergence_findings(
            entries,
            max_examples=args.max_examples,
        ),
        "same_es_multiple_sources": collapsed_translation_findings(
            entries,
            max_examples=args.max_examples,
        ),
        "same_es_source_variants_gender_number": same_es_source_variants_gender_number_findings(
            entries,
            max_examples=args.max_examples,
        ),
        "same_jp_or_zh_en_variants": same_jp_or_zh_en_variants_findings(
            entries,
            max_examples=args.max_examples,
        ),
        "placeholder_agreement_risk": placeholder_agreement_risk_findings(entries),
        "placeholder_gender_number_risk": placeholder_risk_findings(
            entries,
            max_examples=args.max_examples,
        ),
        "gnosia_article_review": gnosia_article_findings(entries),
        "source_identity_matrix": source_identity_matrix(entries),
    }
    summary = summarize_findings(sections)

    report_dir = ensure_dir(args.report_dir)
    write_json(
        report_dir / "qa_consistencia.json",
        {
            "summary": summary,
            "source_manifest": str(args.source_manifest),
            "work_manifest": str(args.work_manifest),
            "sections": sections,
        },
    )
    (report_dir / "qa_consistencia.txt").write_text(
        render_text_report(sections, summary),
        encoding="utf-8",
    )

    print("QA consistency audit complete")
    for section, count in summary["section_counts"].items():
        print(f"{section}: {count}")
    print(f"status_counts: {summary['status_counts']}")
    print(f"Report: {report_dir / 'qa_consistencia.txt'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
