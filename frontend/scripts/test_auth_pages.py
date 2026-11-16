import os
import sys
import time
from playwright.sync_api import sync_playwright

BASE_URL = os.environ.get("PREVIEW_URL", "http://localhost:4173")
SHOTS_DIR = os.path.join(os.path.dirname(__file__), "..", ".audit", "auth_shots")
os.makedirs(SHOTS_DIR, exist_ok=True)

def test_auth_flows():
    print(f"Testing Authentication experience against {BASE_URL}...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        # 1. Test /sign-in page
        print("[1] Verifying /sign-in (Desktop 1280x800)...")
        page.goto(f"{BASE_URL}/sign-in")
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)

        # Check title and elements
        assert "Sign In" in page.title()
        assert page.locator("h1:has-text('Welcome back')").is_visible()
        assert page.locator("input#signin-email").is_visible()
        assert page.locator("input#signin-password").is_visible()
        assert page.locator("text=Deterministic Civil Engineering Core").is_visible()

        # Capture screenshot
        page.screenshot(path=os.path.join(SHOTS_DIR, "01_sign_in_desktop.png"), full_page=True)

        # Test Caps lock warning on password field
        page.locator("input#signin-password").focus()
        page.keyboard.press("CapsLock")
        page.locator("input#signin-password").type("a")
        time.sleep(0.2)
        page.keyboard.press("CapsLock") # toggle off

        # Test empty submit error feedback
        page.locator("button[type='submit']").click()
        time.sleep(0.3)
        assert page.locator("role=alert").is_visible()
        assert "Please enter both" in page.locator("role=alert").text_content()
        page.screenshot(path=os.path.join(SHOTS_DIR, "02_sign_in_validation_error.png"))

        # 2. Test /sign-up page
        print("[2] Verifying /sign-up...")
        page.goto(f"{BASE_URL}/sign-up")
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)

        assert "Create Account" in page.title()
        assert page.locator("h1:has-text('Create your account')").is_visible()

        # Type weak password -> check strength indicators
        page.locator("input#signup-password").type("abc")
        time.sleep(0.2)
        assert page.locator("text=8+ characters").is_visible()

        # Type robust password -> check strength indicators
        page.locator("input#signup-password").fill("RobustPassword999!")
        page.locator("input#signup-confirm-password").fill("RobustPassword999!")
        time.sleep(0.3)
        assert page.locator("text=Passwords match").is_visible()

        page.screenshot(path=os.path.join(SHOTS_DIR, "03_sign_up_strength_meter.png"), full_page=True)

        # 3. Test /forgot-password page
        print("[3] Verifying /forgot-password...")
        page.goto(f"{BASE_URL}/forgot-password")
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)

        assert "Password Recovery" in page.title()
        assert page.locator("text=Request Code").is_visible()
        assert page.locator("input#forgot-email").is_visible()

        page.screenshot(path=os.path.join(SHOTS_DIR, "04_forgot_password.png"), full_page=True)

        # 4. Test /reset-password page
        print("[4] Verifying /reset-password with Segmented 6-Box OTP...")
        page.goto(f"{BASE_URL}/reset-password?email=architect%40buildwise.ai")
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)

        assert page.locator("h1:has-text('Set new password')").is_visible()
        # Verify 6 segmented input boxes exist
        for i in range(6):
            assert page.locator(f"input#otp-box-{i}").is_visible()

        # Type OTP digits
        page.locator("input#otp-box-0").type("1")
        page.locator("input#otp-box-1").type("2")
        page.locator("input#otp-box-2").type("3")
        page.locator("input#otp-box-3").type("4")
        page.locator("input#otp-box-4").type("5")
        page.locator("input#otp-box-5").type("6")
        time.sleep(0.2)

        page.screenshot(path=os.path.join(SHOTS_DIR, "05_reset_password_otp.png"), full_page=True)

        # 5. Test /verify-email page
        print("[5] Verifying /verify-email with Segmented 6-Box OTP and Masked Email...")
        page.goto(f"{BASE_URL}/verify-email?email=architect%40buildwise.ai")
        page.wait_for_load_state("networkidle")
        time.sleep(0.5)

        assert "Verify Email" in page.title()
        assert page.locator("h1:has-text('Verify your email')").is_visible()
        # Check masked email presentation
        assert page.locator("text=a***t@b***e.ai").is_visible()

        # Check 6 segmented input boxes exist
        otp_inputs = page.locator("input[inputmode='numeric']")
        assert otp_inputs.count() == 6

        # Type OTP digits
        for i in range(6):
            otp_inputs.nth(i).type(str(i + 1))
        time.sleep(0.2)

        page.screenshot(path=os.path.join(SHOTS_DIR, "06_verify_email_otp.png"), full_page=True)

        # 6. Test Mobile Viewport (390x844) on /sign-in, /sign-up, and /verify-email
        print("[6] Verifying Mobile Viewport (390x844)...")
        mobile_context = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True)
        mobile_page = mobile_context.new_page()

        mobile_page.goto(f"{BASE_URL}/verify-email?email=architect%40buildwise.ai")
        mobile_page.wait_for_load_state("networkidle")
        time.sleep(0.5)
        can_scroll_x = mobile_page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
        assert not can_scroll_x, "Mobile verify-email has horizontal overflow!"
        mobile_page.screenshot(path=os.path.join(SHOTS_DIR, "07_verify_email_mobile_390.png"), full_page=True)

        mobile_page.goto(f"{BASE_URL}/sign-in")
        mobile_page.wait_for_load_state("networkidle")
        time.sleep(0.5)
        # Check no horizontal scroll
        can_scroll_x = mobile_page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
        assert not can_scroll_x, "Mobile sign-in has horizontal overflow!"
        mobile_page.screenshot(path=os.path.join(SHOTS_DIR, "08_sign_in_mobile_390.png"), full_page=True)

        # 7. Test Unauthenticated bounce from /app
        print("[7] Verifying Unauthenticated bounce from /app...")
        mobile_page.goto(f"{BASE_URL}/app")
        mobile_page.wait_for_load_state("networkidle")
        time.sleep(1.0)
        # Should be redirected to /sign-in
        assert "/sign-in" in mobile_page.url
        print(f"Bounced safely to: {mobile_page.url}")

        browser.close()
        print("ALL AUTHENTICATION BROWSER VERIFICATIONS PASSED!")

if __name__ == "__main__":
    test_auth_flows()
