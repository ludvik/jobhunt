"""Experiment v3: Fill ALL fields properly, then submit.
Goal: does reCAPTCHA Enterprise block Playwright submission?
"""
from __future__ import annotations
import sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright, Page

TARGET_URL = "https://job-boards.greenhouse.io/reddit/jobs/6909091"

def create_dummy_resume() -> Path:
    p = Path("/tmp/test_resume.pdf")
    p.write_bytes(
        b"%PDF-1.0\n1 0 obj<</Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</MediaBox[0 0 612 792]>>endobj\n"
        b"xref\n0 4\n0000000000 65535 f \n"
        b"0000000009 00000 n \n0000000058 00000 n \n"
        b"0000000115 00000 n \ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n190\n%%EOF"
    )
    return p


def pick_select(page: Page, field_id: str, option_text: str, label: str = ""):
    """Open a Greenhouse react-select by field id, type to filter, click option."""
    # The select container has the label with for=field_id
    # The clickable control is inside .select-shell
    container = page.locator(f"label[for='{field_id}']").locator("xpath=..").first
    control = container.locator(".select-shell").first
    if control.count() == 0:
        print(f"  [MISS] No select-shell for {field_id} ({label[:40]})")
        return
    control.click()
    time.sleep(0.3)
    page.keyboard.type(option_text[:12], delay=30)
    time.sleep(0.5)
    
    # Find matching option in the open menu
    options = page.locator("[id*='-option-']")
    for i in range(options.count()):
        txt = options.nth(i).inner_text()
        if option_text.lower() in txt.lower():
            options.nth(i).click()
            print(f"  [OK] {field_id}: '{txt[:50]}'")
            return
    # Fallback: first option
    if options.count() > 0:
        txt = options.first.inner_text()
        options.first.click()
        print(f"  [FALLBACK] {field_id}: '{txt[:50]}'")
    else:
        page.keyboard.press("Escape")
        print(f"  [MISS] {field_id}: no options matched '{option_text}'")


def run_test(headless: bool = False):
    resume = create_dummy_resume()
    print(f"=== Greenhouse reCAPTCHA v3 ===\nTarget: {TARGET_URL}\nHeadless: {headless}\n")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900},
            locale="en-US",
        )
        ctx.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page = ctx.new_page()

        page.goto(TARGET_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_selector("#first_name", timeout=15000)
        print("Form loaded.\n")

        # --- Text inputs ---
        print("Text fields:")
        for fid, val in [
            ("first_name", "Test"), ("last_name", "Automation"),
            ("email", "test.automation.throwaway@gmail.com"),
            ("phone", "+15550000000"),
            ("question_56910504", "https://linkedin.com/in/testautomation"),  # LinkedIn
            ("question_56910505", "LinkedIn"),  # How did you hear
            ("question_56910509", "TestCorp"),  # Current company
        ]:
            el = page.locator(f"#{fid}")
            if el.count() > 0:
                el.fill(val)
                print(f"  [OK] #{fid} = {val[:30]}")
            else:
                print(f"  [MISS] #{fid}")

        # --- Resume upload ---
        print("\nResume:")
        fi = page.locator("input[type='file']")
        if fi.count() > 0:
            fi.first.set_input_files(str(resume))
            print("  [OK] Uploaded")
            time.sleep(1)

        # --- Selects ---
        print("\nDropdowns:")
        select_map = [
            ("country", "United States"),
            ("candidate-location", "Seattle"),
            ("question_56910506", "Yes"),   # authorized to work
            ("question_56910507", "No"),    # sponsorship
            ("question_56910508", "I agree"),  # privacy
            ("question_58737519", "No"),    # Colorado/UK
            ("430", "I don't wish"),   # gender
            ("431", "I don't wish"),   # transgender
            ("432", "I don't wish"),   # sexual orientation
            ("433", "I don't wish"),   # disability
            ("434", "I don't wish"),   # veteran
            ("436", "I don't wish"),   # ethnicity
        ]
        for fid, opt in select_map:
            pick_select(page, fid, opt, fid)
            time.sleep(0.2)

        # --- Checkbox ---
        print("\nCheckboxes:")
        cbs = page.locator("input[type='checkbox']")
        for i in range(cbs.count()):
            if not cbs.nth(i).is_checked():
                cbs.nth(i).check()
                print(f"  [OK] Checked #{i}")

        # --- Screenshot ---
        page.screenshot(path="/tmp/gh_v3_pre_submit.png", full_page=True)
        print("\nPre-submit screenshot saved.")

        # --- Submit ---
        print("\n=== SUBMITTING ===")
        captured = {"status": None, "url": None, "body": None}

        def on_resp(resp):
            if resp.request.method == "POST" and "greenhouse" in resp.url:
                captured["status"] = resp.status
                captured["url"] = resp.url
                try:
                    captured["body"] = resp.text()[:1000]
                except:
                    captured["body"] = "(unreadable)"
                print(f"  >>> POST {resp.url}")
                print(f"  >>> HTTP {resp.status}")

        page.on("response", on_resp)
        page.locator("button:has-text('Submit')").first.click()

        time.sleep(10)

        print("\n=== RESULT ===")
        if captured["status"]:
            s = captured["status"]
            if s in (200, 201):
                print(f"  HTTP {s} — SUCCESS. reCAPTCHA did NOT block.")
            elif s == 302:
                print(f"  HTTP {s} — Redirect (likely success).")
            elif s == 422:
                print(f"  HTTP {s} — Validation error. CAPTCHA PASSED, form data rejected.")
            elif s == 428:
                print(f"  HTTP {s} — CAPTCHA BLOCKED.")
            elif s == 400:
                print(f"  HTTP {s} — Bad request.")
            else:
                print(f"  HTTP {s} — unexpected.")
            print(f"  Body: {captured['body'][:500]}")
        else:
            print("  No POST captured.")
            url = page.url
            print(f"  URL: {url}")
            if "thank" in page.content().lower():
                print("  THANK YOU page — full success!")
            else:
                errs = page.locator("[class*='error']")
                print(f"  Validation errors: {errs.count()}")
                for i in range(min(errs.count(), 5)):
                    print(f"    - {errs.nth(i).inner_text()[:80]}")

        page.screenshot(path="/tmp/gh_v3_post_submit.png", full_page=True)
        print(f"\nPost-submit screenshot: /tmp/gh_v3_post_submit.png")
        browser.close()

    print("\n=== Done ===")


if __name__ == "__main__":
    run_test(headless="--headless" in sys.argv)
