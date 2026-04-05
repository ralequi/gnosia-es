from __future__ import annotations

import hashlib
import json
import re
import shutil
import struct
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:
    import UnityPy
except ImportError:  # pragma: no cover - dependency guard
    UnityPy = None


LANGUAGES = ["jp", "en", "zh"]
ENTITY_SCRIPT_PREFIX = "Entity_"
ROOT_DIR = Path(__file__).resolve().parent.parent
TRANSLATOR_DIR = Path(__file__).resolve().parent
DEFAULT_SHAREDASSETS = ROOT_DIR / "Gnosia_Data" / "sharedassets0.assets"
DEFAULT_BUNDLE_DIR = ROOT_DIR / "Gnosia_Data" / "StreamingAssets" / "aa" / "StandaloneWindows64"
OUTPUT_DIR = TRANSLATOR_DIR / "out"
TMP_DIR = TRANSLATOR_DIR / "tmp"
WORK_DIR = TRANSLATOR_DIR / "work"
PATCH_DIR = TRANSLATOR_DIR / "parches"
ENTITY_JSON_DIRNAME = "entities"
RECONSTRUCTED_BLOB_DIRNAME = "blobs"
PATCH_SUFFIX = ".parche"
WRITER_PADDING = b"\x00\x00\x00\x00"
PATCH_SLOT_INDEX = 1
PATCH_REFERENCE_SLOT_INDEX_JP = 0
PATCH_REFERENCE_SLOT_INDEX_ZH = 2


@dataclass
class EntityHeader:
    game_object_file_id: int
    game_object_path_id: int
    enabled: int
    script_file_id: int
    script_path_id: int
    name: str


@dataclass
class EntitySheet:
    name: str
    params: list[list[str]]


@dataclass
class ParsedEntity:
    path_id: int
    entity_name: str
    script_name: str
    byte_size: int
    header: EntityHeader
    sheets: list[EntitySheet]


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    ensure_dir(path.parent)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def align4(offset: int) -> int:
    return (offset + 3) & ~3


def read_i32(data: bytes, offset: int) -> tuple[int, int]:
    return struct.unpack_from("<i", data, offset)[0], offset + 4


def read_i64(data: bytes, offset: int) -> tuple[int, int]:
    return struct.unpack_from("<q", data, offset)[0], offset + 8


def write_i32(value: int) -> bytes:
    return struct.pack("<i", value)


def write_i64(value: int) -> bytes:
    return struct.pack("<q", value)


def read_unity_string(data: bytes, offset: int) -> tuple[bytes, int]:
    length, offset = read_i32(data, offset)
    value = data[offset : offset + length]
    offset += length
    offset = align4(offset)
    return value, offset


def write_unity_string(raw: bytes) -> bytes:
    padding = b"\x00" * ((4 - (len(raw) % 4)) % 4)
    return write_i32(len(raw)) + raw + padding


def decode_text(raw: bytes) -> str:
    return raw.decode("utf-8")


def encode_text(text: str) -> bytes:
    return text.encode("utf-8")


def slugify_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_") or "entity"


def entity_filename(path_id: int, entity_name: str, suffix: str) -> str:
    return f"{path_id:04d}_{slugify_name(entity_name)}{suffix}"


def patch_filename(entity_name: str) -> str:
    return f"{slugify_name(entity_name)}{PATCH_SUFFIX}"


def entity_param_count(entity: ParsedEntity) -> int:
    return sum(len(sheet.params) for sheet in entity.sheets)


def entity_localized_string_count(entity: ParsedEntity) -> int:
    return sum(len(texts) for sheet in entity.sheets for texts in sheet.params)


