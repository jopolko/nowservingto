from playwright.sync_api import sync_playwright
import os

BASE = "https://nowservingto.com"
OUT = "/home/josh/nowservingto/screenshots"
os.makedirs(OUT, exist_ok=True)

PAGES = [
    ("home",        "/"),
    ("vietnamese",  "/cuisine/vietnamese.html"),
    ("listing",     "/r/pho-128-345"),
    ("filipino_wt", "/cuisine/filipino/west-toronto"),
    ("az_index",    "/all"),
]

VIEWPORTS = [
    ("desktop", 1440, 900),
    ("mobile",  390,  844),
]

def capture_all():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for slug, path in PAGES:
            for device, w, h in VIEWPORTS:
                url = BASE + path
                out = f"{OUT}/{slug}_{device}.png"
                print(f"Capturing {url} @ {w}x{h} -> {out}")
                page = browser.new_page(viewport={'width': w, 'height': h})
                try:
                    page.goto(url, wait_until='networkidle', timeout=15000)
                    page.wait_for_timeout(800)
                    page.screenshot(path=out, full_page=False)
                except Exception as e:
                    print(f"  ERROR: {e}")
                    page.screenshot(path=out, full_page=False)
                finally:
                    page.close()
        browser.close()

capture_all()
print("Done.")
