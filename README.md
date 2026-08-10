# Grocery Automation

Public CLI tools and Codex-ready skills for browser-driven grocery automation against Ocado and Sainsbury's.

The repo packages two installable CLIs:

- `grocery-shopping`: local shopping state plus retailer automation
- `weekly-shop`: optional calendar-aware slot suggestion and checkout helper

The project is intentionally browser-first. It expects manual login in a headed browser, stores local browser state outside the repo, and avoids embedding private credentials.

## Current Support

Support is retailer- and flow-specific. Keep the support table honest and re-validate it after retailer site changes.

| Flow | Ocado | Sainsbury's |
| --- | --- | --- |
| Login / session reuse | validated | validated |
| Search | validated | validated |
| Add to basket | validated | validated |
| Basket summary | validated | validated |
| Checkout state | validated | validated |
| Slots listing | validated | validated |
| Slot booking | implemented; re-test before relying on it | validated |
| Orders | implemented | best-effort, likely stale until revalidated |
| Favourites | implemented | best-effort |

If a retailer flow breaks, use the self-healing skill in `skills/self-heal-grocery-cli/SKILL.md` to re-discover the current site flow before patching code.

## Installation

```bash
git clone <your-public-repo-url>
cd public-grocery-automation
./scripts/bootstrap.sh
```

This creates a virtual environment, installs the package in editable mode, and adds test tooling.

### Browser Automation Prerequisite

The package now supports two browser execution paths:

- default: a long-lived Python Playwright worker for the hot interactive flows
- fallback: the existing `playwright-cli` runner for flows that still use the older wrapper path

Install a browser for the Python worker path:

```bash
. .venv/bin/activate
python -m playwright install chromium
```

The fallback CLI path resolves the Playwright-compatible command in this order:

1. `GROCERY_PLAYWRIGHT_CLI`
2. `playwright-cli` on `PATH`
3. Codex Playwright skill wrapper at `~/.codex/skills/playwright/scripts/playwright_cli.sh`

If you use Codex locally, the third option is often enough. Otherwise set `GROCERY_PLAYWRIGHT_CLI` to the browser-automation command you want the package to use.

## Local Data and Configuration

By default the package stores local state under:

- macOS: `~/Library/Application Support/grocery-automation/`
- Linux: `${XDG_STATE_HOME:-~/.local/state}/grocery-automation/`

Useful environment variables:

- `GROCERY_AUTOMATION_HOME`: override the entire local app-data directory
- `GROCERY_WORKER_DIR`: override the worker runtime directory
- `GROCERY_PLAYWRIGHT_CLI`: override the Playwright command
- `GROCERY_SHOPPING_BIN`: override how `weekly-shop` calls `grocery-shopping`
- `WEEKLY_SHOP_GCALCLI`: path to `gcalcli`
- `WEEKLY_SHOP_CALENDAR`: default calendar name for `weekly-shop`

## Quick Start

Initialize local state:

```bash
grocery-shopping init
```

Open a headed browser and log in manually:

```bash
grocery-shopping ocado login
grocery-shopping sainsburys login
```

Check sessions:

```bash
grocery-shopping ocado session-status
grocery-shopping sainsburys session-status
grocery-shopping worker start
grocery-shopping worker status
```

Search and inspect baskets:

```bash
grocery-shopping ocado search milk --limit 5
grocery-shopping sainsburys search milk --limit 5
grocery-shopping ocado basket-show
grocery-shopping sainsburys basket-show
```

Inspect slots:

```bash
grocery-shopping ocado slots
grocery-shopping sainsburys slots
```

Book only with explicit confirmation:

```bash
grocery-shopping ocado slot-book <slot_id> --confirm
grocery-shopping sainsburys slot-book <slot_id> --confirm
```

Weekly helper examples:

```bash
weekly-shop slot-suggest --retailer ocado
weekly-shop slot-suggest --retailer sainsburys --no-calendar
weekly-shop regular-items --retailer ocado
weekly-shop open-checkout --retailer sainsburys
```

Stop the long-lived worker when you want to clear warm browser state:

```bash
grocery-shopping worker stop
```

## Skills

The repo includes public Codex-oriented skills:

- `skills/grocery-shopping/SKILL.md`
- `skills/weekly-shop/SKILL.md`
- `skills/add-shopping-list/SKILL.md`
- `skills/add-regulars/SKILL.md`
- `skills/add-recipe/SKILL.md`
- `skills/look-up-and-add-recipe/SKILL.md`
- `skills/extend-supermarket/SKILL.md`
- `skills/self-heal-grocery-cli/SKILL.md`

These are written to be safe for a public repo. They contain no personal paths, private credentials, or repo-specific storage state.

## Development

Run static checks and tests:

```bash
. .venv/bin/activate
python -m py_compile src/grocery_automation/*.py
pytest
```

Before publishing, run a fresh live verification pass and update the support table if retailer behavior changed.
