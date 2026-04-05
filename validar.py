from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from gnosia_common import (  # noqa: E402
    DEFAULT_BUNDLE_DIR,
    DEFAULT_SHAREDASSETS,
    OUTPUT_DIR,
    TMP_DIR,
    WRITER_PADDING,
    entity_to_dict,
    extract_entities,
    inventory_localized_bundles,
    load_entities_from_manifest,
    load_replacements_from_manifest,
    load_source_entity_raw_map,
    load_unity_env,
    normalize_saved_asset_bytes,
    save_repacked_asset,
    sha256_bytes,
    summarize_entities,
    validate_entity_roundtrip,
)

EXPECTED_SUMMARY = {
    "entity_count": 22,
    "sheet_count": 197,
    "param_count": 9563,
    "localized_string_count": 28689,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate GNOSIA extraction/rebuild pipeline.")
    parser.add_argument(
        "--asset",
        type=Path,
        default=DEFAULT_SHAREDASSETS,
        help="Path to sharedassets0.assets",
    )
    parser.add_argument(
        "--bundle-dir",
        type=Path,
        default=DEFAULT_BUNDLE_DIR,
        help="Directory with localized Addressables bundles",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=OUTPUT_DIR / "manifest.json",
        help="Path to manifest.json produced by extractor.py",
    )
    parser.add_argument(
        "--replacements-manifest",
        type=Path,
        default=TMP_DIR / "reconstructed" / "replacements.json",
        help="Path to replacements.json produced by reconstructor.py",
    )
    parser.add_argument(
        "--repacked-asset",
        type=Path,
        default=TMP_DIR / "sharedassets0.repacked.assets",
        help="Path to the repacked sharedassets0.assets copy",
    )
    return parser.parse_args()


def fail(message: str) -> int:
    print(f"ERROR: {message}", file=sys.stderr)
    return 1


def main() -> int:
    args = parse_args()
    original_bytes = args.asset.read_bytes()

    extracted_entities = extract_entities(args.asset)
    summary = summarize_entities(extracted_entities)
    if summary != EXPECTED_SUMMARY:
        return fail(f"unexpected extraction summary: {summary!r}")

    source_raw_map = load_source_entity_raw_map(args.asset)
    roundtrip_errors = validate_entity_roundtrip(extracted_entities, source_raw_map)
    if roundtrip_errors:
        return fail(f"entity round-trip failed: {roundtrip_errors[0]}")
    print("TEST 1 OK: parse + serialize is byte-identical for the 22 Entity_*Text blobs.")

    if not args.manifest.exists():
        return fail(f"manifest not found: {args.manifest}")
    manifest, manifest_entities = load_entities_from_manifest(args.manifest)
    if summarize_entities(manifest_entities) != EXPECTED_SUMMARY:
        return fail("manifest-backed corpus summary does not match the source asset")
    if manifest["source_asset_sha256"] != sha256_bytes(original_bytes):
        return fail("manifest source_asset_sha256 does not match the source asset")
    if [entity_to_dict(entity) for entity in manifest_entities] != [
        entity_to_dict(entity) for entity in extracted_entities
    ]:
        return fail("manifest/entity JSON corpus does not match a fresh extraction")
    print("TEST 2 OK: extraction artifacts rehydrate to the same structured corpus field by field.")

    if not args.replacements_manifest.exists():
        return fail(f"replacements manifest not found: {args.replacements_manifest}")
    _, replacements = load_replacements_from_manifest(args.replacements_manifest)
    if any(source_raw_map.get(path_id) != blob for path_id, blob in replacements.items()):
        return fail("reconstructed blobs are not a no-op match against the source asset")

    if not args.repacked_asset.exists():
        return fail(f"repacked asset not found: {args.repacked_asset}")
    repacked_bytes = args.repacked_asset.read_bytes()
    if repacked_bytes != original_bytes:
        return fail("repacked asset is not byte-identical to the original sharedassets0.assets")
    if sha256_bytes(repacked_bytes) != sha256_bytes(original_bytes):
        return fail("repacked asset SHA-256 does not match the original")
    print("TEST 3 OK: no-op reconstruction of sharedassets0.assets matches byte for byte.")

    env, serialized_file = load_unity_env(args.asset)
    del env
    raw_saved_bytes = serialized_file.save()
    if len(raw_saved_bytes) != len(original_bytes) + len(WRITER_PADDING):
        return fail("UnityPy raw save does not exhibit the expected +4 byte writer artifact")
    if not raw_saved_bytes.endswith(WRITER_PADDING):
        return fail("UnityPy raw save is missing the expected trailing 4-byte padding")
    declared_size = int.from_bytes(raw_saved_bytes[4:8], "big")
    if declared_size != len(raw_saved_bytes):
        return fail("UnityPy raw save header size does not match the saved file length")
    normalized_bytes = normalize_saved_asset_bytes(raw_saved_bytes)
    if normalized_bytes != original_bytes:
        return fail("writer normalization did not restore an exact no-op asset")
    print("TEST 4 OK: writer normalization fixes the header size and trims the trailing padding.")

    inventory = inventory_localized_bundles(args.bundle_dir)
    if inventory["bundle_count"] == 0:
        return fail("no localized raster bundles were found")
    for bundle in inventory["bundles"]:
        if bundle["has_text_assets"]:
            return fail(f"bundle unexpectedly contains TextAsset entries: {bundle['bundle']}")
        if not bundle["only_raster_localization"]:
            return fail(f"bundle contains non-raster localized objects: {bundle['bundle']}")
    print("TEST 5 OK: localized help/pre/systm/title bundles contain only Sprite/Texture2D data.")

    tmp_validation_asset = TMP_DIR / "validation" / "sharedassets0.noop.assets"
    saved_again = save_repacked_asset(
        source_asset=args.asset,
        replacements=replacements,
        output_asset=tmp_validation_asset,
    )
    if saved_again != original_bytes:
        return fail("save_repacked_asset no-op check did not reproduce the original asset")

    print(f"ALL TESTS OK: sha256={sha256_bytes(original_bytes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
