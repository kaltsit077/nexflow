"""GitHub token for catalog API (raise rate limit; never commit the file)."""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path
from typing import Any

from .config import ROOT

# Local secret file (gitignored). Env overrides file.
TOKEN_PATH = ROOT / ".github_token"
# Classic PAT create page — no scopes required just to authenticate API.
CREATE_TOKEN_URL = "https://github.com/settings/tokens/new"
# Fine-grained alternative (Docs tip in UI).
CREATE_FINE_GRAINED_URL = "https://github.com/settings/personal-access-tokens/new"

ENV_KEYS = ("GAME_RUNNER_GITHUB_TOKEN", "GITHUB_TOKEN")


def get_github_token() -> str:
    for key in ENV_KEYS:
        val = (os.environ.get(key) or "").strip()
        if val:
            return val
    if TOKEN_PATH.is_file():
        try:
            return TOKEN_PATH.read_text(encoding="utf-8").strip()
        except OSError:
            return ""
    return ""


def set_github_token(token: str) -> Path | None:
    """Save token to .github_token. Empty string clears. Returns path or None if cleared."""
    text = (token or "").strip()
    if not text:
        clear_github_token()
        return None
    TOKEN_PATH.write_text(text + "\n", encoding="utf-8")
    try:
        os.chmod(TOKEN_PATH, 0o600)
    except OSError:
        pass
    return TOKEN_PATH


def clear_github_token() -> None:
    try:
        TOKEN_PATH.unlink(missing_ok=True)
    except OSError:
        pass


def token_status() -> dict[str, Any]:
    """UI-facing status without exposing the full secret."""
    for key in ENV_KEYS:
        val = (os.environ.get(key) or "").strip()
        if val:
            return {
                "configured": True,
                "source": f"环境变量 {key}",
                "masked": _mask(val),
                "editable": False,
            }
    if TOKEN_PATH.is_file():
        val = get_github_token()
        if val:
            return {
                "configured": True,
                "source": str(TOKEN_PATH.name),
                "masked": _mask(val),
                "editable": True,
            }
    return {
        "configured": False,
        "source": "",
        "masked": "",
        "editable": True,
    }


def _mask(token: str) -> str:
    t = token.strip()
    if len(t) <= 8:
        return "****"
    return f"{t[:4]}…{t[-4:]}"


def auth_headers(token: str | None = None) -> dict[str, str]:
    """Extra headers for api.github.com when a token is available."""
    tok = (token if token is not None else get_github_token()).strip()
    if not tok:
        return {}
    return {"Authorization": f"Bearer {tok}"}


def probe_rate_limit(
    timeout: int = 30, *, token: str | None = None
) -> dict[str, Any]:
    """Hit /rate_limit to verify token / show remaining quota.

    If ``token`` is passed, use it for this probe only (does not save).
    """
    use = (token if token is not None else get_github_token()).strip()
    headers = {
        "User-Agent": "GameRunner-Catalog/1.0",
        "Accept": "application/vnd.github+json",
        **auth_headers(use),
    }
    req = urllib.request.Request("https://api.github.com/rate_limit", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}
    core = (data.get("resources") or {}).get("core") or {}
    return {
        "ok": True,
        "limit": core.get("limit"),
        "remaining": core.get("remaining"),
        "authenticated": bool(use),
        "masked": _mask(use) if use else "",
    }
