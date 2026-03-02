# Oracle HCM / Taleo ATS — Platform Knowledge

## URL Patterns
- Job listings: `<company>.taleo.net/careersection/<section>/jobdetail.ftl?job=<id>`
- Apply: `<company>.taleo.net/careersection/<section>/jobapply.ftl`

## Form Structure
- Account required (Oracle Taleo account)
- Profile builder: work history, education, skills
- Resume upload (optional but recommended)
- Step-by-step wizard similar to Workday

## Known Behaviors
- Session timeouts quickly — keep page active
- File upload size limit: 5MB
- PDF and DOCX supported
- May require answering screening questions before seeing application form

## Tips
- Oracle login can be reused across many employers using Taleo
- Check "Profile" vs "Application" — profile updates don't auto-apply
- Some forms use legacy HTML — snapshot may look cluttered

---

## Oracle HCM External (eeho.fa.us2.oraclecloud.com) — Updated 2026-03-01

### Authentication
- OTP-only flow (no password required): enter email → receive 6-digit code via email
- Code expires in 10 minutes; request new code if expired
- Session expires after ~30 min inactivity; all server-saved data persists as draft
- After re-auth, draft is fully restored — navigate to /apply/section/2 and click Next

### Framework
- Oracle HCM uses **Knockout.js** (not React/Vue): observable data model
- KO key on elements: `element.__ko__<timestamp>`
- KO ViewModel accessible via: `el.__ko__<key>[innerKey].context.$data`
- To find gender dropdown options: `document.getElementById('US-STANDARD-ORA_GENDER-STANDARD-11-listbox').querySelectorAll('[role=gridcell]')`

### Resume Upload Blocker (CRITICAL)
- Oracle HCM's resume upload (`resume-upload-button` custom element) uses KO ViewModel
- Playwright's `setInputFiles()` via CDP does NOT trigger KO's change handler
- CSP blocks fetch from localhost (cross-origin) 
- **Workaround**: If candidate has prior application on file, an existing resume appears with a "Use" link below the upload button. Clicking "Use" attaches it without file chooser.
- Text visible: "These files were uploaded to your profile by a recruiter. You can select to use one of them or to upload a new file."
- If no prior resume exists, must use native browser file chooser (cannot automate)
- **CRITICAL (learned 2026-03-01)**: Do NOT remove existing attached resume before confirming new upload works. Removing old attachment eliminates the "Use" fallback. Better strategy: keep old resume → attempt next section → if needed, submit with old resume (any resume beats no resume).
- The resume field is REQUIRED — application cannot submit without it.

### Dropdown Pattern (Step 3)
- Gender dropdown: doesn't appear via `[role=listbox]` selector (finds chatbot instead)
- Find by label: `document.querySelector('label[for*=GENDER]').getAttribute('for')` → get input id
- Open: click input element → wait → listbox appears as `<inputId>-listbox`
- Select option: `document.getElementById('<inputId>-listbox').querySelectorAll('[role=gridcell]')[N].click()`
- Options: Female(0), Male(1), Nonbinary(2), Do not wish to disclose(3)

### Step Navigation
- Section 1: personal info (/section/1 URL but loads at /apply/email after auth)
- Section 2: experience, education, skills, documents
- Section 3: extra info, application questions, diversity, disability, e-signature
- Submit is on section 3

### Data Persistence
- Experience entries, education, skills: auto-saved server-side per API call
- Step 3 fields (date, questions, diversity, e-sig): saved when "Next" is clicked
- Gender field: NOT pre-populated from draft; must re-select each session

### Month/Year Dropdown Pattern
- Oracle HCM dropdowns use grid-based pickers (not native `<select>`)
- Must: click "Open drop-down" button → wait for gridcell → click gridcell by text
- Year grid starts at 2076 and goes DOWN; must scroll to reach older years
- Month gridcells are in 3-col grid: click by text label

### Application Questions
- "Are you an ex-Oracle employee?" — select No (or Yes if applicable)
- "Government contractor?" — No
- "Authorized to work?" — Yes

## JPMC Oracle HCM — hCaptcha on Email Step [2026-03-02]

- JPMorgan Chase uses Oracle HCM at jpmc.fa.oraclecloud.com
- LinkedIn application redirects via contacthr.com to Oracle HCM
- On new account creation: after entering email + agreeing to terms + clicking Next, an hCaptcha visual challenge appears
- Challenge: "Please click on the two lines that are shorter" — image with wavy line strokes
- hCaptcha loads in a cross-origin iframe (newassets.hcaptcha.com) — CANNOT be solved by browser automation
- Status: apply_failed if no existing account; human must manually create account first
