# LinkedIn Job Posting Patterns

## Closed Listings
If page shows "No longer accepting applications" — set status `blocked` immediately. No active Apply CTA will be in the DOM. One best-effort check for explicit external form link is sufficient; no repeated retries.

## Shadow DOM Radio Buttons
LinkedIn Easy Apply renders radio button groups inside **shadow DOM**. Standard ref clicks fail with "not found or not visible."

```js
// Collect all shadow DOM radios and click by index
(() => {
  var all = document.querySelectorAll('*');
  var allRadios = [];
  for (var i = 0; i < all.length; i++) {
    var el = all[i];
    if (el.shadowRoot) {
      var radios = el.shadowRoot.querySelectorAll('input[type=radio]');
      for (var j = 0; j < radios.length; j++) allRadios.push(radios[j]);
    }
  }
  // Example: 3 questions x 2 options = 6 radios (0=Q1-Yes, 1=Q1-No, 2=Q2-Yes, ...)
  allRadios[1].click(); // Q1: No
  allRadios[2].click(); // Q2: Yes
  allRadios[4].click(); // Q3: Yes
  return 'clicked';
})()
```
Note: `const` is not allowed in evaluate fn — use `var`.

## Greenhouse via LinkedIn Redirect
- "Apply on company website" links to `https://job-boards.greenhouse.io/<company>/jobs/<id>` via lnkd.in redirect
- Navigate directly to the Greenhouse URL — avoids redirect issues
- All Greenhouse dropdowns are react-select components; see greenhouse.md for full patterns

## Resume Upload — Greenhouse via LinkedIn
- Arm upload FIRST (`browser action=upload`), then click the Attach button via evaluate (not ref — ref click timeout can preempt file chooser arming)
- After upload, take snapshot to confirm filename appears in correct slot
- If resume lands in wrong slot: click "Remove file", re-arm upload, click the correct Attach
