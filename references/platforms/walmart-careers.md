# Walmart Careers Platform (careers.walmart.com)

## Overview
- External career site for Walmart/Sam's Club jobs
- Linked from LinkedIn as "Apply on company website" via appcast.io redirect
- 14-step application flow with progress bar
- Supports saving progress and resuming via "Candidate Home" account

## Authentication
- Email-only authentication (no password required)
- OTP sent to email on each session
- Email input is on a "contact details" page before the apply form

## Application Flow (14 steps)
1. Contact details (email + T&C checkbox)
2. Email OTP verification
3. "Start your application" page: Upload resume | Use my last application | Apply manually
4. Tell us about yourself (personal info)
5. Home address
6. Employment history (with education, languages, website)
7. Voluntary disclosure (work auth, sponsorship, etc.)
8. EEO (ethnicity, gender - both optional/prefer not to say)
9. [Skipped steps - likely background]
10. Military service
11. Terms and conditions
12. Review your application
13. Submit → Confirmation page

## Key Tricks

### "Use my last application" is GOLD
- Pre-fills ALL personal data from previous application session
- Saves HouseWhisper/Gaida work entries if previously entered
- Always choose this if applicant has applied to any Walmart job before

### Date Entry in Work Experience Dialog
- Date comboboxes accept `mm/yyyy` format (e.g., `09/2020`)
- After typing, the calendar picker shows as "expanded"
- Must click on the first day of the month in the calendar popup to confirm and clear `aria-invalid`
- Start date calendar: just typing is enough (it validates)
- End date: need to click calendar button + select a day

### Work Experience Dialog - Submit
- The "Continue" button in the dialog must be triggered via JS: `document.querySelectorAll('[role=dialog] button').find(b => b.textContent === 'Continue').click()`
- Regular ref-based click sometimes doesn't work; JS scrollIntoView + click is reliable

### Resume PDF Upload - KNOWN ISSUE
- Walmart uses a hidden `<input type=file>` inside a React component
- Playwright's `setInputFiles` returns `{ok:true}` but React state doesn't update
- The file count stays at 0 after upload attempt
- Workaround: skip PDF upload; proceed with manual form entry
- Application still submits successfully without PDF

## Confirmation
- Page title changes to show "Application Submitted!" with the job title and location
- Roles picked for you / "What's next?" section appears
- A "Thank you for Applying!" email is sent to the applicant's email

## Notes
- Progress can be saved (system says "you can return anytime by signing up or logging in")
- Assessments may be required after submission for some roles
- Bellevue WA address shown on confirmation page for tech roles


## Radio Button Clicking
- Direct aria ref clicks (`act` with ref=eXX) consistently fail with "not found or not visible"
- **Workaround**: Use `evaluate` with `getElementById(hashedId).click()`
- Get hashed IDs via: `document.querySelectorAll('input[type="radio"]').map(r => ({id: r.id, label: r.labels[0].textContent}))`
- Then click by: `document.getElementById('<hashedId>').click()`

## OTP Digit Entry
- OTP form uses 6 individual `<input>` boxes, one per digit
- `type` action only fills the first box then stops (doesn't auto-advance)
- Must type each digit into the correct box via separate type calls (ref=e9 for digit 1, e10 for digit 2, etc.)
- Auto-submits when 6th digit is entered

## Resume Upload (Session 2026-03-02)
- Upload did work: `browser upload` + clicking "Upload resume" button navigated forward
- Resume was parsed correctly, extracting 6 employment entries
- Address parsed incorrectly ("Seattle, WA" instead of "Redmond, WA") - always verify/correct on address step

## Additional Notes (2026-03-02)
- Job ID in URL: R-XXXXXXX format (e.g., R-2121005 for this role)
