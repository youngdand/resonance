#!/usr/bin/env python3
"""Allowlisted public release builder. Never copies a live installation or data folder."""
from pathlib import Path
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED
import argparse, hashlib, json, re, shutil, subprocess, sys

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {
    "LICENSE",
    "README.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "VERSION",
    "requirements.txt",
    "global.json",
    "package.json",
    "package-lock.json",
    "pyproject.toml",
    ".gitignore",
    ".prettierrc.json",
    "Install-Resonance.cmd",
    "Setup-New-User.cmd",
    "Start-Engine.cmd",
    "Start-Resonance.cmd",
    "Start-Resonance-with-Engine.cmd",
}
ROOT_PY = {
    "album_jobs.py",
    "build_meta.py",
    "config_journal.py",
    "diagnostics.py",
    "discovery.py",
    "downloads.py",
    "features.py",
    "folder_scan.py",
    "identity.py",
    "launch_engine.py",
    "library_index.py",
    "library_sync.py",
    "metadata_store.py",
    "new_releases.py",
    "realtime.py",
    "release_artwork.py",
    "release_context.py",
    "release_details.py",
    "release_genres.py",
    "release_sources.py",
    "review_sources.py",
    "server.py",
    "setup_user.py",
    "showcase_data.py",
    "storage.py",
    "supplier_http.py",
    "transfer_progress.py",
    "transfer_state.py",
}
TREES = {"web", "docs", "scripts", "tests", "engine", ".github"}
OMIT = {
    "bin",
    "obj",
    "__pycache__",
    "node_modules",
    ".git",
    "dist",
    "build",
    "TestResults",
    ".vs",
    ".vscode",
    ".idea",
    "test-results",
    "playwright-report",
}
PRIVATE_SUFFIX = {
    ".db",
    ".sqlite",
    ".sqlite3",
    ".bak",
    ".pfx",
    ".p12",
    ".key",
    ".log",
    ".pyc",
    ".pdb",
}
SECRET = re.compile(
    rb"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[A-Z0-9]{16}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)"
)


def public_files(root=ROOT):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(p in OMIT for p in rel.parts):
            continue
        if path.is_symlink():
            raise ValueError("Symlink excluded: " + str(rel))
        if len(rel.parts) == 1:
            if rel.name not in ROOT_FILES | ROOT_PY:
                continue
        elif rel.parts[0] not in TREES:
            continue
        if path.suffix.lower() in PRIVATE_SUFFIX or ".db-" in path.name or ".sqlite3-" in path.name:
            raise ValueError("Private state in public source tree: " + str(rel))
        if (
            rel.parts[0] == "engine"
            and "config" == rel.parts[1]
            and rel.name != "slskd.example.yml"
        ):
            raise ValueError("Only the sanitised example configuration may ship")
        raw = path.read_bytes()
        if SECRET.search(raw):
            raise ValueError("Credential pattern found in " + str(rel))
        if len(raw) > 20_000_000:
            raise ValueError("Unexpected large source file: " + str(rel))
        yield rel.as_posix(), path


def zip_files(output, files):
    # Stable order, timestamps and permissions; no machine paths in the manifest.
    with ZipFile(output, "w", ZIP_DEFLATED, compresslevel=9) as archive:
        for name, path in sorted(files):
            info = ZipInfo("Resonance/" + name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--build-engine", action="store_true")
    p.add_argument("--dotnet", default="dotnet")
    p.add_argument("--skip-engine-tests", action="store_true")
    a = p.parse_args()
    version = (ROOT / "VERSION").read_text().strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+-rc\.\d+", version):
        raise ValueError("Expected release candidate version")
    out = ROOT / "dist"
    out.mkdir(exist_ok=True)
    files = list(public_files())
    manifest = {
        "version": version,
        "files": {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in files},
    }
    manifest_path = out / "PUBLIC-MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    files.append(("PUBLIC-MANIFEST.json", manifest_path))
    source = out / f"Resonance-{version}-Source.zip"
    zip_files(source, files)
    print(f"Validated {len(files)} public source files: {source.name}")
    if a.build_engine:
        engine = out / "engine-win-x64"
        if engine.exists():
            shutil.rmtree(engine)
        cmd = [
            sys.executable,
            str(ROOT / "engine/build_engine.py"),
            "--output",
            str(engine),
            "--dotnet",
            a.dotnet,
        ]
        if a.skip_engine_tests:
            cmd.append("--skip-tests")
        subprocess.run(cmd, check=True)
        if not (engine / "ResonanceEngine.exe").exists():
            raise ValueError("Matching engine executable is missing")
        binaries = [
            ("Engine/" + x.relative_to(engine).as_posix(), x)
            for x in engine.rglob("*")
            if x.is_file() and x.suffix not in {".pdb"}
        ]
        release = out / f"Resonance-{version}-Windows-x64.zip"
        zip_files(release, files + binaries)
        print("Built " + release.name)
    for path in sorted(out.glob("*.zip")):
        print(hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.name)


if __name__ == "__main__":
    main()
