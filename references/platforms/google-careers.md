# Google Careers Platform Notes

**URL:** careers.google.com / google.com/about/careers/applications

## Overview

Google uses its own proprietary careers platform. LinkedIn "Apply on company website" links redirect here.

## Application Flow

4-step form:
1. **Careers Profile** - Name, resume, education, work experience (pre-filled from Google account)
2. **Role Information** - Preferred location, minimum qualifications (Yes/No/Not sure), work authorization
3. **Voluntary Self-Identification** - Gender, race/ethnicity, veteran status, disability (all optional)
4. **Review & Apply** - Review all info, check consent checkbox, click Apply

Steps 1 and 3 are often pre-filled/completed from prior applications.

## Key Behaviors

- Google account login required (uses Google SSO)
- Career profile is reused across applications (resume, contact info, skills, work history)
- 3 application limit per 30-day window
- Application saved as draft automatically

## Gotchas

### Consent Checkbox Click Fails via Playwright Ref
- The consent checkbox on the Review page has an extremely long accessible name
- getByRole('checkbox', { name: '...long text...' }) times out (8s default)
- **Workaround:** Use JavaScript evaluate: document.querySelector('input[type=checkbox]').click()

### Tab Focus Switches on Failed Clicks
- When a Playwright act call times out, browser focus can switch to another open tab
- Subsequent evaluate/navigate calls may target the wrong tab
- **Workaround:** After timeout error, call browser focus(targetId=...) explicitly
- If targetId is lost, navigate the Google Careers URL on a fresh tab

### Ref Expiry
- Playwright refs expire after DOM changes (dropdown open/close causes new snapshot needed)
- Take snapshot, immediately act on refs without delay

## Voluntary Self-ID defaults for Haomin
- Gender: I choose not to disclose
- Race: I choose not to disclose
- Veteran: I choose not to disclose
- Disability: I do not want to answer

## Work Authorization for Haomin
- Legally eligible: Yes
- Needs sponsorship: No
