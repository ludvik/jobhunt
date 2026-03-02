# GE HealthCare Careers Platform Notes

## Session Notes (2026-03-01, Job 101 - Sr Staff Software Engineer)

- The page flow is accessed via LinkedIn redirect to `careers.gehealthcare.com/global/en/apply?...&step=...`.
- In multiple steps, `Next` buttons are not reliably clickable through snapshot refs (multiple anonymous buttons). DOM-driven `requestSubmit()` on `<form>` or direct button query by text was more reliable.
- Step 4 voluntary disclosures and Step 5 self-identification allowed submission only after all visible required selects/inputs were populated.
- **Important UI gotcha:** On Review step (`step=6`), the `Submit` button may appear enabled in UI but is effectively disabled; proceeding via the review `Next` action moved to `applythankyou` confirmation URL.
- There can be an active cookie notice dialog (`_evidon-*` IDs). It should be safe to ignore if not blocking targeted form elements, but it can steal ref-based click actions.

## Apply Patterns
- Save resume to `/tmp/openclaw/uploads/<name>.pdf` and use the browser `upload` action after triggering the file chooser.
- If a required field has many options (e.g., `ethnicity`, `genderus`), setting by `selectedIndex` worked when direct value assignment failed due exact-value mismatch.
