# Oracle HCM / Taleo ATS — Platform Knowledge

## URL Patterns
- Job listings: `<company>.taleo.net/careersection/<section>/jobdetail.ftl?job=<id>`
- Apply: `<company>.taleo.net/careersection/<section>/jobapply.ftl`

## Form Structure
- Account required (Oracle Taleo account)
- Profile builder: work history, education, skills
- Resume upload (optional but recommended)
- Step-by-step wizard similar to Workday

## Known Behaviors
- Session timeouts quickly — keep page active
- File upload size limit: 5MB
- PDF and DOCX supported
- May require answering screening questions before seeing application form

## Tips
- Oracle login can be reused across many employers using Taleo
- Check "Profile" vs "Application" — profile updates don't auto-apply
- Some forms use legacy HTML — snapshot may look cluttered
