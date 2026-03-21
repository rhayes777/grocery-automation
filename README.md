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
| Search | validated but flaky in one smoke run | validated |
| Add to basket | implemented | validated |
| Basket summary | flaky in one smoke run | validated |
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

The CLIs expect a Playwright-compatible command runner. They resolve it in this order:

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

## Skills

The repo includes public Codex-oriented skills:

- `skills/grocery-shopping/SKILL.md`
- `skills/weekly-shop/SKILL.md`
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
