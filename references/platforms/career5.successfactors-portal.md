# Platform: EY SuccessFactors Career Portal (career5.successfactors.eu)

## 2026-03-01 Learnings

- The EY job page can land directly on a **create-account** flow. For first-time users, use `login_ns=register` path and acknowledge the privacy modal before proceeding.
- The platform exposes a **resume required** check in a custom "My Documents" section.
- In this session, browser `upload` did not attach successfully; the UI repeatedly showed:
  - `Error Encountered while uploading your file.`
  - then `Resume is required` on apply validation.
- The post-registration application page has required sections under **Job-Specific Information** including:
  - voluntary self-identification fields (`Ethnicity`, `Race`, `Gender`, veteran status)
  - alternate dispute resolution checkbox
  - compensation range
  - NYC resident, work authorization, and visa questions
- The page can remain in validation-error state if any of the above required fields are missing, even after resume section error.
- For automation resilience, consider a fallback path: pre-check if the platform rejects external upload tooling, then mark job as `apply_failed` promptly with screenshot/context, or support a native file-upload API path if available.
