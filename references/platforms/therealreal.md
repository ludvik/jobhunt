# The RealReal — Phenom ATS

Platform: Phenom People (careers.therealreal.com)
Apply URL pattern: https://careers.therealreal.com/us/en/apply?jobSeqNo=<SEQ>&step=1&stepname=personalInformation

## Form Flow (6 steps)
1. personalInformation — personal contact fields + resume upload
2. workAndEducation — work history (often auto-parsed from resume) + education
3. jobSpecificQuestions — role-specific questions
4. voluntaryInformation — diversity disclosures + T&C checkbox
5. disabilityInformation — disability self-ID form
6. applicationReview — review + Submit

## Gotchas
- **Step 3 date field**: The date input (type=date) requires a React synthetic event to register. Simply typing the value is not enough — dispatch via JS: Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(inp, val); inp.dispatchEvent(new Event('change', {bubbles:true}));
- **Step 3 compensation**: "What is your desired compensation?" is required despite sometimes appearing optional. Must fill it.
- **Resume upload**: Arm file chooser via browser upload tool, then click "Upload Resume" button. Resume auto-parses into work experience fields.
- **Rating popup**: A "How would you rate your experience?" popup appears on step 1. Closing it (X button) also triggers Next navigation.
- **Submit button**: Goes disabled briefly while submitting — normal. Wait for redirect to applythankyou page.
- **Confirmation URL**: https://careers.therealreal.com/us/en/applythankyou?status=success — status=success is the signal.
- **Application ID**: Found in confirmation URL as jobApplicationId=<id>

## Confirmed Working (2026-03-02)
Job: Staff Software Engineer - R11990, Application ID: f56b94ebe6b99000e3a0b5b986750003
