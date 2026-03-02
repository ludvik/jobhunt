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
