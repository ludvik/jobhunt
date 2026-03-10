# Amazon Jobs (amazon.jobs)

## Overview
Dedicated ATS at amazon.jobs. LinkedIn redirects here.

## Auth
- URL: `https://passport.amazon.jobs/`
- Email/password preferred (fastest, no OAuth redirect chain)
- Account: `haomin.liu@gmail.com` / `HaominLiu@2026!`
- Keychain: `jobhunt:passport.amazon.jobs`
- MFA: skip when prompted

## Application Flow
URL: `https://www.amazon.jobs/en-US/applicant/jobs/{JOB_ID}/apply`
1. SMS notifications → "Skip & continue"
2. Job-specific questions → Select2 comboboxes (JS required)
3. Work eligibility → radio buttons (JS required)
4. Review & Resume → replace with tailored PDF
5. Submit → confirm "Next steps of your application" heading

## Select2 Combobox Workaround
Standard ref clicks FAIL on Select2. Use evaluate():
```js
(function(){
  var s = document.querySelectorAll('select');
  s[0].value = '1';  // '1'=Yes, '2'=No
  s[0].dispatchEvent(new Event('change', {bubbles: true}));
  return s[0].value;
})()
```
Selects appear in DOM order; 0-indexed.

## Work Eligibility Radio Buttons
Refs don't work; use evaluate():
```js
(function(){
  var r = document.querySelectorAll('input[type=radio]');
  r[9].click();   // REQUIRE_SPONSORSHIP
  r[12].click();  // GOVERNMENT_EMPLOYEE
  return [r[9].checked, r[12].checked];
})()
```
- Immigration sponsorship is always blank — set explicitly every time
- Indices vary by profile state; verify by checking input names

## Resume Upload
Arm file chooser FIRST, then trigger via evaluate:
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
Wait 2-4s after upload before clicking Continue.

## Submit Button
May not respond to ref click; use evaluate():
```js
Array.from(document.querySelectorAll('button'))
  .filter(b => b.textContent.includes('Submit'))[0].click()
```
Confirmation: URL contains `result=success`, heading says "Next steps of your application"

## Known Issues
- LinkedIn OAuth needs LinkedIn password (not in keychain) — always use email/password
- Pre-filled data may be stale — verify before submitting
- Select2 dropdowns and radio buttons always require JS workarounds

## 10-Application Hard Limit
Amazon enforces a maximum of 10 concurrent active applications per account. The block can surface in two ways:
1. **Immediately on navigate** to `/applicant/jobs/{id}/apply` — heading "You've reached the maximum number of job applications." with no form shown.
2. **After filling the full form** — error appears after clicking "Submit application" on the Review page.

In both cases: mark status as `blocked`, note "Amazon 10-app limit — withdraw an existing application at https://www.amazon.jobs/applicant/dashboard then re-run the pipeline for this job."
