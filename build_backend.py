#!/usr/bin/env python3
"""Rebuild unmodified pinned Atheris against the shared patched PIC archive.

Run inside the active Python venv; this intentionally replaces Atheris's wheel
with the same upstream version, not a Python fork or a preload interposer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

VERSION = "3.0.0"
SDIST_URL = "https://files.pythonhosted.org/packages/f8/58/5965955898e16bee17c8379eae12194993bf641c4629016991248b862069/atheris-3.0.0.tar.gz"
SDIST_SHA256 = "1f0929c7bc3040f3fe4102e557718734190cf2d7718bbb8e3ce6d3eb56ef5bb3"
ROOT = Path(__file__).resolve().parent


def run(args, **kwargs):
    print("+", " ".join(map(str, args)), flush=True)
    subprocess.run(list(map(str, args)), check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--libfuzzer", type=Path, default=ROOT.parent / "tkur_libfuzzer/build/libclang_rt.fuzzer_no_main.a")
    parser.add_argument("--build-dir", type=Path, default=ROOT / "build")
    parser.add_argument("--backend-only", action="store_true", help="install rebuilt upstream Atheris only; skip overlay install/probe for Docker cache layering")
    parser.add_argument("--sdist", type=Path, help="optional offline source tarball, exact SHA256 required")
    args = parser.parse_args()
    if not args.libfuzzer.is_file():
        parser.error(
            "PIC no_main archive not found: " + str(args.libfuzzer) +
            ". Build the sibling tkur_libfuzzer checkout with CMake first: "
            "cmake -S ../tkur_libfuzzer -B ../tkur_libfuzzer/build "
            "-DCMAKE_CXX_COMPILER=clang++-18 && "
            "cmake --build ../tkur_libfuzzer/build --parallel 2; "
            "or pass --libfuzzer /absolute/path/libclang_rt.fuzzer_no_main.a"
        )
    archive = args.libfuzzer.resolve(strict=True)
    initial_archive_sha256 = hashlib.sha256(archive.read_bytes()).hexdigest()
    build = args.build_dir.resolve()
    build.mkdir(parents=True, exist_ok=True)
    tarball = args.sdist or build / f"atheris-{VERSION}.tar.gz"
    if not tarball.is_file():
        if args.sdist:
            parser.error("--sdist does not exist")
        with urllib.request.urlopen(SDIST_URL, timeout=120) as response:
            tarball.write_bytes(response.read())
    actual = hashlib.sha256(tarball.read_bytes()).hexdigest()
    if actual != SDIST_SHA256:
        raise SystemExit(f"Atheris source SHA256 mismatch: {actual}")
    # Fresh extraction forces relinking when the native archive changes. Never
    # reuse setuptools' cached object/shared-library outputs from an older run.
    work = Path(tempfile.mkdtemp(prefix="atheris-build-", dir=build))
    # data filter rejects links/path traversal; available on our Python 3.12.
    with tarfile.open(tarball) as source:
        source.extractall(work, filter="data")
    source_dir = work / f"atheris-{VERSION}"
    wheel_dir = work / "wheels"
    wheel_dir.mkdir()
    environment = dict(os.environ, CC="clang-18", CXX="clang++-18", CLANG_BIN="clang-18", LIBFUZZER_LIB=str(archive), CFLAGS="-O1 -g0", CXXFLAGS="-O1 -g0")
    run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation", "--no-cache-dir", "--wheel-dir", wheel_dir, source_dir], env=environment)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != initial_archive_sha256:
        raise SystemExit("Native archive changed during Atheris build; rebuild after native finishes")
    wheels = list(wheel_dir.glob(f"atheris-{VERSION}-*.whl"))
    if len(wheels) != 1:
        raise SystemExit(f"Expected exactly one built Atheris wheel; found {len(wheels)}")
    run([sys.executable, "-m", "pip", "install", "--no-deps", "--force-reinstall", wheels[0]])
    if not args.backend_only:
        run([sys.executable, "-m", "pip", "install", "--no-deps", "--no-build-isolation", "-e", ROOT])
        run([sys.executable, "-m", "tkur_atheris", "--backend-info"])
    manifest = {"atheris_version": VERSION, "atheris_sdist_sha256": actual,
                "libfuzzer_archive": str(archive), "libfuzzer_sha256": initial_archive_sha256,
                "wheel": str(wheels[0]), "python": sys.version}
    (build / "backend-build.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    shutil.copyfile(source_dir / "LICENSE", build / "ATHERIS-LICENSE")


if __name__ == "__main__":
    main()
