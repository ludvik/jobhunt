# Microsoft Careers (apply.careers.microsoft.com)

## Overview
eightfold.ai ATS. LinkedIn redirects here.

## Auth
- **Google SSO only** (LinkedIn SSO fails even when signed in on another tab — popup window doesn't share cookies)
- Google account: `haomin.liu@gmail.com`
- New accounts: complete "Country/region of residence" + communication preferences modal first

## OAuth Known Issue (CRITICAL)
All provider OAuth flows are structurally broken in Playwright multi-tab context:
- `window.open()` for OAuth creates a tab instead of a popup
- Tab loses `window.opener` reference
- eightfold.ai OAuth callback (`window.opener.postMessage`) fails silently — auth modal never updates
- **Workaround options**: Pre-authenticate manually once (persistent cookie), or inject session cookie from a pre-authenticated eightfold.ai session

## React Combobox Pattern
Custom React combobox components — NOT native selects.
- Open combobox: click it, then use `document.querySelector('[role="listbox"]')` to get options
- Select option: `document.getElementById('<option-id>').click()` or find by `.title` attribute
- Do NOT type into comboboxes — typing sets input value but doesn't filter/select options
- Radio buttons: must click via Playwright ref (not JS `input.checked = true + dispatchEvent`)
- Refs expire per snapshot — always re-snapshot before acting

## File Upload Flow
1. `cp resume.pdf /tmp/openclaw/uploads/resume_<id>.pdf`
2. Make file input visible: `document.querySelector('input[type="file"]').style.display = 'block'`
3. Click "Choose File" button ref to trigger file chooser
4. Use `browser upload action` with selector `input[type="file"]`

## Application Structure (8 sections)
1. Application location(s) — pre-set from job posting
2. Resume — upload from prior step
3. Contact Information — parsed from resume; verify address/state/city/zip
4. Work Authorization — US authorized? / sponsorship?
5. Self-identification — ethnicity, gender, armed forces, veteran, disability (all voluntary)
6. Candidate questions — military/govt, NDA, prior MS experience, MS subsidiary
7. Job specific questions — role-specific Yes/No qualifications (radio buttons)
8. Acknowledgment — 3 checkboxes (qualifications, DPN, code of conduct)

## Known Issues
- If auth modal is non-interactive (anti-bot/reCAPTCHA-influenced), mark `blocked` immediately — do not retry
- If keychain has no `jobhunt:linkedin.com` credential, LinkedIn auth path should be marked blocked immediately
