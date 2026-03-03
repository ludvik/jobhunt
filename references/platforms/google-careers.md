# Google Careers (careers.google.com)

## Overview
Proprietary platform. LinkedIn "Apply on company website" redirects here. Google account login required (Google SSO).

## Application Flow (4 steps)
1. Careers Profile — name, resume, education, work experience (pre-filled from Google account)
2. Role Information — preferred location, min qualifications (Yes/No/Not sure), work authorization
3. Voluntary Self-Identification — gender, race/ethnicity, veteran, disability (all optional, pre-filled)
4. Review & Apply — consent checkbox + Apply button

## Default Self-ID Values for Haomin
- Gender, Race, Veteran: "I choose not to disclose"
- Disability: "I do not want to answer"

## Work Authorization
- Legally eligible: Yes
- Needs sponsorship: No

## Consent Checkbox Workaround
The consent checkbox on the Review page has an extremely long accessible name — `getByRole` times out.
```js
document.querySelector('input[type=checkbox]').click()
```

## Tab Focus Issue
When a Playwright act call times out, browser focus can switch to another open tab. After timeout error, call `browser focus(targetId=...)` explicitly. If targetId is lost, navigate to Google Careers URL on a fresh tab.

## Application Limit
**Hard limit: 3 applications per 30-day rolling window.** When reached, clicking Apply shows: "You can't submit an application at this time. You've reached the limit of 3 applications in a 30 day window." Set status = `blocked`, note the retry date.

## General Tips
- Career profile is reused across applications
- Application saves as draft automatically
- Refs expire after DOM changes (dropdown open/close) — take snapshot and act immediately
