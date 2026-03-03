# Workday ATS — Platform Knowledge

## URL Patterns
- Job listings: `<company>.wd<N>.myworkdayjobs.com/en-US/<path>/job/<title>/<id>`
- Apply URL: same path + `/apply`

## Form Structure
- Multi-step wizard (typically 5-7 steps)
- Step 1: Account creation / sign-in
- Step 2: Personal info (name, address, contact)
- Step 3: Work experience (dynamic add/remove)
- Step 4: Education
- Step 5: Resume / cover letter upload
- Step 6: Voluntary self-ID
- Step 7: Review + submit

## Known Behaviors
- JavaScript-heavy SPA — always wait for page to fully load between steps
- "Next" button may be disabled until all required fields filled
- Date fields: use MM/YYYY format
- Radio buttons for Yes/No questions are aria-labeled

## Tips
- Create account with work email to avoid spam
- Save to profile feature allows faster re-apply
- Error messages appear inline — check snapshot after each submit attempt

## New Insight (2026-02-28)
- Some Workday domains (example: `crowdstrike.wd5.myworkdayjobs.com`) launch a nested dialog overlay for Sign In/Create Account during external application flow. DOM can contain duplicate IDs (`input-4`, `input-5`) across base form and modal form, requiring field selection by dialog context.
- The create-account password validation may still show "Please enter your password" even when values are programmatically set, suggesting Workday auth can reject synthetic input events and require more human-like interaction.
- In this case, existing credentials from keychain for `jobhunt:myworkdaysite.com` were valid, but automated Sign In could not be progressed reliably past the auth modal.

---

## Lessons Learned (2026-03-01, NVIDIA application)

### Date Spinbutton Problem
- Workday date spinbuttons (`role=spinbutton`) have near-zero pixel dimensions (width ~0.09px) — they are visually hidden.
- `setNativeValue` + `dispatchEvent('input')` does NOT update React state; the error persists.
- **Solution: Always use the Calendar button** (`button "Calendar"`) adjacent to the date field. This opens a real calendar UI, selecting a date from it properly fires React synthetic events.

### "How Did You Hear About Us?" Nested Dropdown
- This field uses a 2-level nested category → sub-option structure.
- LinkedIn is NOT under "Social Media" — it is under **"Job Board" → "Linkedin Jobs"**.
- Typing in the textbox while in a sub-category view does not search globally.
- To navigate back from a sub-category, close and re-click the main combobox.

### Account Creation Flow
- NVIDIA Workday may already have an account from a prior run. Always try "Forgot Password" first.
- Password reset email comes from `myworkday.com` domain; check Gmail for it.
- After password reset, the redirect may go to the Sign In page (not directly back to the application).
- Credentials should be saved to keychain as `jobhunt:nvidia.wd5.myworkdayjobs.com`.

### Session Persistence
- If the browser tab closes mid-application, log back in and navigate back to the apply URL.
- Workday server-saves form data per step that was successfully saved; completed steps are restored.
- Steps NOT saved (e.g., Self Identify disability form date) must be re-entered.

### "Apply Manually" vs "Autofill with Resume"
- "Autofill with Resume" requires login first but skips the "Have you previously worked for NVIDIA?" question.
- "Apply Manually" does not add that question.
- Both flows have 6 steps once logged in.
- Both flows save progress server-side.

### Work Experience Start Month (Alibaba 2010)
- When typing in spinbuttons, multiple keypresses can accumulate unexpected values (e.g., "12" instead of "1").
- If spinbutton shows wrong value and setNativeValue approach fails, the Calendar button is not available for work experience dates — only for CC-305 disability form.
- The server saves the value from the spinbutton's actual rendered state. After a fresh page load, the saved value was correctly "1" (January 2010), confirming the setNativeValue eventually worked or the previous session had stored it correctly.

## Spinbutton Date Input Issues (discovered 2026-03-01)

