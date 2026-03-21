#!/usr/bin/env python3
"""Helper CLI for optional calendar-aware weekly grocery shopping."""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import webbrowser
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Optional

from grocery_automation.config import default_calendar_name, grocery_cli_command, resolve_gcalcli


DEFAULT_CALENDAR = default_calendar_name()
SUPPORTED_RETAILERS = {"ocado", "sainsburys"}
RETAILER_CHECKOUT_URLS = {
    "ocado": "https://www.ocado.com/checkout",
    "sainsburys": "https://www.sainsburys.co.uk/gol-ui/slot/book?slot_type=saver_slot",
}


@dataclass
class CalendarEvent:
    title: str
    start: Optional[datetime]
    end: Optional[datetime]
    all_day: bool


def serialise(data: Any) -> str:
    return json.dumps(data, indent=2, sort_keys=True)


def run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, capture_output=True, text=True)


def run_or_exit(command: list[str]) -> str:
    result = run_command(command)
    if result.returncode != 0:
        if result.stdout:
            print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
        if result.stderr:
            print(result.stderr, end="" if result.stderr.endswith("\n") else "\n")
        raise SystemExit(result.returncode)
    return result.stdout


def extract_json(output: str) -> Any:
    output = output.strip()
    for index, char in enumerate(output):
        if char not in "[{":
            continue
        candidate = output[index:]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    raise SystemExit("Command output did not contain JSON.")


def ensure_retailer_open(retailer: str) -> None:
    if retailer not in SUPPORTED_RETAILERS:
        raise SystemExit(f"Unsupported retailer {retailer!r}.")
    run_or_exit(grocery_cli_command() + [retailer, "open"])


def grocery_json(*args: str) -> Any:
    output = run_or_exit(grocery_cli_command() + list(args))
    return extract_json(output)


def parse_date_label(label: str, *, horizon_days: int = 14) -> date:
    today = datetime.now().date()
    target = label.strip()
    direct_formats = ("%a %d %B", "%A %d %B", "%a %d %b", "%A %d %b")
    for fmt in direct_formats:
        try:
            candidate = datetime.strptime(target, fmt).date().replace(year=today.year)
        except ValueError:
            continue
        if candidate < today:
            candidate = candidate.replace(year=today.year + 1)
        return candidate
    for offset in range(horizon_days + 1):
        candidate = today + timedelta(days=offset)
        if candidate.strftime("%a %-d") == target or candidate.strftime("%a %#d") == target:
            return candidate
        if candidate.strftime("%a %d").replace(" 0", " ") == target:
            return candidate
    raise SystemExit(f"Could not resolve slot date label {label!r}.")


def parse_time_with_inference(raw: str, reference: Optional[time] = None) -> time:
    value = raw.strip().lower()
    direct = ("%I:%M%p",)
    for fmt in direct:
        try:
            return datetime.strptime(value, fmt).time()
        except ValueError:
            continue
    if re.fullmatch(r"\d{1,2}:\d{2}", value):
        if reference is None:
            return datetime.strptime(value, "%H:%M").time()
        suffix = "pm" if reference.hour >= 12 else "am"
        candidate = datetime.strptime(value + suffix, "%I:%M%p").time()
        if candidate > reference:
            adjusted = (datetime.combine(date.today(), candidate) - timedelta(hours=12)).time()
            return adjusted
        return candidate
    if reference is None:
        raise ValueError(f"Could not parse time {raw!r}")
    for suffix in ("am", "pm"):
        try:
            candidate = datetime.strptime(value + suffix, "%I:%M%p").time()
        except ValueError:
            continue
        ref_minutes = reference.hour * 60 + reference.minute
        cand_minutes = candidate.hour * 60 + candidate.minute
        if 0 < ref_minutes - cand_minutes <= 240:
            return candidate
    raise ValueError(f"Could not infer meridiem for time {raw!r}")


def parse_slot_window(slot_date: date, window: str) -> tuple[datetime, datetime]:
    start_raw, end_raw = window.split("-", 1)
    end_time = parse_time_with_inference(end_raw)
    if re.search(r"(am|pm)\s*$", start_raw.strip().lower()):
        start_time = parse_time_with_inference(start_raw)
    else:
        start_time = parse_time_with_inference(start_raw, reference=end_time)
    start_dt = datetime.combine(slot_date, start_time)
    end_dt = datetime.combine(slot_date, end_time)
    if end_dt <= start_dt:
        end_dt += timedelta(hours=12)
        if end_dt <= start_dt:
            end_dt += timedelta(days=1)
    return start_dt, end_dt


