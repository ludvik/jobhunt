## Rippling ATS (ats.rippling.com) - 2026-03-03

### General Pattern
- Single-page application form (no multi-step pagination in most cases)
- No login required to apply
- Resume upload auto-parses and pre-fills fields (but fields should always be verified/filled manually)
- File upload: arm with `browser(action="upload")` then click the "Drop or select (.doc / .docx / .pdf)" button

### Form Fields (observed at Shippo)
Required: Resume, First name, Last name, Email, Phone, Location, LinkedIn Link
Optional: Pronouns (combobox), Current company, Cover letter
Custom questions vary by job

### EEO Section
Standard EEO dropdowns at bottom: Gender, Race, Hispanic/Latino, Veteran Status, Disability Status
All use custom combobox (click to open, click option to select — NOT `kind: "select"`)
Options include "Choose not to disclose" / "I don't wish to answer"

### Radio Buttons
Standard HTML radio buttons (not shadow DOM like LinkedIn). `kind: "click"` with ref works fine.

### Combobox Pattern
Rippling uses custom combobox components (not native `<select>`):
1. Click the combobox to open dropdown
2. Click the option in the listbox
3. No typing needed for most EEO fields

### Confirmation
Rippling shows a "Confirmation" heading page with text:
"You have successfully applied to <job title>"
URL changes to `?step=confirmation`

### Phone Number
Phone field has a country code selector (combobox, defaults to +1 US) + separate number field
Enter digits without formatting (e.g. "4253806253")
