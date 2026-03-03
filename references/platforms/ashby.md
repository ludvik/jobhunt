# Ashby Application Platform Notes

- Date added: 2026-02-28
- Job: Snowflake Principal Software Engineer - PostgreSQL (LinkedIn sourced)

## Observed patterns / gotchas
- Ashby often redirects from job board pages (LinkedIn in this case) to `jobs.ashbyhq.com` with an application form that includes:
  - Resume upload for autofill, but required fields may not auto-populate reliably after manual re-upload on first pass.
  - A location field presented as plain text input with generic placeholder (`Start typing...`) and no stable id/name; harder to reliably target via automation.
  - Multiple compliance/legal checkboxes/radio groups (EEOC/veteran/privacy) rendered as large generic widgets.
- Submission frequently lands on a reCAPTCHA gate before confirmation, even after filling and consenting.
  - Snapshot shows only reCAPTCHA banner with no clear submit confirmation text.

## Recommended automation workflow updates
- Pre-check for `This site is protected by reCAPTCHA` after clicking submit.
- If surfaced, mark as blocked and escalate for manual completion rather than repeated submit attempts.
- Upload resume once, then wait for parsing completion before filling text fields; in this run, upload appeared to clear entered fields, requiring a second pass.

## Ironclad / Ashby (2026-03-02, Job 344)
- Ashby single-page application at jobs.ashbyhq.com/ironcladhq/<uuid>/application
- Yes/No toggle buttons for required fields (work auth, sponsorship, hybrid) need to be clicked AFTER the page has fully stabilized. If you click them before submitting and the form re-renders on submit, the selections may not register — always re-click if validation errors show these fields missing.
- City of Residence is a combobox (type → pick from dropdown), not a plain text box
- Resume upload: two upload areas — one autofill area at top, one attached to the Resume required field. Upload to the second (required field) area for the actual resume.
- Diversity survey is fully optional, all prefer-not-to-answer options available
- Application limits: max 2 applications per 90 days, no re-apply within 180 days for same role

## River / Ashby (2026-03-02, Job 340)
- Form at jobs.ashbyhq.com/river/<uuid>/application — single page, no pagination
- Yes/No toggle buttons for H1B sponsorship and "located in Americas" do NOT register on first click when using browser act/click — always re-click them immediately before submit (or after first submit validation error)
- The upload flow: arm `browser(action="upload")` BEFORE clicking the upload button; the click triggers the file chooser and resolves to the armed file
- No reCAPTCHA gate surfaced (unlike Snowflake run) — form submitted cleanly on second submit attempt
- Confirmation displayed as a status element: "Your application was successfully submitted. We'll contact you if there are next steps."
- Fields: Name, Email, Resume (required), Cover Letter (optional), LinkedIn Profile, H1B sponsorship (Yes/No toggle), Located in Americas (Yes/No toggle), Why interested, Salary expectations, Available start date, Proudest achievement, Technical problem

## Cohere / Ashby (2026-03-03, Job 360)
- Form at jobs.ashbyhq.com/cohere/<uuid>/application — single page, no pagination
- **React SPA gotcha**: DOM manipulation via `evaluate` (setting `.value` + dispatching `input`/`change` events) fills fields visually but React's internal state is NOT updated — form validation will fail on submit for those fields
- **Fix**: Must use actual keyboard interaction: `click` → `press Meta+a` → `type` to properly trigger React's `onChange` handlers
- Upload arm + click pattern works fine — arm `browser(action="upload")` before clicking "Upload File" button
- **Upload arm misfires**: If the openclaw browser has other tabs with file chooser interceptors (e.g., from previous upload arms), navigate-after-upload can land on a different tab's pending file chooser. Open a fresh tab for the application to avoid this.
- No Yes/No toggles, no reCAPTCHA gate, no login required
- Confirmation: status element — "Your application has been submitted! Thank you for your interest in a career growth opportunity at Cohere!"
- Fields: Name*, Email*, Current company, Current location, Phone, Resume* (upload), Additional information, Which location are you closest to?, LinkedIn, Website, Twitter, GitHub
- Additional questions (all required*): AI systems experience, Most interesting thing built, Hardest you've worked on something