def fetch_calendar_events(days: int, calendar_name: str) -> list[CalendarEvent]:
    gcalcli = resolve_gcalcli()
    if gcalcli is None:
        raise SystemExit(
            "Calendar support requires `gcalcli` or `WEEKLY_SHOP_GCALCLI`. "
            "Re-run with `--no-calendar` to score slots without calendar conflicts."
        )
    start = datetime.now().date().isoformat()
    end = (datetime.now().date() + timedelta(days=days)).isoformat()
    output = run_or_exit(
        ["env", "LANG=en_US.UTF-8", "LC_ALL=en_US.UTF-8"] + gcalcli
        + [
            "agenda",
            start,
            end,
            "--calendar",
            calendar_name,
            "--tsv",
            "--details",
            "end",
        ]
    )
    reader = csv.DictReader(output.splitlines(), delimiter="\t")
    events: list[CalendarEvent] = []
    for row in reader:
        start_date = row.get("start_date", "") or ""
        end_date = row.get("end_date", "") or ""
        start_time = row.get("start_time", "") or ""
        end_time = row.get("end_time", "") or ""
        title = row.get("title", "") or ""
        if not start_date:
            continue
        if not start_time and not end_time:
            start_dt = datetime.fromisoformat(f"{start_date}T00:00:00")
            if end_date:
                end_dt = datetime.fromisoformat(f"{end_date}T23:59:00")
            else:
                end_dt = start_dt + timedelta(days=1)
            events.append(CalendarEvent(title=title, start=start_dt, end=end_dt, all_day=True))
            continue
        start_dt = datetime.fromisoformat(f"{start_date}T{start_time}:00")
        end_dt = datetime.fromisoformat(f"{end_date}T{end_time}:00")
        events.append(CalendarEvent(title=title, start=start_dt, end=end_dt, all_day=False))
    return events


def overlaps(start_a: datetime, end_a: datetime, start_b: datetime, end_b: datetime) -> bool:
    return start_a < end_b and start_b < end_a


def score_slot(slot: dict[str, Any], events: list[CalendarEvent]) -> dict[str, Any]:
    slot_date = parse_date_label(str(slot["date_label"]))
    start_dt, end_dt = parse_slot_window(slot_date, str(slot["window"]))
    score = 100.0
    reasons: list[str] = []

    price_match = re.search(r"([0-9]+\.[0-9]{2})", str(slot.get("price", "")))
    if price_match:
        price = float(price_match.group(1))
        score -= price * 5
        reasons.append(f"price £{price:.2f}")

    weekday = start_dt.strftime("%A")
    if weekday in {"Tuesday", "Wednesday"} and start_dt.time() < time(17, 30) and end_dt.time() > time(9, 0):
        score -= 60
        reasons.append("usual daytime work conflict")

    if weekday in {"Wednesday", "Thursday"} and start_dt.time() >= time(18, 0):
        score -= 20
        reasons.append("likely evening plans")

    conflicting_events: list[str] = []
    for event in events:
        if event.start is None or event.end is None:
            continue
        if event.all_day:
            if event.start.date() <= slot_date <= event.end.date():
                score -= 15
                reasons.append(f"all-day calendar item: {event.title}")
            continue
        if overlaps(start_dt, end_dt, event.start, event.end):
            score -= 200
            conflicting_events.append(
                f"{event.title} ({event.start.strftime('%a %H:%M')}-{event.end.strftime('%H:%M')})"
            )
    if conflicting_events:
        reasons.append("calendar conflict")

    if slot.get("eco"):
        score += 4
        reasons.append("eco slot")

    score -= (start_dt - datetime.now()).total_seconds() / 86400 * 0.5

    enriched = dict(slot)
    enriched.update(
        {
            "slot_start": start_dt.isoformat(),
            "slot_end": end_dt.isoformat(),
            "score": round(score, 2),
            "reasons": reasons,
            "calendar_conflicts": conflicting_events,
        }
    )
    return enriched


