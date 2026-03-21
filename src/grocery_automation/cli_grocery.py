#!/usr/bin/env python3
"""Public CLI for grocery planning and Playwright-assisted retailer automation."""

from __future__ import annotations

import argparse
import csv
import fcntl
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
from hashlib import sha1
from pathlib import Path
from typing import Any, Optional

from grocery_automation.config import default_data_dir, default_output_dir, default_state_path, resolve_pwcli

DEFAULT_STATE = default_state_path()
DEFAULT_DATA_DIR = default_data_dir()
DEFAULT_OUTPUT_DIR = default_output_dir()
SUPPORTED_RETAILERS = {"ocado", "sainsburys"}
RETAILER_URLS = {
    "ocado": "https://www.ocado.com/",
    "sainsburys": "https://www.sainsburys.co.uk/shop/groceries",
}
RETAILER_SESSIONS = {
    "ocado": "grocery-ocado",
    "sainsburys": "grocery-sainsburys",
}
RETAILER_PAGE_URLS = {
    "ocado": {
        "home": "https://www.ocado.com/",
        "orders": "https://www.ocado.com/orders",
        "checkout": "https://www.ocado.com/checkout",
        "favourites": "https://www.ocado.com/favorites",
    },
    "sainsburys": {
        "home": "https://www.sainsburys.co.uk/shop/groceries",
        "home_new": "https://www.sainsburys.co.uk/groceries",
        "orders": "https://www.sainsburys.co.uk/shop/gb/groceries/my-orders",
        "checkout": "https://www.sainsburys.co.uk/gol-ui/slot/book?slot_type=saver_slot",
        "favourites": "https://www.sainsburys.co.uk/webapp/wcs/stores/servlet/gb/groceries/favourites",
    },
}
OCADO_SESSION = RETAILER_SESSIONS["ocado"]
SAINSBURYS_SESSION = RETAILER_SESSIONS["sainsburys"]


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(
            f"Missing grocery state at {path}. Run `grocery-shopping init` first."
        )
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"Grocery state at {path} is invalid JSON. Run `grocery-shopping init` "
            "again or restore a valid state file."
        ) from exc


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state, indent=2, sort_keys=True) + "\n"
    temp_path = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temp_path.write_text(payload)
    temp_path.replace(path)


def ensure_state_shape(state: dict[str, Any]) -> dict[str, Any]:
    state.setdefault("staples", [])
    state.setdefault("preferences", {})
    state.setdefault("plans", {})
    state.setdefault("retailers", {})
    return state


def normalise_name(value: str) -> str:
    return " ".join(value.strip().split())


def retailer_state(state: dict[str, Any], retailer: str) -> dict[str, Any]:
    retailers = state.setdefault("retailers", {})
    entry = retailers.setdefault(retailer, {})
    entry.setdefault("storage_state", str(DEFAULT_OUTPUT_DIR / retailer / "storage-state.json"))
    entry.setdefault("notes", [])
    return entry


def serialise(data: Any) -> str:
    return json.dumps(data, indent=2, sort_keys=True)


def print_completed_process(result: subprocess.CompletedProcess[str]) -> None:
    if result.stdout:
        sys.stdout.write(result.stdout)
        if not result.stdout.endswith("\n"):
            sys.stdout.write("\n")
    if result.stderr:
        sys.stderr.write(result.stderr)
        if not result.stderr.endswith("\n"):
            sys.stderr.write("\n")


class RetailerSessionLock:
    def __init__(self, retailer: str):
        self.path = DEFAULT_OUTPUT_DIR / retailer / "session.lock"
        self.handle: Optional[Any] = None

    def __enter__(self) -> "RetailerSessionLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("w")
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)
        self.handle.write(str(os.getpid()))
        self.handle.flush()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.handle is None:
            return
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        self.handle.close()
        self.handle = None


def cmd_init(args: argparse.Namespace) -> None:
    path = Path(args.state)
    state = ensure_state_shape(
        {
            "staples": [],
            "preferences": {},
            "plans": {},
            "retailers": {},
        }
    )
    save_state(path, state)
    Path(args.data_dir).mkdir(parents=True, exist_ok=True)
    DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Initialised grocery shopping state at {path}")


def cmd_staple_add(args: argparse.Namespace) -> None:
    path = Path(args.state)
    state = ensure_state_shape(load_state(path))
    name = normalise_name(args.name)

    for item in state["staples"]:
        if item["name"].casefold() == name.casefold():
            item["quantity"] = args.quantity
            if args.unit:
                item["unit"] = args.unit
            if args.notes is not None:
                item["notes"] = args.notes
            save_state(path, state)
            print(f"Updated staple {name}")
            return

    payload = {"name": name, "quantity": args.quantity}
    if args.unit:
        payload["unit"] = args.unit
    if args.notes:
        payload["notes"] = args.notes
    state["staples"].append(payload)
    save_state(path, state)
    print(f"Added staple {name}")


def cmd_staple_list(args: argparse.Namespace) -> None:
    state = ensure_state_shape(load_state(Path(args.state)))
    print(serialise(state["staples"]))


def cmd_preference_set(args: argparse.Namespace) -> None:
    path = Path(args.state)
    state = ensure_state_shape(load_state(path))
    key = normalise_name(args.name)
    state["preferences"][key] = {
        "status": args.status,
        "notes": args.notes,
    }
    save_state(path, state)
    print(f"Saved preference for {key}")


def cmd_preference_list(args: argparse.Namespace) -> None:
    state = ensure_state_shape(load_state(Path(args.state)))
    print(serialise(state["preferences"]))


def cmd_plan_new(args: argparse.Namespace) -> None:
    path = Path(args.state)
    state = ensure_state_shape(load_state(path))
    if args.name in state["plans"]:
        raise SystemExit(f"Plan {args.name!r} already exists.")
    state["plans"][args.name] = {"items": []}
    save_state(path, state)
    print(f"Created plan {args.name}")


def cmd_plan_add(args: argparse.Namespace) -> None:
    path = Path(args.state)
    state = ensure_state_shape(load_state(path))
    plan = state["plans"].get(args.plan)
    if plan is None:
        raise SystemExit(f"Unknown plan {args.plan!r}. Run `plan new` first.")

    item = {
        "name": normalise_name(args.name),
        "quantity": args.quantity,
        "reason": args.reason,
    }
    if args.unit:
        item["unit"] = args.unit
    if args.notes:
        item["notes"] = args.notes
    plan["items"].append(item)
    save_state(path, state)
    print(f"Added {item['name']} to plan {args.plan}")


def cmd_plan_show(args: argparse.Namespace) -> None:
    state = ensure_state_shape(load_state(Path(args.state)))
    plan = state["plans"].get(args.plan)
    if plan is None:
        raise SystemExit(f"Unknown plan {args.plan!r}.")
    print(serialise(plan))


def cmd_import_ocado_favourites(args: argparse.Namespace) -> None:
    path = Path(args.state)
    state = ensure_state_shape(load_state(path))
    csv_path = Path(args.csv_path)
    if not csv_path.exists():
        raise SystemExit(f"Missing CSV at {csv_path}")

    imported = 0
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            values = [value.strip() for value in row.values() if value and value.strip()]
            if not values:
                continue
            name = values[0]
            if any(item["name"].casefold() == name.casefold() for item in state["staples"]):
                continue
            state["staples"].append(
                {
                    "name": name,
                    "quantity": 1,
                    "notes": "Imported from Ocado favourites CSV",
                }
            )
            imported += 1

    save_state(path, state)
    print(f"Imported {imported} favourites from {csv_path}")


def build_pwcli_command(args: argparse.Namespace) -> list[str]:
    return resolve_pwcli()


def build_session_pwcli_command(args: argparse.Namespace, session: str) -> list[str]:
    return build_pwcli_command(args) + ["--session", session]


def retailer_url(retailer: str) -> str:
    if retailer not in SUPPORTED_RETAILERS:
        raise SystemExit(
            f"Unsupported retailer {retailer!r}. Choose one of: {', '.join(sorted(SUPPORTED_RETAILERS))}."
        )
    return RETAILER_URLS[retailer]


def retailer_session(retailer: str) -> str:
    try:
        return RETAILER_SESSIONS[retailer]
    except KeyError as exc:
        raise SystemExit(f"No browser session configured for retailer {retailer!r}.") from exc


def retailer_page_url(retailer: str, page: str) -> str:
    pages = RETAILER_PAGE_URLS.get(retailer, {})
    try:
        return pages[page]
    except KeyError as exc:
        raise SystemExit(f"No {page!r} page configured for retailer {retailer!r}.") from exc


def storage_state_path(state: dict[str, Any], retailer: str) -> Path:
    entry = retailer_state(state, retailer)
    return Path(entry["storage_state"])


def run_playwright(
    command: list[str],
    *,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, capture_output=capture_output, text=True)


def run_playwright_or_exit(
    command: list[str], *, capture_output: bool = False, echo: bool = True
) -> str:
    result = run_playwright(command, capture_output=capture_output)
    if capture_output and echo:
        print_completed_process(result)
    if result.returncode != 0:
        if capture_output and not echo:
            print_completed_process(result)
        raise SystemExit(result.returncode)
    return result.stdout if capture_output else ""


def playwright_session_is_open(args: argparse.Namespace, session: str) -> bool:
    output = run_playwright_or_exit(
        build_pwcli_command(args) + ["list"],
        capture_output=True,
        echo=False,
    )
    return f"- {session}:" in output and "status: open" in output


def latest_snapshot_path_from_output(output: str) -> Path:
    matches = re.findall(r"\[Snapshot\]\(([^)]+)\)", output)
    if not matches:
        raise SystemExit("Playwright did not report a snapshot path.")
    path = Path(matches[-1]).expanduser()
    if path.is_absolute():
        return path
    return Path.cwd() / path


def page_metadata_from_output(output: str) -> dict[str, str]:
    metadata: dict[str, str] = {}
    url_matches = re.findall(r"- Page URL: (.+)", output)
    title_matches = re.findall(r"- Page Title: (.+)", output)
    if url_matches:
        metadata["url"] = url_matches[-1]
    if title_matches:
        metadata["title"] = title_matches[-1]
    return metadata


def result_json_from_output(output: str) -> Optional[dict[str, Any]]:
    match = re.search(r"### Result\s*(\{.*?\})\s*### Ran Playwright code", output, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict):
        return data
    return None


