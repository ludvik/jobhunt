# Lever ATS

## hCaptcha Block
Lever uses **invisible hCaptcha** on form submission. Automated submit returns:
> "There was an error verifying your application. Please try again."

The form fully resets after this failure (resume cleared, fields cleared). hCaptcha runs invisibly in the background — no visible widget appears.

**Evidence**: hCaptcha iframes visible in tabs list (`newassets.hcaptcha.com`).

**Action**: Mark `apply_failed` with note "CAPTCHA", send Discord report for manual follow-up. No automated workaround exists.

## Select/Combobox Pattern
Lever select elements frequently cause ref ambiguity (`Selector matched N elements`). Use JS evaluate:
```js
() => {
  const sels = document.querySelectorAll('select');
  let target;
  for (const s of sels) {
    if ([...s.options].some(o => o.text.includes('desired_option'))) {
      target = s; break;
    }
  }
  if (target) {
    target.value = 'value';
    target.dispatchEvent(new Event('change', {bubbles: true}));
    return 'done';
  }
  return 'not found';
}
```
