# LinkedIn Job Posting Patterns (Apply Workflow)

- **2026-02-28**: Job 88 (CoreWeave: Staff Software Engineer, Cluster Orchestration) showed a hard block state with banner text `No longer accepting applications` on the LinkedIn job detail page.
- In this state, no active `Apply` CTA was exposed in the snapshot DOM even though other related cards may include company/job context sections.
- For this posting, LinkedIn includes a company post link and an `lnkd.in` form link in related feed content, but the referenced form URL appears outdated/invalid or inaccessible from the automated browser flow.
- If the page is marked closed this way, treat as `blocked` immediately without pursuing repeated retries of the external links; one best-effort external path check is sufficient.
- **2026-02-28 (Job 87)**: LinkedIn card text may show "No longer accepting applications" while including recruiter-contact instructions (CV email / lnkd.in form) but no visible apply control. In this case treat as closed and prefer immediate blocked without retries; if needed, only one best-effort check for explicit external form link.
- **2026-02-28 (Job 85 - Pinterest: Sr. Staff Software Engineer, Conversion Visibility)**: job detail page rendered normal listing context with matching tools but no active `Apply` CTA; `No longer accepting applications` effectively blocks submission. Set status `blocked` immediately.
