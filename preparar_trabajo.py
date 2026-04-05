from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from gnosia_common import ENTITY_JSON_DIRNAME, OUTPUT_DIR, ensure_dir, read_json, write_json  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a tracked work corpus from the extracted snapshot.")
    parser.add_argument(
        "--source-manifest",
        type=Path,
        default=OUTPUT_DIR / "manifest.json",
        help="Path to the extracted snapshot manifest.",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=SCRIPT_DIR / "work",
        help="Destination directory for the tracked work corpus.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the existing work directory if it already exists.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.source_manifest.exists():
        raise SystemExit(f"Source manifest not found: {args.source_manifest}")

    work_dir = args.work_dir
    if work_dir.exists():
        if not args.force:
            raise SystemExit(f"Work directory already exists: {work_dir} (use --force to overwrite)")
        shutil.rmtree(work_dir)

    ensure_dir(work_dir / ENTITY_JSON_DIRNAME)
    manifest = read_json(args.source_manifest)
    source_base = args.source_manifest.parent

    for entry in manifest["entities"]:
        source_file = source_base / entry["file"]
        dest_file = work_dir / entry["file"]
        ensure_dir(dest_file.parent)
        shutil.copy2(source_file, dest_file)

    work_manifest = dict(manifest)
    work_manifest["translation_target_language"] = "es"
    work_manifest["translation_overrides_slot"] = "en"
    work_manifest["translation_source_manifest"] = str(args.source_manifest.resolve())
    work_manifest["translation_work_dir"] = str(work_dir.resolve())
    write_json(work_dir / "manifest.json", work_manifest)

    print(f"Work corpus created at: {work_dir}")
    print(f"Entities copied: {len(manifest['entities'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
