# LinkedIn Easy Apply

## Overview
LinkedIn Easy Apply opens a modal on the job detail page. Some content renders inside nested iframes.

## Known Issues
- Snapshot at page root shows `iframe [ref=eXXX]`; `refs: aria` ignores iframe content — use `refs: role` + `frame` targeting
- Modal can enter an unreachable state after extended DOM snapshots / repeated interaction attempts
- If modal becomes unreachable, do NOT retry inside the same run — treat as blocked and report

## Shadow DOM Radio Buttons
LinkedIn Easy Apply renders radio button groups inside **shadow DOM** on some question pages. Standard `kind:click` with a ref fails with "not found or not visible."

```js
// Click radio inside shadow DOM (index 0 = Yes, 1 = No)
const all = document.querySelectorAll('*');
for (const el of all) {
  if (el.shadowRoot) {
    const radios = el.shadowRoot.querySelectorAll('input[type=radio], [role=radio]');
    if (radios.length > 0) {
      radios[0].click(); // 0=Yes, 1=No
      break;
    }
  }
}
```
Use `kind: "evaluate"` with this fn. Affects "Additional Questions" step. Combobox dropdowns on same page work normally with `kind: "select"`.

## Greenhouse Redirect via LinkedIn
LinkedIn "Apply on company website" often redirects to Greenhouse ATS (`https://job-boards.greenhouse.io/<company>/jobs/<id>`). Navigate directly to the Greenhouse URL — faster, avoids redirect issues. See greenhouse.md for Greenhouse-specific patterns.

## Closed Listings
If job page shows "No longer accepting applications" — set status `blocked` immediately. One best-effort check for an explicit external form link is sufficient; no repeated retries.
