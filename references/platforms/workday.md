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
