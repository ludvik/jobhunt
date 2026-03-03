# EY SuccessFactors Career Portal (career5.successfactors.eu)

## Overview
SAP SuccessFactors-based portal. Used by EY.

## Auth
- First-time: use `login_ns=register` path
- Acknowledge privacy modal before proceeding

## Known Issues
- Resume upload frequently fails with "Error Encountered while uploading your file." then "Resume is required" on apply validation
- If upload fails repeatedly, mark `apply_failed` promptly — no reliable automated workaround found

## Required Fields (Job-Specific Information section)
- Voluntary self-identification: Ethnicity, Race, Gender, veteran status
- Alternate dispute resolution checkbox
- Compensation range
- NYC resident, work authorization, visa questions

## Recommendation
Pre-check whether the platform accepts external upload tooling. If upload fails, mark `apply_failed` immediately with screenshot/context rather than retrying.
