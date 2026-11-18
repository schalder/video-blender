"""Hybrid Video Blender license — activate online once, then work offline."""

from __future__ import annotations

import json
import os
import platform
import ssl
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    import certifi

    _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except Exception:  # noqa: BLE001
    _SSL_CONTEXT = ssl.create_default_context()

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
LICENSE_PATH = DATA / "license.json"
MACHINE_PATH = DATA / "machine_id.txt"
DEV_UNLOCK = DATA / ".dev_unlock"

SUPABASE_URL = (
    os.environ.get("VIDEO_BLENDER_SUPABASE_URL")
    or "https://tpsutldfptiypgtveply.supabase.co"
).rstrip("/")
ANON_KEY = os.environ.get("VIDEO_BLENDER_SUPABASE_ANON_KEY") or (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InRwc3V0bGRmcHRpeXBndHZlcGx5Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTM1NjY3MjAs"
    "ImV4cCI6MjEwOTE0MjcyMH0.nNrlIRQzMQMr6mo8tCWPiUd8JJo0swKI2SbeUt_hDg8"
)
LICENSE_FN = f"{SUPABASE_URL}/functions/v1/video-blender-license"
DASHBOARD_URL = os.environ.get(
    "VIDEO_BLENDER_DASHBOARD_URL",
    "https://flagbattle.powerkits.net/dashboard.html#/video-blender",
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def machine_id() -> str:
    DATA.mkdir(parents=True, exist_ok=True)
    if MACHINE_PATH.is_file():
        mid = MACHINE_PATH.read_text(encoding="utf-8").strip()
        if mid:
            return mid
    mid = uuid.uuid4().hex
    MACHINE_PATH.write_text(mid, encoding="utf-8")
    return mid


def machine_label() -> str:
    return f"{platform.system()} · {platform.node() or 'Desktop'}"


def _load() -> Optional[dict[str, Any]]:
    if not LICENSE_PATH.is_file():
        return None
    try:
        return json.loads(LICENSE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _save(payload: dict[str, Any]) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    LICENSE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def clear_license() -> None:
    LICENSE_PATH.unlink(missing_ok=True)


def _dev_unlocked() -> bool:
    if os.environ.get("VIDEO_BLENDER_DEV_UNLOCK", "").strip() in {"1", "true", "yes"}:
        return True
    return DEV_UNLOCK.is_file()


def _token_fresh(state: dict[str, Any]) -> bool:
    exp = state.get("token_expires_at")
    if not exp:
        return False
    try:
        when = datetime.fromisoformat(str(exp).replace("Z", "+00:00"))
    except ValueError:
        return False
    return when > _utc_now()


def _post(action: str, body: dict[str, Any], timeout: float = 20.0) -> dict[str, Any]:
    payload = json.dumps({"action": action, **body}).encode("utf-8")
    req = Request(
        LICENSE_FN,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {ANON_KEY}",
            "apikey": ANON_KEY,
        },
    )
    try:
        with urlopen(req, timeout=timeout, context=_SSL_CONTEXT) as res:
            raw = res.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            data = {"message": raw or str(exc)}
        data.setdefault("error", "http_error")
        data["_status"] = exc.code
        return data
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {"error": "network", "message": str(exc)}


def activate(license_key: str) -> dict[str, Any]:
    key = (license_key or "").strip().upper()
    if not key:
        return {"ok": False, "message": "Enter a license key."}
    mid = machine_id()
    data = _post(
        "activate",
        {
            "licenseKey": key,
            "machineId": mid,
            "machineLabel": machine_label(),
        },
    )
    if data.get("ok") and data.get("token"):
        _save(
            {
                "license_key": data.get("license", {}).get("licenseKey") or key,
                "token": data["token"],
                "token_expires_at": data.get("tokenExpiresAt"),
                "machine_id": mid,
                "activated_at": _utc_now().isoformat(),
                "license": data.get("license"),
            }
        )
        return {
            "ok": True,
            "message": "License activated.",
            "license": data.get("license"),
            "token_expires_at": data.get("tokenExpiresAt"),
        }
    return {
        "ok": False,
        "message": data.get("message") or data.get("error") or "Activation failed.",
    }


def status() -> dict[str, Any]:
    if _dev_unlocked():
        return {
            "licensed": True,
            "mode": "dev_unlock",
            "message": "Developer unlock active.",
            "dashboard_url": DASHBOARD_URL,
            "machine_id": machine_id(),
        }

    state = _load()
    if not state or not state.get("license_key") or not state.get("token"):
        return {
            "licensed": False,
            "mode": "none",
            "message": "Enter a license key to unlock Create.",
            "dashboard_url": DASHBOARD_URL,
            "machine_id": machine_id(),
        }

    # Prefer online refresh; fall back to offline token window.
    online = _post(
        "validate",
        {
            "licenseKey": state["license_key"],
            "machineId": state.get("machine_id") or machine_id(),
            "token": state.get("token"),
        },
        timeout=8.0,
    )
    if online.get("valid") and online.get("token"):
        state["token"] = online["token"]
        state["token_expires_at"] = online.get("tokenExpiresAt")
        state["license"] = online.get("license") or state.get("license")
        state["last_validated_at"] = _utc_now().isoformat()
        _save(state)
        return {
            "licensed": True,
            "mode": "online",
            "message": "Licensed",
            "license": state.get("license"),
            "license_key": state.get("license_key"),
            "token_expires_at": state.get("token_expires_at"),
            "dashboard_url": DASHBOARD_URL,
            "machine_id": machine_id(),
        }

    if online.get("error") == "network" and _token_fresh(state):
        return {
            "licensed": True,
            "mode": "offline",
            "message": "Licensed (offline)",
            "license": state.get("license"),
            "license_key": state.get("license_key"),
            "token_expires_at": state.get("token_expires_at"),
            "dashboard_url": DASHBOARD_URL,
            "machine_id": machine_id(),
        }

    if _token_fresh(state) and online.get("valid") is not False:
        # stale response but token still in window
        return {
            "licensed": True,
            "mode": "cached",
            "message": "Licensed",
            "license": state.get("license"),
            "license_key": state.get("license_key"),
            "token_expires_at": state.get("token_expires_at"),
            "dashboard_url": DASHBOARD_URL,
            "machine_id": machine_id(),
        }

    return {
        "licensed": False,
        "mode": "invalid",
        "message": online.get("reason")
        or online.get("message")
        or "License is not valid on this machine.",
        "dashboard_url": DASHBOARD_URL,
        "machine_id": machine_id(),
    }


def require_licensed() -> dict[str, Any]:
    """Return status; caller raises if not licensed."""
    return status()
