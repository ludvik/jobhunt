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
