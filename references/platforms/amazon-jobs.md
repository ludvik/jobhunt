# Amazon Jobs Platform Reference (amazon.jobs)

## Overview
Amazon uses a dedicated ATS at amazon.jobs. LinkedIn "Apply on company website" redirects here.

## Authentication
- Login: `https://passport.amazon.jobs/` (redirects to idp.federate.amazon.com)
- Supports email/password, OAuth (Amazon, Google, Apple, LinkedIn)
- MFA optional (click "Skip for now")
- Account email: `haomin.liu@gmail.com` / `HaominLiu@2026!`
- Keychain: `jobhunt:passport.amazon.jobs`
- **Prefer email/password** (fastest, no OAuth redirect chains)

## Application Flow
URL: `https://www.amazon.jobs/en-US/applicant/jobs/{JOB_ID}/apply`

### Steps
1. **SMS Notifications** (optional) — Click "Skip & continue"
2. **Job-specific questions** — Select2 combobox dropdowns (Yes/No)
3. **Work Eligibility** — Radio buttons (mostly pre-filled from prior applications)
4. **Review & Resume** — Upload tailored PDF, verify all sections
5. **Submit Application** — Click submit button
6. **Confirmation** — "Thank you for applying" heading + job title/ID

## Select2 Combobox Workaround
Standard ref-based click FAILS on Select2 dropdowns. Use evaluate():
```js
(function(){
  var s = document.querySelectorAll('select');
  s[0].value = '1';  // '1'=Yes, '2'=No
  s[0].dispatchEvent(new Event('change', {bubbles: true}));
  return s[0].value;
})()
```
- Selects appear in DOM order matching question order (0-indexed)
- No snapshots needed between selections

## Work Eligibility Radio Buttons
Radio buttons not accessible via snapshot refs. Use evaluate():
```js
(function(){
  var r = document.querySelectorAll('input[type=radio]');
  r[9].click();   // REQUIRE_SPONSORSHIP
  r[12].click();  // GOVERNMENT_EMPLOYEE
  return [r[9].checked, r[12].checked];
})()
```
- Most fields pre-populated from prior applications — verify before continuing
- Immigration sponsorship is always blank — must set explicitly each time
- Radio indices vary by profile state; check names: REQUIRE_SPONSORSHIP, GEF_EXT_USA_GOVERNMENT_EMPLOYEE

## Resume Upload
- Review page has "Replace Resume" button (prior upload persists)
- Always replace with tailored PDF for each application
- Arm file chooser FIRST with `browser(action="upload")`, then click:
```js
(function(){
  var links = document.querySelectorAll('a');
  for (var i = 0; i < links.length; i++) {
    if (links[i].textContent.indexOf('Browse device') > -1) {
      links[i].click(); return 'clicked';
    }
  }
  return 'not found';
})()
```

## Submit Button
May not respond to normal ref click. Use evaluate():
```js
Array.from(document.querySelectorAll('button'))
  .filter(b => b.textContent.includes('Submit'))[0].click()
```
- Confirmation: URL contains `result=success`, heading says "Next steps of your application"

## Known Issues
1. LinkedIn OAuth requires LinkedIn password (not in keychain) — use email/password instead
2. Pre-filled data may be stale from prior applications — always verify
3. Resume upload takes 2-4 seconds — wait before clicking Continue
4. Select2 and radio buttons require JS workarounds (refs don't work)

## Session Log
- Job 322 (2026-03-02): Applied successfully. Select2 JS workaround was key.
- Job 374 (2026-03-02): Applied successfully. Full flow ~10 minutes.
- Job 441 (2026-03-03): Blocked — browser timeout on combobox interactions.
- Job 443 (2026-03-03): Failed — file upload tab routing issue with multiple tabs open.
- Job 445 (2026-03-03): Applied successfully.
