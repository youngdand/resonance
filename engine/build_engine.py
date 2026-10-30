#!/usr/bin/env python3
# Copyright (c) 2026 Resonance contributors.
# AGPL-3.0-only with Additional Terms. See LICENSE for the complete licence.
"""Rebuild and package the engine, retaining the corresponding source offer."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import argparse, os, shutil, subprocess

ROOT = Path(__file__).resolve().parent


def source_zip(target):
    with ZipFile(target, "w", ZIP_DEFLATED, compresslevel=6) as archive:
        archive.write(ROOT.parent / "VERSION", "ResonanceEngine-Source/VERSION")
        archive.write(ROOT.parent / "global.json", "ResonanceEngine-Source/global.json")
        for folder, dirs, files in os.walk(ROOT):
            dirs[:] = [
                d
                for d in dirs
                if d
                not in (
                    ".git",
                    "node_modules",
                    "obj",
                    "build",
                    "dist",
                    "TestResults",
                    "__pycache__",
                )
                and not (d == "bin" and Path(folder) != ROOT)
            ]
            for name in files:
                path = Path(folder) / name
                if name in ("Engine-Source.zip", "source.zip") or path.suffix in (".pyc", ".pdb"):
                    continue
                archive.write(
                    path, Path("ResonanceEngine-Source") / "engine" / path.relative_to(ROOT)
                )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", default=str(ROOT / "dist" / "win-x64"))
    p.add_argument("--dotnet", default="dotnet")
    p.add_argument("--skip-tests", action="store_true")
    a = p.parse_args()
    output = Path(a.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    if not a.skip_tests:
        subprocess.run(
            [
                a.dotnet,
                "test",
                str(ROOT / "tests/slskd.Tests.Unit/slskd.Tests.Unit.csproj"),
                "-p:RunAnalyzers=false",
            ],
            check=True,
        )
    subprocess.run(
        [
            a.dotnet,
            "publish",
            str(ROOT / "src/slskd/slskd.csproj"),
            "-c",
            "Release",
            "-r",
            "win-x64",
            "--self-contained",
            "true",
            "-p:PublishSingleFile=true",
            "-p:IncludeNativeLibrariesForSelfExtract=true",
            "-p:RunAnalyzers=false",
            "-o",
            str(output),
        ],
        check=True,
    )
    source_zip(output / "Engine-Source.zip")
    www = output / "wwwroot"
    www.mkdir(exist_ok=True)
    shutil.copy2(output / "Engine-Source.zip", www / "source.zip")
    shutil.copy2(ROOT / "LICENSE", www / "LICENSE")
    shutil.copy2(ROOT / "LICENSE", www / "license.txt")
    for name in ("LICENSE", "NOTICE", "README.md", "UPSTREAM.json"):
        shutil.copy2(ROOT / name, output / name)
    print("Engine and corresponding source ready:", output)


if __name__ == "__main__":
    main()
