---
name: weekly-shop
description: Use when the user wants a weekly grocery workflow that combines slot suggestions, regular-item discovery, and checkout opening.
---

# Weekly Shop

Use this skill when the user wants an end-to-end weekly-shop assistant layered on top of the public grocery CLI.

The workflow stays agent-driven. The CLI is a tool layer, not a rigid wizard.

## Defaults

- Default retailer: Ocado
- Default calendar: `Primary`, unless `WEEKLY_SHOP_CALENDAR` overrides it
- Suggest slots before booking
- Suggest regular items before adding them
- Do not book or add until the user confirms

## Slot workflow

Suggest delivery slots:

```bash
weekly-shop slot-suggest
weekly-shop slot-suggest --retailer sainsburys
weekly-shop slot-suggest --retailer sainsburys --no-calendar
```

If calendar integration is available, use it. If not, either set `WEEKLY_SHOP_GCALCLI` or use `--no-calendar`.

After the user confirms a slot, book it with the main CLI:

```bash
grocery-shopping ocado slot-book <slot_id> --confirm
grocery-shopping sainsburys slot-book <slot_id> --confirm
```

## Basket workflow

Start with regular items:

```bash
weekly-shop regular-items
weekly-shop regular-items --retailer sainsburys
```

Then search and add concrete products with `grocery-shopping` after the user confirms.

## Finish

Open the checkout flow in the default browser:

```bash
weekly-shop open-checkout
weekly-shop open-checkout --retailer sainsburys
```
