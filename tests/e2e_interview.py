"""End-to-end interview simulation with WAV files through the REAL pipeline.

Flow (all through the running system, no mocks):
  1. Host opens the redesigned UI, creates a room                    [screenshots]
  2. Host uploads resume via Copilot -> graph seeded                 [screenshots]
  3. Host generates questions from the resume (LLM)                  [screenshots]
  4. A WS client replays TTS WAV files through the real STT:
       interviewer wav = the generated question (spoken aloud)
       candidate  wav = scripted answer
     -> Groq whisper-large-v3 -> transcript -> live UI                [screenshots]
  5. After every answer: adaptive follow-up via /questions/next      [screenshots]
  6. Final adaptive answer deliberately contradicts the resume
     (never ran Kubernetes in production) -> contradicts edge
  7. Graph rebuild from resume + transcript                          [screenshots]
  8. D3 knowledge graph rendered                                     [screenshots]
  9. Markdown report with every screenshot as proof

Run:  python tests/e2e_interview.py
"""
from __future__ import annotations

import base64
import json
import re
import sys
import threading
import time
import wave
from datetime import datetime, timezone
from pathlib import Path

import requests
import websocket
from playwright.sync_api import sync_playwright

# Windows consoles default to cp1252 — status dots and arrows would crash prints.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from e2e.make_wavs import ANSWERS, make_answers, make_question  # noqa: E402

BASE = "http://localhost:5173"
API = "http://localhost:8000"
REPORTS = ROOT / "reports"
EVID = REPORTS / "evidence"
WAVS = ROOT / "tests" / "e2e" / "wavs"

HOST_NAME = "Ada Host"
JOB_TITLE = "Backend Engineer"

STOP_TOKENS = re.compile(r"[^a-z0-9 ]+")


def norm(text: str) -> list[str]:
    return [t for t in STOP_TOKENS.sub(" ", text.lower()).split() if len(t) > 2]


def similarity(expected: str, got: str) -> float:
    e, g = set(norm(expected)), set(norm(got))
    if not e:
        return 0.0
    return len(e & g) / len(e)


# --------------------------------------------------------------------------- #
# WebSocket probe client (same protocol the browser speaks)
# --------------------------------------------------------------------------- #

class WsClient:
    def __init__(self, code: str, name: str):
        from urllib.parse import quote
        self.code, self.name = code, name
        self.q: list[dict] = []
        self.lock = threading.Lock()
        # NOTE: query params must be URL-encoded — a raw space breaks the
        # handshake ("Invalid HTTP request received" server-side).
        self.ws = websocket.WebSocketApp(
            f"ws://127.0.0.1:8000/ws/{code}?name={quote(name)}",
            on_message=lambda _ws, m: self._push(json.loads(m)),
        )
        self.thread = threading.Thread(target=self.ws.run_forever, daemon=True)
        self.thread.start()
        for _ in range(50):
            if self.ws.sock and self.ws.sock.connected:
                break
            time.sleep(0.1)

    def _push(self, msg: dict) -> None:
        with self.lock:
            self.q.append(msg)

    def send(self, payload: dict) -> None:
        self.ws.send(json.dumps(payload))

    def drain(self) -> None:
        with self.lock:
            self.q.clear()

    def wait_for(self, pred, timeout: float = 60.0) -> dict | None:
        deadline = time.time() + timeout
        seen_idx = 0
        while time.time() < deadline:
            with self.lock:
                msgs = self.q[seen_idx:]
                seen_idx = len(self.q)
            for m in msgs:
                if pred(m):
                    return m
            time.sleep(0.2)
        return None

    def close(self) -> None:
        try:
            self.ws.close()
        except Exception:
            pass


def wav_info(path: Path) -> tuple[bytes, int]:
    """Return the COMPLETE RIFF file bytes (the browser uploads a full wav,
    and the server's decoder expects one — raw readframes() PCM has no header
    and fails server-side decode) plus the duration in ms."""
    with wave.open(str(path), "rb") as w:
        n, sr = w.getnframes(), w.getframerate()
    return path.read_bytes(), (n * 1000) // sr