def parse_entity_raw(
    *,
    path_id: int,
    entity_name: str,
    script_name: str,
    byte_size: int,
    raw: bytes,
) -> ParsedEntity:
    offset = 0
    game_object_file_id, offset = read_i32(raw, offset)
    game_object_path_id, offset = read_i64(raw, offset)
    enabled, offset = read_i32(raw, offset)
    script_file_id, offset = read_i32(raw, offset)
    script_path_id, offset = read_i64(raw, offset)
    stored_name_raw, offset = read_unity_string(raw, offset)
    sheet_count, offset = read_i32(raw, offset)

    sheets: list[EntitySheet] = []
    for _ in range(sheet_count):
        sheet_name_raw, offset = read_unity_string(raw, offset)
        param_count, offset = read_i32(raw, offset)
        params: list[list[str]] = []
        for _ in range(param_count):
            text_count, offset = read_i32(raw, offset)
            texts: list[str] = []
            for _ in range(text_count):
                value_raw, offset = read_unity_string(raw, offset)
                texts.append(decode_text(value_raw))
            params.append(texts)
        sheets.append(EntitySheet(name=decode_text(sheet_name_raw), params=params))

    if offset != len(raw):
        raise ValueError(
            f"{entity_name} path_id={path_id}: parser stopped at {offset}, expected {len(raw)}"
        )

    stored_name = decode_text(stored_name_raw)
    if stored_name != entity_name:
        raise ValueError(
            f"Entity name mismatch for path_id={path_id}: {entity_name!r} != {stored_name!r}"
        )

    return ParsedEntity(
        path_id=path_id,
        entity_name=entity_name,
        script_name=script_name,
        byte_size=byte_size,
        header=EntityHeader(
            game_object_file_id=game_object_file_id,
            game_object_path_id=game_object_path_id,
            enabled=enabled,
            script_file_id=script_file_id,
            script_path_id=script_path_id,
            name=stored_name,
        ),
        sheets=sheets,
    )


def serialize_entity(entity: ParsedEntity) -> bytes:
    payload = bytearray()
    payload += write_i32(entity.header.game_object_file_id)
    payload += write_i64(entity.header.game_object_path_id)
    payload += write_i32(entity.header.enabled)
    payload += write_i32(entity.header.script_file_id)
    payload += write_i64(entity.header.script_path_id)
    payload += write_unity_string(encode_text(entity.header.name))
    payload += write_i32(len(entity.sheets))

    for sheet in entity.sheets:
        payload += write_unity_string(encode_text(sheet.name))
        payload += write_i32(len(sheet.params))
        for param in sheet.params:
            payload += write_i32(len(param))
            for text in param:
                payload += write_unity_string(encode_text(text))

    return bytes(payload)


def entity_to_dict(entity: ParsedEntity) -> dict[str, Any]:
    return {
        "path_id": entity.path_id,
        "entity_name": entity.entity_name,
        "script_name": entity.script_name,
        "byte_size": entity.byte_size,
        "languages": LANGUAGES,
        "header": asdict(entity.header),
        "sheet_count": len(entity.sheets),
        "param_count": entity_param_count(entity),
        "localized_string_count": entity_localized_string_count(entity),
        "sheets": [
            {
                "name": sheet.name,
                "param_count": len(sheet.params),
                "params": [{"texts": param} for param in sheet.params],
            }
            for sheet in entity.sheets
        ],
    }


def entity_from_dict(payload: dict[str, Any]) -> ParsedEntity:
    return ParsedEntity(
        path_id=int(payload["path_id"]),
        entity_name=str(payload["entity_name"]),
        script_name=str(payload["script_name"]),
        byte_size=int(payload["byte_size"]),
        header=EntityHeader(**payload["header"]),
        sheets=[
            EntitySheet(
                name=str(sheet["name"]),
                params=[list(param["texts"]) for param in sheet["params"]],
            )
            for sheet in payload["sheets"]
        ],
    )


def load_unity_env(asset_path: Path):
    if UnityPy is None:
        raise SystemExit(
            "Missing dependency 'UnityPy'. Install with "
            "'python -m pip install -r traductor_es/requirements.txt'."
        )
    env = UnityPy.load(str(asset_path))
    serialized_file = next(iter(env.files.values()))
    return env, serialized_file


def iter_text_entity_objects(asset_path: Path) -> list[tuple[Any, Any, str]]:
    env, _ = load_unity_env(asset_path)
    entities: list[tuple[Any, Any, str]] = []
    for obj in env.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        head = obj.parse_monobehaviour_head()
        script_name = head.m_Script.read().m_Name
        if not script_name.startswith(ENTITY_SCRIPT_PREFIX):
            continue
        entities.append((obj, head, script_name))
    entities.sort(key=lambda item: item[0].path_id)
    return entities


def extract_entities(asset_path: Path) -> list[ParsedEntity]:
    entities: list[ParsedEntity] = []
    for obj, head, script_name in iter_text_entity_objects(asset_path):
        entities.append(
            parse_entity_raw(
                path_id=obj.path_id,
                entity_name=head.m_Name,
                script_name=script_name,
                byte_size=obj.byte_size,
                raw=obj.get_raw_data(),
            )
        )
    return entities


