# LinkedIn Job Posting Patterns (Apply Workflow)

- **2026-02-28**: Job 88 (CoreWeave: Staff Software Engineer, Cluster Orchestration) showed a hard block state with banner text `No longer accepting applications` on the LinkedIn job detail page.
- In this state, no active `Apply` CTA was exposed in the snapshot DOM even though other related cards may include company/job context sections.
- For this posting, LinkedIn includes a company post link and an `lnkd.in` form link in related feed content, but the referenced form URL appears outdated/invalid or inaccessible from the automated browser flow.
- If the page is marked closed this way, treat as `blocked` immediately without pursuing repeated retries of the external links; one best-effort external path check is sufficient.
- **2026-02-28 (Job 87)**: LinkedIn card text may show "No longer accepting applications" while including recruiter-contact instructions (CV email / lnkd.in form) but no visible apply control. In this case treat as closed and prefer immediate blocked without retries; if needed, only one best-effort check for explicit external form link.
- **2026-02-28 (Job 85 - Pinterest: Sr. Staff Software Engineer, Conversion Visibility)**: job detail page rendered normal listing context with matching tools but no active `Apply` CTA; `No longer accepting applications` effectively blocks submission. Set status `blocked` immediately.

## Shadow DOM Radio Buttons (discovered 2026-03-02)
LinkedIn Easy Apply renders radio button groups inside **shadow DOM** on some question pages. Standard `kind:click` with a `ref` will fail with "not found or not visible" even when the snapshot shows the radio.

**Workaround:**
```js
// Find the shadow host and click the radio inside it
const all = document.querySelectorAll('*');
for (const el of all) {
  if (el.shadowRoot) {
    const radios = el.shadowRoot.querySelectorAll('input[type=radio], [role=radio]');
    if (radios.length > 0) {
      radios[0].click(); // index 0 = first option (Yes), index 1 = No
      break;
    }
  }
}
```
Use `kind: "evaluate"` with this fn to click radio[0] for Yes or radio[1] for No.

This affects the "Additional Questions" step. Combobox dropdowns on the same page work normally with `kind: "select"`.

## Greenhouse ATS via LinkedIn redirect (discovered 2026-03-02, Job 359 Grammarly)
- LinkedIn "Apply on company website" often redirects to Greenhouse ATS
- Greenhouse URL pattern: `https://job-boards.greenhouse.io/<company>/jobs/<id>`
- Navigate directly to Greenhouse URL rather than clicking through LinkedIn redirect
- All dropdowns are react-select components (not native `<select>`); use evaluate+click pattern:
  - Open dropdown: `kind: "click"` on the combobox ref
  - Get options: `[...document.querySelectorAll('[class*=menu] [class*=option]')].map(o=>({text,id}))`
  - Click option: `document.querySelector('#react-select-<field>-option-<N>').click()`
- School combobox: Most universities not in Greenhouse database → shows "No options"; field is optional, skip gracefully
- Resume upload: arm with `browser(action="upload")` BEFORE clicking Attach button; file chooser auto-resolves
- Pre-existing resume may be attached from prior sessions; check for "Remove file" button and replace
- Single-page application (no pagination / Next buttons)
- Phone number often pre-fills from browser profile data

## "Apply on company website" → Greenhouse redirect (2026-03-02)
- LinkedIn "Apply on company website" links to `https://job-boards.greenhouse.io/<company>/jobs/<id>` via lnkd.in redirect.
- Extract the Greenhouse job ID from the redirect URL and navigate directly — faster and avoids redirect issues.
- Example URL pattern: `https://job-boards.greenhouse.io/anthropic/jobs/5107121008`

## Greenhouse: Pre-existing resume in form (discovered 2026-03-03, Job 357 Scale AI)
- Greenhouse forms may retain a resume from a prior session (e.g., "cv-ai-engineer.pdf" still attached).
- The upload tool arms a file chooser globally — if you click "Attach" and the file chooser fires before it's armed, the file goes to the wrong slot (e.g., Cover Letter instead of Resume).
- **Safe pattern**: arm upload FIRST (`browser action=upload`), then immediately call evaluate to click the correct Attach button. Do NOT click Attach via ref (ref click has a timeout that can preempt the file chooser arming).
- After upload, always take a snapshot to confirm the filename appears in the correct slot before proceeding.
- If resume lands in wrong slot: use "Remove file" button on that slot, re-arm upload, then click the correct Attach.
- Greenhouse single-page form fields: First Name, Last Name, Email, Phone (auto-formats to (XXX) XXX-XXXX), Resume/CV, Cover Letter (optional), LinkedIn Profile, Website, custom questions, EEO section.
- `generate_pdf.py` script path referenced in SKILL.md does not exist; use `pandoc --pdf-engine=tectonic` as fallback directly.

## Shadow DOM Radio Buttons in Greenhouse Modal (2026-03-03)

When LinkedIn Easy Apply uses Greenhouse as backend, the additional questions (radio button groups) are rendered inside shadow DOM. Regular `click` by aria ref fails with "Element not found or not visible."

**Workaround:** Use `browser(action="act", request={kind: "evaluate"})` to collect all radio inputs across all shadow roots and click by index:

```js
(() => {
  var all = document.querySelectorAll('*');
  var allRadios = [];
  for (var i = 0; i < all.length; i++) {
    var el = all[i];
    if (el.shadowRoot) {
      var radios = el.shadowRoot.querySelectorAll('input[type=radio]');
      for (var j = 0; j < radios.length; j++) allRadios.push(radios[j]);
    }
  }
  // Example: 3 questions × 2 options = 6 radios (0=Q1-Yes, 1=Q1-No, 2=Q2-Yes, ...)
  allRadios[1].click(); // Q1: No
  allRadios[2].click(); // Q2: Yes
  allRadios[4].click(); // Q3: Yes
  return 'clicked';
})()
```

Note: `const` is not allowed in evaluate fn — use `var`.
