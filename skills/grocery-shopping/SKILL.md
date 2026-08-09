---
name: grocery-shopping
description: Use when the user wants browser-driven grocery shopping with Ocado or Sainsbury's through the public `grocery-shopping` CLI.
---

# Grocery Shopping

Use this skill for local grocery planning, retailer search, basket building, batch shopping-list execution, and guarded slot booking.

Start with the CLI:

```bash
grocery-shopping --help
```

## Defaults

- Prefer manual login in a headed browser.
- Keep credentials and storage state out of the repo.
- Prefer browser automation over guessed private APIs.
- Stop before checkout or slot booking unless the user explicitly confirms.
- Default retailer: Ocado unless the user specifies otherwise.
- For multi-item requests, search several items first and review choices before basket mutation.
- Use a hybrid confidence rule:
  - auto-add only high-confidence matches
  - review ambiguous matches with the user
  - report unresolved items and skip them
- Always finish multi-item workflows with `basket-show` and a summary of skipped, substituted, or unresolved items.
- For image-based shopping lists or recipes, first show the interpreted items before searching or adding.

## Batch workflow

When the user gives a shopping list, recipe ingredients, or a top-up request:

1. Normalize the requested items into a concrete list.
2. Search each item with `grocery-shopping <retailer> search <query> --limit 3` or `--limit 5`.
3. Build a compact review covering:
   - high-confidence matches that can be auto-added
   - ambiguous items that need a choice
   - unresolved items with no credible result
4. Only after the review, call `add-to-basket` for the selected items.
5. End with `basket-show` and a short exceptions summary.

Treat an item as ambiguous, not high-confidence, when the user specified a brand, size, quantity, dietary property, or product type that the top result does not clearly match.

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

Batch review pattern:

```bash
grocery-shopping ocado search milk --limit 5
grocery-shopping ocado search bananas --limit 5
grocery-shopping ocado search pasta --limit 5
grocery-shopping ocado add-to-basket milk --product "Ocado British Semi Skimmed Milk 4 Pints"
grocery-shopping ocado add-to-basket bananas --product "Ocado Rainforest Alliance Bananas"
grocery-shopping ocado basket-show
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
- Serialize repeated Ocado browser actions against one session. Parallel search/add commands can race the page state and make snapshots unreliable.
- If a command that used to work starts failing, switch to the self-healing skill instead of guessing selectors.
- Prefer the workflow skills for richer jobs:
  - `skills/add-shopping-list/SKILL.md`
  - `skills/add-regulars/SKILL.md`
  - `skills/add-recipe/SKILL.md`
  - `skills/look-up-and-add-recipe/SKILL.md`
