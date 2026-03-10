# eBay Phenom ATS (jobs.ebayinc.com)

## Overview
6-step application: My Information → My Experience → Application Questions → Voluntary Disclosures → Self Identify → Review → Submit

## Key Patterns
- **Top toolbar "Next" bypasses disabled bottom "Next"**: Bottom Next is frequently [disabled] even when form is complete. Use the toolbar button at top of page — it always works.
- **Resume upload**: Arm before clicking "Upload Resume"; auto-populates work experience from PDF.
- **Education fields**: School name auto-fills from resume but Degree and Field of Study dropdowns need manual selection.

## Application Questions (Step 3 — 6 questions)
1. Non-compete agreement → No
2. Authorize eBay to retain info → Yes
3. Legally authorized to work in US → Yes
4. Require sponsorship → No
5. Current/former eBay employee → No
6. Open to relocating → "Open to relocation" / "Interested in remote only" / "Flexible with both options"

## Disability Form Radio IDs
```
Yes:     disability_heading_self_identity.disabilityStatus.YES_REV_2026
No:      disability_heading_self_identity.disabilityStatus.NO_REV_2026
Decline: disability_heading_self_identity.disabilityStatus.DECLINE_REV_2026
```
Use JS evaluate to click by ID if not visible in snapshot.

## SPA Navigation — Waiting Between Steps (CRITICAL)
eBay Phenom is a React SPA. Clicking Next does NOT trigger a full page navigation.
**Never use `wait_for_load_state("networkidle")`** — it will either time out or return too early.

After clicking Next:
```js
// Wait for next step heading to appear
browser(action="wait", selector="[data-automation-id='headingSectionTitle']", profile="jobhunt", target="host")
```
Or wait for a known element in the next step. If wait times out (10s), re-snapshot and check current step — the click may have registered but rendered slowly.

## Confirmation
URL pattern: `applythankyou?status=success&jobSeqNo=...&candidateId=CAN...`
Heading: "Thank you for applying"
