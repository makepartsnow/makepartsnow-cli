"""What the CLI keeps on this computer: consent and the last ZIP (settings.json), and the files it uploaded with
their delete tokens (uploads.json), so ``mpn delete --all`` can remove them later. Nothing else is stored."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

CONSENT_VERSION = 1


def config_dir() -> Path:
    """%APPDATA%\\makepartsnow, ~/Library/Application Support/makepartsnow or $XDG_CONFIG_HOME/makepartsnow;
    MPN_CONFIG_DIR overrides it (tests, CI)."""
    override = os.environ.get("MPN_CONFIG_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "makepartsnow"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "makepartsnow"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "makepartsnow"


def _read(name: str, default: Any) -> Any:
    try:
        with open(config_dir() / name, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return default
    return data if isinstance(data, type(default)) else default


def _write(name: str, data: Any) -> None:
    """Write atomically, readable only by this user where the OS supports it."""
    directory = config_dir()
    directory.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=f".{name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
        os.chmod(tmp, 0o600)
        os.replace(tmp, directory / name)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def settings() -> dict[str, Any]:
    return _read("settings.json", {})


def save_settings(data: dict[str, Any]) -> None:
    _write("settings.json", data)


def has_consent() -> bool:
    return int(settings().get("consent_version") or 0) >= CONSENT_VERSION


def record_consent() -> None:
    data = settings()
    data["consent_version"] = CONSENT_VERSION
    data["consent_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    save_settings(data)


def last_zip() -> Optional[str]:
    value = settings().get("zip")
    return value if isinstance(value, str) and value else None


def remember_zip(zip_code: str) -> None:
    data = settings()
    data["zip"] = zip_code
    save_settings(data)


def uploads() -> list[dict[str, Any]]:
    return [u for u in _read("uploads.json", []) if isinstance(u, dict) and u.get("part_id") and u.get("delete_token")]


def add_uploads(entries: list[dict[str, Any]], base_url: str) -> None:
    """Remember uploaded parts (part_id, delete_token, file name, quote id), keeping the first token per part."""
    known = {u["part_id"]: u for u in uploads()}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for entry in entries:
        if entry.get("part_id") and entry.get("delete_token") and entry["part_id"] not in known:
            known[entry["part_id"]] = {**entry, "base_url": base_url, "uploaded_at": now}
    _write("uploads.json", list(known.values()))


def forget_uploads(part_ids: set[str]) -> None:
    _write("uploads.json", [u for u in uploads() if u["part_id"] not in part_ids])
