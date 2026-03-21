from __future__ import annotations

from datetime import time

from grocery_automation.cli_weekly import parse_time_with_inference


def test_parse_time_with_reference_infers_meridiem():
    assert parse_time_with_inference("7:00", reference=time(23, 0)) == time(19, 0)


def test_parse_time_without_reference_uses_24h():
    assert parse_time_with_inference("07:30") == time(7, 30)