def load_source_entity_raw_map(asset_path: Path) -> dict[int, bytes]:
    raw_map: dict[int, bytes] = {}
    for obj, _, _ in iter_text_entity_objects(asset_path):
        raw_map[obj.path_id] = obj.get_raw_data()
    return raw_map


def load_raw_data_for_path_ids(asset_path: Path, path_ids: set[int]) -> dict[int, bytes]:
    env, _ = load_unity_env(asset_path)
    raw_map: dict[int, bytes] = {}
    for obj in env.objects:
        if obj.path_id not in path_ids:
            continue
        raw_map[obj.path_id] = obj.get_raw_data()
    return raw_map


def build_manifest(asset_path: Path, entities: list[ParsedEntity]) -> dict[str, Any]:
    asset_raw = asset_path.read_bytes()
    entity_entries = []
    for entity in entities:
        entity_entries.append(
            {
                "path_id": entity.path_id,
                "entity_name": entity.entity_name,
                "script_name": entity.script_name,
                "byte_size": entity.byte_size,
                "sheet_count": len(entity.sheets),
                "param_count": entity_param_count(entity),
                "localized_string_count": entity_localized_string_count(entity),
                "file": f"{ENTITY_JSON_DIRNAME}/{entity_filename(entity.path_id, entity.entity_name, '.json')}",
            }
        )

    return {
        "source_asset": str(asset_path.resolve()),
        "source_asset_sha256": sha256_bytes(asset_raw),
        "languages": LANGUAGES,
        "entity_count": len(entities),
        "sheet_count": sum(len(entity.sheets) for entity in entities),
        "param_count": sum(entity_param_count(entity) for entity in entities),
        "localized_string_count": sum(entity_localized_string_count(entity) for entity in entities),
        "entities": entity_entries,
    }


def load_entities_from_manifest(manifest_path: Path) -> tuple[dict[str, Any], list[ParsedEntity]]:
    manifest = read_json(manifest_path)
    base_dir = manifest_path.parent
    entities: list[ParsedEntity] = []
    for entry in manifest["entities"]:
        entity_payload = read_json(base_dir / entry["file"])
        entities.append(entity_from_dict(entity_payload))
    entities.sort(key=lambda entity: entity.path_id)
    return manifest, entities


def build_replacements_manifest(
    *,
    manifest: dict[str, Any],
    entities: list[ParsedEntity],
    blob_dir: Path,
) -> dict[str, Any]:
    entries = []
    for entity in entities:
        blob_path = blob_dir / entity_filename(entity.path_id, entity.entity_name, ".bin")
        blob_bytes = blob_path.read_bytes()
        entries.append(
            {
                "path_id": entity.path_id,
                "entity_name": entity.entity_name,
                "script_name": entity.script_name,
                "byte_size": len(blob_bytes),
                "sha256": sha256_bytes(blob_bytes),
                "file": str(blob_path.relative_to(blob_dir.parent)),
            }
        )

    return {
        "source_manifest": str(manifest.get("source_manifest", "")),
        "source_asset": manifest["source_asset"],
        "source_asset_sha256": manifest["source_asset_sha256"],
        "entity_count": len(entries),
        "entities": entries,
    }


def load_replacements_from_manifest(
    replacements_manifest_path: Path,
) -> tuple[dict[str, Any], dict[int, bytes]]:
    manifest = read_json(replacements_manifest_path)
    base_dir = replacements_manifest_path.parent
    replacements: dict[int, bytes] = {}
    for entry in manifest["entities"]:
        replacements[int(entry["path_id"])] = (base_dir / entry["file"]).read_bytes()
    return manifest, replacements