def parse_result_payload(output: str) -> Any:
    match = re.search(r"### Result\s*(.+?)\s*(?:### Ran Playwright code|### Page|$)", output, re.DOTALL)
    if not match:
        return None
    payload = match.group(1).strip()
    if not payload:
        return None
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None


def ensure_retailer_state(args: argparse.Namespace, retailer: str) -> dict[str, Any]:
    path = Path(args.state)
    state = ensure_state_shape(load_state(path))
    retailer_state(state, retailer)
    save_state(path, state)
    return state


def ensure_retailer_open(
    args: argparse.Namespace,
    retailer: str,
    *,
    headed: bool = False,
) -> None:
    ensure_retailer_state(args, retailer)
    session = retailer_session(retailer)
    if playwright_session_is_open(args, session):
        return
    command = build_session_pwcli_command(args, session) + ["open", retailer_url(retailer)]
    if headed:
        command.append("--headed")
    result = run_playwright(command, capture_output=True)
    if result.returncode == 0:
        if headed:
            print_completed_process(result)
        return
    combined = f"{result.stdout}\n{result.stderr}"
    if "EADDRINUSE" in combined:
        goto = build_session_pwcli_command(args, session) + ["goto", retailer_url(retailer)]
        run_playwright_or_exit(goto, capture_output=True, echo=False)
        return
    print_completed_process(result)
    raise SystemExit(result.returncode)


def load_retailer_storage_state_if_present(
    args: argparse.Namespace,
    retailer: str,
    *,
    refresh_page: bool = True,
) -> bool:
    state = ensure_retailer_state(args, retailer)
    storage_state = storage_state_path(state, retailer)
    if not storage_state.exists():
        return False
    session = retailer_session(retailer)
    command = build_session_pwcli_command(args, session) + ["state-load", str(storage_state)]
    run_playwright_or_exit(command, capture_output=True, echo=False)
    if refresh_page:
        run_playwright_or_exit(
            build_session_pwcli_command(args, session) + ["goto", retailer_url(retailer)],
            capture_output=True,
            echo=False,
        )
    return True


def save_retailer_storage_state(args: argparse.Namespace, retailer: str) -> Path:
    state = ensure_retailer_state(args, retailer)
    output = storage_state_path(state, retailer)
    output.parent.mkdir(parents=True, exist_ok=True)
    session = retailer_session(retailer)
    command = build_session_pwcli_command(args, session) + ["state-save", str(output)]
    run_playwright_or_exit(command, capture_output=True, echo=True)
    return output


def ensure_ocado_state(args: argparse.Namespace) -> dict[str, Any]:
    return ensure_retailer_state(args, "ocado")


def ensure_ocado_open(args: argparse.Namespace, *, headed: bool = False) -> None:
    ensure_retailer_open(args, "ocado", headed=headed)


def load_ocado_storage_state_if_present(args: argparse.Namespace, *, refresh_page: bool = True) -> bool:
    return load_retailer_storage_state_if_present(args, "ocado", refresh_page=refresh_page)


def save_ocado_storage_state(args: argparse.Namespace) -> Path:
    return save_retailer_storage_state(args, "ocado")


def snapshot_path_for_session(args: argparse.Namespace, session: str) -> Path:
    output = run_playwright_or_exit(
        build_session_pwcli_command(args, session) + ["snapshot"],
        capture_output=True,
        echo=False,
    )
    return latest_snapshot_path_from_output(output)


def goto_and_snapshot(
    args: argparse.Namespace,
    session: str,
    url: str,
) -> tuple[Path, dict[str, str]]:
    result = run_playwright(
        build_session_pwcli_command(args, session) + ["goto", url],
        capture_output=True,
    )
    if result.returncode != 0:
        print_completed_process(result)
    output = result.stdout
    metadata = page_metadata_from_output(output)
    if "[Snapshot](" in output:
        return latest_snapshot_path_from_output(output), metadata
    snapshot = snapshot_path_for_session(args, session)
    metadata.update(current_page_metadata(args, session))
    return snapshot, metadata


def current_page_metadata(args: argparse.Namespace, session: str) -> dict[str, str]:
    output = run_playwright_or_exit(
        build_session_pwcli_command(args, session)
        + ["eval", "() => ({href: location.href, title: document.title})"],
        capture_output=True,
        echo=False,
    )
    data = parse_result_payload(output) or {}
    metadata: dict[str, str] = {}
    href = data.get("href")
    title = data.get("title")
    if isinstance(href, str):
        metadata["url"] = href
    if isinstance(title, str):
        metadata["title"] = title
    return metadata


def eval_json(args: argparse.Namespace, session: str, expression: str) -> Any:
    output = run_playwright_or_exit(
        build_session_pwcli_command(args, session) + ["eval", expression],
        capture_output=True,
        echo=False,
    )
    data = parse_result_payload(output)
    if data is None:
        raise SystemExit("Playwright eval did not return JSON.")
    return data


def parse_snapshot_text(path: Path) -> str:
    if not path.exists():
        raise SystemExit(f"Snapshot file not found: {path}")
    return path.read_text()


def capture_snapshot_text(args: argparse.Namespace, session: str) -> str:
    snapshot = snapshot_path_for_session(args, session)
    return parse_snapshot_text(snapshot)


def first_ref_matching(text: str, pattern: str) -> Optional[str]:
    match = re.search(pattern, text)
    return match.group(1) if match else None


def button_ref_from_snapshot(text: str, *, label: str) -> Optional[str]:
    pattern = rf'button "{re.escape(label)}"(?: \[[^\]]+\])* \[ref=(e\d+)\]'
    return first_ref_matching(text, pattern)


def first_sainsburys_reserve_ref_from_snapshot(text: str) -> Optional[str]:
    return first_ref_matching(
        text,
        r'button "Reserve slot(?: on [^"]+)?"(?: \[[^\]]+\])* \[ref=(e\d+)\]',
    )


def accept_ocado_cookies_if_present(args: argparse.Namespace) -> None:
    snapshot = snapshot_path_for_session(args, OCADO_SESSION)
    text = parse_snapshot_text(snapshot)
    accept_ref = first_ref_matching(
        text,
        r'button "Accept" \[ref=(e\d+)\]',
    )
    if accept_ref is None or "Cookie banner" not in text:
        return
    run_playwright_or_exit(
        build_session_pwcli_command(args, OCADO_SESSION) + ["click", accept_ref],
        capture_output=True,
        echo=False,
    )


def search_ref_from_snapshot(text: str, *, label: str) -> Optional[str]:
    pattern = rf'searchbox "{re.escape(label)}" \[ref=(e\d+)\]'
    return first_ref_matching(text, pattern)


def button_ref_from_snapshot(text: str, *, label: str) -> Optional[str]:
    pattern = rf'button "{re.escape(label)}" \[ref=(e\d+)\]'
    return first_ref_matching(text, pattern)


def search_controls_from_snapshot(text: str) -> tuple[str, str]:
    search_ref = first_ref_matching(text, r"combobox(?: [^\n]*)? \[ref=(e\d+)\]")
    button_ref = first_ref_matching(text, r'button "Find a product" \[ref=(e\d+)\]')
    if search_ref is None or button_ref is None:
        raise SystemExit("Could not find Ocado search controls in the current snapshot.")
    return search_ref, button_ref


def parse_ocado_search_results(text: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    lines = text.splitlines()
    for index, line in enumerate(lines):
        button_match = re.search(r'button "Add (.+?) to trolley" \[ref=(e\d+)\]', line)
        if not button_match:
            continue
        name = button_match.group(1)
        add_ref = button_match.group(2)
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)

        url = None
        price = None
        for reverse_index in range(index - 1, max(index - 40, -1), -1):
            if url is None:
                url_match = re.search(r"- /url: (.+)", lines[reverse_index].strip())
                if url_match and "/products/" in url_match.group(1):
                    url = url_match.group(1)
            if price is None:
                price_match = re.search(r"generic \[ref=e\d+\]: (£[0-9]+\.[0-9]{2})", lines[reverse_index])
                if price_match:
                    price = price_match.group(1)
            if url is not None and price is not None:
                break

        results.append(
            {
                "name": name,
                "add_ref": add_ref,
                "price": price,
                "url": f"https://www.ocado.com{url}" if url and url.startswith("/") else url,
            }
        )
    return results


def parse_ocado_trolley_summary(text: str) -> dict[str, Any]:
    match = re.search(
        r"Total number of items in your trolley: (\d+)\. Trolley amount: (£[0-9]+\.[0-9]{2})",
        text,
    )
    if not match:
        return {}
    return {
        "item_count": int(match.group(1)),
        "amount": match.group(2),
    }


def parse_ocado_session_status(text: str, metadata: dict[str, str]) -> dict[str, Any]:
    status: dict[str, Any] = {
        "logged_in": 'button "My Ocado"' in text and 'heading "Welcome,' in text,
        "page_url": metadata.get("url"),
        "page_title": metadata.get("title"),
        "basket": parse_ocado_trolley_summary(text),
    }
    welcome = re.search(r'heading "Welcome, ([^"]+)" \[level=1\]', text)
    if welcome:
        status["customer_name"] = welcome.group(1)

    next_slot = re.search(
        r'text: "Next available slot:"\s*\n\s*- generic \[ref=e\d+\]: ([^\n]+)',
        text,
    )
    if next_slot:
        status["next_available_slot"] = next_slot.group(1).strip()

    active_order = re.search(
        r'link "([^"]*View order[^"]*)" \[ref=e\d+\] \[cursor=pointer\]:\s*\n'
        r'\s*- /url: (/orders/(\d+)/details[^\n]*)'
        r'.*?\n\s*- heading "([^"]+)" \[level=2\] \[ref=e\d+\]:'
        r'.*?\n\s*- generic \[ref=e\d+\]: ([^\n]+)\s*'
        r'\n\s*- generic \[ref=e\d+\]: ([^\n]+)',
        text,
        re.DOTALL,
    )
    if active_order:
        status["active_order"] = {
            "label": active_order.group(1),
            "url": f"https://www.ocado.com{active_order.group(2)}",
            "order_id": active_order.group(3),
            "headline": active_order.group(4).strip(),
            "window": active_order.group(5).strip(),
            "status": active_order.group(6).strip(),
        }
    return status


