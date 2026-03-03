# GE HealthCare Careers (careers.gehealthcare.com)

## Overview
Multi-step form accessed via LinkedIn redirect to `careers.gehealthcare.com/global/en/apply?...&step=...`.

## Form Navigation
- `Next` buttons are not reliably clickable via snapshot refs (multiple anonymous buttons)
- Use DOM-driven `requestSubmit()` on `<form>` or direct button query by text: `document.querySelector('button[type=submit]').click()`
- Review step (step=6): Submit button may appear enabled but is effectively disabled — clicking Next on review navigates to `applythankyou` confirmation URL

## Dropdowns with Many Options
- For fields like `ethnicity` or `genderus`, setting by `selectedIndex` works when direct value assignment fails due to exact-value mismatch

## Resume Upload
- Save resume to `/tmp/openclaw/uploads/<name>.pdf`
- Use browser `upload` action after triggering the file chooser

## Known Issues
- Cookie notice dialog (`_evidon-*` IDs) may appear; safe to ignore if not blocking form elements, but can intercept ref-based clicks
- Steps 4-5 (voluntary disclosures, self-identification) require all visible required selects/inputs to be populated before submission
