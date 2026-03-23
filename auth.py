#!/usr/bin/env python3
"""Login flow and session persistence for ChatGPT/Codex."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

try:
    import pyotp
except ImportError:
    pyotp = None  # type: ignore[assignment]

if TYPE_CHECKING:
    from playwright.sync_api import Page, BrowserContext
    from config import Config

log = logging.getLogger(__name__)

# --- Selectors for login page detection and interaction ---

LOGIN_PAGE_INDICATORS = [
    "input[name='email']",
    "input[name='username']",
    "input[type='email']",
    "button:has-text('Log in')",
    "button:has-text('Sign in')",
    "[data-testid='login-button']",
]

WELCOME_BUTTON_SELECTORS = [
    "a[href*='/auth/login']",
    "a:has-text('Log in')",
    "button:has-text('Log in')",
    "button:has-text('Sign in')",
    "a:has-text('Sign in')",
]

EMAIL_INPUT_SELECTORS = [
    "input[name='email']",
    "input[name='username']",
    "input[type='email']",
    "input[id='email-input']",
    "#username",
]

CONTINUE_BUTTON_SELECTORS = [
    "button[type='submit']",
    "button:has-text('Continue')",
    "button:has-text('Next')",
    "input[type='submit']",
]

PASSWORD_INPUT_SELECTORS = [
    "input[name='password']",
    "input[type='password']",
    "input[id='password']",
]

PASSWORD_SUBMIT_SELECTORS = [
    "button[type='submit']",
    "button:has-text('Continue')",
    "button:has-text('Log in')",
    "button:has-text('Sign in')",
]

CAPTCHA_INDICATORS = [
    "iframe[src*='captcha']",
    "iframe[src*='challenge']",
    "[class*='captcha']",
    "[id*='captcha']",
    "iframe[src*='turnstile']",
]

MFA_INDICATORS = [
    "input[name='code']",
    "input[name='totp']",
    "input[placeholder*='code']",
    "[data-testid*='mfa']",
]

CODEX_READY_INDICATORS = [
    "textarea[placeholder*='Ask Codex']",
    "button:has-text('New thread')",
    "[data-slot='button'][data-kind='sidebar']",
    "textarea#prompt-textarea",
    "textarea[placeholder*='Message']",
    "textarea[placeholder*='task']",
    "[data-testid='codex-main']",
    "div[contenteditable='true'][data-lexical-editor='true']",
    "a[href*='/codex/tasks/']",
]

# If any of these are visible, the user is NOT logged in (marketing/landing page)
LOGGED_OUT_INDICATORS = [
    "a[href*='/auth/login']",
    "a:has-text('Log in')",
    "button:has-text('Log in')",
    "button:has-text('Sign up')",
    "a:has-text('Sign up')",
    "button:has-text('Download for Windows')",
    "button:has-text('Try ChatGPT')",
]


def _first_visible(page: "Page", selectors: list[str]):
    """Return the first visible element matching any selector, or None."""
    for selector in selectors:
        try:
            loc = page.locator(selector)
            if loc.count() and loc.first.is_visible():
                return loc.first
        except Exception:
            continue
    return None


def _any_present(page: "Page", selectors: list[str]) -> bool:
    """Return True if any selector matches a visible element."""
    return _first_visible(page, selectors) is not None


def is_logged_in(page: "Page") -> bool:
    """Check whether the page shows Codex (logged in) rather than a login screen."""
    url = page.url.lower()
    # If we're on an auth/login URL, definitely not logged in
    if "/auth" in url or "/login" in url:
        return False
    # If logged-out indicators are visible, we're on the public/marketing page
    if _any_present(page, LOGGED_OUT_INDICATORS):
        return False
    # Check for Codex-specific UI elements
    return _any_present(page, CODEX_READY_INDICATORS)


def _wait_for_login_page(page: "Page", timeout_s: float = 30) -> None:
    """Wait until a login form or welcome button appears."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if _any_present(page, LOGIN_PAGE_INDICATORS) or _any_present(page, WELCOME_BUTTON_SELECTORS):
            return
        if is_logged_in(page):
            return  # Already logged in, no need to wait for login page
        time.sleep(1)
    log.warning("Login page elements not found within timeout; proceeding anyway")


