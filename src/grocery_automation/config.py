from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Optional


APP_NAME = "grocery-automation"


def app_home() -> Path:
    override = os.environ.get("GROCERY_AUTOMATION_HOME")
    if override:
        return Path(override).expanduser()
    if platform.system() == "Darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    xdg_state = os.environ.get("XDG_STATE_HOME")
    if xdg_state:
        return Path(xdg_state).expanduser() / APP_NAME
    return Path.home() / ".local" / "state" / APP_NAME


def default_state_path() -> Path:
    return app_home() / "state.json"


def default_data_dir() -> Path:
    return app_home() / "data"


def default_output_dir() -> Path:
    return app_home() / "playwright"


def default_worker_dir() -> Path:
    return app_home() / "worker"


def default_calendar_name() -> str:
    return os.environ.get("WEEKLY_SHOP_CALENDAR", "Primary")


def grocery_cli_command() -> list[str]:
    override = os.environ.get("GROCERY_SHOPPING_BIN")
    if override:
        return [override]
    return [sys.executable, "-m", "grocery_automation.cli_grocery"]


def resolve_gcalcli() -> Optional[list[str]]:
    override = os.environ.get("WEEKLY_SHOP_GCALCLI")
    if override:
        return [override]
    candidate = shutil.which("gcalcli")
    if candidate:
        return [candidate]
    return None


def resolve_pwcli() -> list[str]:
    override = os.environ.get("GROCERY_PLAYWRIGHT_CLI")
    if override:
        return override.split()
    candidate = shutil.which("playwright-cli")
    if candidate:
        return [candidate]
    codex_wrapper = Path.home() / ".codex" / "skills" / "playwright" / "scripts" / "playwright_cli.sh"
    if codex_wrapper.exists():
        return ["bash", str(codex_wrapper)]
    raise SystemExit(
        "Could not find a Playwright CLI. Install `playwright-cli` or set "
        "`GROCERY_PLAYWRIGHT_CLI` to the command used to drive browser sessions."
    )
