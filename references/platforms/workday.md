# Workday ATS

## URL Patterns
- Job listings: `<company>.wd<N>.myworkdayjobs.com/en-US/<path>/job/<title>/<id>`
- Apply: same path + `/apply`

## Auth
- Account per company (email/password)
- Keychain: `jobhunt:<company>.wd<N>.myworkdayjobs.com`
- If account exists with unknown password: use "Forgot Password" first; reset email comes from `myworkday.com` domain
- New accounts may require email verification before login works — check email for verification link

## Application Flow (6 steps — Apply Manually path)
1. My Information (contact details)
2. My Experience (work history, education, resume upload)
3. Application Questions (custom per-job)
4. Voluntary Disclosures (EEO)
5. Self Identify (CC-305 disability form)
6. Review + Submit

## Date Fields — Calendar Button (CRITICAL)
Workday date spinbuttons have near-zero pixel dimensions and behave unpredictably with keyboard input — digits can "leak" between adjacent fields.
**Always use the Calendar button** adjacent to the date field. Click highlighted date (today's date) or navigate with "Next month"/"Previous month".
- `[data-automation-id="nextMonth"]` selector may not exist — use button ref from snapshot
- For large date jumps, use evaluate() with JS `button.click()` in loop with setTimeout delays

## Resume Upload
- "Autofill with Resume" option: arms file chooser — upload BEFORE clicking OR arm first then click
- Upload is in Step 2 (My Experience), below work history and education fields

## React Combobox / Dropdowns
- Custom React combobox — NOT native selects
- "How Did You Hear About Us?": 2-level nested category → sub-option. LinkedIn is under **"Job Board" → "Linkedin Jobs"** (NOT "Social Media")
- Typing in textbox while in sub-category view does not search globally — close and re-click to navigate back

## Field of Study Typeahead
Requires selecting from dropdown; typing does not auto-commit. If dropdown doesn't appear, field can be left blank (not required).

## Session Persistence
Workday server-saves form data per step. If tab closes mid-application, log back in, navigate back to apply URL — completed steps are restored. Exception: Self Identify disability form date must be re-entered.

## CC-305 Disability Form Date
Spinbutton JS assignment does NOT work. Use Calendar button — Workday pre-selects today's date as highlighted, just click it.

## Post-Submit Account Creation
After successful submission, Workday shows "Congratulations!" dialog with account creation form. Create password and save to keychain:
```
security add-generic-password -a "<email>" -s "jobhunt:<company>.wd<N>.myworkdayjobs.com" -w "<password>" -U
```

## Company-Specific Notes
- **Blue Origin** (`blueorigin.wd5`): Requires U.S. citizen/national/permanent resident/refugee/asylum. After account creation, login fails until email is verified — mark `blocked` with "Needs email verification" note.
- **Salesforce** (`salesforce.wd12`): 10 government/ethics screening questions. EEO: "I prefer not to disclose" for all fields.
- **NVIDIA** (`nvidia.wd5`): Account may exist from prior run — try "Forgot Password" first.
- **Phenom → Workday redirect** (e.g. WBD): Phenom "Apply Now" opens new tab with Workday URL.
