---
name: add-shopping-list
description: Use when the user wants to turn a text or image shopping list into a reviewed grocery basket on Ocado or Sainsbury's.
---

# Add Shopping List

Use this skill when the user provides a shopping list directly, either as text or as an image.

The workflow is agent-driven and review-first. Do not add items one by one as soon as they appear.

## Defaults

- Default retailer: Ocado
- If the list is an image, extract the items first and show the interpreted list before searching
- Search several items before adding anything
- Auto-add only high-confidence matches
- Ask the user to resolve ambiguous items
- Finish with `basket-show` and a summary of unresolved or skipped items

## Workflow

1. Turn the input into a structured item list.
2. Normalize obvious duplicates and spelling variants.
3. Search each item:

```bash
grocery-shopping <retailer> search "<item>" --limit 3
```

4. Build a review covering:
   - exact or near-exact matches that can be auto-added
   - ambiguous matches that need a user choice
   - unresolved items with no credible result
5. Add the selected products:

```bash
grocery-shopping <retailer> add-to-basket "<query>" --product "<chosen product>"
```

6. Review the final basket:

```bash
grocery-shopping <retailer> basket-show
```

## Confidence Rules

- High-confidence: the result clearly matches the requested item and does not change brand, size, or product type in a meaningful way
- Ambiguous: multiple plausible matches, unclear pack size, brand mismatch, or weak search results
- Unresolved: no credible product found

If the user asked for a specific brand, quantity, pack size, or dietary property, keep that as part of the matching decision.
