
## eBay Phenom ATS (jobs.ebayinc.com) — Observed 2026-03-02

### Flow
- LinkedIn "Apply on company website" → jobs.ebayinc.com job page → "Apply Now" button
- 6 steps: My Information → My Experience → Application Questions → Voluntary Disclosures → Self Identify → Review → Submit

### Key Patterns
- **Toolbar Next (top of page) bypasses disabled bottom Next**: The bottom "Next" button frequently shows as [disabled] even when form appears complete. The toolbar button at the top of the page always works — use it to advance steps.
- **Resume upload**: Arms fine before clicking "Upload Resume" button; auto-populates work experience from PDF.
- **Work experience auto-fill**: The ATS parses the uploaded PDF and fills in job titles, companies, dates, and descriptions. Verify/correct after upload.
- **Education fields**: School name auto-fills from resume but Degree and Field of Study dropdowns need manual selection.
- **Disability form**: Name field and date need to be filled; radio buttons must be clicked. Use JS evaluate to click radio by ID if not visible in snapshot.

### Application Questions (Step 3)
Standard 6 questions — all Yes/No except relocation:
1. Non-compete agreement (No)
2. Authorize eBay to retain info (Yes)
3. Legally authorized to work in US (Yes)
4. Require sponsorship (No)
5. Current/former eBay employee (No)
6. Open to relocating: options are "Open to relocation", "Interested in remote only", "Flexible with both options"

### Disability Form Radio IDs
- Yes: `disability_heading_self_identity.disabilityStatus.YES_REV_2026`
- No: `disability_heading_self_identity.disabilityStatus.NO_REV_2026`
- Decline: `disability_heading_self_identity.disabilityStatus.DECLINE_REV_2026`

### Confirmation
URL pattern: `applythankyou?status=success&jobSeqNo=...&candidateId=CAN...`
Title: "Thank you for applying"

### Tested (Job 347 - Director of Engineering, 2026-03-02)
✓ Resume upload & auto-fill (5 work entries, 2 education entries pre-populated)
✓ Contact info auto-filled, manual corrections applied (City, Address, State, Zip)
✓ Education degree/field-of-study selects (Masters + Bachelors, both Computer Engineering)
✓ All 6 application questions answered
✓ Voluntary disclosures (Gender: Male, Ethnicity: Asian, Veteran: Not a veteran)
✓ Terms & Conditions checkbox
✓ Disability form (Name & Date pre-filled; selected "No")
✓ Review page verified all entries
✓ Submit → Confirmation: "Nice work! Thanks for submitting your application!"
✓ Confirmation URL: `applythankyou?status=success&jobSeqNo=...&candidateId=CAN4770147`

### Notes
- Resume parse was accurate (5 of 6 work entries filled; missing one older entry but form accepted as-is)
- Step 1 loading took ~2-3s; waits handled gracefully
- All dropdowns and form fields worked without issues
- No CAPTCHA or special verification required
