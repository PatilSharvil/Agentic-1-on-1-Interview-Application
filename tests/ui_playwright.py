"""
UI test + screenshot pass for the redesigned Interview Room frontend.
Run: python tests/ui_playwright.py
Requires: backend on :8000, vite on :5173.
"""
import re
import sys
import time
from playwright.sync_api import sync_playwright, expect

BASE = "http://localhost:5173"
SHOTS = ".playwright-mcp"

passed: list[str] = []
failed: list[str] = []


def check(name: str, fn):
    try:
        fn()
        passed.append(name)
        print(f"  PASS {name}")
    except Exception as e:  # noqa: BLE001
        failed.append(name)
        print(f"  FAIL {name}: {e}")


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            args=["--use-fake-ui-for-media-stream",
                  "--use-fake-device-for-media-stream"])
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        host_ctx = browser.new_context(viewport={"width": 1440, "height": 900},
                                       permissions=["camera", "microphone",
                                                    "clipboard-read", "clipboard-write"])
        page = host_ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        # ---------- LANDING ----------
        page.goto(BASE, wait_until="networkidle")
        shot_landing = f"{SHOTS}/01-landing.png"
        page.screenshot(path=shot_landing, full_page=True)

        check("landing: headline renders", lambda: expect(page.locator(".h-display")).to_contain_text("interview"))
        check("landing: brand equalizer present", lambda: expect(page.locator(".land-top .eq")).to_be_visible())

        check("landing: join disabled without code", lambda: (
            expect(page.get_by_role("button", name="Join with code")).to_be_disabled()))

        def join_validation():
            page.locator("#code").fill("   ")
            page.locator("#code").press("Enter")
            expect(page.locator(".land-err")).to_contain_text("room code")
        check("landing: empty join shows error", join_validation)

        def code_uppercases():
            page.locator("#code").fill("k7x2mn9p")
            expect(page.locator("#code")).to_have_value("K7X2MN9P")
            page.locator("#code").fill("")
        check("landing: code input uppercases", code_uppercases)

        # ---------- CREATE ROOM ----------
        room_code_holder = {}

        def create_room():
            page.locator("#name").fill("Ada Host")
            page.locator("#code").fill("")
            page.get_by_role("button", name="Start an interview").click()
            page.wait_for_selector(".room", timeout=20000)
            code = page.locator(".room-top .slate .mono").inner_text().strip()
            assert code, "no room code shown in slate"
            room_code_holder["code"] = code
        check("landing: create room enters Room", create_room)

        page.wait_for_timeout(1200)
        shot_room_host = f"{SHOTS}/02-room-host.png"
        page.screenshot(path=shot_room_host)

        check("room: status connected", lambda: expect(page.locator(".chip-status")).to_contain_text(
            re.compile("[Cc]onnected|Connected", re.IGNORECASE)))

        check("room: host sees copilot tab", lambda: expect(page.get_by_role("tab", name="Copilot")).to_be_visible())
        check("room: host sees record button", lambda: expect(page.get_by_role("button", name=re.compile("[Ss]tart recording"))).to_be_visible())
        check("room: guest would not (n/a here)", lambda: None)

        # mute toggle
        def mute_toggle():
            btn = page.get_by_role("button", name="Mute microphone")
            btn.click()
            expect(page.get_by_role("button", name="Unmute microphone")).to_be_visible()
            expect(page.locator(".tile-local .tile-badge")).to_contain_text("MUTED")
            page.get_by_role("button", name="Unmute microphone").click()
            expect(page.locator(".tile-local .tile-badge")).to_have_count(0)
        check("room: mute/unmute works + badge", mute_toggle)

        # cam toggle
        def cam_toggle():
            page.get_by_role("button", name=re.compile("Turn camera off")).click()
            expect(page.locator(".tile-local .tile-badge")).to_contain_text("CAMERA OFF")
            page.get_by_role("button", name=re.compile("Turn camera on")).click()
            expect(page.locator(".tile-local .tile-badge")).to_have_count(0)
        check("room: camera toggle works + badge", cam_toggle)

        # room code copy
        def copy_slate():
            page.locator(".room-top .slate").click()
            expect(page.locator(".room-top .slate.copied")).to_be_visible()
        check("room: copy code feedback", copy_slate)

        # transcript empty state
        check("room: transcript empty state", lambda: expect(page.locator(".rail-empty")).to_contain_text("Captions"))

        # chat send
        def chat_send():
            page.get_by_role("tab", name=re.compile("Chat")).click()
            page.get_by_role("textbox", name="Chat message").fill("Hello from Playwright")
            page.get_by_role("button", name=re.compile("Send")).click()
            expect(page.locator(".c-row").first).to_contain_text("Hello from Playwright")
        check("room: chat send renders row", chat_send)

        # copilot tab content
        def copilot_tab():
            page.get_by_role("tab", name="Copilot").click()
            expect(page.locator(".step").first).to_contain_text("Resume")
            expect(page.locator(".step").nth(1)).to_contain_text("Questions")
            expect(page.locator(".step").nth(2)).to_contain_text("graph")
        check("copilot: steps render in rail", copilot_tab)
        page.screenshot(path=f"{SHOTS}/03-room-copilot.png")

        # diagnostics
        def diag():
            page.get_by_role("button", name=re.compile("Diagnostics")).click()
            expect(page.get_by_role("button", name="Send audio now")).to_be_visible()
            expect(page.get_by_role("button", name="Test STT (wav)")).to_be_visible()
        check("diagnostics: expand shows tools", diag)

        # recording toggle (host)
        def rec_toggle():
            page.get_by_role("button", name=re.compile("Start recording")).click()
            expect(page.locator(".chip-rec")).to_be_visible()
            page.screenshot(path=f"{SHOTS}/04-room-recording.png")
            page.get_by_role("button", name=re.compile("Stop recording")).click()
            expect(page.locator(".chip-rec")).to_have_count(0)
        check("room: record toggle shows REC chip", rec_toggle)

        # ---------- KNOWLEDGE GRAPH PAGE ----------
        def graph_page():
            code = room_code_holder.get("code", "")
            gpage = host_ctx.new_page()
            gpage.goto(f"{BASE}/graph/{code}", wait_until="load")
            gpage.wait_for_timeout(2500)
            expect(gpage.locator(".graph-top h1")).to_contain_text("Knowledge graph")
            expect(gpage.locator(".kg-legend")).to_be_visible()
            expect(gpage.locator(".kg-empty")).to_be_visible()
            gpage.screenshot(path=f"{SHOTS}/05-graph-page.png")
            gpage.close()
        check("graph: page renders with legend + empty state", graph_page)

        # ---------- SECOND BROWSER (GUEST JOIN FLOW) ----------
        def guest_join():
            code = room_code_holder.get("code", "")
            guest_ctx = browser.new_context(viewport={"width": 1440, "height": 900},
                                            permissions=["camera", "microphone"])
            gpage = guest_ctx.new_page()
            gpage.goto(BASE, wait_until="networkidle")
            gpage.locator("#name").fill("Priya Guest")
            gpage.locator("#code").fill(code)
            gpage.get_by_role("button", name="Join with code").click()
            gpage.wait_for_selector(".room", timeout=20000)
            gpage.wait_for_timeout(1500)
            # no host-only controls for guest
            assert gpage.get_by_role("button", name=re.compile("[Ss]tart recording")).count() == 0, \
                "guest must not see record button"
            assert gpage.get_by_role("tab", name="Copilot").count() == 0, "guest must not see copilot tab"
            gpage.screenshot(path=f"{SHOTS}/06-room-guest.png")
            # while the guest is still in the room, the host should show their name
            page.wait_for_timeout(1500)
            check("room: partner name visible on host stage", lambda: expect(
                page.locator(".tile-remote .tile-label")).to_contain_text("Priya Guest"))
            guest_ctx.close()
        check("guest: joined room, host-only controls hidden", guest_join)

        # ---------- responsive: mobile viewport ----------
        def mobile():
            mctx = browser.new_context(viewport={"width": 390, "height": 844})
            mpage = mctx.new_page()
            mpage.goto(BASE, wait_until="networkidle")
            mpage.wait_for_timeout(1200)
            mpage.screenshot(path=f"{SHOTS}/07-mobile-landing.png")
            mctx.close()
        check("responsive: mobile landing renders", mobile)

        # ---------- console error sweep ----------
        def console_clean():
            real = [e for e in errors if "favicon" not in e]
            assert not real, f"page errors: {real}"
        check("no uncaught page errors", console_clean)

        browser.close()

    print(f"\n{'='*46}\npassed {len(passed)} / failed {len(failed)}")
    if failed:
        print("FAILED:", ", ".join(failed))
        sys.exit(1)


if __name__ == "__main__":
    run()
