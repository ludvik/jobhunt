
## hCaptcha on Lever (discovered 2026-03-02, Job 342 - Zoox)
Lever uses **hCaptcha** for bot protection on form submission. When the automated browser submits the form, Lever returns:
> "✱ There was an error verifying your application. Please try again."

The form fully resets (resume cleared, some fields cleared) after this failure. The hCaptcha challenge runs invisibly in the background and cannot be solved in automated browser flow.

**Workaround:** None found for automated submission. Mark `apply_failed` with note "CAPTCHA" and send Discord report for manual follow-up.

**Evidence:** hCaptcha iframes visible in tabs list (`newassets.hcaptcha.com`). The error fires immediately on submit click — no visible CAPTCHA widget appears, it's an invisible/background challenge.

**Note on `select` refs:** Lever combobox/select elements frequently cause ref ambiguity errors (`Selector matched N elements`). Use JS evaluate to set select values instead:
```js
() => {
  const sels = document.querySelectorAll('select');
  let target;
  for (const s of sels) {
    if ([...s.options].some(o => o.text.includes('desired_option'))) {
      target = s; break;
    }
  }
  if (target) { target.value = 'value'; target.dispatchEvent(new Event('change', {bubbles: true})); return 'done'; }
  return 'not found';
}
```
