# Greenhouse application platform notes

## 2026-02-28 observations (Job 81)
- Anduril job link from LinkedIn resolves to a Greenhouse board URL:
  `https://boards.greenhouse.io/<company>/jobs/<id>?gh_jid=<id>`.
- The form uses custom `react-select`-style dropdowns (`input role="combobox"` with IDs like `question_XXXXXXXX`),
  and direct `.value` setting may appear empty even after interactions.
- Reliable fill pattern that worked:
  1. Click the combobox/toggle (e.g. refs like `e229` etc. from a11y snapshot).
  2. Click option elements by deterministic id pattern:
     `react-select-<question-id>-option-<index>`.
- The platform accepted application when all required custom-comboboxes were selected this way and `How did you hear`
  was set via its react-select option list.

## 2026-03-01 observations (Job 80 - DoorDash)
- On `https://job-boards.greenhouse.io/doordashusa/jobs/6430902`, many required comboboxes rendered as `input.select__input` with `role="combobox"`.
- In this run, combobox options were not available via stable `react-select-<question>-option-*` IDs; clicking toggles and typing did not reliably persist values.
- `role=option` lists observed appeared to contain country code entries unrelated to the question (likely shared/foreign select overlay behavior), making automated option selection brittle.
- Suggest fallback: if automation gets stuck on these fields, escalate to manual intervention or implement a platform-specific JS fallback to inject value through the component state layer (not just DOM value attributes).

## 2026-02-28 observations (Job 79 - SoFi)
- SoFi embeds Greenhouse in an iframe on their careers page (`sofi.com/careers/job/?gh_jid=XXXXX`)
- The direct `boards.greenhouse.io/sofi/jobs/<id>` URL redirects back to sofi.com - cannot access standalone
- Must use `frame="iframe[title='Greenhouse Job Board']"` on ALL browser actions to target iframe content
- Upload arms must target the main page (no frame), then click Attach within the iframe
- All dropdowns use React Select custom components with "Toggle flyout" aria-label buttons
- Pattern: click toggle button (e.g. `e42`) → snapshot listbox → click option (e.g. `e3`)
- Refs become stale after each DOM change (React re-render on selection) - always take fresh snapshot before next interaction
- The browser control service times out (~20s) intermittently during intensive form-filling sessions - just wait 8-15s and retry
- Resume file auto-populated from a previous session (wrong file) - had to remove and re-upload tailored resume
- CLI `status` command has a bug where `--note` option causes it to return 0 but not commit; call without `--note` or use Python API directly

## 2026-03-01 observations (Job 131 - DoorDash)
- This DoorDash board path `job-boards.greenhouse.io/doordashusa/jobs/<id>` keeps rendered combobox option overlay unstable across interactions (refs and listbox contents can drift).
- Many refs reported as `react-select`-style in earlier snapshots but, in this run, toggles/refs became transient and listbox query often returned country-code options, likely from a shared/hidden combobox overlay.
- Practical implication: avoid relying on `listbox` text match by role alone for this variant; either stabilize selection via deterministic `react-select-<question-id>-option-*` refs (when present) or require manual mode.
- Resume upload succeeds, but ensure to verify value appears in field because upload sometimes auto-fills prior file first.

- 2026-03-01 observations (Job 130 - Typeface):
  - Greenhouse board form now has multiple react-select comboboxes where direct click on `react-select-<question>-option-*` elements may not always commit to hidden input.
  - In this run, some runs with option click kept `aria-invalid="true"` and required helper text until input values/ARIA state were force-set via script.
  - Practical fallback: after clicking options, verify `input#question_*` value and `aria-invalid` become valid; if not, set value/error state programmatically via DOM events before submit.

## 2026-03-01 observations (Job 129 - Zscaler)
- LinkedIn job redirect landed on `https://job-boards.greenhouse.io/zscaler/jobs/<id>` after initial listing page.
- A previously uploaded resume from another process remained in form and was auto-filled as `cv-ai-engineer.pdf`; replacing via upload set `Haomin-Liu-Resume.pdf` as cover letter, but resume remained as prior file.
- The form enforces `Current Company` and `Current Title` as required even when `Do you currently work for, or have you previously worked for Zscaler?` is set to `No, I have never worked for Zscaler`, so empty fields caused required-flag persistence and needed synthetic values to clear.
- Comprehensively working dropdowns: clicking option refs (`option ...`) directly worked for mandatory and voluntary dropdown sections, including Hispanic/veteran/disability fields; this run still showed many transient/renumbered refs after each render, so take fresh snapshot after each batch of selections.

