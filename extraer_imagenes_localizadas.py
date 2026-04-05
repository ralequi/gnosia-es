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
    ensure_dir,
    iter_localized_bundle_paths,
    load_unity_env,
    slugify_name,
    write_json,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract previews from GNOSIA localized raster bundles."
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
        default=TMP_DIR / "imagenes_localizadas",
        help="Directory for previews and the generated catalog",
    )
    return parser.parse_args()


def preview_priority(type_name: str) -> int:
    return 0 if type_name == "Sprite" else 1


def build_logical_key(*, asset_name: str, width: int, height: int, type_name: str, path_id: int) -> str:
    if asset_name:
        return f"{asset_name}|{width}x{height}"
    return f"{type_name}|{path_id}"


def main() -> int:
    args = parse_args()
    output_dir = ensure_dir(args.output_dir)
    previews_root = ensure_dir(output_dir / "previews")

    bundle_summaries: list[dict[str, object]] = []
    object_catalog: list[dict[str, object]] = []
    preview_count = 0

    for bundle_path, metadata in iter_localized_bundle_paths(args.bundle_dir):
        env, _ = load_unity_env(bundle_path)
        bundle_entries: list[dict[str, object]] = []
        preview_candidates: dict[str, dict[str, object]] = {}
        bundle_preview_dir = ensure_dir(previews_root / bundle_path.stem)

        for obj in env.objects:
            if obj.type.name not in {"Sprite", "Texture2D"}:
                continue

            data = obj.read()
            image = getattr(data, "image", None)
            if image is None:
                continue

            asset_name = str(getattr(data, "m_Name", "") or "")
            width, height = image.size
            logical_key = build_logical_key(
                asset_name=asset_name,
                width=width,
                height=height,
                type_name=obj.type.name,
                path_id=obj.path_id,
            )
            entry = {
                "bundle": bundle_path.name,
                "category": metadata["category"],
                "language": metadata["language"],
                "asset_name": asset_name,
                "type": obj.type.name,
                "path_id": obj.path_id,
                "width": width,
                "height": height,
                "logical_key": logical_key,
            }
            bundle_entries.append(entry)

            candidate = preview_candidates.get(logical_key)
            priority = preview_priority(obj.type.name)
            if candidate is None or (priority, obj.path_id) < (
                int(candidate["priority"]),
                int(candidate["path_id"]),
            ):
                preview_candidates[logical_key] = {
                    "entry": entry,
                    "image": image,
                    "priority": priority,
                    "path_id": obj.path_id,
                }

        preview_relpaths: dict[str, str] = {}
        for logical_key, candidate in sorted(preview_candidates.items()):
            chosen_entry = candidate["entry"]
            chosen_image = candidate["image"]
            asset_slug = slugify_name(str(chosen_entry["asset_name"])) or "asset"
            preview_name = (
                f"{asset_slug}_{chosen_entry['path_id']}_{chosen_entry['width']}x"
                f"{chosen_entry['height']}.png"
            )
            preview_path = bundle_preview_dir / preview_name
            chosen_image.save(preview_path)
            preview_relpaths[logical_key] = str(preview_path.relative_to(output_dir))
            preview_count += 1

        for entry in bundle_entries:
            object_catalog.append(
                {
                    **entry,
                    "preview_path": preview_relpaths[entry["logical_key"]],
                }
            )

        bundle_summaries.append(
            {
                "bundle": bundle_path.name,
                "category": metadata["category"],
                "language": metadata["language"],
                "object_count": len(bundle_entries),
                "preview_count": len(preview_candidates),
                "preview_dir": str(bundle_preview_dir.relative_to(output_dir)),
            }
        )

    catalog = {
        "bundle_root": str(args.bundle_dir.resolve()),
        "output_dir": str(output_dir.resolve()),
        "bundle_count": len(bundle_summaries),
        "object_count": len(object_catalog),
        "preview_count": preview_count,
        "bundles": bundle_summaries,
        "objects": object_catalog,
    }
    write_json(output_dir / "catalog.json", catalog)
    print(
        "Localized image extraction complete:",
        f"bundles={catalog['bundle_count']}",
        f"objects={catalog['object_count']}",
        f"previews={catalog['preview_count']}",
        f"catalog={output_dir / 'catalog.json'}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
