# Greenhouse Platform Playbook

## URL Strategy
- Direct URL: `boards.greenhouse.io/<company>/jobs/<id>` or `job-boards.greenhouse.io/<company>/jobs/<id>` (preferred)
- If redirect to company site: extract iframe src via JS (`document.querySelectorAll('iframe')[0].src`) and navigate to embed URL directly
- Databricks: extract `job-boards.greenhouse.io/embed/job_app?for=databricks&...&token=<id>`, navigate to it in a new tab
- SoFi: LinkedIn external link leads to sofi.com careers page with embedded Greenhouse iframe. Extract iframe src via JS (`document.querySelector('iframe[src*="greenhouse"]')?.src`) and navigate directly to that URL instead of using `frame=` param. Upload arm must target the Greenhouse iframe URL page, not the sofi.com wrapper.
- Nuro: cross-origin iframe on nuro.ai — `evaluate()` blocked by CORS; use aria refs only; wrapper page URL routes refs into iframe automatically
- Confirmation URL pattern: `job-boards.greenhouse.io/embed/job_app/confirmation?for=<company>&token=<id>`

## Form Filling (JS-first approach)
Use `kind: evaluate` to fill all text fields in one call — more reliable than aria refs which expire:
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
// Standard IDs: first_name, last_name, email, phone
// Custom questions: discover with document.querySelectorAll('input[id^=question_]')
// Textarea: use HTMLTextAreaElement.prototype instead
```
Always select-all before retyping a pre-filled field to avoid double-fire.

## React Select Comboboxes
Two reliable patterns (try in order):
1. **JS click on option element**: `document.getElementById('react-select-<inputId>-option-<idx>').click()` — most reliable when IDs are present
2. **Aria ref flow**: click combobox input ref → type to filter → press Enter (works for cross-origin iframes where evaluate() is blocked)

After each selection, refs shift (React re-renders). Always re-snapshot before next interaction.
"Clear selections" button visible next to a combobox = value is selected (verification signal).
If option click leaves `aria-invalid="true"`, force-set via DOM events or JS state.

## Phone Country Widget (intl-tel-input)
Standard click approach often fails (dropdown doesn't render options reliably in automation). Use JS directly:
```js
// Force US country selection on intl-tel-input
var phoneInput = document.querySelector('input[type=tel]') || document.getElementById('phone');
if (phoneInput && phoneInput._intlTelInput) {
  phoneInput._intlTelInput.setCountry('us');
} else {
  // Fallback: click the flag button then click US option
  var btn = document.querySelector('button.iti__selected-country, .iti__flag-container button');
  if (btn) btn.click();
  setTimeout(function() {
    var us = document.querySelector('li[data-country-code="us"]');
    if (us) us.click();
  }, 300);
}
```
After selecting, phone field may auto-format. Re-fill phone value via nativeSetter if cleared.
If intl-tel-input blocks form submit entirely, fill phone without country prefix (just digits) and skip country selector — Greenhouse usually defaults to US.

## Resume Upload
1. Arm upload first (provide file path to upload arm)
2. Click the "Attach" button ref
3. Confirm: `document.body.textContent.includes('Haomin-Liu-Resume.pdf')` — `#resume` input disappears and is replaced by "Remove file" button
4. If old resume pre-populated: `document.querySelector('button[aria-label="Remove file"]').click()` in JS, then re-upload
5. Scale AI workaround: file dialog caused tab navigation crash — use "Enter manually" textarea + JS nativeSetter instead

## Known Gotchas
- **Refs expire** after each DOM change (React re-render) — always re-snapshot before next action
- **Multiple tabs** (CRITICAL): `act` always routes to the Chrome foreground tab, ignoring `targetId`. Close ALL browser tabs before starting any Greenhouse application (Step 0 in the apply prompt). Even unrelated tabs can capture focus and cause form navigation failures. This is the #1 cause of failed applications.
- **CORS on cross-origin iframes**: `evaluate()` blocked — use aria refs only (Nuro, potentially others)
- **Pre-filled fields**: old resume or profile data may auto-populate — verify and clear before submitting. `kind: "type"` appends to existing value rather than replacing — always use the JS fill pattern (nativeSetter + input/change events) or select-all before typing to avoid doubled text (e.g. "HaominHaomin"). Pre-existing resumes (from prior Greenhouse sessions) will appear as a named file with "Remove file" button — always remove and re-upload the tailored resume.
- **Zip code / special-char field names**: Some Greenhouse custom question fields have long names with quotes/special chars (e.g. `Zip Code / Postal Code (Non-U.S. based candidates, please enter "00000")`). The `kind: "type"` ref locator times out because Playwright truncates the name match. Use `document.getElementById('question_<id>')` via evaluate + nativeSetter pattern instead. Discover the ID first: `document.querySelectorAll('input[id^=question_]')` or check label `for` attribute.
- **API challenge (Hightouch)**: some companies embed API challenges in JD — always read full JD first
  - `curl -X POST jobapi.hightouchdata.com:13784 -H "Content-Type: application/json" -d '{"email": "<email>"}'`
  - Put returned code in "Referred By" field (marked required *)
- **hCaptcha**: cannot automate — mark job as blocked if triggered

## Company-specific Notes
- **Databricks**: embed iframe on databricks.com; extract src and navigate directly to embed URL
- **SoFi**: careers page wraps Greenhouse iframe. Navigate directly to the extracted iframe src (job-boards.greenhouse.io URL) rather than using `frame=` param — direct navigation avoids cross-origin ref issues and simplifies form filling. Extract: `document.querySelector("iframe[src*=greenhouse]")?.src` on the sofi.com page.
- **Nuro**: cross-origin iframe; evaluate() blocked; use aria refs; wrapper URL auto-routes refs into iframe
- **Anthropic**: 255-char cap on "prompt engineering challenge" text input; `kind: "select"` does not work — use evaluate+listbox click
- **DoorDash**: `job-boards.greenhouse.io/doordashusa/jobs/<id>`; combobox overlays can drift — use JS option click by ID
- **Zscaler**: `Current Company` and `Current Title` required even if "never worked for Zscaler"; provide synthetic values
- **Glean**: single-page form, all fields including diversity visible at once; no pagination
- **Scale AI**: file dialog unstable — use "Enter manually" textarea fallback for resume