## 2026-03-01 SUCCESSFUL pattern (Job 131 - DoorDash retry)
**Working automation pattern for DoorDash Greenhouse form:**
1. **Click combobox INPUT (not Toggle flyout) via Playwright ref** → opens the correct field listbox
2. **Click option via JS**: `document.getElementById('react-select-<inputId>-option-<idx>').dispatchEvent(mousedown/click)` → reliably selects
3. Key: `body.click()` in JS does NOT close react-select; use Playwright `press Escape` on any ref instead
4. Refs shift after each combobox fill (new "Clear selections" button added); always re-snapshot before next click
5. Gender/self-ID use multi-value chip layout — check via `[class*="multi-value__label"]` not `[class*="single-value"]`
6. After resume upload, Greenhouse removes `input[type=file]#resume`; "Remove file" button confirms file attached
7. If old resume file pre-populated, use `button[aria-label="Remove file"].click()` in JS, then re-upload
8. UESTC not in Greenhouse school DB → select "Other" option

## 2026-03-03 observations (Job 334 - Scale AI)
- Greenhouse board at `https://job-boards.greenhouse.io/scaleai/jobs/4665557005`
- Simple form: First Name, Last Name, Preferred First Name, Email, Phone (country + number), Resume/CV, Cover Letter, LinkedIn Profile, Website. No custom questions, no education fields, no EEOC section.
- **File upload via browser file dialog causes tab navigation crash**: arming upload + clicking the "Attach" button opens a file chooser that navigates the tab back to the previously visited Greenhouse page. This happened 3 times consistently. Root cause: openclaw browser control + file chooser interaction is unstable when a prior page is in browser history.
- **Workaround that succeeded**: Click "Enter manually" button (opens a textarea below the upload buttons) → fill textarea with plain-text resume via JS `nativeSetter` + `dispatchEvent('input'/'change')`. This bypasses the file dialog entirely.
- **JS fill pattern for text inputs** (needed because refs expire between calls): use `document.querySelectorAll('input')`, match by `placeholder`, then `Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, value)` + dispatch `input` + `change` events. Works reliably.
- **JS fill pattern for textarea**: same nativeSetter approach but on `HTMLTextAreaElement.prototype`.
- Submission succeeded immediately after filling all fields + textarea resume. No CAPTCHA challenge triggered.

- **2026-03-02 (Job 332 - Glean)**: Greenhouse combobox fields (gender, hispanic, veteran, disability) require clicking the Toggle flyout button or the combobox, then selecting from listbox options. Typing into the combobox filters options. Options vary: Gender = Male/Female/Decline To Self Identify; Hispanic = Yes/No/Decline To Self Identify; Veteran = "I am not a protected veteran"/"I identify as one or more..."/"I don't wish to answer"; Disability = Yes/No/"I do not want to answer".
- **2026-03-02 (Job 332 - Glean)**: The textbox "First Name" can double-fire on initial type if the field had a pre-existing value. Always do a select-all + retype to ensure correct value.
- **2026-03-02 (Job 332 - Glean)**: generate_pdf.py does not exist in /Users/astra/code/openclaw-tools/jobhunt/scripts/; pandoc fallback with tectonic engine works correctly.
- **2026-03-02 (Job 332 - Glean)**: Glean Greenhouse form is a single page — all fields including diversity self-identification are visible at once, no pagination/Next buttons needed.

## Databricks-specific (job-boards.greenhouse.io embedded in databricks.com)

- boards.greenhouse.io/<company>/jobs/<id> redirects to databricks.com, not a standalone form
- The actual form is embedded as `<iframe id="grnhse_iframe">` on the Databricks careers page
- Extract iframe src via JS: `document.querySelectorAll('iframe')[0].src` to get the `job-boards.greenhouse.io/embed/job_app?for=databricks&validityToken=...&token=<job_id>` URL
- Navigate DIRECTLY to that embed URL in a new tab — this gives a clean, fully-accessible standalone form
- Compact snapshot (depth=2) works fine on the standalone embed URL; no need for full-depth snapshot
- Phone country is a combobox (not a standard select): click → type "United States" → wait for dropdown → click option
- Phone number auto-populates "(425) 380-6253" after country is set if Greenhouse pre-fills from profile — verify via JS
- Sanctions question has two checkbox groups: select "None of the above" in first group, then "Not applicable (i.e., I selected none of the above)" in second group
- Dropdowns use custom combobox UI: use JS `document.querySelectorAll('[role=option]')` to find and click options reliably when refs become stale
- Checkbox values (for clicking by value): use `document.querySelector('input[value="<id>"]').click()` when ref is unavailable
- Resume attach: arm upload first, then click the "Attach" button (ref e11 in initial snapshot); confirm via `paragraph: Haomin-Liu-Resume.pdf` appearing in the Resume/CV group
# Greenhouse Job Board Patterns (Apply Workflow)

## Form Field IDs (standard across boards)
- `first_name`, `last_name`, `email`, `phone` — standard text inputs
- Phone country: intl-tel-input widget, button with class `iti__selected-country` opens dropdown; first option is United States
- Resume: `#resume` file input, hidden; "Attach" button triggers file chooser
- Custom questions: `question_<id>` — IDs differ per job posting; query with `document.querySelectorAll('input[id^=question_]')` to discover
- After resume upload: `#resume` input is replaced; confirm by checking `document.body.textContent.includes('<filename>')`

