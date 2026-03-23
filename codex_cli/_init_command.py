"""Interactive config setup wizard (codex-cli init)."""

from __future__ import annotations

import getpass
import subprocess
import sys
from pathlib import Path


def cmd_init(args, config) -> int:
    """Interactive setup wizard for codex-cli."""
    env_path = Path(".env")

    if env_path.is_file():
        overwrite = input(".env already exists. Overwrite? [y/N]: ").strip().lower()
        if overwrite != "y":
            print("Keeping existing .env")
            return 0

    print("\n=== codex-cli setup ===\n")

    email = input("ChatGPT email: ").strip()
    if not email:
        print("Email is required.")
        return 1

    password = getpass.getpass("ChatGPT password: ")
    if not password:
        print("Password is required.")
        return 1

    totp = input("TOTP secret (base32, press Enter to skip): ").strip()

    env_name = input("Default environment/repo (press Enter to skip): ").strip()

    headless = input("Run headless by default? [Y/n]: ").strip().lower()
    headless = "false" if headless == "n" else "true"

    # Write .env
    lines = [
        f"CODEX_EMAIL={email}",
        f"CODEX_PASSWORD={password}",
    ]
    if totp:
        lines.append(f"CODEX_TOTP_SECRET={totp}")
    if env_name:
        lines.append(f"CODEX_ENV={env_name}")
    lines.append(f"CODEX_HEADLESS={headless}")
    lines.append("CODEX_REQUEST_PR=true")

    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nConfig written to {env_path}")

    # Check Playwright browsers
    print("\nChecking Playwright browsers...")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode == 0:
            print("Chromium browser installed/verified.")
        else:
            print(f"Warning: Playwright install returned code {result.returncode}")
            if result.stderr:
                print(result.stderr[:200])
    except Exception as e:
        print(f"Warning: Could not install Playwright browsers: {e}")
        print("Run manually: python -m playwright install chromium")

    # Offer test login
    test = input("\nTest login now? [Y/n]: ").strip().lower()
    if test != "n":
        print("Running login test...")
        try:
            from .config import load_config
            from ._session import codex_session

            cfg = load_config()
            cfg.headless = False
            with codex_session(cfg) as client:
                print("Login successful!")
        except Exception as e:
            print(f"Login failed: {e}")
            print("You can retry with: codex-cli --show-browser login")

    print("\nSetup complete! Try: codex-cli list-tasks")
    return 0
