#!/usr/bin/env python3
"""
capture_mockup_screenshot.py — Screenshot a mockup HTML file using Playwright.

Returns a PNG image at 1200x630px (og:image / email thumbnail size).
Works with local file paths or hosted URLs.

Requires: pip install playwright && python -m playwright install chromium

USAGE — standalone
    python3 capture_mockup_screenshot.py mockups/Bloom-Florist.html
    python3 capture_mockup_screenshot.py https://... --out preview.png

USAGE — imported
    from capture_mockup_screenshot import capture_to_b64, capture_to_file
    b64_str = capture_to_b64("mockups/Bloom-Florist.html")  # base64 PNG
    path    = capture_to_file("mockups/Bloom-Florist.html") # saves .png, returns Path
"""

import argparse
import base64
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
SCREENSHOT_DIR = SCRIPT_DIR / "screenshots"

DEFAULT_WIDTH  = 1200
DEFAULT_HEIGHT = 630


def capture_mockup(source: str, width: int = DEFAULT_WIDTH, height: int = DEFAULT_HEIGHT) -> bytes:
    """
    Screenshot a mockup HTML file or URL.
    source: local file path string OR https:// URL
    Returns PNG bytes.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError(
            "Playwright not installed.\n"
            "  pip install playwright\n"
            "  python -m playwright install chromium"
        )

    if source.startswith("http://") or source.startswith("https://"):
        url = source
    else:
        path = Path(source)
        if not path.is_absolute():
            path = SCRIPT_DIR / path
        url = f"file://{path.absolute()}"

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": width, "height": height})
        page.goto(url, wait_until="networkidle", timeout=15000)
        png = page.screenshot(clip={"x": 0, "y": 0, "width": width, "height": height})
        browser.close()

    return png


def capture_to_b64(source: str, width: int = DEFAULT_WIDTH, height: int = DEFAULT_HEIGHT) -> str:
    """Return base64-encoded PNG string (suitable for embedding in email HTML)."""
    png = capture_mockup(source, width, height)
    return base64.b64encode(png).decode("ascii")


def capture_to_file(source: str, out_path: str = "", width: int = DEFAULT_WIDTH, height: int = DEFAULT_HEIGHT) -> Path:
    """Screenshot and save to file. Returns the output Path."""
    SCREENSHOT_DIR.mkdir(exist_ok=True)

    if out_path:
        dest = Path(out_path)
    else:
        stem = Path(source).stem if not source.startswith("http") else "screenshot"
        dest = SCREENSHOT_DIR / f"{stem}.png"

    png = capture_mockup(source, width, height)
    dest.write_bytes(png)
    return dest


def screenshot_html_for_email(name: str, category: str = "") -> str:
    """
    Convenience: screenshot the local mockup HTML for a business and return base64.
    Returns '' if no matching HTML file or Playwright fails.
    """
    slug = "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")
    candidates = list((SCRIPT_DIR / "mockups").glob(f"{slug}*.html"))
    if not candidates:
        return ""
    try:
        return capture_to_b64(str(candidates[0]))
    except Exception:
        return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source", help="Local HTML file path or https:// URL")
    ap.add_argument("--out",    default="", help="Output PNG path")
    ap.add_argument("--width",  type=int, default=DEFAULT_WIDTH)
    ap.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    ap.add_argument("--b64",    action="store_true", help="Print base64 to stdout instead of saving")
    args = ap.parse_args()

    if args.b64:
        print(capture_to_b64(args.source, args.width, args.height))
    else:
        dest = capture_to_file(args.source, args.out, args.width, args.height)
        print(f"Saved: {dest}  ({dest.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
