# Greenhouse ATS — Platform Knowledge

## URL Patterns
- Job listings: `boards.greenhouse.io/<company>/jobs/<id>`
- Application form: `boards.greenhouse.io/<company>/jobs/<id>#app`

## Form Structure
- Standard fields: first_name, last_name, email, phone, resume upload
- Education section: institution, degree, discipline, start_date, end_date
- Work history: company, title, start_date, end_date (checkbox for current)
- Custom questions: vary by company

## Known Behaviors
- Resume upload triggers autofill of experience fields (may overwrite your entries)
- Submit button may be inside an iframe — use snapshot to find it
- After submit: look for "Application submitted" confirmation text

## Tips
- Always upload resume PDF first before filling form fields
- Some companies require LinkedIn URL — use profile field
- Phone format: +1XXXXXXXXXX (no spaces)
