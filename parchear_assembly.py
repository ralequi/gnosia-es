from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = SCRIPT_DIR.parent / "Gnosia_Data" / "Managed" / "Assembly-CSharp.dll"
DEFAULT_OUTPUT = SCRIPT_DIR / "tmp" / "managed" / "Assembly-CSharp.dll"
HELPER_SOURCE = SCRIPT_DIR / "parchear_assembly_helper.cs"
HELPER_BUILD_DIR = SCRIPT_DIR / "tmp" / "assembly_patcher"
EXPECTED_INPUT_SHA256 = "d5b0f013fc343e5cdde56f598a251c7cd7acfdd258430910b50707faf2362fe2"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Patch GNOSIA runtime English grammar literals into Spanish on a DLL copy."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--cecil",
        type=Path,
        default=None,
        help="Path to Mono.Cecil.dll; auto-detected from the Mono GAC by default.",
    )
    parser.add_argument(
        "--allow-unknown-source",
        action="store_true",
        help="Allow a source DLL with an unknown SHA-256; IL match counts are still enforced.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing generated output file.",
    )
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_cecil(explicit_path: Path | None) -> Path:
    if explicit_path is not None:
        if not explicit_path.is_file():
            raise SystemExit(f"Mono.Cecil.dll not found: {explicit_path}")
        return explicit_path.resolve()

    gac_root = Path("/usr/lib/mono/gac/Mono.Cecil")
    candidates = sorted(gac_root.glob("0.11.*/Mono.Cecil.dll"), reverse=True)
    candidates.extend(sorted(gac_root.glob("*/Mono.Cecil.dll"), reverse=True))
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise SystemExit("Mono.Cecil.dll not found; pass its path with --cecil")


def require_command(name: str) -> str:
    command = shutil.which(name)
    if command is None:
        raise SystemExit(f"required command not found: {name}")
    return command


def main() -> int:
    args = parse_args()
    input_path = args.input.resolve()
    output_path = args.output.resolve()

    if not input_path.is_file():
        raise SystemExit(f"input DLL not found: {input_path}")
    if input_path == output_path:
        raise SystemExit("refusing to patch the installed DLL in place")

    input_sha256 = sha256_file(input_path)
    if input_sha256 != EXPECTED_INPUT_SHA256 and not args.allow_unknown_source:
        raise SystemExit(
            "unexpected Assembly-CSharp.dll SHA-256: "
            f"{input_sha256}; expected {EXPECTED_INPUT_SHA256}"
        )

    if output_path.exists():
        if not args.force:
            raise SystemExit(f"output already exists (use --force): {output_path}")
        output_path.unlink()

    cecil_path = find_cecil(args.cecil)
    compiler = require_command("mcs")
    runtime = require_command("mono")
    if not HELPER_SOURCE.is_file():
        raise SystemExit(f"patch helper source not found: {HELPER_SOURCE}")

    HELPER_BUILD_DIR.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    helper_exe = HELPER_BUILD_DIR / "AssemblyPatcher.exe"

    compile_result = subprocess.run(
        [
            compiler,
            "-nologo",
            "-optimize+",
            "-target:exe",
            f"-r:{cecil_path}",
            f"-out:{helper_exe}",
            str(HELPER_SOURCE),
        ],
        check=False,
    )
    if compile_result.returncode != 0:
        return compile_result.returncode

    patch_result = subprocess.run(
        [runtime, str(helper_exe), str(input_path), str(output_path)],
        check=False,
    )
    if patch_result.returncode != 0:
        return patch_result.returncode

    print(f"Source SHA-256:  {input_sha256}")
    print(f"Patched SHA-256: {sha256_file(output_path)}")
    print(f"Patched DLL: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
