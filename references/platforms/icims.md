# iCIMS Platform

## Overview
iCIMS is used by companies like Arm. LinkedIn redirects to `careers.<company>.com/job/...` then to `<company>.icims.com/jobs/.../job/login`.

## Known Issues
- **Heavy anti-bot protection**: hCaptcha, GDPR-style popups, and hidden iframes
- Main form content rarely becomes reachable in automation snapshots
- `frame` mode repeatedly times out
- No reliable retry path after frame timeouts

## Recommendation
Mark `apply_failed` immediately if iCIMS form content is unreachable. Do not attempt repeated retries. Escalate for human-assisted completion or a lower-level browser profile approach.
