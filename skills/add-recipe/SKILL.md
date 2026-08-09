---
name: add-recipe
description: Use when the user provides a recipe as text or image and wants the ingredient list converted into a reviewed grocery basket.
---

# Add Recipe

Use this skill when the user supplies recipe text, a screenshot, or a photo of ingredients and wants those ingredients added to a grocery basket.

## Defaults

- Default retailer: Ocado
- If the recipe is an image, extract ingredients first and show the interpreted list
- Convert ingredients into shoppable grocery items before searching
- Search several ingredients first, then review choices
- Auto-add only high-confidence matches
- Finish with `basket-show` and a summary of substitutions, skips, and unresolved items

## Workflow

1. Extract ingredients from the provided recipe.
2. Convert them into concise shopping queries.
3. Remove obvious duplicates only when they are clearly duplicates in the recipe.
4. Search ingredient queries in batch:

```bash
grocery-shopping <retailer> search "<ingredient>" --limit 3
```

5. Present a review:
   - planned adds
   - ambiguous ingredients needing a product choice
   - unresolved ingredients
6. Add selected products with `add-to-basket`.
7. End with `basket-show`.

## Notes

- Do not assume pantry staples are already available unless the user says so.
- Keep ingredient intent intact. For example, do not silently switch chopped tomatoes to fresh tomatoes or parmesan to generic hard cheese.