def fetch_regular_items(retailer: str, limit: int) -> tuple[str, list[dict[str, Any]]]:
    payload = grocery_json(retailer, "favourites", "--limit", str(limit))
    items = payload.get("items", [])
    if payload.get("supported") is False:
        raise SystemExit(
            payload.get("message")
            or f"Regular-item source is not available for retailer {retailer!r}."
        )
    if not isinstance(items, list):
        raise SystemExit("Unexpected favourites payload.")
    source = payload.get("source")
    if not isinstance(source, str) or not source.strip():
        source = "Ocado favourites" if retailer == "ocado" else "Sainsbury's favourites"
    return source, items[:limit]


def cmd_slot_suggest(args: argparse.Namespace) -> None:
    slots_payload = grocery_json(args.retailer, "slots")
    slots = slots_payload.get("slots", [])
    if not slots:
        raise SystemExit(f"No {args.retailer} slots were parsed.")
    events = [] if args.no_calendar else fetch_calendar_events(args.days, args.calendar)
    scored = [score_slot(slot, events) for slot in slots]
    scored.sort(key=lambda item: (-float(item["score"]), item["slot_start"]))
    payload = {
        "retailer": args.retailer,
        "calendar": args.calendar,
        "days_considered": args.days,
        "slot_page_url": slots_payload.get("page_url"),
        "delivery_address": slots_payload.get("delivery_address"),
        "suggested_slots": scored[: args.limit],
        "calendar_events_considered": [
            {
                "title": event.title,
                "start": event.start.isoformat() if event.start else None,
                "end": event.end.isoformat() if event.end else None,
                "all_day": event.all_day,
            }
            for event in events
        ],
    }
    print(serialise(payload))


def cmd_regular_items(args: argparse.Namespace) -> None:
    source, items = fetch_regular_items(args.retailer, args.limit)
    payload = {
        "retailer": args.retailer,
        "source": source,
        "items": items,
    }
    print(serialise(payload))


def cmd_open_checkout(args: argparse.Namespace) -> None:
    ensure_retailer_open(args.retailer)
    checkout_url = RETAILER_CHECKOUT_URLS[args.retailer]
    if not webbrowser.open(checkout_url):
        raise SystemExit(f"Could not open a browser for {checkout_url}")
    print(f"Opened a browser on {args.retailer} checkout.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Weekly grocery shopping helper")
    subparsers = parser.add_subparsers(dest="command")

    slot_suggest = subparsers.add_parser(
        "slot-suggest", help="Suggest good delivery slots using calendar and retailer availability"
    )
    slot_suggest.add_argument("--days", type=int, default=7, help="Number of days to inspect")
    slot_suggest.add_argument("--limit", type=int, default=5, help="Number of slots to return")
    slot_suggest.add_argument(
        "--calendar", default=DEFAULT_CALENDAR, help="Calendar name to consult"
    )
    slot_suggest.add_argument(
        "--no-calendar",
        action="store_true",
        help="Skip calendar lookup and score slots only by retailer availability and price",
    )
    slot_suggest.add_argument(
        "--retailer",
        choices=sorted(SUPPORTED_RETAILERS),
        default="ocado",
        help="Retailer to inspect; defaults to Ocado",
    )
    slot_suggest.set_defaults(func=cmd_slot_suggest)

    regular_items = subparsers.add_parser(
        "regular-items", help="Suggest regular weekly-shop items from retailer favourites"
    )
    regular_items.add_argument("--limit", type=int, default=12, help="Max items to return")
    regular_items.add_argument(
        "--retailer",
        choices=sorted(SUPPORTED_RETAILERS),
        default="ocado",
        help="Retailer to inspect; defaults to Ocado",
    )
    regular_items.set_defaults(func=cmd_regular_items)

    open_checkout = subparsers.add_parser(
        "open-checkout", help="Open the retailer checkout flow in your default browser"
    )
    open_checkout.add_argument(
        "--retailer",
        choices=sorted(SUPPORTED_RETAILERS),
        default="ocado",
        help="Retailer to open; defaults to Ocado",
    )
    open_checkout.set_defaults(func=cmd_open_checkout)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        return
    args.func(args)


if __name__ == "__main__":
    main()
