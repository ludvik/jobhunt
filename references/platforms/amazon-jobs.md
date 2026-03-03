# Amazon Jobs Platform Notes

## Application Flow (amazon.jobs)

- LinkedIn jobs at Amazon show "Apply on company website" — links to amazon.jobs, NOT LinkedIn Easy Apply
- amazon.jobs maintains a candidate account; contact info, education, resume are pre-populated from prior applications
- Application steps: SMS verification (skip) → Job-specific questions → Work Eligibility → Review → Submit

## Job-Specific Questions

- Questions are Yes/No comboboxes using **Select2** library (custom SPAN-based dropdowns)
- Normal click interaction on a textbox inside one Select2 may inadvertently re-expand a different (already-filled) Select2 above it
- **Best approach:** Use JS to set the underlying select elements and dispatch change events:
  const selects = document.querySelectorAll('select');
  selects[N].value = '1'; // '1'=Yes, '2'=No
  selects[N].dispatchEvent(new Event('change', {bubbles:true}));
- Selects appear in DOM order matching the question order (0-indexed)

## Work Eligibility

- Has radio buttons for: previously applied, previously employed, non-compete, eligible to start, immigration sponsorship, lived outside US, government employee, sanctioned countries, citizenship, permanent resident status
- Pre-populated values from prior applications carry over (verify before continuing)
- Immigration sponsorship question is always blank (required); must set explicitly each time
- Use JS: document.querySelectorAll('input[type=radio]')[N].click() to set radio buttons by index

## Submit Button

- The "Submit application" button on the review page may not respond to normal browser click action via aria ref
- Use JS: Array.from(document.querySelectorAll('button')).filter(b => b.textContent.includes('Submit'))[0].click()
- After click, URL changes to /applicant/jobs/{jobId}/summary?result=success then redirects to homepage = confirmed success

## Resume

- Resume upload persists across applications — same file reused if previously uploaded
- Previous session may have already uploaded; check "Resume" section on review page

## 2026-03-02 (Job 322 — Amazon Data Engineer)

- Successfully applied via amazon.jobs external link from LinkedIn
- Select2 JS workaround was key for filling Q5/Q6 (clicking textboxes caused Q1 to re-expand)
- Submit button required JS evaluate approach
- Total time: multiple model sessions (prior attempts timed out on Select2 interaction)
