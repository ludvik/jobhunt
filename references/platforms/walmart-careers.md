# Walmart Careers (careers.walmart.com)

## Overview
14-step application flow. Linked from LinkedIn via appcast.io redirect (opens new tab — check tabs after clicking Apply).

## Auth
- Email OTP (no password). OTP sent on each session.
- OTP form: 6 individual input boxes — must type each digit separately; auto-submits on 6th digit
- OTP digit entry: `type` only fills first box — use separate type calls per digit (ref=e9 for digit 1, e10 for digit 2, etc.)

## Application Flow (14 steps)
1. Contact details (email + T&C)
2. Email OTP verification
3. **"Start your application"**: Upload resume | Use my last application | Apply manually
4. Personal info
5. Home address
6. Employment history (with education, languages, website)
7. Voluntary disclosure (work auth, sponsorship)
8. EEO (ethnicity, gender — optional)
9–10. Military service
11. Terms and conditions
12–13. Review your application
14. Submit → Confirmation

## "Use my last application" — USE THIS
Pre-fills ALL personal data from previous session. Always choose if applicant has applied before.

## Radio Buttons
Direct aria ref clicks FAIL. Use evaluate:
```js
// Get IDs: document.querySelectorAll('input[type="radio"]').map(r => ({id: r.id, label: r.labels[0].textContent}))
document.getElementById('<hashedId>').click()
```

## React Dropdown (select elements in dialogs)
`kind: "select"` fails. Native value setter doesn't update React state.
**Working solution**:
```js
element.selectedIndex = N;
element.dispatchEvent(new Event('change', {bubbles: true}));
```
Determine option indices first: `Array.from(el.options).map(o=>o.text)`

## Work Experience Dialog — Submit Button
Regular ref click unreliable. Use JS:
```js
document.querySelectorAll('[role=dialog] button').find(b => b.textContent === 'Continue').click()
```

## Date Entry in Work Experience Dialog
- Format: `mm/yyyy` (e.g., `09/2020`)
- After typing, calendar picker opens — click the first day of the month to confirm

## Education Section
- Initially empty even with resume upload — must add manually via "Add education" dialog
- Dialog: School (text), Degree (select index), Field of study (select index), GPA (optional), Start date, End date
- Date inputs use `mm/dd/yyyy`; use native input setter for React hydration
- Continue button: `dialog.querySelectorAll('button')[4].click()` (5th button)

## Resume Upload
- Upload does work: `browser upload` + click "Upload resume" button
- Resume parses correctly; verify address (may extract "City, State" as address line 1 — fix it)
- Website URL fields may be pre-filled with non-URL placeholder text — always verify and correct

## Application Recovery
If previous agent attempt timed out but already submitted: check all browser tabs for "JobSubmitted" title at `careers.walmart.com/us/en/jobs/submitted?applicationGroupId=...`. If found, snapshot to confirm "Application Submitted!" heading and mark `applied` without re-applying.

## Confirmation
Page title: "Application Submitted!" with job title and location. Alert role: `JobSubmitted`. A "Thank you for Applying!" email is sent.
