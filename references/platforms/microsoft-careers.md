
## Session Notes (2026-02-28, Job 104 - Principal Software Engineer)

### Authentication
- Platform: apply.careers.microsoft.com (eightfold.ai ATS)
- LinkedIn OAuth opens in a separate popup window that doesn't share browser cookies - LinkedIn SSO fails even if LinkedIn is signed in on another tab
- **Use Google SSO** - if Google is signed in in the browser session, it shows account chooser and auto-approves after consent
- Google account used: haomin.liu@gmail.com

### Profile Setup
- New accounts: must complete "Country/region of residence" + communication preferences modal first
- Then: "Create your profile" dialog - upload resume or manual entry
- Resume upload: copy file to /tmp/openclaw/uploads/, make input[type=file] visible with JS, then use browser upload action after clicking "Choose File" button

### Form Interaction
- Custom React combobox components - NOT native selects
- Opening a combobox: click it, then use `document.querySelector('[role="listbox"]')` to get options
- Selecting an option: `document.getElementById('<option-id>').click()` or find by `.title` attribute
- **Do NOT type into comboboxes** - typing doesn't filter to matching options, it just sets the input value
- Radio buttons: must click via Playwright ref (not JS `input.checked = true + dispatchEvent`)
- Refs expire per snapshot - always re-snapshot before acting

### File Upload Flow
1. `cp resume.pdf /tmp/openclaw/uploads/resume_104.pdf`
2. Make file input visible: `document.querySelector('input[type="file"]').style.display = 'block'`
3. Click "Choose File" button ref to trigger file chooser
4. Use `browser upload action` with selector `input[type="file"]`

### Application Structure (8 sections)
1. Application location(s) - pre-set from job posting
2. Resume - upload from prior step carries over
3. Contact Information - parsed from resume, verify/fill address/state/city/zip
4. Work Authorization - US: authorized? / sponsorship?
5. Self-identification - ethnicity, gender, armed forces, veteran, disability (all voluntary)
6. Candidate questions - military/govt, NDA, prior MS experience, MS subsidiary
7. Job specific questions - role-specific Yes/No qualifications (radio buttons)
8. Acknowledgment - 3 checkboxes (qualifications, DPN, code of conduct)

### Session Notes (2026-03-01, Job 86)
- On /careers/apply?pid=<id> auth wall, provider buttons are rendered but do not expose easy-clickable DOM targets in snapshot (`e5`-`e8` style modal buttons in this run did not trigger and `querySelector('button')` inspection only found close/consent controls).
- DOM appears to use anti-bot behavior/reCAPTCHA-influenced auth modal; automated click/evaluate attempts fail to launch provider OAuth.
- Recommend fallback rule: if auth modal is non-interactive and no direct fields load, mark as blocked rather than repeatedly retrying.


### Session Notes (2026-03-01, Job 133 - Principal Software Engineer)
- From LinkedIn `/careers/job/<id>` path, `/careers/apply?pid=...` and `/en-us/careers/apply?...` redirects did not render a usable application form (anti-bot/JS handshake likely blocked).
- Auth stage landed on LinkedIn checkpoint with prefilled `Email or Phone` and explicit password form at `mscareers.b2clogin.com` style page; interactive login automation failed without pre-existing keychain credential.
- New insight: if keychain has no `jobhunt:linkedin.com` for hotmail/gmail account, this path should be marked blocked immediately to avoid repeated retries on modal redirects.


### Session Notes (2026-03-02, Job 123 - Principal Software Engineer Web App Architect)
- Google SSO button click DID successfully open Google account chooser (as a new Playwright tab, not popup)
- Account chooser interaction: standard ref clicks fail; must use `evaluate(() => document.querySelector('[jsname]')?.click())` to advance from account list → consent page
- Consent page ("You're signing back in to eightfold.ai"): Continue button can be clicked via ref
- CRITICAL FINDING: OAuth callback is permanently broken in Playwright multi-tab context
  - window.open() for OAuth creates a tab instead of a popup window
  - Tab loses window.opener reference
  - eightfold.ai callback (window.opener.postMessage or window.opener.location) fails silently
  - Parent page auth modal never updates regardless of OAuth completion on Google side
- LinkedIn SSO: button click did not open any popup or tab (blocked silently)
- CONCLUSION: All provider OAuth flows on apply.careers.microsoft.com are structurally blocked in Playwright
- WORKAROUND OPTIONS:
  1. Pre-authenticate: sign in manually once with human interaction, then use that persistent cookie session
  2. Playwright waitForPopup(): intercept the popup before it loses opener reference
  3. Inject session cookie from a pre-authenticated eightfold.ai session directly
