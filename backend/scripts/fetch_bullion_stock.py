#!/usr/bin/env python3
"""Isolated MCXCCL bullion warehouse-stock scraper (runs as a SUBPROCESS, once/day).

Why a separate process: Playwright + headless Chromium/Chrome are heavy. Spawning
this from mcxccl_service via subprocess (killed on timeout) keeps that memory and
the playwright/pdfplumber imports OUT of the long-running FastAPI process, and a
hang here can't touch the live feed.

Source = the DAILY "Exchange Deliverable Stock Position" feed. The page's date
picker calls:
    GET .../warehouse-report/GetFilteredDeliverableStock?fromDate=MM/DD/YYYY&page=1
    → {"DeliverableStock":[{"Title":"DD/MM/YYYY","SummaryDocURL":"...pdf",...}], ...}
The filter is an EXACT date match (empty on non-published / non-trading days), so
we walk back from today to the most recent available file. The bullion
"Summary of Stock – Bullion Commodities" (Eligible Units) is the PDF's last page.

Output: one JSON object on stdout, then exit 0:
    {"ok": true, "latest_available": "2026-06-29",
     "items": [ {"as_on_date":"2026-06-29","source_url":"...","pdf_name":"...",
                 "pdf_b64":"<newest only>","rows":[{"commodity","unit","eligible_units"}]}, ... ]}
`items` is newest-first and EXCLUDES dates already stored (passed via
MCXCCL_HAVE_DATES) so steady-state runs download just the one new day; the first
run backfills the whole lookback window. `pdf_b64` is attached only to the newest
day (that's the file the dashboard serves for View/Download).
On failure: {"ok": false, "error": "..."} and a non-zero exit code.

mcxccl.com is behind Akamai bot-protection: a plain request (even real headless
Chrome with a normal UA) → 403. The stealth init-script + anti-automation launch
flags below defeat the headless fingerprinting and pass.
"""
from __future__ import annotations

import base64
import datetime as dt
import io
import json
import os
import sys

DELIVERABLE_API = os.environ.get(
    "MCXCCL_DELIVERABLE_API",
    "https://www.mcxccl.com/warehousing-logistics/warehouse-report/GetFilteredDeliverableStock",
)
LOOKBACK_DAYS = int(os.environ.get("MCXCCL_LOOKBACK_DAYS", "14"))
HAVE_DATES = {x for x in os.environ.get("MCXCCL_HAVE_DATES", "").split(",") if x}
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
# Defeats Akamai's headless fingerprinting.
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

# Optional explicit browser overrides; otherwise we auto-detect.
CHROME_CHANNEL = os.environ.get("MCXCCL_CHROME_CHANNEL", "").strip()  # e.g. "chrome"
CHROME_PATH = os.environ.get("MCXCCL_CHROME_PATH", "").strip()        # e.g. /usr/bin/google-chrome
_FALLBACK_PATHS = (
    "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium", "/usr/bin/chromium-browser", "/snap/bin/chromium",
)

# Only rows naming one of these commodities (plus a GM/KG unit) are kept.
_COMMODITY_HINTS = ("GOLD", "SILVER", "PETAL", "GUINEA")


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


def _list_available(ctx):
    """Walk back from today; return [(date_iso, summary_pdf_url), ...] newest-first."""
    out = []
    today = dt.date.today()  # server runs in Asia/Kolkata → IST date
    for i in range(LOOKBACK_DAYS + 1):
        d = today - dt.timedelta(days=i)
        fd = f"{d.month:02d}/{d.day:02d}/{d.year}"  # API wants MM/DD/YYYY
        try:
            resp = ctx.request.get(f"{DELIVERABLE_API}?fromDate={fd}&page=1", timeout=NAV_TIMEOUT_MS)
            if resp.status != 200:
                continue
            rows = (resp.json() or {}).get("DeliverableStock") or []
        except Exception:  # noqa: BLE001 — skip a bad day, keep walking
            continue
        if rows and rows[0].get("SummaryDocURL"):
            out.append((d.isoformat(), rows[0]["SummaryDocURL"]))
    return out


def _parse_bullion(pdf_bytes):
    """Extract the 'Summary of Stock – Bullion Commodities' rows (last page)."""
    import pdfplumber

    rows = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
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
                    continue  # skips header / title / disclaimer rows
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


def _scrape():
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

            available = _list_available(ctx)
            if not available:
                raise RuntimeError(f"no daily deliverable-stock file found in last {LOOKBACK_DAYS} days")
            latest_available = available[0][0]

            items = []
            for date_iso, url in available:
                if date_iso in HAVE_DATES:
                    continue  # already stored — let steady-state runs skip the download
                resp = ctx.request.get(url, timeout=NAV_TIMEOUT_MS)
                if resp.status != 200:
                    continue
                pdf = resp.body()
                try:
                    rows = _parse_bullion(pdf)
                except Exception:  # noqa: BLE001 — one bad PDF shouldn't drop the rest
                    continue
                item = {
                    "as_on_date": date_iso,
                    "source_url": url,
                    "pdf_name": url.split("/")[-1].split("?")[0],
                    "rows": rows,
                }
                if date_iso == latest_available:  # only the newest carries the PDF for View/Download
                    item["pdf_b64"] = base64.b64encode(pdf).decode("ascii")
                items.append(item)
            return {"latest_available": latest_available, "items": items}
        finally:
            browser.close()


def main():
    try:
        result = _scrape()
        print(json.dumps({"ok": True, **result}))
        return 0
    except Exception as e:  # noqa: BLE001 — any failure → clean JSON for the parent
        print(json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
