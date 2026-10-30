"""Canonical application/build version shared by the service, UI and engine."""

from pathlib import Path

VERSION = (Path(__file__).parent / "VERSION").read_text(encoding="utf-8").strip()