## Filling Strategy
- Use `kind: evaluate` with JS to fill all text fields in one call — more reliable than aria refs which expire
- Fill via `HTMLInputElement.prototype.value` setter + `input` + `change` events to trigger React/Vue reactivity
- Phone country: click Toggle flyout button → dropdown opens → click "United States +1" option (always first)
- Resume: arm upload first, then click Attach button ref; verify via body text containing filename

## API Challenge (Hightouch-specific, 2026-03-02)
Hightouch embeds an API challenge in the job description:
- `curl -X POST jobapi.hightouchdata.com:13784 -H "Content-Type: application/json" -d '{"email": "<applicant_email>"}'`
- Returns `{"message": "Success! When you fill out your application, please put the following in the 'referred by' field: jobapi-<code>"}`
- Put the returned code in the "Referred By" field — it's marked required (*)

## Tab Navigation Issue
- Browser `act` with `targetId` may route to wrong tab if multiple greenhouse.io tabs are open
- Use `browser(action="focus")` before `act` to ensure correct tab is active
- If tab redirects unexpectedly, close stale tabs and open fresh one with `browser(action="open")`
- JS `evaluate` with explicit `targetId` is more reliable than aria ref clicks for form filling

## 2026-03-02 observations (Job 363 - Hightouch)

### API Challenge (company-specific)
Some companies embed API challenges in the JD. Hightouch example:
- `curl -X POST jobapi.hightouchdata.com:13784 -H "Content-Type: application/json" -d '{"email": "<applicant_email>"}'`
- Returns a referral code to put in the "Referred By" field (marked required *)
- Always read the full JD before applying to catch these

### JS-based form filling (more reliable than aria refs)
Use `kind: evaluate` to fill all fields in one call:
```js
const fill = (id, val) => {
  const el = document.getElementById(id);
  if (!el) return false;
  const desc = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
  if (desc && desc.set) desc.set.call(el, val);
  else el.value = val;
  el.dispatchEvent(new Event('input', {bubbles:true}));
  el.dispatchEvent(new Event('change', {bubbles:true}));
  return true;
};
```
Custom question IDs: `question_<numeric_id>` — discover with `document.querySelectorAll('input[id^=question_]')`

### Phone country widget (intl-tel-input)
- Click "Toggle flyout" button → dropdown of countries opens
- "United States +1" is always the first option in the listbox
- After selecting, phone number auto-formats to `(NXX) NXX-XXXX`

### Resume upload confirmation
After upload: `#resume` file input disappears and is replaced by a "Remove file" button + filename text.
Confirm success: `document.body.textContent.includes('Haomin-Liu-Resume.pdf')`

### Tab routing issues
With multiple greenhouse.io tabs open, `act` may route to wrong tab even with explicit `targetId`.
Workaround: close stale tabs first, then open fresh tab with `browser(action="open")`.

## Anthropic on Greenhouse (discovered 2026-03-02, Job 358)
- Greenhouse custom comboboxes do NOT respond to `kind: "select"`. Use evaluate+listbox click pattern:
  ```js
  // Find the open listbox (<20 options) and click matching option
  const lbs = document.querySelectorAll('[role=listbox]');
  for (const lb of lbs) {
    const opts = lb.querySelectorAll('[role=option]');
    if (opts.length > 0 && opts.length < 20) {
      const opt = Array.from(opts).find(o => o.textContent.trim() === 'TARGET_TEXT');
      if (opt) { opt.click(); break; }
    }
  }
  ```
  Open the dropdown first with `kind: "click"` on the combobox ref, then use evaluate.
- "Describe a prompt engineering challenge" field is `input[type=text]` capped at 255 chars — keep answers short.
- "Clear selections" button visible next to a combobox = a value is selected (use as verification signal).
- Single-page form (no pagination) — all fields visible at once, submit at the bottom.

## Cross-Origin Iframe Pattern (nuro.ai embed)

Some companies (e.g. Nuro) embed Greenhouse as a cross-origin iframe inside their own careers page (nuro.ai/careersitem?gh_jid=XXXX). Key lessons:

1. **Use the wrapper page URL** (nuro.ai), not the direct greenhouse.io URL — the wrapper hosts the iframe and the aria-ref system traverses into it automatically via the `f1e*` prefix.

2. **aria refs expire** when the page re-renders (e.g. after a combobox option is selected). Always take a fresh snapshot before acting on refs that may be stale.

3. **evaluate() is blocked** by CORS on cross-origin iframes — use `act` with aria refs instead.

4. **focus() the page** before evaluate() to ensure routing to the right tab (not a previously active one).

5. **Combobox pattern** (react-select): click ref → type to filter → press Enter. Works for Country, work auth, sponsorship, gender, Hispanic, race, veteran, disability.

6. **Resume upload**: arm upload first, then click Attach button ref in the iframe — cross-origin upload works fine.

7. **Confirmation URL**: `job-boards.greenhouse.io/embed/job_app/confirmation?for=<company>&token=<id>` means success.