Workday date fields use custom ARIA spinbuttons that behave unpredictably with automated keyboard input:
- Typing a single digit into Month works (e.g., "3" → March)
- But subsequent digits in adjacent fields can "leak" into earlier fields due to digit-accumulation timeout
- Example: type "3" in Month, then "1" in Day → Month may become "31" (clamped to 12)
- **Workaround**: Use the Calendar button (ref: `button "Calendar"`) to open the date picker
- Navigate to the target month using "Next month"/"Previous month" buttons
- For large date jumps, use `evaluate()` with JS: `button.click()` in a loop with `setTimeout(r, 20)` delays
- The `[data-automation-id="nextMonth"]` selector may not exist; use the button ref from snapshot instead

## Multi-Step Application (Apply Manually path)

Standard 6-step Workday application:
1. My Information (contact details)
2. My Experience (work history, education, resume upload)
3. Application Questions (custom per-job)
4. Voluntary Disclosures (EEO)
5. Self Identify (CC-305 disability form)
6. Review + Submit

## Field of Study Typeahead

The Field of Study field in Education is a typeahead that requires selecting from dropdown. Typing text does not auto-commit. The search button (binoculars icon) opens a search modal. If dropdown doesn't appear, this field can be left blank as it's not required.

## Post-Submit Account Creation

After successful submission, Workday shows a "Congratulations!" dialog with account creation form. Email is pre-filled. Create a password and submit to create an account for tracking applications. Save password to macOS Keychain: `security add-generic-password -a "<email>" -s "jobhunt:warnerbros.wd5.myworkdayjobs.com" -w "<password>" -U`

## Phenom → Workday Redirect Pattern

WBD uses Phenom as career site (careers.wbd.com) which redirects to Workday for actual application. The "Apply Now" button on the Phenom page opens a new tab with the Workday URL.

## Salesforce Workday Specifics (2026-03-01, Job 134)

### Account Reset Pattern
- Salesforce uses `salesforce.wd12.myworkdayjobs.com`
- If account exists from previous session with unknown password, use "Forgot your password?" on the Sign In page
- Reset email comes from `myworkday.com`, arrives within ~60 seconds
- After reset, you're redirected to Sign In page (not back to application) — re-navigate to the apply URL

### CC-305 Date Field (Disability Form Step)
- The date spinbuttons on the CC-305 form are NOT auto-populated
- JS direct assignment via `dispatchEvent('change')` does NOT work here
- **Must use the Calendar button** — Workday pre-selects today's date as highlighted, just click the highlighted "1" (or whatever today's date is)

### EEO Dropdown Values
- Gender → "I prefer not to disclose"
- Veterans → "I do not wish to self-identify."
- Ethnicity → "I prefer not to disclose (United States of America)"

### 10 Application Questions
Salesforce has extensive government/ethics screening questions (10 total):
1. Preferred geographic location (free text)
2. I-9 requirement acknowledgment (Yes/No)
3. Unrestricted right to work (Yes/No)
4. Future sponsorship required (Yes/No)
5. Government employee in last 5 years (Yes/No)
6. Government responsibilities involving Salesforce (Yes/No)
7. Immediate family in government (Yes/No)
8. Post-government employment restrictions attestation (Yes/No)
9. Debarred from federal contracts (Yes/No)
10. Citizen of Iran/Cuba/NK/Syria (Yes/No)
Plus: Future positions contact preference

### Resume Upload Location
In Step 2 (My Experience), the resume upload is at the bottom below work history and education fields. The upload successfully accepted a PDF file.

## Blue Origin Workday (blueorigin.wd5.myworkdayjobs.com) — 2026-03-02

### Account Creation Flow
- Apply button triggers a "Start Your Application" modal with 3 options: "Autofill with Resume", "Apply Manually", "Use My Last Application"
- Choosing "Autofill with Resume" arms the file chooser — upload BEFORE clicking the button OR arm upload first then click
- After upload, navigates to 8-step application: Create Account/Sign In → Autofill with Resume → My Information → My Experience → Application Questions → Voluntary Disclosures → Self Identify → Review
- **IMPORTANT**: Workday account creation requires email verification before login works. After creating account, Workday redirects to Sign In page but login will fail until the email is verified. Check the registered email for a verification link.
- Keychain service name: `jobhunt:blueorigin.wd5.myworkdayjobs.com`
- If login fails after account creation: mark `blocked`, note "Needs email verification", send Discord report.

### Export Control Note
- Blue Origin requires U.S. citizen, national, permanent resident (Green Card), refugee, or asylum. Green Card holders qualify.
