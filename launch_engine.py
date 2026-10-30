"""Start the bundled engine against the existing compatible configuration and data."""

from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen
import json, os, shutil, socket, sqlite3, subprocess, sys, time

ROOT = Path(__file__).resolve().parent


def saved_settings():
    database = Path(os.environ.get("RESONANCE_DATA_DIR", str(ROOT / "data"))) / "resonance.db"
    if not database.exists():
        return {}
    import storage

    with storage.connect(database) as c:
        row = c.execute("SELECT value FROM settings WHERE id=1").fetchone()
        return json.loads(row[0]) if row else {}


def main():
    if "--wait-ready" in sys.argv:
        settings = saved_settings()
        if not settings.get("key"):
            raise ValueError(
                "Run Setup-New-User.cmd or save your engine API key in Settings first."
            )
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                from urllib.request import Request

                with urlopen(
                    Request(
                        settings.get("url", "http://127.0.0.1:5030").rstrip("/")
                        + "/api/v0/application",
                        headers={"X-API-Key": settings.get("key", "")},
                    ),
                    timeout=2,
                ) as response:
                    if response.status == 200:
                        return 0
            except OSError:
                pass
            time.sleep(0.5)
        raise ValueError("Engine readiness timed out. Check its configuration, API key and port.")
    if os.name != "nt":
        raise ValueError(
            "This launcher is for Windows. The engine source can also be built for Linux."
        )
    settings = saved_settings()
    address = urlsplit(settings.get("url", "http://127.0.0.1:5030"))
    if address.scheme != "http" or address.hostname not in ("localhost", "127.0.0.1"):
        raise ValueError(
            "The combined launcher requires a local HTTP backend address in Resonance Settings."
        )
    port = address.port or 80
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            pass
    except OSError:
        pass
    else:
        try:
            with urlopen("http://127.0.0.1:" + str(port) + "/", timeout=2) as r:
                engine = b"Resonance Engine" in r.read(20000)
        except Exception:
            engine = False
        if engine:
            print("Resonance Engine is already running.")
            return 0
        raise ValueError(
            "Another backend is already listening. Close the existing slskd console with Ctrl+C, then run this launcher again."
        )
    candidates = [
        sys.argv[1] if len(sys.argv) > 1 else "",
        settings.get("slskdConfig", ""),
        str(ROOT / "data" / "engine.yml"),
    ]
    config = next((Path(x) for x in candidates if x and Path(x).is_file()), None)
    if config is None:
        value = input("Full path to your existing slskd.yml: ").strip().strip('"')
        config = Path(value)
        if not config.is_file():
            raise ValueError("Configuration file not found. No changes were made.")
    executable = ROOT / "Engine" / "ResonanceEngine.exe"
    if not executable.is_file():
        raise ValueError("Engine/ResonanceEngine.exe is missing. Extract the complete update ZIP.")
    # Keep the original application directory, including default incomplete/download paths.
    app = Path(
        settings.get("engineAppDir")
        or (
            str(Path(os.environ["LOCALAPPDATA"]) / "slskd")
            if (Path(os.environ["LOCALAPPDATA"]) / "slskd").exists()
            else str(ROOT / "data" / "engine")
        )
    )
    app.mkdir(parents=True, exist_ok=True)
    backups = Path(os.environ.get("RESONANCE_DATA_DIR", str(ROOT / "data"))) / "engine-backups"
    marker = backups / "first-engine-start.json"
    if not marker.exists():
        backup = backups / time.strftime("%Y%m%d-%H%M%S")
        backup.mkdir(parents=True, exist_ok=False)
        if (app / "data").exists():
            shutil.copytree(app / "data", backup / "data")
        shutil.copy2(config, backup / "slskd.yml")
        marker.write_text(
            json.dumps({"created": time.time(), "backup": str(backup)}),
            encoding="utf-8",
        )
        print(
            "A backup of the previous backend data and configuration has been saved under data/engine-backups."
        )
    print("Starting Resonance Engine. Press Ctrl+C in this window for a normal shutdown.")
    process = subprocess.Popen(
        [
            str(executable),
            "--config",
            str(config.resolve()),
            "--app-dir",
            str(app),
            "--no-https",
            "--http-ip-address",
            "127.0.0.1",
            "--http-port",
            str(port),
            "--no-version-check",
        ]
    )
    try:
        return process.wait()
    except KeyboardInterrupt:
        try:
            return process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            print("Engine is still shutting down. Leave this window open until it finishes.")
            return process.wait()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print("Resonance Engine could not start: " + str(e))
        input("Press Enter to close...")
        sys.exit(1)
