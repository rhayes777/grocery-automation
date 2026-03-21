from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_module(module: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    return subprocess.run(
        [sys.executable, "-m", module, *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_grocery_help():
    result = run_module("grocery_automation.cli_grocery", "--help")
    assert result.returncode == 0
    assert "sainsburys" in result.stdout
    assert "ocado" in result.stdout


def test_weekly_help():
    result = run_module("grocery_automation.cli_weekly", "--help")
    assert result.returncode == 0
    assert "slot-suggest" in result.stdout
    assert "open-checkout" in result.stdout
