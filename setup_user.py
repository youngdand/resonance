"""Create a private first-run configuration. No secrets are shipped in releases."""

from pathlib import Path
from getpass import getpass
import os, secrets, json, sys


def main():
    import server, storage
    from ruamel.yaml import YAML

    server.init()
    config = server.DATA / "engine.yml"
    if config.exists():
        print("A private configuration already exists. Use Settings to change it.")
        return
    print("Resonance first-time setup. Your details stay in the private data folder.")
    username = input("Soulseek username: ").strip()
    password = getpass("Soulseek password (hidden): ")
    if not username or not password:
        raise ValueError("A Soulseek username and password are required.")
    folder = (
        input("Completed downloads folder (blank for your Music/Resonance folder): ")
        .strip()
        .strip('"')
    )
    downloads = Path(folder).expanduser() if folder else Path.home() / "Music" / "Resonance"
    if not downloads.is_absolute():
        raise ValueError("Use an absolute downloads folder.")
    downloads.mkdir(parents=True, exist_ok=True)
    incomplete = downloads / ".incomplete"
    incomplete.mkdir(exist_ok=True)
    share = input("Music folder to share (blank to configure sharing later): ").strip().strip('"')
    if share and not Path(share).expanduser().is_dir():
        raise ValueError("The shared folder does not exist.")
    if share:
        share = str(Path(share).expanduser().resolve())
    key = secrets.token_urlsafe(48)
    web_password = secrets.token_urlsafe(32)
    value = {
        "instance_name": "resonance",
        "flags": {"no_version_check": True},
        "web": {
            "ip_address": "127.0.0.1",
            "port": 5030,
            "https": {"disabled": True},
            "authentication": {
                "username": "resonance",
                "password": web_password,
                "api_keys": {
                    "resonance": {
                        "key": key,
                        "role": "Administrator",
                        "cidr": "127.0.0.1/32",
                    }
                },
            },
        },
        "soulseek": {"username": username, "password": password},
        "directories": {"downloads": str(downloads), "incomplete": str(incomplete)},
        "shares": {"directories": [share] if share else []},
    }
    with config.open("w", encoding="utf-8") as f:
        YAML().dump(value, f)
    try:
        os.chmod(config, 0o600)
    except OSError:
        pass
    storage.settings_patch(
        server,
        {
            "url": "http://127.0.0.1:5030",
            "key": key,
            "slskdConfig": str(config.resolve()),
            "librarySource": "slskd",
            "discoveryOnline": False,
            "engineAppDir": str((server.DATA / "engine").resolve()),
        },
    )
    print(
        "Setup saved locally. No credentials were printed. Start Resonance with Engine to connect."
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("Setup did not finish: " + str(exc))
        sys.exit(1)