def parse_ocado_orders(text: str, metadata: dict[str, str]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "page_url": metadata.get("url"),
        "page_title": metadata.get("title"),
        "upcoming_orders": [],
        "previous_orders": [],
    }
    order_matches = re.finditer(
        r'link "([^"]+)" \[ref=e\d+\] \[cursor=pointer\]:\s*\n\s*- /url: (/orders/(\d+)/details[^\n]*)'
        r'.*?\n\s*- heading "([^"]+)" \[level=3\] \[ref=e\d+\]: ([^\n]+)'
        r'\s*\n\s*- generic \[ref=e\d+\]: ([^\n]+)'
        r'\s*\n\s*- generic \[ref=e\d+\]: ([^\n]+)',
        text,
        re.DOTALL,
    )
    for match in order_matches:
        order = {
            "label": match.group(1),
            "url": f"https://www.ocado.com{match.group(2)}",
            "order_id": match.group(3),
            "window_heading": match.group(4),
            "window": match.group(5).strip(),
            "summary": match.group(6).strip(),
            "status": match.group(7).strip(),
        }
        result["upcoming_orders"].append(order)

    if 'heading "You have no more orders to display."' in text:
        result["previous_orders_empty"] = True
    return result


def parse_ocado_checkout_state(text: str, metadata: dict[str, str]) -> dict[str, Any]:
    state: dict[str, Any] = {
        "page_url": metadata.get("url"),
        "page_title": metadata.get("title"),
        "basket": parse_ocado_trolley_summary(text),
    }
    heading = re.search(r'heading "([^"]+)" \[level=1\] \[ref=e\d+\]', text)
    if heading:
        state["heading"] = heading.group(1)
    address = re.search(
        r'button "Home Delivery selected\. Address ([^"]+) selected\. Change delivery method and address"',
        text,
    )
    if address:
        state["delivery_address"] = address.group(1).strip()
    return state


