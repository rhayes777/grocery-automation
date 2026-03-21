---
name: extend-supermarket
description: Use when adding a new grocery retailer to the public grocery automation CLI.
---

# Extend Supermarket

Use this skill when adding a new retailer such as Tesco, Waitrose, or Morrisons.

## Principles

- Start with live headed-browser exploration.
- Do not assume legacy routes still work.
- Prefer stable ARIA labels, semantic roles, and visible headings over positional selectors.
- Keep retailer logic isolated from shared session and state helpers.
- Do not add speculative private HTTP APIs unless verified and clearly simpler than browser automation.

## Implementation sequence

1. Add the retailer descriptor:
   - base URL
   - session name
   - storage-state path
   - known page URLs for home, orders, checkout, favourites or equivalent
2. Get manual login working with saved storage state.
3. Implement and verify `session-status`.
4. Implement and verify `search`.
5. Implement and verify `add-to-basket` and `basket-show`.
6. Implement and verify `checkout-state`, `slots`, and guarded `slot-book`.
7. Implement `orders` and any favourites/saved-items equivalent only after the correct live route is confirmed.
8. Update README support tables and examples.
9. Add tests for retailer dispatch, slot normalization, and any parser-specific logic.

## Required output contract

Aim for parity with the existing retailer JSON shapes so higher-level automation needs minimal branching.

If a capability does not exist or is not stable enough yet:

- return a structured unsupported response
- document it honestly in the README

Do not fabricate parity.
