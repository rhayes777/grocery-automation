---
name: add-regulars
description: Use when the user wants to rebuild a regular weekly basket from favourites or regular-item suggestions before adding them to Ocado or Sainsbury's.
---

# Add Regulars

Use this skill when the user wants a regular weekly shop, staples refill, or a usual basket.

## Defaults

- Default retailer: Ocado
- Start from regular-item suggestions, not immediate basket mutation
- Present the proposed regular set before adding anything
- Let the user remove, tweak, or extend the regular set
- Finish with `basket-show`

## Workflow

Start with regular-item suggestions:

```bash
weekly-shop regular-items --retailer ocado
weekly-shop regular-items --retailer sainsburys
```

Then treat the chosen regular items like a batch shopping list:

1. confirm the regular set
2. search the concrete products
3. review ambiguous items
4. add the selected products
5. summarize the final basket and any skipped items

Use `grocery-shopping <retailer> search`, `add-to-basket`, and `basket-show` for the execution steps.