class E2E:
    def __init__(self):
        self.seq = 0
        self.results: list[dict] = []
        self.timeline: list[dict] = []
        self.questions: list[dict] = []
        self.adaptive: list[dict] = []
        self.graph_samples: list[dict] = []
        self.errors: list[str] = []

    # -- helpers ------------------------------------------------------------
    def shot(self, page, name: str) -> str:
        EVID.mkdir(parents=True, exist_ok=True)
        path = f"{EVID.name}/{name}"
        page.screenshot(path=str(REPORTS / path))
        return path

    def record(self, step: str, ok: bool, detail: str = "") -> None:
        self.results.append({"step": step, "ok": bool(ok), "detail": detail})
        print(f"  {'PASS' if ok else 'FAIL'} {step} {('- ' + detail) if detail else ''}")

    def api(self, method: str, path: str, **kw) -> dict:
        r = requests.request(method, f"{API}{path}", timeout=60, **kw)
        r.raise_for_status()
        return r.json()

    def send_wav(self, ws: WsClient, path: Path, speaker: str) -> int:
        data, dur_ms = wav_info(path)
        self.seq += 1
        now = int(time.time() * 1000) % 10_000_000
        ws.send({
            "type": "audio-chunk",
            "audio": base64.b64encode(data).decode(),
            "suffix": ".wav",
            "speaker": speaker,
            "seq": self.seq,
            "start_ms": now - dur_ms,
            "end_ms": now,
            "speech_ms": dur_ms,
        })
        return dur_ms

    def wait_transcript(self, ws: WsClient, speaker: str, expected: str,
                        timeout: float = 90.0) -> dict | None:
        """Wait for a transcript from `speaker` that resembles `expected`."""
        deadline = time.time() + timeout
        best, best_sim = None, 0.0
        while time.time() < deadline:
            m = ws.wait_for(
                lambda x: x.get("type") == "transcript" and x.get("speaker") == speaker,
                timeout=min(5.0, max(0.5, deadline - time.time())),
            )
            if not m:
                continue
            sim = similarity(expected, m.get("text", ""))
            self.timeline.append({
                "speaker": speaker, "text": m.get("text", ""), "sim": round(sim, 2),
                "model": m.get("model"), "latency_ms": m.get("latency_ms"),
                "t": datetime.now(timezone.utc).strftime("%H:%M:%S"),
            })
            print(f"    [{speaker}] {m.get('text', '')!r} (sim={sim:.2f})")
            if sim > best_sim:
                best, best_sim = m, sim
            if sim >= 0.45:
                return m
        self.errors.append(
            f"transcript mismatch for {speaker}: best sim {best_sim:.2f}; "
            f"best={best.get('text') if best else None!r}")
        return best


# --------------------------------------------------------------------------- #
# main scenario
# --------------------------------------------------------------------------- #

def run():
    e2e = E2E()
    code = None
    try:
        _run_scenario(e2e)
    except Exception as fatal:  # noqa: BLE001 — always produce the report
        e2e.record("scenario aborted", False, f"{type(fatal).__name__}: {fatal}")
    finally:
        if code is None:
            code = getattr(e2e, "code", "unknown")
        write_report(e2e, code)
    failed = [r for r in e2e.results if not r["ok"]]
    print(f"\n{'=' * 50}\nE2E finished: {len(e2e.results) - len(failed)} passed, {len(failed)} failed")
    if failed:
        for f in failed:
            print(f"  FAIL {f['step']}: {f['detail']}")
        sys.exit(1)