def inventory_localized_bundles(bundle_dir: Path) -> dict[str, Any]:
    pattern = re.compile(r"^(help|pre|systm|title)_(jp|en|zh)_.*\.bundle$")
    bundle_entries = []
    for bundle_path in sorted(bundle_dir.glob("*.bundle")):
        match = pattern.match(bundle_path.name)
        if not match:
            continue

        env, _ = load_unity_env(bundle_path)
        counts = Counter(obj.type.name for obj in env.objects)
        asset_names = []
        for obj in env.objects:
            if obj.type.name not in {"Sprite", "Texture2D"}:
                continue
            data = obj.read()
            asset_names.append(data.m_Name)

        bundle_entries.append(
            {
                "bundle": bundle_path.name,
                "path": str(bundle_path.resolve()),
                "category": match.group(1),
                "language": match.group(2),
                "object_counts": dict(counts),
                "has_text_assets": counts.get("TextAsset", 0) > 0,
                "only_raster_localization": set(counts).issubset({"Sprite", "Texture2D", "AssetBundle"}),
                "raster_asset_count": counts.get("Sprite", 0) + counts.get("Texture2D", 0),
                "asset_names_sample": sorted(asset_names)[:25],
            }
        )

    return {
        "bundle_root": str(bundle_dir.resolve()),
        "bundle_count": len(bundle_entries),
        "bundles": bundle_entries,
    }


def normalize_saved_asset_bytes(saved_bytes: bytes) -> bytes:
    if len(saved_bytes) < 8:
        return saved_bytes

    declared_size = int.from_bytes(saved_bytes[4:8], "big")
    if declared_size == len(saved_bytes) and saved_bytes.endswith(WRITER_PADDING):
        normalized_size = len(saved_bytes) - len(WRITER_PADDING)
        patched = bytearray(saved_bytes[:-len(WRITER_PADDING)])
        patched[4:8] = normalized_size.to_bytes(4, "big")
        return bytes(patched)
    return saved_bytes


def save_repacked_asset(
    *,
    source_asset: Path,
    replacements: dict[int, bytes],
    output_asset: Path,
) -> bytes:
    env, serialized_file = load_unity_env(source_asset)
    for obj in env.objects:
        replacement = replacements.get(obj.path_id)
        if replacement is None:
            continue
        obj.set_raw_data(replacement)

    saved_bytes = serialized_file.save()
    normalized = normalize_saved_asset_bytes(saved_bytes)
    ensure_dir(output_asset.parent)
    output_asset.write_bytes(normalized)
    return normalized


def validate_entity_roundtrip(entities: list[ParsedEntity], source_raw_map: dict[int, bytes]) -> list[str]:
    errors: list[str] = []
    for entity in entities:
        raw = source_raw_map[entity.path_id]
        rebuilt = serialize_entity(entity)
        if rebuilt != raw:
            errors.append(
                f"path_id={entity.path_id} {entity.entity_name}: raw round-trip mismatch "
                f"({len(rebuilt)} != {len(raw)})"
            )
    return errors


def validate_repacked_asset(output_asset: Path, replacements: dict[int, bytes]) -> list[str]:
    errors: list[str] = []
    raw_map = load_raw_data_for_path_ids(output_asset, set(replacements))
    for path_id, expected in replacements.items():
        actual = raw_map.get(path_id)
        if actual is None:
            errors.append(f"path_id={path_id}: entity missing from repacked asset")
            continue
        if actual != expected:
            errors.append(f"path_id={path_id}: repacked blob mismatch")
    return errors


def summarize_entities(entities: list[ParsedEntity]) -> dict[str, int]:
    return {
        "entity_count": len(entities),
        "sheet_count": sum(len(entity.sheets) for entity in entities),
        "param_count": sum(entity_param_count(entity) for entity in entities),
        "localized_string_count": sum(entity_localized_string_count(entity) for entity in entities),
    }


def create_work_corpus_from_manifest(
    *,
    source_manifest_path: Path,
    work_dir: Path,
    force: bool = False,
) -> dict[str, Any]:
    if work_dir.exists():
        if not force:
            raise FileExistsError(f"Work directory already exists: {work_dir}")
        shutil.rmtree(work_dir)

    ensure_dir(work_dir / ENTITY_JSON_DIRNAME)
    manifest = read_json(source_manifest_path)
    source_base = source_manifest_path.parent

    for entry in manifest["entities"]:
        source_file = source_base / entry["file"]
        dest_file = work_dir / entry["file"]
        ensure_dir(dest_file.parent)
        shutil.copy2(source_file, dest_file)

    work_manifest = dict(manifest)
    work_manifest["translation_target_language"] = "es"
    work_manifest["translation_overrides_slot"] = "en"
    work_manifest["translation_source_manifest"] = str(source_manifest_path.resolve())
    work_manifest["translation_work_dir"] = str(work_dir.resolve())
    write_json(work_dir / "manifest.json", work_manifest)
    return work_manifest


