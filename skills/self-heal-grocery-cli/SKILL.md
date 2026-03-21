---
name: self-heal-grocery-cli
description: Use when an Ocado or Sainsbury's grocery flow breaks and the CLI needs to be repaired against the live site.
---

# Self-Heal Grocery CLI

Use this skill when a previously working grocery command starts failing because the retailer site changed.

## Diagnostic order

1. Reproduce the exact user-facing command.
2. Determine whether the failure is:
   - login/session state
   - blocked navigation or anti-bot behavior
   - stale page URL
   - stale selector or parser
   - wrapper/process issue around Playwright output
3. Re-run the flow in a headed browser and snapshot the live DOM.
4. Confirm the real page URL before editing any parser or selector.

## Repair rules

- Prefer minimal fixes that match the live site.
- Update route discovery before tweaking selectors if the command is landing on the wrong page.
- Use stable ARIA labels and visible semantics where available.
- If a site now uses a modal or confirmation page, encode that real flow instead of inferring success from old page state.
- Re-test the exact same CLI command after each fix.

## Validation checklist

For the affected retailer, re-run as applicable:

```bash
grocery-shopping <retailer> session-status
grocery-shopping <retailer> search <query>
grocery-shopping <retailer> basket-show
grocery-shopping <retailer> checkout-state
grocery-shopping <retailer> slots
grocery-shopping <retailer> slot-book <slot_id> --confirm
```

If the fix only raises confidence for some flows, update the README support table accordingly rather than silently overstating support.