def _run_scenario(e2e: E2E):
    code = None
    answers = make_answers()
    # clear stale spoken-question wavs from previous runs
    for old in WAVS.glob("interviewer_q_*.wav"):
        old.unlink()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"])
        ctx = browser.new_context(viewport={"width": 1440, "height": 900},
                                  permissions=["camera", "microphone",
                                               "clipboard-read", "clipboard-write"])
        page = ctx.new_page()
        page_errors: list[str] = []
        page.on("pageerror", lambda e: page_errors.append(str(e)))

        print("== Phase A: landing, room, resume, questions ==")
        page.goto(BASE, wait_until="networkidle")
        page.wait_for_timeout(1500)
        e2e.shot(page, "01-landing.png")

        page.locator("#name").fill(HOST_NAME)
        page.get_by_role("button", name="Start an interview").click()
        page.wait_for_selector(".room", timeout=20000)
        page.wait_for_timeout(1500)
        code = page.locator(".room-top .slate .mono").inner_text().strip()
        e2e.code = code
        e2e.record("host created room via UI", bool(re.fullmatch(r"[A-Z2-9]{8}", code)), f"code={code}")
        e2e.shot(page, "02-room-created.png")

        ws = WsClient(code, "E2E Probe")
        e2e.record("ws probe joined room", ws.ws.sock is not None and ws.ws.sock.connected)

        # smoke test with the bundled test.wav
        e2e.send_wav(ws, ROOT / "frontend" / "public" / "test.wav", "Interviewer")
        smoke = ws.wait_for(lambda m: m.get("type") in ("transcript", "stt-status"), timeout=90)
        e2e.record("bundled test.wav through STT", smoke is not None,
                   json.dumps({k: smoke.get(k) for k in ("status", "text", "reason")} if smoke else {}))

        # resume upload through the copilot UI
        page.get_by_role("tab", name="Copilot").click()
        page.locator(".copilot input[type='file']").set_input_files(
            str(ROOT / "tests" / "e2e" / "resume_sample.md"))
        page.wait_for_selector(".skill-tags span", timeout=60000)
        page.wait_for_timeout(800)
        e2e.shot(page, "03-resume-uploaded.png")
        skills_ui = page.locator(".skill-tags span").all_inner_texts()
        e2e.record("resume uploaded via copilot UI", len(skills_ui) > 0, f"skills={skills_ui[:6]}…")
        graph_after_resume = e2e.api("GET", f"/api/rooms/{code}/graph")
        e2e.graph_samples.append({"after": "resume upload",
                                  "nodes": len(graph_after_resume["nodes"]),
                                  "edges": len(graph_after_resume["edges"])})

        # question generation through the copilot UI
        page.locator(".copilot input[aria-label='Job title']").fill(JOB_TITLE)
        page.get_by_role("button", name="Generate 5").click()
        deadline = time.time() + 180
        while time.time() < deadline:
            qs = e2e.api("GET", f"/api/rooms/{code}/questions")
            if len(qs) >= 5:
                break
            page.wait_for_timeout(3000)
        e2e.questions = qs
        page.wait_for_timeout(600)
        e2e.shot(page, "04-questions-generated.png")
        e2e.record("5 questions generated from resume (LLM)", len(qs) >= 5,
                   f"n={len(qs)} sources={sorted({q['source'] for q in qs})}")

        print("== Phase B: the interview ==")
        # transcript tab stays visible while the interview runs
        page.get_by_role("tab", name=re.compile("^Transcript")).click()

        adaptive_q: dict | None = None
        n_base = len([q for q in qs if q["source"] != "adaptive"])
        for i, q in enumerate([x for x in qs if x["source"] != "adaptive"], 1):
            # --- interviewer asks the question (wav) ---
            qpath = make_question(q["text"], i)
            ws.drain()
            e2e.send_wav(ws, qpath, "Interviewer")
            got = e2e.wait_transcript(ws, "Interviewer", q["text"])
            e2e.record(f"Q{i} asked via wav -> transcript", got is not None,
                       f"sim={similarity(q['text'], got['text']) if got else 0:.2f}")
            e2e.shot(page, f"q{i}-asked.png")

            # --- candidate answers (wav) ---
            ws.drain()
            e2e.send_wav(ws, answers[f"a{i}"], "Candidate")
            got_a = e2e.wait_transcript(ws, "Candidate", ANSWERS[f"a{i}"])
            e2e.record(f"A{i} answered via wav -> transcript", got_a is not None,
                       f"sim={similarity(ANSWERS[f'a{i}'], got_a['text']) if got_a else 0:.2f}")
            e2e.shot(page, f"a{i}-answered.png")

            # auto graph rebuild fires ~5s after candidate speech; sample it
            page.wait_for_timeout(9000)
            g = e2e.api("GET", f"/api/rooms/{code}/graph")
            e2e.graph_samples.append({"after": f"answer {i}", "nodes": len(g["nodes"]),
                                      "edges": len(g["edges"])})

            # --- adaptive follow-up from the transcript ---
            before = {x["id"] for x in e2e.api("GET", f"/api/rooms/{code}/questions")}
            page.get_by_role("tab", name="Copilot").click()
            page.get_by_role("button", name="Next from answer").click()
            deadline = time.time() + 180
            nxt = None
            while time.time() < deadline:
                now_qs = e2e.api("GET", f"/api/rooms/{code}/questions")
                fresh = [x for x in now_qs if x["id"] not in before]
                if fresh:
                    nxt = fresh[-1]
                    break
                page.wait_for_timeout(3000)
            e2e.adaptive.append({"after_answer": i, **(nxt or {"text": None, "source": "none"})})
            page.wait_for_timeout(600)
            e2e.shot(page, f"adaptive-{i}.png")
            overlap = set(norm(nxt["text"])) & set(norm(ANSWERS[f"a{i}"])) if nxt else set()
            e2e.record(f"adaptive follow-up after A{i}",
                       nxt is not None and nxt["text"] not in {x["text"] for x in qs},
                       f"source={nxt['source'] if nxt else 'none'} "
                       f"answer-overlap={sorted(overlap)[:4]}")
            page.get_by_role("tab", name=re.compile("^Transcript")).click()
            adaptive_q = nxt

        # --- the final adaptive question is asked and answered with a contradiction ---
        if adaptive_q and adaptive_q.get("text"):
            i = n_base + 1
            qpath = make_question(adaptive_q["text"], i)
            ws.drain()
            e2e.send_wav(ws, qpath, "Interviewer")
            got = e2e.wait_transcript(ws, "Interviewer", adaptive_q["text"])
            e2e.record("final adaptive question asked via wav -> transcript", got is not None,
                       f"sim={similarity(adaptive_q['text'], got['text']) if got else 0:.2f}")
            e2e.shot(page, "adaptive-final-asked.png")

            ws.drain()
            e2e.send_wav(ws, answers["adaptive_final"], "Candidate")
            got_c = e2e.wait_transcript(ws, "Candidate", ANSWERS["adaptive_final"])
            e2e.record("contradiction answer -> transcript", got_c is not None,
                       f"sim={similarity(ANSWERS['adaptive_final'], got_c['text']) if got_c else 0:.2f}")
            e2e.shot(page, "contradiction-answered.png")

        print("== Phase C: graph rebuild through the transcript ==")
        page.get_by_role("tab", name=re.compile("^Transcript")).click()
        page.wait_for_timeout(400)
        e2e.shot(page, "transcript-final.png")

        page.get_by_role("tab", name="Copilot").click()
        counts_before = e2e.api("GET", f"/api/rooms/{code}/graph")
        page.get_by_role("button", name="Rebuild all").first.click()
        # the copilot banner reports "Graph rebuilt: N nodes · M edges."
        page.wait_for_selector(".copilot-msg", timeout=240000)
        deadline = time.time() + 240
        rebuilt_text = ""
        while time.time() < deadline:
            rebuilt_text = page.locator(".copilot-msg").inner_text()
            if "rebuilt" in rebuilt_text.lower() or "fail" in rebuilt_text.lower():
                break
            page.wait_for_timeout(2000)
        page.wait_for_timeout(600)
        e2e.shot(page, "graph-rebuilt.png")
        e2e.record("graph rebuild from resume + transcript (UI)", "rebuilt" in rebuilt_text.lower(),
                   rebuilt_text)

        counts_final = e2e.api("GET", f"/api/rooms/{code}/graph")
        e2e.graph_samples.append({"after": "final rebuild", "nodes": len(counts_final["nodes"]),
                                  "edges": len(counts_final["edges"])})

        # knowledge-graph page render
        gpage = ctx.new_page()
        gpage.goto(f"{BASE}/graph/{code}", wait_until="load")
        gpage.wait_for_timeout(6000)
        e2e.shot(gpage, "graph-view.png")
        gpage.wait_for_timeout(3000)
        e2e.shot(gpage, "graph-view-settled.png")
        stat = gpage.locator(".graph-stat").inner_text()
        m_nodes = re.search(r"(\d+)\s+NODES", stat.upper().replace("\n", " "))
        e2e.record("knowledge graph page renders nodes",
                   bool(m_nodes) and int(m_nodes.group(1)) > 0, " ".join(stat.split()))
        gpage.close()

        e2e.shot(page, "copilot-final.png")

        print("== Phase D: verification ==")
        # resume skills present as graph nodes
        labels = " | ".join(n.get("label", "") for n in counts_final["nodes"]).lower()
        expected_skills = ["python", "fastapi", "postgresql", "redis", "docker",
                           "kubernetes", "aws", "terraform"]
        missing = [s for s in expected_skills if s not in labels]
        e2e.record("all resume skills present as graph nodes", not missing,
                   f"missing={missing or 'none'}")

        # transcript claims made it into the graph
        transcript_nodes = [n for n in counts_final["nodes"]
                            if (n.get("meta") or {}).get("source") == "transcript"]
        e2e.record("transcript contributed nodes to the graph", len(transcript_nodes) > 0,
                   f"{len(transcript_nodes)} transcript-sourced nodes")
        claim_nodes = [n for n in counts_final["nodes"] if n.get("type") == "claim"]
        e2e.record("claims extracted from answers", len(claim_nodes) > 0,
                   f"{len(claim_nodes)} claim nodes")
        contradicts = [e for e in counts_final["edges"] if e.get("relation") == "contradicts"]
        e2e.record("contradiction (never ran k8s) produced a contradicts edge",
                   len(contradicts) > 0, f"{len(contradicts)} contradicts edges")
        grew = (len(counts_final["nodes"]) > len(graph_after_resume["nodes"]))
        e2e.record("graph grew from resume-only to resume+transcript", grew,
                   f"{len(graph_after_resume['nodes'])} -> {len(counts_final['nodes'])} nodes")

        e2e.record("no uncaught browser errors", not page_errors, "; ".join(page_errors[:3]))

        # evidence dumps
        (EVID / "graph_final.json").write_text(json.dumps(counts_final, indent=2))
        (EVID / "transcript_dump.json").write_text(json.dumps(e2e.timeline, indent=2))
        (EVID / "questions_final.json").write_text(json.dumps(
            e2e.api("GET", f"/api/rooms/{code}/questions"), indent=2))
        (EVID / "summary.json").write_text(json.dumps({
            "code": code, "results": e2e.results, "timeline": e2e.timeline,
            "adaptive": e2e.adaptive, "graph_samples": e2e.graph_samples,
        }, indent=2))

        browser.close()

    # ---------------- report written by run() ----------------


