from __future__ import annotations

from pathlib import Path

from grocery_automation import config


def test_default_paths_live_under_app_home(monkeypatch):
    monkeypatch.setenv("GROCERY_AUTOMATION_HOME", "/tmp/grocery-automation-test")

    app_home = config.app_home()

    assert app_home == Path("/tmp/grocery-automation-test")
    assert config.default_state_path().parent == app_home
    assert config.default_data_dir().parent == app_home
    assert config.default_output_dir().parent == app_home
    assert config.default_worker_dir().parent == app_home


def test_grocery_cli_command_uses_module_by_default(monkeypatch):
    monkeypatch.delenv("GROCERY_SHOPPING_BIN", raising=False)
    command = config.grocery_cli_command()
    assert command[-2:] == ["-m", "grocery_automation.cli_grocery"]
