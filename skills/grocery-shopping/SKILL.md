---
name: grocery-shopping
description: Use when the user wants browser-driven grocery shopping with Ocado or Sainsbury's through the public `grocery-shopping` CLI.
---

# Grocery Shopping

Use this skill for local grocery planning, retailer search, basket building, slot inspection, and guarded slot booking.

Start with the CLI:

```bash
grocery-shopping --help
```

## Defaults

- Prefer manual login in a headed browser.
- Keep credentials and storage state out of the repo.
- Prefer browser automation over guessed private APIs.
- Stop before checkout or slot booking unless the user explicitly confirms.

## Core workflow

Initialize local state:

```bash
grocery-shopping init
```

Log in and save reusable browser state:

```bash
grocery-shopping ocado login
grocery-shopping sainsburys login
```

Check session state:

```bash
grocery-shopping ocado session-status
grocery-shopping sainsburys session-status
```

Search and add products:

```bash
grocery-shopping ocado search tofu
grocery-shopping ocado add-to-basket tofu --product "The Tofoo Co Naked Organic Extra Firm Tofu"
grocery-shopping sainsburys search tofu
grocery-shopping sainsburys add-to-basket tofu --product "Cauldron Organic Tofu"
```

Inspect basket and slots:

```bash
grocery-shopping ocado basket-show
grocery-shopping sainsburys basket-show
grocery-shopping ocado slots
grocery-shopping sainsburys slots
```

Only book a slot after the user confirms:

```bash
grocery-shopping ocado slot-book <slot_id> --confirm
grocery-shopping sainsburys slot-book <slot_id> --confirm
```

## Notes

- `orders` and `favourites` may be retailer-specific and best-effort. Verify current live behavior before promising them.
- If a command that used to work starts failing, switch to the self-healing skill instead of guessing selectors.
