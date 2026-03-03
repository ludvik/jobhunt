# The RealReal — Phenom ATS (careers.therealreal.com)

## Overview
Apply URL: `https://careers.therealreal.com/us/en/apply?jobSeqNo=<SEQ>&step=1&stepname=personalInformation`

## Form Flow (6 steps)
1. personalInformation — contact fields + resume upload
2. workAndEducation — work history (auto-parsed from resume) + education
3. jobSpecificQuestions — role-specific questions
4. voluntaryInformation — diversity disclosures + T&C checkbox
5. disabilityInformation — disability self-ID form
6. applicationReview — review + Submit

## Key Gotchas
- **Step 3 date field**: React synthetic event required. Type value is not enough:
  ```js
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(inp, val);
  inp.dispatchEvent(new Event('change', {bubbles:true}));
  ```
- **Step 3 compensation**: "What is your desired compensation?" is required — fill it even if it looks optional
- **Resume upload**: Arm file chooser first, then click "Upload Resume" button
- **Rating popup**: Appears on step 1; closing it (X button) also triggers Next navigation
- **Submit button**: Goes disabled briefly while submitting — normal, wait for redirect

## Confirmation
URL: `https://careers.therealreal.com/us/en/applythankyou?status=success`
Application ID in URL as `jobApplicationId=<id>`
