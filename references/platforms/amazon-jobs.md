# Amazon.jobs Platform Notes

## Flow
1. LinkedIn "Apply on company website" → redirects to amazon.jobs job page
2. Click "Apply now" on amazon.jobs → opens apply portal at `/en-US/applicant/jobs/<jobid>/apply`
3. SMS verification step (can skip)
4. Job-specific Yes/No questions
5. Work Eligibility (radio buttons + comboboxes)
6. Review page
7. Submit

## Authentication
- Amazon.jobs uses a persistent applicant account
- Profile data (name, email, address, phone) is pre-populated from previous applications
- Resume can be re-used from previous submissions

## Custom Combobox UI (Yes/No Questions)
- The comboboxes are custom React components, NOT native `<select>` elements
- **Quirky behavior**: Clicking the inner textbox of a combobox sometimes re-opens Q1 instead of the target combobox
- **Correct approach**: Click the combobox element itself (e.g., `combobox "Do you have 5+ years..."`) not the inner textbox
- After clicking the combobox element, a dropdown appears with Yes/No options — click the desired option
- Auto-save works ("Progress auto-saved" appears after each selection)

## Work Eligibility Page
- Radio groups for: prior Amazon application, prior employment, non-compete, work authorization, immigration sponsorship, outside-US residency, government employment, sanctioned countries
- Comboboxes for citizenship country and PR country
- Required fields that are often not pre-filled: `REQUIRE_SPONSORSHIP` and `GEF_EXT_USA_GOVERNMENT_EMPLOYE`
- Can use JavaScript `document.querySelectorAll('input[type=radio]')` to inspect/click radio states

## Resume
- Previously uploaded resumes are reused by default
- "Replace Resume" button available on review page
- Upload timestamp shown ("Uploaded: Yesterday at 11:01PM")

## Confirmation
- Success page: "Thank you for applying! Your application for [Job Title] (Job ID: XXXXXXX) has been submitted."
- URL pattern: `/en-US/applicant/jobs/<jobid>/summary?result=success`

- New runtime finding: Amazon job-questions radios can fail if you set `input.checked=true` only in JS; dispatching click/change events or interacting by `name`/`value` is more reliable than ref-based selectors.
- Ref tokens (`ref=e####`) and some generated input IDs for required Work Eligibility radios change across renders; avoid persisting refs across steps and always re-snapshot or query by semantic selectors before clicking.