def write_report(e: E2E, code: str) -> None:
    REPORTS.mkdir(exist_ok=True)
    EVID.mkdir(exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    def table(rows: list[list[str]], header: list[str]) -> str:
        out = ["| " + " | ".join(header) + " |",
               "|" + "|".join("---" for _ in header) + "|"]
        out += ["| " + " | ".join(str(c).replace("|", "\\|") for c in r) + " |" for r in rows]
        return "\n".join(out)

    L: list[str] = []
    L.append("# End-to-End Interview Simulation — Proof Report\n")
    L.append(f"**Room:** `{code}` · **Generated:** {now} · **Stack:** FastAPI + Groq whisper-large-v3 "
             f"(real STT) + OpenRouter/Groq LLM + React UI · **Driver:** Playwright + WebSocket WAV replay\n")
    L.append("Every claim below is backed by a screenshot in `evidence/`. "
             "All audio was real WAV speech (Windows SAPI TTS) pushed through the production "
             "WebSocket protocol — no mocks.\n")

    L.append("## 1. Verification results\n")
    L.append(table([[r["step"], "✅ PASS" if r["ok"] else "❌ FAIL", r["detail"] or "—"]
                    for r in e.results], ["Check", "Result", "Detail"]))

    L.append("\n## 2. Interview timeline (WAV → STT → transcript)\n")
    L.append(table([[t["t"], t["speaker"], f"`{t['text'][:110]}{'…' if len(t['text']) > 110 else ''}`",
                     f"{t['sim']:.2f}", t.get("latency_ms") or "—"] for t in e.timeline],
                   ["Time (UTC)", "Speaker", "Transcribed utterance", "Similarity", "STT latency (ms)"]))

    L.append("\n## 3. Resume-seeded questions\n")
    L.append(table([[i, f"`{q['text'][:120]}`", q["source"]] for i, q in enumerate(e.questions, 1)],
                   ["#", "Question (from /api/rooms/{code}/questions)", "Source"]))

    L.append("\n## 4. Adaptive question generation (from the transcript)\n")
    L.append(table([[a["after_answer"], f"`{(a.get('text') or '—')[:130]}`", a.get("source", "—")]
                    for a in e.adaptive], ["After answer #", "Adaptive follow-up generated", "Source"]))

    L.append("\n## 5. Knowledge graph growth\n")
    L.append(table([[g["after"], g["nodes"], g["edges"]] for g in e.graph_samples],
                   ["Stage", "Nodes", "Edges"]))

    L.append("\n## 6. Proof — screenshots\n")
    sections = [
        ("Landing page (redesigned UI)", ["01-landing.png"]),
        ("Host creates the room", ["02-room-created.png"]),
        ("Resume uploaded via Copilot — skills detected, graph seeded", ["03-resume-uploaded.png"]),
        ("Questions generated from the resume (LLM)", ["04-questions-generated.png"]),
    ]
    n_q = len([s for s in e.results if s["step"].startswith("Q") and "asked" in s["step"]])
    for i in range(1, n_q + 1):
        sections.append((f"Interview round {i}: question asked (WAV) → live transcript, "
                         f"candidate answers (WAV) → live transcript, adaptive follow-up generated",
                         [f"q{i}-asked.png", f"a{i}-answered.png", f"adaptive-{i}.png"]))
    sections += [
        ("Final adaptive question asked and answered with the deliberate contradiction",
         ["adaptive-final-asked.png", "contradiction-answered.png"]),
        ("Full transcript at the end of the interview", ["transcript-final.png"]),
        ("Graph rebuild from resume + transcript (Copilot banner)", ["graph-rebuilt.png"]),
        ("Live knowledge graph (D3 render)", ["graph-view.png", "graph-view-settled.png"]),
        ("Copilot panel after the full interview", ["copilot-final.png"]),
    ]
    for title, imgs in sections:
        L.append(f"\n### {title}\n")
        for img in imgs:
            if (EVID / img).exists():
                L.append(f"![{img}](evidence/{img})\n")

    L.append("\n## 7. Raw evidence\n")
    L.append("- `evidence/graph_final.json` — final graph (nodes, edges, relations, evidence spans)\n"
             "- `evidence/transcript_dump.json` — every transcribed utterance with STT latency\n"
             "- `evidence/questions_final.json` — full question list incl. adaptive follow-ups\n"
             "- `evidence/summary.json` — machine-readable check results\n")

    (REPORTS / "E2E-INTERVIEW-REPORT.md").write_text("\n".join(L), encoding="utf-8")
    print(f"report -> {REPORTS / 'E2E-INTERVIEW-REPORT.md'}")


if __name__ == "__main__":
    run()
