# Ashby ATS (jobs.ashbyhq.com)

## Overview
Single-page application forms. No login required. Used by Snowflake, Ironclad, River, Cohere, and others.

## Form Filling
- Upload resume first; wait for parse to complete before filling text fields
- Resume upload may clear entered fields — always do a second pass to verify
- City of Residence is a combobox (type → pick from dropdown), not plain text
- Two upload areas: one for autofill (top), one for the actual required Resume field — upload to the second

## Radio Buttons (CRITICAL)
Ashby uses React-controlled radio inputs. Standard `element.click()` in `evaluate` does NOT trigger React's onChange — the radio appears checked in DOM but React state doesn't update, causing validation to reject the field as missing.
**Fix**: Click via `label[for="<id>"].click()` — this dispatches synthetic events that React's event delegation picks up.
```js
var rs = document.querySelectorAll('input[type=radio]');
var r = rs[0]; // target radio
var lbl = document.querySelector('label[for="' + r.id + '"]');
lbl.click(); // correct — triggers React onChange
```
Get radio IDs first: `rs[i].id` from a querySelectorAll pass.

## Yes/No Toggle Buttons
Toggle buttons for work auth / sponsorship / location questions do NOT reliably register on first click via automation. Always re-click immediately before submit (or after a validation error shows the field missing).

## React SPA Text Fields
DOM manipulation via `evaluate` (setting `.value` + dispatching `input`/`change`) fills fields visually but React internal state is NOT updated — validation fails on submit.
**Fix**: Use actual keyboard interaction: `kind: type` via ref — this properly triggers React state.

Note: After a failed submit, aria snapshots show text fields as empty even though DOM `.value` is set. Always verify via `input.value` in evaluate before re-filling, to avoid double-typing.

## Location Combobox
City-level search may select wrong country (e.g. "Redmond, WA" → "Wallis and Futuna" because "WA" matches). Use the full country name "United States" as a safe fallback for US-remote roles.

## File Upload Pattern
Arm `browser(action="upload")` BEFORE clicking "Upload File" button. If multiple tabs are open with prior upload arms, misfires can occur — open a fresh tab for each application to avoid this.

## reCAPTCHA Gate
Some companies (e.g. Snowflake) surface reCAPTCHA after submit. Check for "This site is protected by reCAPTCHA" after clicking submit. If present, mark `blocked` and escalate for manual completion.

## Confirmation
Status element text varies by company:
- River: "Your application was successfully submitted. We'll contact you if there are next steps."
- Cohere: "Your application has been submitted! Thank you for your interest..."

## Application Limits
Ashby enforces per-company limits: max 2 applications per 90 days, no re-apply within 180 days for same role.
