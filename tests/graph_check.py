from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto("http://localhost:5133/graph/KY25PM43")
    page.wait_for_timeout(6000)
    circles = page.locator("circle").count()
    lines = page.locator("line").count()
    print("circles:", circles, "lines:", lines)
    browser.close()