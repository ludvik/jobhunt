"""Minimal test: connect CDP, navigate, wait for manual fill, then click submit + watch POST.
Fill the form manually in the browser, then press Enter here to trigger submit."""
from __future__ import annotations
import sys, time
from playwright.sync_api import sync_playwright

TARGET_URL = "https://job-boards.greenhouse.io/reddit/jobs/6909091"
CDP_ENDPOINT = "http://127.0.0.1:18800"


def run():
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(CDP_ENDPOINT)
        ctx = browser.contexts[0]
        page = ctx.new_page()
        page.goto(TARGET_URL, wait_until="networkidle", timeout=30000)
        print(f"Page loaded: {page.title()}")
        print(f"\n>>> Fill the form MANUALLY in the browser.")
        print(f">>> When ready, press Enter here to click Submit and monitor the POST.\n")
        input("Press Enter when form is filled... ")

        responses = []
        def on_response(resp):
            if resp.request.method == "POST":
                body = ""
                try: body = resp.text()[:800]
                except: pass
                responses.append({"url": resp.url, "status": resp.status, "body": body})
                print(f"  >>> POST {resp.url} => {resp.status}")
                if body: print(f"      Body: {body[:400]}")

        page.on("response", on_response)

        submit = page.query_selector('button[type="submit"]')
        if submit:
            print("Clicking submit...")
            submit.click()
        else:
            print("No submit button found. Trying JS click...")
            page.evaluate("document.querySelector('button[type=\"submit\"]')?.click()")

        print("Waiting 30s for POST...")
        time.sleep(30)

        page.screenshot(path="/tmp/cdp_submit_only.png", full_page=True)
        print(f"\nScreenshot: /tmp/cdp_submit_only.png")

        if responses:
            for r in responses:
                s = r["status"]
                if s in (200, 301, 302):
                    print(f"\n*** SUCCESS ({s}) — reCAPTCHA PASSED via CDP! ***")
                elif s == 428:
                    print(f"\n*** BLOCKED (428) — reCAPTCHA rejected ***")
                elif s == 422:
                    print(f"\n*** 422 — reCAPTCHA likely PASSED, form validation error ***")
                else:
                    print(f"\n*** Status {s} ***")
        else:
            print("\nNo POST intercepted — likely still validation errors in form.")

        page.close()
    print("Done.")

if __name__ == "__main__":
    run()
