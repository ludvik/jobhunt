"""CDP Greenhouse submit test v4 — fill everything, upload resume, submit."""
from __future__ import annotations
import sys, time, json
from pathlib import Path
from playwright.sync_api import sync_playwright, Page

TARGET_URL = "https://job-boards.greenhouse.io/reddit/jobs/6909091"
CDP_ENDPOINT = "http://127.0.0.1:18800"
DRY_RUN = "--dry-run" in sys.argv

# Use a real-looking resume for upload test
RESUME_PATH = "/Users/astra/.openclaw/data/jobhunt/resumes/355/resume.pdf"
if not Path(RESUME_PATH).exists():
    # Fallback: create a minimal PDF
    RESUME_PATH = "/tmp/test_resume.pdf"


def fill_react_select_by_label(page: Page, label_text: str, value: str):
    """Find react-select by its label text, click, type, select option."""
    clicked = page.evaluate(f"""(() => {{
        const labels = Array.from(document.querySelectorAll('label'));
        for (const l of labels) {{
            if (l.textContent.includes({json.dumps(label_text)})) {{
                const field = l.closest('.field') || l.parentElement;
                const input = field.querySelector('input[role="combobox"], input[id*="react-select"]');
                if (input) {{ input.click(); return true; }}
                // Maybe the label's sibling has a clickable div
                const div = field.querySelector('[class*="react-select"]');
                if (div) {{ div.querySelector('input')?.click() || div.click(); return true; }}
            }}
        }}
        return false;
    }})()""")
    if not clicked:
        print(f"  [FAIL] label={label_text!r} — not found")
        return False
    time.sleep(0.3)
    page.keyboard.type(value, delay=30)
    time.sleep(0.5)
    option = page.query_selector("[id*='react-select'][id*='option']")
    if option:
        option.click()
        print(f"  [OK] {label_text!r} = {value!r}")
        return True
    page.keyboard.press("Enter")
    print(f"  [OK?] {label_text!r} = {value!r} (Enter)")
    return True


def run_test():
    print(f"=== CDP Greenhouse v4 ===\nDry run: {DRY_RUN}\n")

    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(CDP_ENDPOINT)
        ctx = browser.contexts[0]
        page = ctx.new_page()
        page.goto(TARGET_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_selector("#first_name", timeout=15000)
        print("Form ready.\n")

        # 1. Standard text fields
        for fid, val in [("first_name","Test"),("last_name","Automation"),
                         ("email","test.automation.noreply@example.com"),("phone","0000000000")]:
            page.fill(f"#{fid}", val)
            print(f"  [OK] #{fid}")

        # 2. Location — react-select
        print("\nLocation:")
        fill_react_select_by_label(page, "Location (City)", "Seattle")
        time.sleep(1)  # wait for geocoding results
        option = page.query_selector("[id*='react-select'][id*='option']")
        if option:
            option.click()
            print("  [OK] Location selected")

        # 3. Resume upload
        print("\nResume:")
        if Path(RESUME_PATH).exists():
            file_input = page.query_selector('input[type="file"]')
            if file_input:
                file_input.set_input_files(RESUME_PATH)
                print(f"  [OK] Resume uploaded: {RESUME_PATH}")
                time.sleep(2)
            else:
                print("  [WARN] No file input found")
        else:
            print(f"  [SKIP] No resume at {RESUME_PATH}")

        # 4. Text questions
        print("\nText questions:")
        for fid, val in [("question_56910505","LinkedIn"),("question_56910509","TestCorp")]:
            page.fill(f"#{fid}", val)
            print(f"  [OK] #{fid}")

        # 5. React-select questions
        print("\nSelect questions:")
        for label, val in [
            ("Are you currently authorized to work in the U.S.", "Yes"),
            ("require immigration sponsorship", "No"),
            ("Are you located in Colorado", "No"),
        ]:
            fill_react_select_by_label(page, label, val)

        # 6. EEO react-selects (decline all)
        print("\nEEO:")
        eeo_labels = [
            "gender identity",
            "transgender",
            "Sexual orientation",
            "Disability",
            "Veteran",
            "Race",
        ]
        for label in eeo_labels:
            fill_react_select_by_label(page, label, "Decline")
            time.sleep(0.3)

        # 7. ALL checkboxes
        print("\nCheckboxes:")
        page.evaluate("""() => {
            document.querySelectorAll('input[type="checkbox"]').forEach(cb => {
                if (!cb.checked) {
                    const ev = new MouseEvent('click', {bubbles: true});
                    cb.dispatchEvent(ev);
                }
            });
        }""")
        print("  [OK] All checkboxes")

        page.screenshot(path="/tmp/cdp_gh_v4_pre.png", full_page=True)
        print(f"\nPre-submit: /tmp/cdp_gh_v4_pre.png")

        if DRY_RUN:
            print("[DRY RUN] Done.")
            page.close()
            return

        # Submit + intercept
        responses = []
        def on_response(resp):
            if resp.request.method == "POST" and ("greenhouse" in resp.url or "recaptcha" in resp.url):
                body = ""
                try: body = resp.text()[:500]
                except: pass
                responses.append({"url": resp.url, "status": resp.status, "body": body})
                print(f"\n  >>> POST {resp.url} => {resp.status}")

        page.on("response", on_response)
        print("\nSubmitting...")
        page.click('button[type="submit"]')

        print("Waiting 25s...")
        time.sleep(25)

        page.screenshot(path="/tmp/cdp_gh_v4_post.png", full_page=True)
        print(f"Post-submit: /tmp/cdp_gh_v4_post.png")

        if responses:
            for r in responses:
                s = r["status"]
                print(f"\n{r['url']} => {s}")
                if r["body"]: print(f"  Body: {r['body'][:300]}")
                if s in (200, 301, 302): print("\n*** reCAPTCHA PASSED! ***")
                elif s == 428: print("\n*** BLOCKED 428 ***")
                elif s == 422: print("\n*** 422 validation — reCAPTCHA likely passed ***")
                elif s == 400: print("\n*** 400 bad request ***")
        else:
            errors = page.evaluate("""() => {
                return Array.from(document.querySelectorAll('[class*="error"], .field-error'))
                    .map(e => e.textContent.trim()).filter(t => t);
            }""")
            if errors:
                print(f"\nStill {len(errors)} validation errors:")
                for e in errors[:15]: print(f"  - {e}")
            else:
                body = page.text_content("body")[:300]
                print(f"\nBody: {body}")

        page.close()
    print("\n=== Done ===")


if __name__ == "__main__":
    run_test()