def compute_patch_hash(jp_text: str, zh_text: str) -> str:
    return hashlib.md5((jp_text + zh_text).encode("utf-8")).hexdigest()


def escape_patch_text(text: str) -> str:
    escaped: list[str] = []
    for char in text:
        if char == "\\":
            escaped.append("\\\\")
        elif char == "\n":
            escaped.append("\\n")
        elif char == "\r":
            escaped.append("\\r")
        elif char == "\t":
            escaped.append("\\t")
        elif char == '"':
            escaped.append('\\"')
        else:
            escaped.append(char)
    return "".join(escaped)


def unescape_patch_text(text: str) -> str:
    chars: list[str] = []
    i = 0
    while i < len(text):
        char = text[i]
        if char != "\\":
            chars.append(char)
            i += 1
            continue
        if i + 1 >= len(text):
            raise ValueError("dangling backslash in patch payload")
        marker = text[i + 1]
        if marker == "n":
            chars.append("\n")
        elif marker == "r":
            chars.append("\r")
        elif marker == "t":
            chars.append("\t")
        elif marker == "\\":
            chars.append("\\")
        elif marker == '"':
            chars.append('"')
        else:
            raise ValueError(f"unsupported patch escape sequence: \\{marker}")
        i += 2
    return "".join(chars)


def decode_corpus_text(text: str) -> str:
    chars: list[str] = []
    i = 0
    while i < len(text):
        char = text[i]
        if char != "\\" or i + 1 >= len(text):
            chars.append(char)
            i += 1
            continue
        marker = text[i + 1]
        if marker == "n":
            chars.append("\n")
            i += 2
            continue
        if marker == "r":
            chars.append("\r")
            i += 2
            continue
        if marker == "t":
            chars.append("\t")
            i += 2
            continue
        if marker == '"':
            chars.append('"')
            i += 2
            continue
        if marker == "\\":
            chars.append("\\")
            i += 2
            continue
        chars.append(char)
        i += 1
    return "".join(chars)


def encode_text_like_source_style(*, source_text: str, logical_text: str) -> str:
    encoded = logical_text
    if "\\\\" in source_text:
        encoded = encoded.replace("\\", "\\\\")
    if '\\"' in source_text:
        encoded = encoded.replace('"', '\\"')
    if "\\n" in source_text and "\n" not in source_text:
        encoded = encoded.replace("\n", "\\n")
    if "\\r" in source_text and "\r" not in source_text:
        encoded = encoded.replace("\r", "\\r")
    if "\\t" in source_text and "\t" not in source_text:
        encoded = encoded.replace("\t", "\\t")
    return encoded


def iter_patch_targets(entity: ParsedEntity):
    duplicate_counts: dict[str, int] = {}
    for sheet_index, sheet in enumerate(entity.sheets):
        for param_index, texts in enumerate(sheet.params):
            if len(texts) <= PATCH_REFERENCE_SLOT_INDEX_ZH:
                continue
            hash_key = compute_patch_hash(
                texts[PATCH_REFERENCE_SLOT_INDEX_JP],
                texts[PATCH_REFERENCE_SLOT_INDEX_ZH],
            )
            duplicate_index = duplicate_counts.get(hash_key, 0)
            duplicate_counts[hash_key] = duplicate_index + 1
            yield {
                "entity_name": entity.entity_name,
                "path_id": entity.path_id,
                "sheet_index": sheet_index,
                "sheet_name": sheet.name,
                "param_index": param_index,
                "hash": hash_key,
                "id": duplicate_index,
                "jp_text": texts[PATCH_REFERENCE_SLOT_INDEX_JP],
                "en_text": texts[PATCH_SLOT_INDEX],
                "zh_text": texts[PATCH_REFERENCE_SLOT_INDEX_ZH],
            }


def build_patch_target_index(entity: ParsedEntity) -> dict[tuple[str, int], dict[str, Any]]:
    index: dict[tuple[str, int], dict[str, Any]] = {}
    for target in iter_patch_targets(entity):
        key = (str(target["hash"]), int(target["id"]))
        if key in index:
            raise ValueError(f"duplicate patch target generated for {entity.entity_name}: {key}")
        index[key] = target
    return index
