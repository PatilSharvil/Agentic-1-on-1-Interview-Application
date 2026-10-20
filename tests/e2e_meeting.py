"""E2E test: two peers join a room, chat, and live STT caption arrives.

Run: python tests/e2e_meeting.py
Requires backend (8000) and frontend (5173) running.
"""
import sys

from playwright.sync_api import sync_playwright

AUDIO = r"C:\Users\patil\AppData\Local\Temp\opencode\speech.wav"
BASE = "http://localhost:5173"
SHOT = r"C:\Users\patil\AppData\Local\Temp\opencode\room.png"


def status(page):
    return page.locator("div").nth(1).inner_text().splitlines()[0]


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--use-fake-ui-for-media-stream",
                "--use-fake-device-for-media-stream",
                f"--use-file-for-fake-audio-capture={AUDIO}%loop",
            ],
        )
        errors = []
        ctx = browser.new_context(permissions=["camera", "microphone"])
        host = ctx.new_page()
        guest = ctx.new_page()
        for pg in (host, guest):
            pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            pg.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))

        host.goto(BASE)
        host.wait_for_load_state("networkidle")
        host.get_by_placeholder("Your name").fill("Alice")
        host.get_by_role("button", name="Create new meeting").click()
        host.wait_for_timeout(1500)
        code = host.locator("h2").inner_text().split()[1]
        print("room code:", code)

        guest.goto(BASE)
        guest.wait_for_load_state("networkidle")
        guest.get_by_placeholder("Your name").fill("Bob")
        guest.get_by_placeholder("Room code").fill(code)
        guest.get_by_role("button", name="Join").click()
        guest.wait_for_timeout(3000)
        print("host status:", status(host))
        print("guest status:", status(guest))
        print("host body:", repr(host.inner_text("body")[:400]))
        print("guest body:", repr(guest.inner_text("body")[:400]))

        # chat guest -> host
        guest.locator("input").first.fill("hi from Bob")
        guest.get_by_role("button", name="Send").click()
        host.wait_for_timeout(1500)
        print("chat on host:", "hi from Bob" in host.inner_text("body"))

        # webrtc media elements
        print("videos on host:", host.evaluate("() => document.querySelectorAll('video').length"))

        # STT: 15s chunk + transcription roundtrip
        print("waiting for STT caption (up to 90s)...")
        caption = ""
        for _ in range(90):
            host.wait_for_timeout(1000)
            panels = host.locator("h3:has-text('Transcript') + div > div")
            if panels.count():
                caption = panels.first.inner_text()
                if caption.strip():
                    break
        print("STT caption:", repr(caption))

        host.screenshot(path=SHOT, full_page=True)
        print("console errors:", errors)
        browser.close()
        return 0 if caption.strip() else 1


if __name__ == "__main__":
    sys.exit(main())
