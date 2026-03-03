# Rippling ATS (ats.rippling.com)

## Overview
Single-page application form. No login required. Used by Shippo and others.

## Resume Upload
Arm `browser(action="upload")` then click the "Drop or select (.doc / .docx / .pdf)" button. Resume auto-parses and pre-fills fields — always verify after.

## Form Fields
- Required: Resume, First name, Last name, Email, Phone, Location, LinkedIn Link
- Optional: Pronouns (combobox), Current company, Cover letter
- Custom questions vary by job

## Phone Number
Country code selector (combobox, defaults to +1 US) + separate number field. Enter digits without formatting (e.g. `4253806253`).

## Combobox Pattern
Custom combobox components (not native `<select>`):
1. Click combobox to open dropdown
2. Click the option in the listbox
No typing needed for most EEO fields.

## Radio Buttons
Standard HTML radio buttons (not shadow DOM). `kind: "click"` with ref works fine.

## EEO Section
Standard EEO dropdowns at bottom: Gender, Race, Hispanic/Latino, Veteran Status, Disability Status. All use custom combobox. Options include "Choose not to disclose" / "I don't wish to answer".

## Confirmation
Heading: "Confirmation" with text "You have successfully applied to <job title>". URL: `?step=confirmation`