def _handle_mfa(page: "Page", totp_secret: str = "") -> None:
    """Handle MFA/TOTP step. Auto-fills if secret is available, otherwise waits for manual entry."""
    if totp_secret and pyotp is not None:
        log.info("Auto-generating TOTP code...")
        totp = pyotp.TOTP(totp_secret)
        code = totp.now()
        log.info(f"Generated TOTP code: {code}")

        # Find the code input field
        code_input = _first_visible(page, [
            "input[name='code']",
            "input[name='totp']",
            "input[placeholder*='code']",
            "input[placeholder*='Code']",
            "input[type='tel']",
            "input[inputmode='numeric']",
            "input[autocomplete='one-time-code']",
        ])
        if code_input:
            code_input.click()
            code_input.fill(code)
            time.sleep(1)

            # Submit the code
            submit = _first_visible(page, [
                "button[type='submit']",
                "button:has-text('Continue')",
                "button:has-text('Verify')",
                "button:has-text('Submit')",
            ])
            if submit:
                submit.click()
            else:
                code_input.press("Enter")
            time.sleep(5)

            if is_logged_in(page):
                log.info("MFA completed successfully!")
                return

            # Code might have expired, try once more with a fresh code
            log.warning("First TOTP attempt may have failed, retrying with fresh code...")
            time.sleep(5)  # Wait for next TOTP window
            code = totp.now()
            code_input = _first_visible(page, [
                "input[name='code']",
                "input[name='totp']",
                "input[placeholder*='code']",
                "input[placeholder*='Code']",
                "input[type='tel']",
                "input[inputmode='numeric']",
                "input[autocomplete='one-time-code']",
            ])
            if code_input:
                code_input.click()
                code_input.fill(code)
                time.sleep(1)
                submit = _first_visible(page, [
                    "button[type='submit']",
                    "button:has-text('Continue')",
                    "button:has-text('Verify')",
                    "button:has-text('Submit')",
                ])
                if submit:
                    submit.click()
                else:
                    code_input.press("Enter")
                time.sleep(5)
        else:
            log.warning("Could not find TOTP input field")
    else:
        if not totp_secret:
            log.warning("No TOTP secret configured. Set CODEX_TOTP_SECRET in .env")
        if pyotp is None:
            log.warning("pyotp not installed. Install with: pip install pyotp")
        log.warning("Waiting up to 120s for manual MFA entry...")

    # Final wait for login to complete (covers manual entry or auto-fill)
    mfa_deadline = time.time() + 120
    while time.time() < mfa_deadline:
        if is_logged_in(page):
            log.info("MFA completed!")
            return
        time.sleep(2)
    if not is_logged_in(page):
        raise RuntimeError("MFA was not completed within timeout")