def normalise_slot_token(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return cleaned or "slot"


def slot_id_for(slot: dict[str, Any]) -> str:
    base = "|".join(
        [
            str(slot.get("date_label", "")),
            str(slot.get("window", "")),
            str(slot.get("price", "")),
            "eco" if slot.get("eco") else "standard",
        ]
    )
    digest = sha1(base.encode("utf-8")).hexdigest()[:10]
    return (
        f"{normalise_slot_token(str(slot.get('date_label', '')))}__"
        f"{normalise_slot_token(str(slot.get('window', '')))}__"
        f"{normalise_slot_token(str(slot.get('price', '')))}__{digest}"
    )


def extract_ocado_slots(args: argparse.Namespace) -> dict[str, Any]:
    slot_data = eval_json(
        args,
        OCADO_SESSION,
        """async () => {
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  for (let i = 0; i < 20; i += 1) {
    if (document.querySelectorAll('button[data-test="selectable-slot"]').length > 0) {
      break;
    }
    await sleep(250);
  }
  const center = (rect, axis) => axis === 'x' ? rect.left + rect.width / 2 : rect.top + rect.height / 2;
  const textOf = (el) => (el.textContent || '').replace(/\\s+/g, ' ').trim();
  const datePattern = /^(Fri|Sat|Sun|Mon|Tue|Wed|Thu) \\d{1,2}$/;
  const timePattern = /^\\d{1,2}:\\d{2}-\\d{1,2}:\\d{2}(am|pm)$/;
  const periodPattern = /^(Morning|Afternoon|Evening)$/;

  const visible = (el) => {
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  };

  const dateHeaders = Array.from(document.querySelectorAll('th')).map((el) => ({
    text: textOf(el),
    rect: el.getBoundingClientRect(),
  })).filter((x) => datePattern.test(x.text) && visible({getBoundingClientRect: () => x.rect}));

  const timeHeaders = Array.from(document.querySelectorAll('th')).map((el) => ({
    text: textOf(el),
    rect: el.getBoundingClientRect(),
  })).filter((x) => timePattern.test(x.text) && visible({getBoundingClientRect: () => x.rect}));

  const periodHeaders = Array.from(document.querySelectorAll('th')).map((el) => ({
    text: textOf(el),
    rect: el.getBoundingClientRect(),
  })).filter((x) => periodPattern.test(x.text) && visible({getBoundingClientRect: () => x.rect}));

  const closestDate = (x) => {
    let best = null;
    let bestDistance = Infinity;
    for (const date of dateHeaders) {
      const distance = Math.abs(center(date.rect, 'x') - x);
      if (distance < bestDistance) {
        bestDistance = distance;
        best = date;
      }
    }
    return best ? best.text : null;
  };

  const closestTime = (y) => {
    let best = null;
    let bestDistance = Infinity;
    for (const time of timeHeaders) {
      const distance = Math.abs(center(time.rect, 'y') - y);
      if (distance < bestDistance) {
        bestDistance = distance;
        best = time;
      }
    }
    return best ? best.text : null;
  };

  const activePeriod = (y) => {
    let best = null;
    for (const period of periodHeaders) {
      if (period.rect.top <= y) {
        best = period.text;
      }
    }
    return best;
  };

  const buttons = Array.from(document.querySelectorAll('button[data-test="selectable-slot"]'))
    .filter(visible)
    .map((button, buttonIndex) => {
      const rect = button.getBoundingClientRect();
      const cx = center(rect, 'x');
      const cy = center(rect, 'y');
      const price = textOf(button);
      const aria = button.getAttribute('aria-label') || '';
      return {
        button_index: buttonIndex,
        date_label: closestDate(cx),
        window: closestTime(cy),
        period: activePeriod(cy),
        price,
        eco: button.className.includes('eco') || aria.toLowerCase().includes('eco slot'),
        selected: button.className.toLowerCase().includes('selected') || button.getAttribute('aria-pressed') === 'true',
        availability: button.disabled ? 'unavailable' : 'available',
      };
    });

  const addressButton = document.querySelector('button[aria-label*="Change delivery method and address"]');
  const heading = document.querySelector('h1');
  return {
    heading: heading ? textOf(heading) : null,
    delivery_address: addressButton ? textOf(addressButton).replace(/^Home Delivery selected\\. Address\\s*/i, '').replace(/\\s*selected\\. Change delivery method and address$/i, '') : null,
    slots: buttons,
  };
}""",
    )
    slots = slot_data.get("slots", [])
    for slot in slots:
        slot["slot_id"] = slot_id_for(slot)
    return slot_data


def click_ocado_slot(args: argparse.Namespace, button_index: int) -> dict[str, Any]:
    result = eval_json(
        args,
        OCADO_SESSION,
        f"""async () => {{
  const buttons = Array.from(document.querySelectorAll('button[data-test="selectable-slot"]')).filter((el) => {{
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }});
  const button = buttons[{button_index}];
  if (!button) {{
    return {{clicked: false, reason: 'slot button not found'}};
  }}
  button.click();
  await new Promise((resolve) => setTimeout(resolve, 1500));
  return {{clicked: true, href: location.href, title: document.title}};
}}""",
    )
    if not isinstance(result, dict):
        raise SystemExit("Unexpected result from slot click.")
    return result


def extract_ocado_favourites(args: argparse.Namespace) -> list[dict[str, Any]]:
    ensure_ocado_open(args)
    load_ocado_storage_state_if_present(args)
    accept_ocado_cookies_if_present(args)
    goto_and_snapshot(args, OCADO_SESSION, "https://www.ocado.com/favorites")
    data = eval_json(
        args,
        OCADO_SESSION,
        """async () => {
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  for (let i = 0; i < 20; i += 1) {
    const buttons = Array.from(document.querySelectorAll('button[aria-label^="Add "]'))
      .filter((button) => (button.getAttribute('aria-label') || '').includes(' to trolley'));
    if (buttons.length > 0) {
      break;
    }
    await sleep(250);
  }
  const textOf = (node) => (node?.textContent || '').replace(/\\s+/g, ' ').trim();
  const products = Array.from(document.querySelectorAll('button[aria-label^="Add "]'))
    .filter((button) => (button.getAttribute('aria-label') || '').includes(' to trolley'))
    .map((button, index) => {
      const aria = button.getAttribute('aria-label') || '';
      const nameMatch = aria.match(/^Add (.+) to trolley$/);
      const name = nameMatch ? nameMatch[1] : textOf(button);
      let node = button.parentElement;
      let lastBought = null;
      while (node && !lastBought) {
        const match = textOf(node).match(/Bought \\d{2}\\/\\d{2}\\/\\d{4}/);
        if (match) {
          lastBought = match[0];
        }
        node = node.parentElement;
      }
      return {
        rank: index + 1,
        name,
        last_bought: lastBought,
      };
    });
  return products;
}""",
    )
    if not isinstance(data, list):
        raise SystemExit("Unexpected favourites payload.")
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in data:
        name = str(item.get("name", "")).strip()
        key = name.casefold()
        if not name or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def ocado_search(args: argparse.Namespace, query: str, *, headed: bool = False) -> list[dict[str, Any]]:
    ensure_ocado_open(args, headed=headed)
    load_ocado_storage_state_if_present(args)
    accept_ocado_cookies_if_present(args)
    snapshot = snapshot_path_for_session(args, OCADO_SESSION)
    text = parse_snapshot_text(snapshot)
    search_ref, button_ref = search_controls_from_snapshot(text)
    run_playwright_or_exit(
        build_session_pwcli_command(args, OCADO_SESSION) + ["fill", search_ref, query],
        capture_output=True,
        echo=False,
    )
    output = run_playwright_or_exit(
        build_session_pwcli_command(args, OCADO_SESSION) + ["click", button_ref],
        capture_output=True,
        echo=False,
    )
    search_snapshot = latest_snapshot_path_from_output(output)
    results = parse_ocado_search_results(parse_snapshot_text(search_snapshot))
    if not results:
        raise SystemExit(f"No Ocado add-to-trolley results found for query {query!r}.")
    return results


def load_ocado_home_snapshot(args: argparse.Namespace, *, headed: bool = False) -> tuple[Path, dict[str, str]]:
    ensure_ocado_open(args, headed=headed)
    load_ocado_storage_state_if_present(args)
    accept_ocado_cookies_if_present(args)
    return goto_and_snapshot(args, OCADO_SESSION, retailer_url("ocado"))


def ensure_ocado_checkout_page(args: argparse.Namespace, *, headed: bool = False) -> tuple[Path, dict[str, str]]:
    ensure_ocado_open(args, headed=headed)
    load_ocado_storage_state_if_present(args)
    accept_ocado_cookies_if_present(args)
    return goto_and_snapshot(args, OCADO_SESSION, "https://www.ocado.com/checkout")


def select_ocado_result(results: list[dict[str, Any]], product_name: Optional[str]) -> dict[str, Any]:
    if not product_name:
        return results[0]
    target = product_name.casefold()
    exact_matches = [result for result in results if result["name"].casefold() == target]
    if exact_matches:
        return exact_matches[0]
    partial_matches = [result for result in results if target in result["name"].casefold()]
    if partial_matches:
        return partial_matches[0]
    raise SystemExit(
        f"No Ocado search result matched {product_name!r}. Top results: "
        + ", ".join(result["name"] for result in results[:5])
    )


def cmd_playwright_open(args: argparse.Namespace) -> None:
    state = ensure_state_shape(load_state(Path(args.state)))
    retailer_state(state, args.retailer)
    save_state(Path(args.state), state)
    command = build_pwcli_command(args) + ["open", retailer_url(args.retailer)]
    if args.headed:
        command.append("--headed")
    run_playwright_or_exit(command)


def cmd_playwright_snapshot(args: argparse.Namespace) -> None:
    command = build_pwcli_command(args) + ["snapshot"]
    run_playwright_or_exit(command)


def cmd_playwright_save_state(args: argparse.Namespace) -> None:
    path = Path(args.state)
    state = ensure_state_shape(load_state(path))
    output = storage_state_path(state, args.retailer)
    output.parent.mkdir(parents=True, exist_ok=True)
    save_state(path, state)
    command = build_pwcli_command(args) + ["state-save", str(output)]
    run_playwright_or_exit(command)


def cmd_playwright_load_state(args: argparse.Namespace) -> None:
    state = ensure_state_shape(load_state(Path(args.state)))
    output = storage_state_path(state, args.retailer)
    if not output.exists():
        raise SystemExit(
            f"No saved storage state for {args.retailer} at {output}. Run `playwright save-state` first."
        )
    command = build_pwcli_command(args) + ["state-load", str(output)]
    run_playwright_or_exit(command)


def cmd_playwright_goto(args: argparse.Namespace) -> None:
    command = build_pwcli_command(args) + ["goto", args.url]
    run_playwright_or_exit(command)


def cmd_playwright_passthrough(args: argparse.Namespace) -> None:
    command = build_pwcli_command(args) + args.playwright_args
    run_playwright_or_exit(command)


def cmd_ocado_open(args: argparse.Namespace) -> None:
    ensure_ocado_open(args, headed=args.headed)
    load_ocado_storage_state_if_present(args)
    accept_ocado_cookies_if_present(args)


def cmd_ocado_login(args: argparse.Namespace) -> None:
    ensure_ocado_open(args, headed=True)
    had_saved_state = load_ocado_storage_state_if_present(args)
    accept_ocado_cookies_if_present(args)
    snapshot = snapshot_path_for_session(args, OCADO_SESSION)
    text = parse_snapshot_text(snapshot)
    login_ref = first_ref_matching(text, r'button "Log in" \[ref=(e\d+)\]')
    if login_ref:
        run_playwright_or_exit(
            build_session_pwcli_command(args, OCADO_SESSION) + ["click", login_ref],
            capture_output=True,
            echo=True,
        )
    if had_saved_state:
        print("Loaded the existing Ocado session first.")
    print("Complete the Ocado login in the headed browser, then press Enter here to save the session.")
    try:
        input()
    except EOFError:
        raise SystemExit(
            "Login flow needs an interactive terminal. Run this command directly in your shell."
        ) from None
    output = save_ocado_storage_state(args)
    print(f"Saved Ocado storage state to {output}")


def cmd_ocado_search(args: argparse.Namespace) -> None:
    results = ocado_search(args, args.query, headed=args.headed)
    print(serialise(results[: args.limit]))


def cmd_ocado_session_status(args: argparse.Namespace) -> None:
    snapshot, metadata = load_ocado_home_snapshot(args, headed=args.headed)
    print(serialise(parse_ocado_session_status(parse_snapshot_text(snapshot), metadata)))


def cmd_ocado_orders(args: argparse.Namespace) -> None:
    ensure_ocado_open(args, headed=args.headed)
    load_ocado_storage_state_if_present(args)
    accept_ocado_cookies_if_present(args)
    snapshot, metadata = goto_and_snapshot(args, OCADO_SESSION, "https://www.ocado.com/orders")
    print(serialise(parse_ocado_orders(parse_snapshot_text(snapshot), metadata)))


def cmd_ocado_checkout_state(args: argparse.Namespace) -> None:
    snapshot, metadata = ensure_ocado_checkout_page(args, headed=args.headed)
    print(serialise(parse_ocado_checkout_state(parse_snapshot_text(snapshot), metadata)))


def cmd_ocado_slots(args: argparse.Namespace) -> None:
    snapshot, metadata = ensure_ocado_checkout_page(args, headed=args.headed)
    checkout_state = parse_ocado_checkout_state(parse_snapshot_text(snapshot), metadata)
    slot_data = extract_ocado_slots(args)
    payload = {
        "page_url": metadata.get("url"),
        "page_title": metadata.get("title"),
        "heading": slot_data.get("heading") or checkout_state.get("heading"),
        "delivery_address": slot_data.get("delivery_address") or checkout_state.get("delivery_address"),
        "basket": checkout_state.get("basket", {}),
        "slots": slot_data.get("slots", []),
    }
    print(serialise(payload))


def cmd_ocado_favourites(args: argparse.Namespace) -> None:
    favourites = extract_ocado_favourites(args)
    print(serialise({"items": favourites[: args.limit]}))


def cmd_ocado_slot_book(args: argparse.Namespace) -> None:
    if not args.confirm:
        raise SystemExit("Refusing to book a slot without --confirm.")
    snapshot, metadata = ensure_ocado_checkout_page(args, headed=args.headed)
    _ = parse_ocado_checkout_state(parse_snapshot_text(snapshot), metadata)
    slot_data = extract_ocado_slots(args)
    slots = slot_data.get("slots", [])
    chosen = next((slot for slot in slots if slot["slot_id"] == args.slot_id), None)
    if chosen is None:
        raise SystemExit(
            f"Unknown slot id {args.slot_id!r}. Run `grocery-shopping ocado slots` first."
        )
    click_result = click_ocado_slot(args, int(chosen["button_index"]))
    if not click_result.get("clicked"):
        raise SystemExit(f"Ocado slot click failed: {click_result.get('reason', 'unknown error')}")
    post_snapshot = snapshot_path_for_session(args, OCADO_SESSION)
    post_metadata = current_page_metadata(args, OCADO_SESSION)
    post_slot_data = extract_ocado_slots(args)
    selected_slot = next(
        (slot for slot in post_slot_data.get("slots", []) if slot.get("selected")),
        None,
    )
    payload = {
        "attempted": True,
        "requested_slot_id": args.slot_id,
        "page_url": post_metadata.get("url"),
        "page_title": post_metadata.get("title"),
        "selected_slot": selected_slot,
        "checkout_state": parse_ocado_checkout_state(parse_snapshot_text(post_snapshot), post_metadata),
    }
    print(serialise(payload))


def cmd_ocado_add_to_basket(args: argparse.Namespace) -> None:
    results = ocado_search(args, args.query, headed=args.headed)
    chosen = select_ocado_result(results, args.product)
    for _ in range(args.quantity):
        run_playwright_or_exit(
            build_session_pwcli_command(args, OCADO_SESSION) + ["click", chosen["add_ref"]],
            capture_output=True,
            echo=False,
        )
    basket_snapshot = snapshot_path_for_session(args, OCADO_SESSION)
    basket = parse_ocado_trolley_summary(parse_snapshot_text(basket_snapshot))
    payload = {
        "selected_product": chosen,
        "quantity_added": args.quantity,
        "basket": basket,
    }
    print(serialise(payload))


def cmd_ocado_basket_show(args: argparse.Namespace) -> None:
    ensure_ocado_open(args, headed=args.headed)
    load_ocado_storage_state_if_present(args)
    accept_ocado_cookies_if_present(args)
    snapshot = snapshot_path_for_session(args, OCADO_SESSION)
    basket = parse_ocado_trolley_summary(parse_snapshot_text(snapshot))
    if not basket:
        raise SystemExit("Could not parse the Ocado trolley summary from the current page.")
    print(serialise(basket))


def accept_sainsburys_cookies_if_present(args: argparse.Namespace) -> None:
    snapshot = snapshot_path_for_session(args, SAINSBURYS_SESSION)
    text = parse_snapshot_text(snapshot)
    for label in ("Accept all cookies", "Accept cookies", "Allow all cookies"):
        ref = button_ref_from_snapshot(text, label=label)
        if ref is None:
            continue
        run_playwright_or_exit(
            build_session_pwcli_command(args, SAINSBURYS_SESSION) + ["click", ref],
            capture_output=True,
            echo=False,
        )
        return


def ensure_sainsburys_open(args: argparse.Namespace, *, headed: bool = False) -> None:
    ensure_retailer_open(args, "sainsburys", headed=headed)


def load_sainsburys_storage_state_if_present(
    args: argparse.Namespace, *, refresh_page: bool = True
) -> bool:
    return load_retailer_storage_state_if_present(
        args, "sainsburys", refresh_page=refresh_page
    )


def save_sainsburys_storage_state(args: argparse.Namespace) -> Path:
    return save_retailer_storage_state(args, "sainsburys")


def sainsburys_headed(args: argparse.Namespace) -> bool:
    return True if not getattr(args, "headed", False) else args.headed


def sainsburys_current_page_info(args: argparse.Namespace) -> dict[str, Any]:
    data = eval_json(
        args,
        SAINSBURYS_SESSION,
        """() => {
  const textOf = (node) => (node?.textContent || '').replace(/\\s+/g, ' ').trim();
  const bodyText = textOf(document.body);
  const title = document.title || '';
  const href = location.href;
  return {
    href,
    title,
    has_search: Boolean(document.querySelector('input[aria-label="Search for products"], input[type="search"]')),
    has_account: Array.from(document.querySelectorAll('a, button')).some((node) => /My account/i.test(textOf(node))),
    access_denied: /Access Denied/i.test(title) || /Access Denied/i.test(bodyText),
    technical_error: /For technical reasons/i.test(bodyText) || /we have not been able to connect you to the page you requested/i.test(bodyText),
  };
}""",
    )
    if not isinstance(data, dict):
        raise SystemExit("Unexpected Sainsbury's page-info payload.")
    return data


def extract_sainsburys_search_results(args: argparse.Namespace) -> list[dict[str, Any]]:
    results = eval_json(
        args,
        SAINSBURYS_SESSION,
        """async () => {
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const normalise = (value) => (value || '').replace(/\\s+/g, ' ').trim();
  const textOf = (node) => normalise(node?.textContent || '');
  for (let i = 0; i < 20; i += 1) {
    const count = Array.from(document.querySelectorAll('button'))
      .filter((button) => /^Add\\s+.+\\s+to trolley$/i.test(button.getAttribute('aria-label') || ''))
      .length;
    if (count > 0) {
      break;
    }
    await sleep(250);
  }
  const addButtons = Array.from(document.querySelectorAll('button'))
    .filter((button) => /^Add\\s+.+\\s+to trolley$/i.test(button.getAttribute('aria-label') || ''));
  const seen = new Set();
  const products = [];
  for (const button of addButtons) {
    let container = button.closest('article, li, div');
    let hops = 0;
    while (container && hops < 4 && !container.querySelector('a')) {
      container = container.parentElement;
      hops += 1;
    }
    const scope = container || button.parentElement || document.body;
    const link = scope.querySelector('a[href]');
    const nameNode = scope.querySelector('h1, h2, h3, h4, [data-test*="product"], [class*="product"] a, a');
    const name = normalise(
      (button.getAttribute('aria-label') || '').replace(/^add\\s+/i, '').replace(/\\s+to.*$/i, '')
    ) || textOf(nameNode);
    if (!name) {
      continue;
    }
    const key = name.toLowerCase();
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    const priceMatch = textOf(scope).match(/£\\d+\\.\\d{2}/);
    const aria = button.getAttribute('aria-label') || '';
    products.push({
      index: products.length,
      name,
      add_index: addButtons.indexOf(button),
      add_label: aria,
      price: priceMatch ? priceMatch[0] : null,
      url: link ? link.href : null,
    });
  }
  return products;
}""",
    )
    if not isinstance(results, list):
        raise SystemExit("Unexpected Sainsbury's search results payload.")
    return results


def ensure_sainsburys_home_ready(args: argparse.Namespace, *, headed: bool = False) -> dict[str, Any]:
    ensure_sainsburys_open(args, headed=headed)
    load_sainsburys_storage_state_if_present(args)
    accept_sainsburys_cookies_if_present(args)
    info = sainsburys_current_page_info(args)
    if info.get("has_search") and not info.get("access_denied") and not info.get("technical_error"):
        return info

    candidate_urls = [
        retailer_page_url("sainsburys", "home_new"),
        retailer_page_url("sainsburys", "home"),
    ]
    for url in candidate_urls:
        run_playwright_or_exit(
            build_session_pwcli_command(args, SAINSBURYS_SESSION) + ["goto", url],
            capture_output=True,
            echo=False,
        )
        accept_sainsburys_cookies_if_present(args)
        info = sainsburys_current_page_info(args)
        if info.get("has_search") and not info.get("access_denied") and not info.get("technical_error"):
            return info

    raise SystemExit(
        "Sainsbury's did not reach a healthy groceries home page. The session landed on an access-denied or technical-error page."
    )


def goto_sainsburys_page(
    args: argparse.Namespace,
    page: str,
    *,
    headed: bool = False,
) -> dict[str, str]:
    ensure_sainsburys_open(args, headed=headed)
    load_sainsburys_storage_state_if_present(args)
    accept_sainsburys_cookies_if_present(args)
    if page == "home":
        info = ensure_sainsburys_home_ready(args, headed=headed)
        return {
            "url": str(info.get("href") or retailer_page_url("sainsburys", "home")),
            "title": str(info.get("title") or ""),
        }
    _, metadata = goto_and_snapshot(
        args,
        SAINSBURYS_SESSION,
        retailer_page_url("sainsburys", page),
    )
    return metadata


def sainsburys_basket_from_text(text: str) -> dict[str, Any]:
    amount_match = re.search(r"Sub-total:\s*(£[0-9]+\.[0-9]{2})", text, re.IGNORECASE)
    count_match = re.search(r"(\d+)\s+items?\s+in\s+(?:your\s+)?trolley", text, re.IGNORECASE)
    basket: dict[str, Any] = {}
    if count_match:
        basket["item_count"] = int(count_match.group(1))
    if amount_match:
        basket["amount"] = amount_match.group(1)
    return basket


def sainsburys_page_state(args: argparse.Namespace) -> dict[str, Any]:
    data = eval_json(
        args,
        SAINSBURYS_SESSION,
        """async () => {
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  await sleep(1500);
  const textOf = (node) => (node?.textContent || '').replace(/\\s+/g, ' ').trim();
  const bodyText = textOf(document.body);
  const links = Array.from(document.querySelectorAll('a, button'));
  const loginVisible = links.some((node) => /log in|register|sign in/i.test(textOf(node)));
  const accountNode = links.find((node) => /my account|my orders|groceries account/i.test(textOf(node)));
  const helloNode = Array.from(document.querySelectorAll('p, span, div')).find((node) => /^Hello\\s+/i.test(textOf(node)));
  const trolleyNode = links.find((node) => /Sub-total:|Full trolley|Trolley/i.test(textOf(node)));
  const quantityNode = Array.from(document.querySelectorAll('button')).find((node) => /in trolley\\. Update quantity/i.test(node.getAttribute('aria-label') || ''));
  const heading = document.querySelector('h1');
  const addressNode = Array.from(document.querySelectorAll('button, a, p, div, span')).find(
    (node) => /delivery|collection|address/i.test(textOf(node)) && /change|selected|home/i.test(textOf(node))
  );
  const amountMatch = textOf(trolleyNode).match(/Sub-total:\\s*(£[0-9]+\\.[0-9]{2})/i);
  const trolleyAmountMatch = textOf(trolleyNode).match(/(£[0-9]+\\.[0-9]{2})/i);
  const quantityMatch = (quantityNode?.getAttribute('aria-label') || '').match(/^(\\d+)\\s+.+\\s+in trolley/i);
  const trolleyCountMatch = textOf(trolleyNode).match(/Trolley\\s*(\\d+)/i);
  const bodyBasketMatch = bodyText.match(/(?:My Account|Favourites|Book a slot)?\\s*(\\d+)\\s*(£[0-9]+\\.[0-9]{2})/i);
  const helloMatch = textOf(helloNode).match(/^Hello\\s+(.+)$/i);
  return {
    page_url: location.href,
    page_title: document.title,
    logged_in: Boolean(accountNode) || Boolean(helloNode) || (!loginVisible && !/Access Denied/i.test(document.title)),
    customer_name: helloMatch ? helloMatch[1] : (accountNode ? textOf(accountNode) : null),
    heading: heading ? textOf(heading) : null,
    delivery_address: addressNode ? textOf(addressNode) : null,
    basket: {
      item_count: quantityMatch ? Number(quantityMatch[1]) : (trolleyCountMatch ? Number(trolleyCountMatch[1]) : (bodyBasketMatch ? Number(bodyBasketMatch[1]) : null)),
      amount: amountMatch ? amountMatch[1] : (trolleyAmountMatch ? trolleyAmountMatch[1] : (bodyBasketMatch ? bodyBasketMatch[2] : null)),
    },
    access_denied: /Access Denied/i.test(document.title) || /Access Denied/i.test(bodyText),
  };
}""",
    )
    if not isinstance(data, dict):
        raise SystemExit("Unexpected Sainsbury's page payload.")
    basket = data.get("basket")
    if isinstance(basket, dict):
        basket = {key: value for key, value in basket.items() if value is not None}
        data["basket"] = basket
    return data


def extract_sainsburys_orders(args: argparse.Namespace, *, headed: bool = False) -> dict[str, Any]:
    metadata = goto_sainsburys_page(args, "orders", headed=headed)
    data = eval_json(
        args,
        SAINSBURYS_SESSION,
        """async () => {
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  await sleep(1000);
  const textOf = (node) => (node?.textContent || '').replace(/\\s+/g, ' ').trim();
  const orderBlocks = Array.from(document.querySelectorAll('main section, main article, main li, main div'))
    .map((node) => textOf(node))
    .filter((text) => /order/i.test(text) && /(delivery|collection|slot|scheduled)/i.test(text))
    .slice(0, 20);
  const orders = orderBlocks.map((text, index) => ({
    order_id: (text.match(/order\\s*(?:number|#)?\\s*([A-Z0-9-]+)/i) || [null, null])[1],
    summary: text,
    index: index + 1,
  }));
  return {
    upcoming_orders: orders,
    previous_orders: [],
    previous_orders_empty: true,
  };
}""",
    )
    if not isinstance(data, dict):
        raise SystemExit("Unexpected Sainsbury's orders payload.")
    data.setdefault("page_url", metadata.get("url"))
    data.setdefault("page_title", metadata.get("title"))
    return data


def extract_sainsburys_slots(args: argparse.Namespace, *, headed: bool = False) -> dict[str, Any]:
    metadata = goto_sainsburys_page(args, "checkout", headed=headed)
    state = sainsburys_page_state(args)
    data = eval_json(
        args,
        SAINSBURYS_SESSION,
        """async () => {
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  await sleep(1000);
  const textOf = (node) => (node?.textContent || '').replace(/\\s+/g, ' ').trim();
  const bodyText = textOf(document.body);
  const slotButtons = Array.from(document.querySelectorAll('button'))
    .filter((button) => {
      const aria = button.getAttribute('aria-label') || '';
      return /between/i.test(aria) || /This slot is fully booked/i.test(aria);
    });
  const slots = slotButtons.map((button, index) => {
    const text = textOf(button);
    const aria = button.getAttribute('aria-label') || '';
    const match = aria.match(/^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\\s+(\\d+)(?:st|nd|rd|th)?\\s+([A-Za-z]+)\\s+between\\s+(\\d+)\\s+(\\d+)\\s+(AM|PM)\\s+and\\s+(\\d+)\\s+(\\d+)\\s+(AM|PM)\\s+for\\s+(£\\d+(?:\\.\\d{2})?|Free)$/i);
    const month = match ? match[3] : null;
    const day = match ? match[2] : null;
    const weekday = match ? match[1] : null;
    const window = match ? `${match[4]}:${match[5]} ${match[6]}-${match[7]}:${match[8]} ${match[9]}` : text;
    const price = match ? match[10] : (text.match(/(£[0-9]+(?:\\.[0-9]{2})?|Free)/i)?.[1] || null);
    const dateLabel = weekday && day && month ? `${weekday} ${day} ${month}` : null;
    return {
      button_index: index,
      date_label: dateLabel,
      window,
      price,
      eco: /saver slot/i.test(bodyText) || /saver/i.test(location.href),
      selected: button.getAttribute('aria-pressed') === 'true' || /selected/i.test(aria) || /selected/i.test(text),
      availability: button.disabled ? 'unavailable' : 'available',
      aria_label: aria,
    };
  });
  const deliveryAddressMatch = bodyText.match(/You are booking delivery to:\\s*([^\\n]+)\\s*click to change your delivery address/i);
  return {
    heading: document.querySelector('h1') ? textOf(document.querySelector('h1')) : null,
    delivery_address: deliveryAddressMatch ? deliveryAddressMatch[1].trim() : null,
    slots,
  };
}""",
    )
    if not isinstance(data, dict):
        raise SystemExit("Unexpected Sainsbury's slots payload.")
    slots = data.get("slots", [])
    if not isinstance(slots, list):
        raise SystemExit("Unexpected Sainsbury's slots list.")
    normalised_slots: list[dict[str, Any]] = []
    for slot in slots:
        if not isinstance(slot, dict):
            continue
        slot["slot_id"] = slot_id_for(slot)
        normalised_slots.append(slot)
    return {
        "page_url": metadata.get("url"),
        "page_title": metadata.get("title"),
        "heading": data.get("heading") or state.get("heading"),
        "delivery_address": data.get("delivery_address") or state.get("delivery_address"),
        "basket": state.get("basket", {}),
        "slots": normalised_slots,
    }


def sainsburys_slot_modal_state(args: argparse.Namespace) -> dict[str, Any]:
    data = eval_json(
        args,
        SAINSBURYS_SESSION,
        """async () => {
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  await sleep(750);
  const textOf = (node) => (node?.textContent || '').replace(/\\s+/g, ' ').trim();
  const dialogs = Array.from(document.querySelectorAll('[role="dialog"], dialog'))
    .map((node) => textOf(node))
    .filter(Boolean);
  const reserveButton = Array.from(document.querySelectorAll('button')).find((button) =>
    /^Reserve slot/i.test(textOf(button)) || /^Reserve slot on /i.test(button.getAttribute('aria-label') || '')
  );
  return {
    too_soon: dialogs.some((text) => /too soon/i.test(text)),
    reserve_present: Boolean(reserveButton),
    reserve_label: reserveButton ? (reserveButton.getAttribute('aria-label') || textOf(reserveButton)) : null,
    dialogs,
    page_url: location.href,
    page_title: document.title,
  };
}""",
    )
    if not isinstance(data, dict):
        raise SystemExit("Unexpected Sainsbury's slot modal payload.")
    return data


def click_sainsburys_slot_by_label(args: argparse.Namespace, label: str) -> dict[str, Any]:
    snapshot_text = capture_snapshot_text(args, SAINSBURYS_SESSION)
    ref = button_ref_from_snapshot(snapshot_text, label=label)
    if ref is None:
        return {"clicked": False, "reason": "slot button not found", "label": label}
    run_playwright_or_exit(
        build_session_pwcli_command(args, SAINSBURYS_SESSION) + ["click", ref],
        capture_output=True,
        echo=False,
    )
    modal_state = sainsburys_slot_modal_state(args)
    modal_state["clicked"] = True
    modal_state["clicked_ref"] = ref
    return modal_state


def click_sainsburys_reserve_slot(args: argparse.Namespace, label: str) -> dict[str, Any]:
    reserve_label = f"Reserve slot on {label}"
    ref = None
    for _ in range(8):
        snapshot_text = capture_snapshot_text(args, SAINSBURYS_SESSION)
        ref = button_ref_from_snapshot(snapshot_text, label=reserve_label)
        if ref is None:
            ref = first_sainsburys_reserve_ref_from_snapshot(snapshot_text)
        if ref is not None:
            break
        time.sleep(0.5)
    if ref is None:
        return {
            "clicked": False,
            "reason": "reserve slot button not found",
            "label": reserve_label,
        }
    run_playwright_or_exit(
        build_session_pwcli_command(args, SAINSBURYS_SESSION) + ["click", ref],
        capture_output=True,
        echo=False,
    )
    return {
        "clicked": True,
        "clicked_ref": ref,
        "page_url": current_page_metadata(args, SAINSBURYS_SESSION).get("url"),
        "page_title": current_page_metadata(args, SAINSBURYS_SESSION).get("title"),
    }


def sainsburys_slot_confirmation_state(args: argparse.Namespace) -> dict[str, Any]:
    state = sainsburys_page_state(args)
    data = eval_json(
        args,
        SAINSBURYS_SESSION,
        """async () => {
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  await sleep(750);
  const textOf = (node) => (node?.textContent || '').replace(/\\s+/g, ' ').trim();
  const bodyText = textOf(document.body);
  const texts = Array.from(document.querySelectorAll('button, a, div, span, p, h1, h2, h3, h4'))
    .map((node) => textOf(node))
    .filter(Boolean);
  const reservedSummary = texts.find((text) =>
    /^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\\s+\\d{1,2}(?:st|nd|rd|th)?,\\s+\\d{1,2}:\\d{2}(?:am|pm)-\\d{1,2}:\\d{2}(?:am|pm)$/i.test(text)
  );
  const slotDetails = texts.find((text) =>
    /^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\\s+\\d{1,2}\\s+[A-Za-z]{3}\\s+at\\s+\\d{1,2}:\\d{2}\\s+-\\s+\\d{1,2}:\\d{2}\\s+[ap]m$/i.test(text)
  );
  const deadlinePrefix = 'To confirm your slot check out before:';
  const deadlineText = texts.find((text) => text.startsWith(deadlinePrefix));
  return {
    page_url: location.href,
    page_title: document.title,
    slot_reserved: /Slot reserved/i.test(bodyText),
    reserved_summary: reservedSummary || null,
    slot_details: slotDetails || null,
    checkout_deadline: deadlineText ? deadlineText.replace(deadlinePrefix, '').trim() : null,
    change_slot_visible: /Change delivery slot/i.test(bodyText),
  };
}""",
    )
    if not isinstance(data, dict):
        raise SystemExit("Unexpected Sainsbury's slot confirmation payload.")
    data["basket"] = state.get("basket", {})
    return data


def sainsburys_search(args: argparse.Namespace, query: str, *, headed: bool = False) -> list[dict[str, Any]]:
    ensure_sainsburys_home_ready(args, headed=headed)
    search_url = "https://www.sainsburys.co.uk/gol-ui/SearchResults/" + urllib.parse.quote(
        query.strip()
    )
    run_playwright_or_exit(
        build_session_pwcli_command(args, SAINSBURYS_SESSION) + ["goto", search_url],
        capture_output=True,
        echo=False,
    )
    results = extract_sainsburys_search_results(args)
    if not isinstance(results, list) or not results:
        raise SystemExit(f"No Sainsbury's add-to-trolley results found for query {query!r}.")
    return results


def select_sainsburys_result(results: list[dict[str, Any]], product_name: Optional[str]) -> dict[str, Any]:
    if not product_name:
        return results[0]
    target = product_name.casefold()
    exact_matches = [result for result in results if str(result.get("name", "")).casefold() == target]
    if exact_matches:
        return exact_matches[0]
    partial_matches = [result for result in results if target in str(result.get("name", "")).casefold()]
    if partial_matches:
        return partial_matches[0]
    raise SystemExit(
        f"No Sainsbury's search result matched {product_name!r}. Top results: "
        + ", ".join(str(result.get("name", "")) for result in results[:5])
    )


def add_sainsburys_result_to_basket(
    args: argparse.Namespace,
    add_index: int,
    quantity: int,
    *,
    add_label: Optional[str] = None,
) -> dict[str, Any]:
    result = eval_json(
        args,
        SAINSBURYS_SESSION,
        f"""async () => {{
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const textOf = (node) => (node?.textContent || '').replace(/\\s+/g, ' ').trim();
  const addButtons = Array.from(document.querySelectorAll('button'))
    .filter((button) => /^Add\\s+.+\\s+to trolley$/i.test(button.getAttribute('aria-label') || ''));
  const button = {json.dumps(add_label)} ? addButtons.find((candidate) => (candidate.getAttribute('aria-label') || '') === {json.dumps(add_label)}) : addButtons[{add_index}];
  if (!button) {{
    return {{clicked: false, reason: 'add button not found'}};
  }}
  const aria = button.getAttribute('aria-label') || '';
  const itemName = aria.replace(/^Add\\s+/i, '').replace(/\\s+to trolley$/i, '').trim();
  for (let i = 0; i < {quantity}; i += 1) {{
    button.click();
    await sleep(1000);
  }}
  const quantityButton = Array.from(document.querySelectorAll('button')).find((candidate) => (candidate.getAttribute('aria-label') || '').includes(itemName) && /in trolley\\. Update quantity/i.test(candidate.getAttribute('aria-label') || ''));
  const removeButton = Array.from(document.querySelectorAll('button')).find((candidate) => (candidate.getAttribute('aria-label') || '').includes(itemName) && /Remove .* from trolley/i.test(candidate.getAttribute('aria-label') || ''));
  return {{
    clicked: true,
    href: location.href,
    title: document.title,
    verified_quantity_control: Boolean(quantityButton),
    verified_remove_control: Boolean(removeButton),
  }};
}}""",
    )
    if not isinstance(result, dict):
        raise SystemExit("Unexpected Sainsbury's add-to-basket payload.")
    return result


def extract_sainsburys_favourites(args: argparse.Namespace, *, headed: bool = False) -> dict[str, Any]:
    metadata = goto_sainsburys_page(args, "favourites", headed=headed)
    data = eval_json(
        args,
        SAINSBURYS_SESSION,
        """async () => {
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  await sleep(1000);
  const normalise = (value) => (value || '').replace(/\\s+/g, ' ').trim();
  const textOf = (node) => normalise(node?.textContent || '');
  const visible = (el) => {
    if (!(el instanceof Element)) return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  };
  const addButtons = Array.from(document.querySelectorAll('button'))
    .filter((button) => visible(button))
    .filter((button) => /^Add\\s+.+\\s+to trolley$/i.test(button.getAttribute('aria-label') || ''));
  const items = [];
  const seen = new Set();
  for (const button of addButtons) {
    const scope = button.closest('article, li, div') || button.parentElement || document.body;
    const nameNode = scope.querySelector('h1, h2, h3, h4, a');
    const name = normalise(
      (button.getAttribute('aria-label') || '').replace(/^add\\s+/i, '').replace(/\\s+to.*$/i, '')
    ) || textOf(nameNode);
    if (!name) continue;
    const key = name.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    items.push({
      rank: items.length + 1,
      name,
    });
  }
  return {
    supported: items.length > 0,
    items,
  };
}""",
    )
    if not isinstance(data, dict):
        raise SystemExit("Unexpected Sainsbury's favourites payload.")
    data.setdefault("page_url", metadata.get("url"))
    data.setdefault("page_title", metadata.get("title"))
    return data


def cmd_sainsburys_open(args: argparse.Namespace) -> None:
    ensure_sainsburys_open(args, headed=sainsburys_headed(args))
    load_sainsburys_storage_state_if_present(args)
    accept_sainsburys_cookies_if_present(args)


def cmd_sainsburys_login(args: argparse.Namespace) -> None:
    ensure_sainsburys_open(args, headed=True)
    had_saved_state = load_sainsburys_storage_state_if_present(args)
    accept_sainsburys_cookies_if_present(args)
    if had_saved_state:
        print("Loaded the existing Sainsbury's session first.")
    print("Complete the Sainsbury's login in the headed browser, then press Enter here to save the session.")
    try:
        input()
    except EOFError:
        raise SystemExit(
            "Login flow needs an interactive terminal. Run this command directly in your shell."
        ) from None
    output = save_sainsburys_storage_state(args)
    print(f"Saved Sainsbury's storage state to {output}")


def cmd_sainsburys_session_status(args: argparse.Namespace) -> None:
    goto_sainsburys_page(args, "home", headed=sainsburys_headed(args))
    print(serialise(sainsburys_page_state(args)))


def cmd_sainsburys_orders(args: argparse.Namespace) -> None:
    print(serialise(extract_sainsburys_orders(args, headed=sainsburys_headed(args))))


def cmd_sainsburys_checkout_state(args: argparse.Namespace) -> None:
    goto_sainsburys_page(args, "checkout", headed=sainsburys_headed(args))
    print(serialise(sainsburys_page_state(args)))


def cmd_sainsburys_slots(args: argparse.Namespace) -> None:
    print(serialise(extract_sainsburys_slots(args, headed=sainsburys_headed(args))))


def cmd_sainsburys_slot_book(args: argparse.Namespace) -> None:
    if not args.confirm:
        raise SystemExit("Refusing to book a slot without --confirm.")
    slot_data = extract_sainsburys_slots(args, headed=sainsburys_headed(args))
    slots = slot_data.get("slots", [])
    chosen = next((slot for slot in slots if slot.get("slot_id") == args.slot_id), None)
    if chosen is None:
        raise SystemExit(
            f"Unknown slot id {args.slot_id!r}. Run `grocery-shopping sainsburys slots` first."
        )
    if chosen.get("availability") != "available":
        raise SystemExit(f"Sainsbury's slot {args.slot_id!r} is not available.")
    aria_label = str(chosen.get("aria_label") or "")
    click_result = click_sainsburys_slot_by_label(args, aria_label)
    if not click_result.get("clicked"):
        raise SystemExit(
            f"Sainsbury's slot click failed: {click_result.get('reason', 'unknown error')}"
        )
    if click_result.get("too_soon") and not click_result.get("reserve_present"):
        raise SystemExit(
            "Sainsbury's rejected that slot because it is too soon for at least one basket item to be prepared."
        )
    if not click_result.get("reserve_present"):
        raise SystemExit("Sainsbury's did not present a reserve-slot confirmation modal.")
    reserve_result = click_sainsburys_reserve_slot(args, aria_label)
    if not reserve_result.get("clicked"):
        raise SystemExit(
            "Sainsbury's reserve-slot confirmation failed: "
            f"{reserve_result.get('reason', 'unknown error')}"
        )
    confirmation = sainsburys_slot_confirmation_state(args)
    payload = {
        "attempted": True,
        "requested_slot_id": args.slot_id,
        "requested_slot": chosen,
        "page_url": confirmation.get("page_url"),
        "page_title": confirmation.get("page_title"),
        "selected_slot": {
            "date_label": chosen.get("date_label"),
            "window": chosen.get("window"),
            "price": chosen.get("price"),
            "slot_id": chosen.get("slot_id"),
        },
        "confirmation": confirmation,
    }
    print(serialise(payload))


def cmd_sainsburys_search(args: argparse.Namespace) -> None:
    results = sainsburys_search(args, args.query, headed=sainsburys_headed(args))
    print(serialise(results[: args.limit]))


def cmd_sainsburys_add_to_basket(args: argparse.Namespace) -> None:
    page_info = sainsburys_current_page_info(args)
    current_href = str(page_info.get("href") or "")
    expected_suffix = "/gol-ui/SearchResults/" + urllib.parse.quote(args.query.strip())
    if current_href.endswith(expected_suffix):
        results = extract_sainsburys_search_results(args)
    else:
        results = sainsburys_search(args, args.query, headed=sainsburys_headed(args))
    chosen = select_sainsburys_result(results, args.product)
    click_result = add_sainsburys_result_to_basket(
        args,
        int(chosen["add_index"]),
        args.quantity,
        add_label=str(chosen.get("add_label") or ""),
    )
    if not click_result.get("clicked"):
        raise SystemExit(
            f"Sainsbury's add-to-basket failed: {click_result.get('reason', 'unknown error')}"
        )
    basket_state = sainsburys_page_state(args)
    payload = {
        "selected_product": chosen,
        "quantity_added": args.quantity,
        "basket": basket_state.get("basket", {}),
    }
    print(serialise(payload))


def cmd_sainsburys_basket_show(args: argparse.Namespace) -> None:
    goto_sainsburys_page(args, "home", headed=sainsburys_headed(args))
    snapshot = snapshot_path_for_session(args, SAINSBURYS_SESSION)
    basket = sainsburys_basket_from_text(parse_snapshot_text(snapshot))
    if not basket:
        basket = sainsburys_page_state(args).get("basket", {})
    if not basket:
        raise SystemExit("Could not parse the Sainsbury's trolley summary from the current page.")
    print(serialise(basket))


def cmd_sainsburys_favourites(args: argparse.Namespace) -> None:
    payload = extract_sainsburys_favourites(args, headed=sainsburys_headed(args))
    supported = bool(payload.get("supported"))
    items = payload.get("items", [])
    if not supported:
        print(
            serialise(
                {
                    "supported": False,
                    "message": "Could not detect a stable Sainsbury's favourites list in the current session.",
                    "page_url": payload.get("page_url"),
                    "page_title": payload.get("page_title"),
                    "items": [],
                }
            )
        )
        return
    print(
        serialise(
            {
                "supported": True,
                "page_url": payload.get("page_url"),
                "page_title": payload.get("page_title"),
                "items": items[: args.limit],
            }
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Grocery shopping assistant CLI")
    parser.set_defaults(func=None)
    parser.add_argument(
        "--state",
        default=str(DEFAULT_STATE),
        help="Path to local grocery shopping state JSON",
    )
    parser.add_argument(
        "--data-dir",
        default=str(DEFAULT_DATA_DIR),
        help="Path to local shopping data directory",
    )

    subparsers = parser.add_subparsers(dest="command")

    init = subparsers.add_parser("init", help="Initialise local grocery state")
    init.set_defaults(func=cmd_init)

    staple = subparsers.add_parser("staple", help="Manage recurring staples")
    staple_subparsers = staple.add_subparsers(dest="staple_command")

    staple_add = staple_subparsers.add_parser("add", help="Add or update a staple")
    staple_add.add_argument("name", help="Staple name")
    staple_add.add_argument("--quantity", type=float, default=1, help="Default quantity")
    staple_add.add_argument("--unit", help="Optional unit")
    staple_add.add_argument("--notes", help="Optional notes")
    staple_add.set_defaults(func=cmd_staple_add)

    staple_list = staple_subparsers.add_parser("list", help="List staples")
    staple_list.set_defaults(func=cmd_staple_list)

    preference = subparsers.add_parser("preference", help="Manage shopping preferences")
    preference_subparsers = preference.add_subparsers(dest="preference_command")

    preference_set = preference_subparsers.add_parser("set", help="Set a product preference")
    preference_set.add_argument("name", help="Product or ingredient name")
    preference_set.add_argument(
        "--status",
        required=True,
        choices=["like", "avoid", "substitute", "try"],
        help="Preference status",
    )
    preference_set.add_argument("--notes", default="", help="Optional notes")
    preference_set.set_defaults(func=cmd_preference_set)

    preference_list = preference_subparsers.add_parser("list", help="List preferences")
    preference_list.set_defaults(func=cmd_preference_list)

    plan = subparsers.add_parser("plan", help="Manage draft shopping plans")
    plan_subparsers = plan.add_subparsers(dest="plan_command")

    plan_new = plan_subparsers.add_parser("new", help="Create a new plan")
    plan_new.add_argument("name", help="Plan name")
    plan_new.set_defaults(func=cmd_plan_new)

    plan_add = plan_subparsers.add_parser("add", help="Add an item to a plan")
    plan_add.add_argument("plan", help="Plan name")
    plan_add.add_argument("name", help="Item name")
    plan_add.add_argument("--quantity", type=float, default=1, help="Quantity")
    plan_add.add_argument("--unit", help="Optional unit")
    plan_add.add_argument(
        "--reason",
        default="manual",
        choices=["manual", "staple", "recipe", "topup", "explore"],
        help="Why the item is in the plan",
    )
    plan_add.add_argument("--notes", help="Optional notes")
    plan_add.set_defaults(func=cmd_plan_add)

    plan_show = plan_subparsers.add_parser("show", help="Show a plan")
    plan_show.add_argument("plan", help="Plan name")
    plan_show.set_defaults(func=cmd_plan_show)

    import_ocado = subparsers.add_parser(
        "import-ocado-favourites", help="Import an Ocado favourites CSV as staple seeds"
    )
    import_ocado.add_argument("csv_path", help="Path to the exported Ocado favourites CSV")
    import_ocado.set_defaults(func=cmd_import_ocado_favourites)

    playwright = subparsers.add_parser(
        "playwright", help="Run Playwright session helpers for retailer exploration"
    )
    playwright_subparsers = playwright.add_subparsers(dest="playwright_command")

    pw_open = playwright_subparsers.add_parser("open", help="Open a retailer in Playwright")
    pw_open.add_argument("retailer", choices=sorted(SUPPORTED_RETAILERS))
    pw_open.add_argument("--headed", action="store_true", help="Run a headed browser")
    pw_open.set_defaults(func=cmd_playwright_open)

    pw_snapshot = playwright_subparsers.add_parser("snapshot", help="Capture a page snapshot")
    pw_snapshot.set_defaults(func=cmd_playwright_snapshot)

    pw_save = playwright_subparsers.add_parser(
        "save-state", help="Save storage state after manual login"
    )
    pw_save.add_argument("retailer", choices=sorted(SUPPORTED_RETAILERS))
    pw_save.set_defaults(func=cmd_playwright_save_state)

    pw_load = playwright_subparsers.add_parser("load-state", help="Load saved storage state")
    pw_load.add_argument("retailer", choices=sorted(SUPPORTED_RETAILERS))
    pw_load.set_defaults(func=cmd_playwright_load_state)

    pw_goto = playwright_subparsers.add_parser("goto", help="Navigate the current page")
    pw_goto.add_argument("url", help="URL to visit")
    pw_goto.set_defaults(func=cmd_playwright_goto)

    pw_raw = playwright_subparsers.add_parser(
        "raw", help="Pass arguments directly to playwright-cli"
    )
    pw_raw.add_argument("playwright_args", nargs=argparse.REMAINDER)
    pw_raw.set_defaults(func=cmd_playwright_passthrough)

    ocado = subparsers.add_parser("ocado", help="Ocado-specific shopping flows")
    ocado_subparsers = ocado.add_subparsers(dest="ocado_command")

    ocado_open = ocado_subparsers.add_parser("open", help="Open Ocado in its dedicated session")
    ocado_open.add_argument("--headed", action="store_true", help="Run a headed browser")
    ocado_open.set_defaults(func=cmd_ocado_open)

    ocado_login = ocado_subparsers.add_parser("login", help="Open the Ocado login flow")
    ocado_login.set_defaults(func=cmd_ocado_login)

    ocado_status = ocado_subparsers.add_parser(
        "session-status", help="Show whether the saved Ocado session is logged in"
    )
    ocado_status.add_argument("--headed", action="store_true", help="Run a headed browser")
    ocado_status.set_defaults(func=cmd_ocado_session_status)

    ocado_orders = ocado_subparsers.add_parser("orders", help="List current Ocado orders")
    ocado_orders.add_argument("--headed", action="store_true", help="Run a headed browser")
    ocado_orders.set_defaults(func=cmd_ocado_orders)

    ocado_checkout_state = ocado_subparsers.add_parser(
        "checkout-state", help="Inspect the current Ocado checkout or slot-booking state"
    )
    ocado_checkout_state.add_argument("--headed", action="store_true", help="Run a headed browser")
    ocado_checkout_state.set_defaults(func=cmd_ocado_checkout_state)

    ocado_slots = ocado_subparsers.add_parser("slots", help="List available Ocado delivery slots")
    ocado_slots.add_argument("--headed", action="store_true", help="Run a headed browser")
    ocado_slots.set_defaults(func=cmd_ocado_slots)

    ocado_favourites = ocado_subparsers.add_parser(
        "favourites", help="List Ocado favourites from the logged-in account"
    )
    ocado_favourites.add_argument("--limit", type=int, default=20, help="Max favourites to print")
    ocado_favourites.set_defaults(func=cmd_ocado_favourites)

    ocado_slot_book = ocado_subparsers.add_parser(
        "slot-book", help="Book an Ocado slot by explicit slot id"
    )
    ocado_slot_book.add_argument("slot_id", help="Slot id returned by `ocado slots`")
    ocado_slot_book.add_argument(
        "--confirm",
        action="store_true",
        help="Required to perform the slot booking click",
    )
    ocado_slot_book.add_argument("--headed", action="store_true", help="Run a headed browser")
    ocado_slot_book.set_defaults(func=cmd_ocado_slot_book)

    ocado_search_parser = ocado_subparsers.add_parser("search", help="Search Ocado products")
    ocado_search_parser.add_argument("query", help="Search query")
    ocado_search_parser.add_argument("--limit", type=int, default=10, help="Max results to print")
    ocado_search_parser.add_argument("--headed", action="store_true", help="Run a headed browser")
    ocado_search_parser.set_defaults(func=cmd_ocado_search)

    ocado_add = ocado_subparsers.add_parser(
        "add-to-basket", help="Search Ocado and add a matching product to the trolley"
    )
    ocado_add.add_argument("query", help="Search query to run first")
    ocado_add.add_argument(
        "--product",
        help="Optional exact or partial product name to select from the search results",
    )
    ocado_add.add_argument("--quantity", type=int, default=1, help="Number of add clicks")
    ocado_add.add_argument("--headed", action="store_true", help="Run a headed browser")
    ocado_add.set_defaults(func=cmd_ocado_add_to_basket)

    ocado_basket = ocado_subparsers.add_parser(
        "basket-show", help="Show the current Ocado trolley item count and amount"
    )
    ocado_basket.add_argument("--headed", action="store_true", help="Run a headed browser")
    ocado_basket.set_defaults(func=cmd_ocado_basket_show)

    sainsburys = subparsers.add_parser("sainsburys", help="Sainsbury's-specific shopping flows")
    sainsburys_subparsers = sainsburys.add_subparsers(dest="sainsburys_command")

    sainsburys_open = sainsburys_subparsers.add_parser(
        "open", help="Open Sainsbury's groceries in its dedicated session"
    )
    sainsburys_open.add_argument("--headed", action="store_true", help="Run a headed browser")
    sainsburys_open.set_defaults(func=cmd_sainsburys_open)

    sainsburys_login = sainsburys_subparsers.add_parser(
        "login", help="Open the Sainsbury's login flow"
    )
    sainsburys_login.set_defaults(func=cmd_sainsburys_login)

    sainsburys_status = sainsburys_subparsers.add_parser(
        "session-status", help="Show whether the saved Sainsbury's session is logged in"
    )
    sainsburys_status.add_argument("--headed", action="store_true", help="Run a headed browser")
    sainsburys_status.set_defaults(func=cmd_sainsburys_session_status)

    sainsburys_orders = sainsburys_subparsers.add_parser(
        "orders", help="List current Sainsbury's orders"
    )
    sainsburys_orders.add_argument("--headed", action="store_true", help="Run a headed browser")
    sainsburys_orders.set_defaults(func=cmd_sainsburys_orders)

    sainsburys_checkout_state = sainsburys_subparsers.add_parser(
        "checkout-state", help="Inspect the current Sainsbury's checkout or slot-booking state"
    )
    sainsburys_checkout_state.add_argument(
        "--headed", action="store_true", help="Run a headed browser"
    )
    sainsburys_checkout_state.set_defaults(func=cmd_sainsburys_checkout_state)

    sainsburys_slots = sainsburys_subparsers.add_parser(
        "slots", help="List available Sainsbury's delivery slots"
    )
    sainsburys_slots.add_argument("--headed", action="store_true", help="Run a headed browser")
    sainsburys_slots.set_defaults(func=cmd_sainsburys_slots)

    sainsburys_favourites = sainsburys_subparsers.add_parser(
        "favourites", help="List Sainsbury's favourites or report if none are detectable"
    )
    sainsburys_favourites.add_argument(
        "--limit", type=int, default=20, help="Max favourites to print"
    )
    sainsburys_favourites.add_argument(
        "--headed", action="store_true", help="Run a headed browser"
    )
    sainsburys_favourites.set_defaults(func=cmd_sainsburys_favourites)

    sainsburys_slot_book = sainsburys_subparsers.add_parser(
        "slot-book", help="Book a Sainsbury's slot by explicit slot id"
    )
    sainsburys_slot_book.add_argument(
        "slot_id", help="Slot id returned by `sainsburys slots`"
    )
    sainsburys_slot_book.add_argument(
        "--confirm",
        action="store_true",
        help="Required to perform the slot booking click",
    )
    sainsburys_slot_book.add_argument(
        "--headed", action="store_true", help="Run a headed browser"
    )
    sainsburys_slot_book.set_defaults(func=cmd_sainsburys_slot_book)

    sainsburys_search_parser = sainsburys_subparsers.add_parser(
        "search", help="Search Sainsbury's groceries products"
    )
    sainsburys_search_parser.add_argument("query", help="Search query")
    sainsburys_search_parser.add_argument(
        "--limit", type=int, default=10, help="Max results to print"
    )
    sainsburys_search_parser.add_argument(
        "--headed", action="store_true", help="Run a headed browser"
    )
    sainsburys_search_parser.set_defaults(func=cmd_sainsburys_search)

    sainsburys_add = sainsburys_subparsers.add_parser(
        "add-to-basket", help="Search Sainsbury's and add a matching product to the trolley"
    )
    sainsburys_add.add_argument("query", help="Search query to run first")
    sainsburys_add.add_argument(
        "--product",
        help="Optional exact or partial product name to select from the search results",
    )
    sainsburys_add.add_argument("--quantity", type=int, default=1, help="Number of add clicks")
    sainsburys_add.add_argument("--headed", action="store_true", help="Run a headed browser")
    sainsburys_add.set_defaults(func=cmd_sainsburys_add_to_basket)

    sainsburys_basket = sainsburys_subparsers.add_parser(
        "basket-show", help="Show the current Sainsbury's trolley item count and amount"
    )
    sainsburys_basket.add_argument(
        "--headed", action="store_true", help="Run a headed browser"
    )
    sainsburys_basket.set_defaults(func=cmd_sainsburys_basket_show)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.func is None:
        parser.print_help()
        return
    if getattr(args, "command", None) == "sainsburys":
        with RetailerSessionLock("sainsburys"):
            args.func(args)
        return
    args.func(args)


if __name__ == "__main__":
    main()
