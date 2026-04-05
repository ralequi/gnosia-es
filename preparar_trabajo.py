from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from gnosia_common import OUTPUT_DIR, WORK_DIR, create_work_corpus_from_manifest  # noqa: E402


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
        default=WORK_DIR,
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

    try:
        work_manifest = create_work_corpus_from_manifest(
            source_manifest_path=args.source_manifest,
            work_dir=args.work_dir,
            force=args.force,
        )
    except FileExistsError as exc:
        raise SystemExit(f"{exc} (use --force to overwrite)") from exc

    print(f"Work corpus created at: {args.work_dir}")
    print(f"Entities copied: {len(work_manifest['entities'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
