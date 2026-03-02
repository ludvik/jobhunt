# iCIMS Platform Notes

- **2026-03-01 (Job 116 - Arm, LinkedIn apply)**: LinkedIn "Apply on company website" for Arm resolves to `careers.arm.com/job/seattle/staff-software-engineer-ai-agents/33099/91812705936` and then to `experienced-arm.icims.com/jobs/.../job/login`.
- **2026-03-01 (Job 116)**: The iCIMS pages surfaced aggressive anti-bot/consent layers (`hCaptcha`, GDPR-style popups and hidden `iframe`s), and the main form content never became directly reachable in automation snapshots (`frame` mode repeatedly timed out).
- **2026-03-01 (Job 116)**: On this run, applying via openclaw browser required robust iframe handling plus CAPTCHA bypass support; no reliable retry path existed after the frame timeouts, so automation should either switch to a human-assisted or lower-level browser profile path.
