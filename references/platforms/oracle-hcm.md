# Oracle HCM / Taleo ATS

## URL Patterns
- Taleo: `<company>.taleo.net/careersection/<section>/jobdetail.ftl?job=<id>`
- Oracle HCM Cloud: `<company>.fa.us2.oraclecloud.com` / `eeho.fa.us2.oraclecloud.com`

## Auth
- OTP-only flow: enter email → receive 6-digit code → code expires in 10 minutes
- Session expires after ~30 min inactivity; draft data persists server-side
- After re-auth, navigate to `/apply/section/2` and click Next to restore draft

## Framework: Knockout.js
- KO (not React/Vue): observable data model
- To access ViewModel: `el.__ko__<key>[innerKey].context.$data`
- Gender dropdown options: `document.getElementById('US-STANDARD-ORA_GENDER-STANDARD-11-listbox').querySelectorAll('[role=gridcell]')`

## Resume Upload (CRITICAL)
- Playwright `setInputFiles()` via CDP does NOT trigger KO's change handler
- CSP blocks fetch from localhost
- **Workaround**: If candidate has prior application, an existing resume appears with a "Use" link — clicking "Use" attaches without file chooser
- **DO NOT remove existing resume** before confirming new upload works — removing eliminates the "Use" fallback
- Resume field is REQUIRED — cannot submit without it

## Dropdown Pattern (Step 3)
Gender dropdown doesn't appear via `[role=listbox]` (finds chatbot instead):
```js
// Find label → input id → open → click gridcell
var labelFor = document.querySelector('label[for*=GENDER]').getAttribute('for');
var input = document.getElementById(labelFor);
input.click(); // open dropdown
// Wait, then:
document.getElementById(labelFor + '-listbox').querySelectorAll('[role=gridcell]')[N].click();
// Options: Female(0), Male(1), Nonbinary(2), Do not wish to disclose(3)
```

## Month/Year Dropdown Pattern
Oracle HCM uses grid-based pickers (not native `<select>`):
1. Click "Open drop-down" button → wait for gridcell
2. Click gridcell by text label
- Year grid starts at 2076 and goes DOWN — must scroll to reach older years

## Application Questions
- "Are you an ex-Oracle employee?" → No
- "Government contractor?" → No
- "Authorized to work?" → Yes

## Step Navigation
- Section 1: personal info
- Section 2: experience, education, skills, documents
- Section 3: extra info, questions, diversity, disability, e-signature + Submit

## Data Persistence
- Experience, education, skills: auto-saved server-side per API call
- Step 3 fields: saved when "Next" clicked
- Gender field: NOT pre-populated from draft — must re-select each session

## hCaptcha (JPMC)
JPMC Oracle HCM shows hCaptcha visual challenge on new account creation (after email + terms + Next). Cross-origin iframe — cannot automate. Mark `apply_failed`; human must create account first.

## Company-Specific
- JPMC: `jpmc.fa.oraclecloud.com`, redirects via contacthr.com
