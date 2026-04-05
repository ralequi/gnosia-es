from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from gnosia_common import (  # noqa: E402
    DEFAULT_BUNDLE_DIR,
    TMP_DIR,
    materialize_localized_bundle_build,
    read_json,
    write_json,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build localized GNOSIA bundles by exact copy or explicit replacement."
    )
    parser.add_argument(
        "--bundle-dir",
        type=Path,
        default=DEFAULT_BUNDLE_DIR,
        help="Directory with localized help/pre/systm/title bundles",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=TMP_DIR / "localized_bundles" / "build",
        help="Destination directory for copied/replaced bundles",
    )
    parser.add_argument(
        "--replacements-json",
        type=Path,
        default=None,
        help="Optional JSON mapping bundle_name -> replacement bundle path",
    )
    parser.add_argument(
        "--manifest-out",
        type=Path,
        default=None,
        help="Optional path for the generated build manifest JSON",
    )
    return parser.parse_args()


def load_replacements(path: Path | None) -> dict[str, Path]:
    if path is None:
        return {}

    payload = read_json(path)
    if isinstance(payload, dict) and "modified_bundles" in payload:
        payload = payload["modified_bundles"]
    if not isinstance(payload, dict):
        raise ValueError("replacement JSON must be an object mapping bundle names to file paths")

    replacements: dict[str, Path] = {}
    for bundle_name, replacement in payload.items():
        replacement_path = Path(str(replacement))
        if not replacement_path.is_absolute():
            replacement_path = (path.parent / replacement_path).resolve()
        replacements[str(bundle_name)] = replacement_path
    return replacements


def main() -> int:
    args = parse_args()
    replacements = load_replacements(args.replacements_json)
    manifest = materialize_localized_bundle_build(
        bundle_dir=args.bundle_dir,
        output_dir=args.output_dir,
        replacements=replacements,
    )
    manifest_out = args.manifest_out or (args.output_dir / "bundle_build_manifest.json")
    write_json(manifest_out, manifest)
    changed = sum(1 for bundle in manifest["bundles"] if not bundle["identical_to_source"])
    print(
        "Localized bundle build complete:",
        f"bundles={manifest['bundle_count']}",
        f"declared_modified={len(manifest['declared_modified_bundles'])}",
        f"changed={changed}",
        f"manifest={manifest_out}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
