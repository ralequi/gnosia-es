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
    ENTITY_JSON_DIRNAME,
    OUTPUT_DIR,
    build_manifest,
    entity_filename,
    entity_to_dict,
    ensure_dir,
    extract_entities,
    inventory_localized_bundles,
    load_source_entity_raw_map,
    summarize_entities,
    validate_entity_roundtrip,
    write_json,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract GNOSIA structured text corpus.")
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
        "--out-dir",
        type=Path,
        default=OUTPUT_DIR,
        help="Output directory for manifest/entity JSON/image inventory",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = ensure_dir(args.out_dir)
    entity_dir = ensure_dir(out_dir / ENTITY_JSON_DIRNAME)

    entities = extract_entities(args.asset)
    source_raw_map = load_source_entity_raw_map(args.asset)
    roundtrip_errors = validate_entity_roundtrip(entities, source_raw_map)
    if roundtrip_errors:
        for error in roundtrip_errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    manifest = build_manifest(args.asset, entities)
    write_json(out_dir / "manifest.json", manifest)

    for entity in entities:
        write_json(
            entity_dir / entity_filename(entity.path_id, entity.entity_name, ".json"),
            entity_to_dict(entity),
        )

    image_inventory = inventory_localized_bundles(args.bundle_dir)
    write_json(out_dir / "image_inventory.json", image_inventory)

    summary = summarize_entities(entities)
    print(
        "Extraction complete:",
        f"{summary['entity_count']} entities,",
        f"{summary['sheet_count']} sheets,",
        f"{summary['param_count']} params,",
        f"{summary['localized_string_count']} localized strings.",
    )
    print(f"Manifest: {out_dir / 'manifest.json'}")
    print(f"Image inventory: {out_dir / 'image_inventory.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
