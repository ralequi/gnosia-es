from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from gnosia_common import (  # noqa: E402
    OUTPUT_DIR,
    TMP_DIR,
    load_entities_from_manifest,
    load_replacements_from_manifest,
    load_source_entity_raw_map,
    save_repacked_asset,
    serialize_entity,
    sha256_bytes,
    validate_repacked_asset,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply GNOSIA entity blobs back into sharedassets0.assets.")
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
        help="Optional replacements.json produced by reconstructor.py",
    )
    parser.add_argument(
        "--output-asset",
        type=Path,
        default=TMP_DIR / "sharedassets0.repacked.assets",
        help="Output path for repacked sharedassets0.assets",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    replacements_manifest = args.replacements_manifest
    if replacements_manifest.exists():
        replacements_data, replacements = load_replacements_from_manifest(replacements_manifest)
        source_asset = Path(replacements_data["source_asset"])
    else:
        manifest, entities = load_entities_from_manifest(args.manifest)
        source_asset = Path(manifest["source_asset"])
        replacements = {entity.path_id: serialize_entity(entity) for entity in entities}

    original_bytes = source_asset.read_bytes()
    source_raw_map = load_source_entity_raw_map(source_asset)
    is_noop = all(source_raw_map.get(path_id) == blob for path_id, blob in replacements.items())

    repacked_bytes = save_repacked_asset(
        source_asset=source_asset,
        replacements=replacements,
        output_asset=args.output_asset,
    )

    validation_errors = validate_repacked_asset(args.output_asset, replacements)
    if validation_errors:
        for error in validation_errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    if is_noop and repacked_bytes != original_bytes:
        print("ERROR: no-op repack is not byte-identical to the original asset", file=sys.stderr)
        return 1

    print(
        "Repack complete:",
        args.output_asset,
        f"sha256={sha256_bytes(repacked_bytes)}",
    )
    if is_noop:
        print("No-op validation: exact byte-for-byte match confirmed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
