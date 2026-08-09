---
name: look-up-and-add-recipe
description: Use when the user wants the assistant to find a recipe, extract ingredients, and build a reviewed grocery basket from it.
---

# Look Up And Add Recipe

Use this skill when the user wants recipe discovery plus grocery execution.

## Defaults

- Ask whether to use a user-provided recipe or to look one up when the source is not already clear
- Default retailer: Ocado
- After the recipe is chosen, extract ingredients and review the interpreted shopping list
- Search ingredients in batch before adding
- Auto-add only high-confidence matches
- Finish with `basket-show` and an exceptions summary

## Workflow

1. Confirm the recipe source if needed:
   - use a recipe the user supplied
   - or search the web for a recipe that fits the request
2. Extract the ingredient list.
3. Show the interpreted shopping items.
4. Search each item with `grocery-shopping <retailer> search`.
5. Review candidate matches across the batch.
6. Add the chosen products with `add-to-basket`.
7. End with `basket-show`.

## Notes

- When looking up a recipe online, prefer ingredients that map cleanly to supermarket products.
- If the recipe choice materially changes the basket, confirm the selected recipe before adding.