def perform_login(page: "Page", email: str, password: str, timeout_s: float = 120, totp_secret: str = "") -> None:
    """Walk through the OpenAI/ChatGPT login flow.

    The flow has multiple steps:
    1. Codex marketing page → click "Log in" link
    2. ChatGPT "Get started" page → click "Log in" button
    3. Auth form → enter email → Continue
    4. Password form → enter password → Continue
    5. Wait for redirect back to Codex
    """
    log.info("Starting login flow...")

    # If already logged in after navigation, skip
    if is_logged_in(page):
        log.info("Already logged in after navigation")
        return

    # Step 1: Click "Log in" link on Codex marketing page (it's an <a> tag)
    login_link = _first_visible(page, ["a[href*='/auth/login']", "a:has-text('Log in')"])
    if login_link:
        log.info("Clicking 'Log in' link on Codex page...")
        login_link.click()
        time.sleep(5)

    # Step 2: Click "Log in" button on "Get started" page (if present)
    login_btn = _first_visible(page, ["button:has-text('Log in')"])
    if login_btn:
        log.info("Clicking 'Log in' button on Get Started page...")
        login_btn.click()
        time.sleep(5)

    # Wait for auth form to appear
    log.info(f"Auth page URL: {page.url}")

    # Step 3: Fill email
    log.info("Looking for email input...")
    deadline = time.time() + 30
    email_input = None
    while time.time() < deadline:
        email_input = _first_visible(page, EMAIL_INPUT_SELECTORS)
        if email_input:
            break
        # Maybe there's another "Log in" button we missed
        btn = _first_visible(page, ["button:has-text('Log in')", "button:has-text('Sign in')"])
        if btn:
            log.info("Found another login button, clicking...")
            btn.click()
            time.sleep(3)
        time.sleep(1)

    if email_input is None:
        if is_logged_in(page):
            log.info("Already logged in")
            return
        raise RuntimeError("Could not find email input field. Page URL: " + page.url)

    log.info("Entering email...")
    email_input.click()
    email_input.fill(email)
    time.sleep(1)

    # Click continue
    continue_btn = _first_visible(page, CONTINUE_BUTTON_SELECTORS)
    if continue_btn:
        continue_btn.click()
    else:
        email_input.press("Enter")
    time.sleep(5)

    # Step 3b: Handle CAPTCHA if present
    if _any_present(page, CAPTCHA_INDICATORS):
        log.warning(
            "CAPTCHA detected! If running headless, re-run with CODEX_HEADLESS=false "
            "to solve it manually. Waiting up to 120s for manual solve..."
        )
        captcha_deadline = time.time() + 120
        while time.time() < captcha_deadline:
            if not _any_present(page, CAPTCHA_INDICATORS):
                break
            time.sleep(2)
        if _any_present(page, CAPTCHA_INDICATORS):
            raise RuntimeError("CAPTCHA was not solved within timeout")

    # Step 4: Fill password
    log.info("Looking for password input...")
    deadline = time.time() + 30
    pw_input = None
    while time.time() < deadline:
        pw_input = _first_visible(page, PASSWORD_INPUT_SELECTORS)
        if pw_input:
            break
        time.sleep(1)

    if pw_input is None:
        if is_logged_in(page):
            log.info("Already logged in (no password step)")
            return
        raise RuntimeError("Could not find password input field. Page URL: " + page.url)

    log.info("Entering password...")
    pw_input.click()
    pw_input.fill(password)
    time.sleep(1)

    pw_submit = _first_visible(page, PASSWORD_SUBMIT_SELECTORS)
    if pw_submit:
        pw_submit.click()
    else:
        pw_input.press("Enter")
    time.sleep(5)

    # Step 5: Handle MFA/TOTP if present
    if _any_present(page, MFA_INDICATORS):
        log.info("MFA/2FA step detected")
        _handle_mfa(page, totp_secret=totp_secret)

    # Step 6: Wait for redirect back to Codex
    log.info("Waiting for Codex page to load after login...")
    login_deadline = time.time() + timeout_s
    while time.time() < login_deadline:
        if is_logged_in(page):
            log.info("Login successful!")
            return
        time.sleep(2)

    raise RuntimeError(f"Login did not complete within {timeout_s}s. Final URL: {page.url}")


def ensure_authenticated(
    context: "BrowserContext",
    page: "Page",
    config: "Config",
) -> None:
    """Navigate to Codex and ensure we're logged in, persisting session on success."""
    log.info(f"Navigating to {config.codex_url}")
    page.goto(config.codex_url, wait_until="domcontentloaded", timeout=60_000)
    time.sleep(3)

    if is_logged_in(page):
        log.info("Session restored from storage state — already logged in")
        return

    if not config.has_credentials:
        raise RuntimeError(
            "Not logged in and no credentials available. "
            "Set CODEX_EMAIL and CODEX_PASSWORD, or delete the storage state file "
            "and re-run with credentials."
        )

    perform_login(page, config.email, config.password, timeout_s=config.login_timeout_s, totp_secret=config.totp_secret)

    # Persist session
    log.info(f"Saving session to {config.storage_state_path}")
    context.storage_state(path=config.storage_state_path)
