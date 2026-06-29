#!/usr/bin/env python3
"""Isolated MCXCCL bullion warehouse-stock scraper (runs as a SUBPROCESS, once/day).

Why a separate process: Playwright + headless Chromium are heavy. Spawning this
from mcxccl_service via subprocess (and killing it on a timeout) means the
~300 MB Chromium footprint and the playwright/pdfplumber imports NEVER live in
the long-running FastAPI process, and a crash/hang here can't touch the live feed.

Output: one JSON object on stdout, then exit 0:
    {"ok": true, "as_on_date": "2026-05-29", "source_url": "...",
     "rows": [{"commodity": "GOLD", "unit": "KG", "eligible_units": 2454.0}, ...]}
On failure: {"ok": false, "error": "..."} on stdout and a non-zero exit code.

mcxccl.com sits behind Akamai bot-protection: a plain request (even real headless
Chromium with a normal UA) gets 403 Access Denied. The stealth init-script +
anti-automation launch flags below defeat the headless fingerprinting and pass.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import sys

PAGE_URL = os.environ.get(
    "MCXCCL_STOCK_PAGE_URL",
    "https://www.mcxccl.com/warehousing-logistics/stock-position",
)
NAV_TIMEOUT_MS = int(os.environ.get("MCXCCL_NAV_TIMEOUT_MS", "45000"))

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
HEADERS = {
    "Accept-Language": "en-US,en;q=0.9",
    "Upgrade-Insecure-Requests": "1",
    "sec-ch-ua": '"Chromium";v="126", "Not?A_Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
}
# Defeats Akamai's headless-Chromium fingerprinting.
STEALTH = (
    "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
    "Object.defineProperty(navigator,'languages',{get:()=>['en-US','en']});"
    "Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3,4,5]});"
    "window.chrome={runtime:{}};"
)
LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-dev-shm-usage",
]

# Optional explicit overrides; otherwise we auto-detect a working browser.
CHROME_CHANNEL = os.environ.get("MCXCCL_CHROME_CHANNEL", "").strip()  # e.g. "chrome"
CHROME_PATH = os.environ.get("MCXCCL_CHROME_PATH", "").strip()        # e.g. /usr/bin/google-chrome
# System browsers to try when Playwright's bundled Chromium is unavailable
# (e.g. a brand-new Ubuntu Playwright has no build for). Install Google Chrome's
# .deb and it lands at /usr/bin/google-chrome.
_FALLBACK_PATHS = (
    "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium", "/usr/bin/chromium-browser", "/snap/bin/chromium",
)


def _launch(p):
    """Launch via the first strategy that works: explicit override → bundled
    Chromium → 'chrome'/'chromium' channel → known system paths."""
    attempts = []
    if CHROME_PATH:
        attempts.append(("executable_path", CHROME_PATH))
    elif CHROME_CHANNEL:
        attempts.append(("channel", CHROME_CHANNEL))
    else:
        attempts.append(("bundled", None))
        attempts.append(("channel", "chrome"))
        attempts.append(("channel", "chromium"))
        attempts += [("executable_path", path) for path in _FALLBACK_PATHS]
    errors = []
    for kind, val in attempts:
        kw = {"headless": True, "args": LAUNCH_ARGS}
        if kind == "channel":
            kw["channel"] = val
        elif kind == "executable_path":
            if not os.path.exists(val):
                continue
            kw["executable_path"] = val
        try:
            return p.chromium.launch(**kw)
        except Exception as e:  # noqa: BLE001 — try the next strategy
            errors.append(f"{kind}={val}: {type(e).__name__}")
    raise RuntimeError("no usable browser — install Google Chrome. Tried: " + "; ".join(errors))

# Only rows naming one of these commodities (plus a GM/KG unit) are kept.
_COMMODITY_HINTS = ("GOLD", "SILVER", "PETAL", "GUINEA")


def _scrape_pdf_bytes():
    """Return (pdf_bytes, source_url) for the latest stock-position PDF."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = _launch(p)
        try:
            ctx = browser.new_context(
                user_agent=UA,
                viewport={"width": 1366, "height": 900},
                locale="en-IN",
                extra_http_headers=HEADERS,
            )
            ctx.add_init_script(STEALTH)
            page = ctx.new_page()
            # Warm up on the homepage so Akamai issues its clearance cookies.
            page.goto("https://www.mcxccl.com/", wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
            page.wait_for_timeout(2000)
            page.goto(PAGE_URL, wait_until="networkidle", timeout=NAV_TIMEOUT_MS)
            page.wait_for_timeout(1500)
            href = page.eval_on_selector(
                "a[href*='warehouse-vault-wise-stock-position']", "e => e.href"
            )
            if not href:
                raise RuntimeError("stock-position PDF link not found on page")
            # Download via the browser's request context so it carries the
            # Akamai clearance cookies (a bare fetch would 403).
            resp = ctx.request.get(href, timeout=NAV_TIMEOUT_MS)
            if resp.status != 200:
                raise RuntimeError(f"PDF download HTTP {resp.status}")
            return resp.body(), href
        finally:
            browser.close()


def _parse_bullion(pdf_bytes):
    """Extract the 'Summary of Stock – Bullion Commodities' rows (last page)."""
    import pdfplumber

    rows = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        # The bullion summary is the last page; scan from the back for safety.
        target = None
        for i in range(len(pdf.pages) - 1, -1, -1):
            text = pdf.pages[i].extract_text() or ""
            if "Bullion" in text and "Eligible" in text:
                target = i
                break
        if target is None:
            raise RuntimeError("bullion summary page not found in PDF")
        for tbl in pdf.pages[target].extract_tables():
            for r in tbl:
                cells = [(c or "").strip() for c in r if (c or "").strip()]
                if len(cells) < 3:
                    continue
                joined = " ".join(cells).upper()
                if not any(k in joined for k in _COMMODITY_HINTS):
                    continue  # skips the header / title / disclaimer rows
                # Robust to the commodity name being split across cells:
                # last cell = number, second-to-last = unit, rest = name.
                unit = cells[-2].upper()
                if unit not in ("GM", "KG"):
                    continue
                try:
                    units = float(cells[-1].replace(",", ""))
                except ValueError:
                    continue
                commodity = " ".join(cells[:-2])
                rows.append({"commodity": commodity, "unit": unit, "eligible_units": units})
    if not rows:
        raise RuntimeError("no bullion rows parsed from summary page")
    return rows


def main():
    try:
        pdf_bytes, src = _scrape_pdf_bytes()
        m = re.search(r"as-on-date-(\d{2})-(\d{2})-(\d{4})", src)
        as_on = f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None
        rows = _parse_bullion(pdf_bytes)
        print(json.dumps({
            "ok": True,
            "as_on_date": as_on,
            "source_url": src,
            "pdf_name": src.split("/")[-1].split("?")[0],
            "pdf_b64": base64.b64encode(pdf_bytes).decode("ascii"),  # tiny (~47 KB) → served back to the client
            "rows": rows,
        }))
        return 0
    except Exception as e:  # noqa: BLE001 — any failure → clean JSON for the parent
        print(json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
