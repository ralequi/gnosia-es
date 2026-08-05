from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from gnosia_common import (  # noqa: E402
    DEFAULT_SHAREDASSETS,
    OUTPUT_DIR,
    RECONSTRUCTED_BLOB_DIRNAME,
    TMP_DIR,
    build_replacements_manifest,
    entity_filename,
    load_entities_from_manifest,
    load_source_entity_raw_map,
    serialize_entity,
    sha256_file,
    write_json,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rebuild GNOSIA entity blobs from extracted JSON.")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=OUTPUT_DIR / "manifest.json",
        help="Path to manifest.json produced by extractor.py",
    )
    parser.add_argument(
        "--asset",
        type=Path,
        default=None,
        help=(
            "Override the source asset path stored in the manifest; useful after moving "
            f"the repository (current default asset: {DEFAULT_SHAREDASSETS})"
        ),
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=TMP_DIR / "reconstructed",
        help="Output directory for rebuilt blobs and replacements manifest",
    )
    parser.add_argument(
        "--verify-source-match",
        action="store_true",
        help="Fail if rebuilt blobs are not byte-identical to the source asset.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest, entities = load_entities_from_manifest(args.manifest)
    source_asset = args.asset if args.asset is not None else Path(manifest["source_asset"])
    if not source_asset.is_file():
        raise SystemExit(
            f"source asset not found: {source_asset}; pass its current path with --asset"
        )
    source_sha256 = sha256_file(source_asset)
    if source_sha256 != manifest["source_asset_sha256"]:
        raise SystemExit(
            "source asset SHA-256 does not match the manifest: "
            f"{source_sha256} != {manifest['source_asset_sha256']}"
        )
    manifest["source_asset"] = str(source_asset.resolve())
    source_raw_map = load_source_entity_raw_map(source_asset)

    out_dir = args.out_dir
    blob_dir = out_dir / RECONSTRUCTED_BLOB_DIRNAME
    blob_dir.mkdir(parents=True, exist_ok=True)

    exact_match_count = 0
    errors: list[str] = []
    for entity in entities:
        rebuilt = serialize_entity(entity)
        source_raw = source_raw_map[entity.path_id]
        if rebuilt != source_raw:
            if args.verify_source_match:
                errors.append(
                    f"path_id={entity.path_id} {entity.entity_name}: rebuilt blob differs from source"
                )
        else:
            exact_match_count += 1
        blob_path = blob_dir / entity_filename(entity.path_id, entity.entity_name, ".bin")
        blob_path.write_bytes(rebuilt)

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    manifest["source_manifest"] = str(args.manifest.resolve())
    replacements_manifest = build_replacements_manifest(
        manifest=manifest,
        entities=entities,
        blob_dir=blob_dir,
    )
    write_json(out_dir / "replacements.json", replacements_manifest)

    print(
        "Reconstruction complete:",
        f"{len(entities)} blobs rebuilt,",
        f"{exact_match_count} currently byte-identical to the source asset.",
    )
    print(f"Replacements manifest: {out_dir / 'replacements.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
