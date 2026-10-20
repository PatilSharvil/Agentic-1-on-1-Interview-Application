"""End-to-end smoke test for Phase 2 copilot + graph."""
import sys
import httpx

BASE = "http://localhost:8000"
GRAPH = "http://localhost:5133"

async def main():
    async with httpx.AsyncClient(timeout=60) as c:
        # create room
        r = await c.post(f"{BASE}/api/rooms", json={"host_name": "Alice"})
        code = r.json()["code"]
        print("room:", code)

        # upload resume
        resume_text = "Sharun Patil\nSoftware Engineer\nSkills: Python, FastAPI, React, Docker, PostgreSQL\nExperience: 3 years at TechCorp"
        files = {"file": ("resume.txt", resume_text.encode(), "text/plain")}
        r = await c.post(f"{BASE}/api/rooms/{code}/resume", files=files)
        print("resume upload:", r.status_code, r.json().get("filename"))

        # generate questions
        r = await c.post(f"{BASE}/api/rooms/{code}/questions/generate", json={"job_title": "backend engineer", "count": 3})
        print("questions:", r.status_code, len(r.json()))
        for q in r.json():
            print("  -", q["text"][:60])

        # next question (adaptive)
        r = await c.post(f"{BASE}/api/rooms/{code}/questions/next", json={"previous_answer": "I built REST APIs with FastAPI and deployed with Docker."})
        print("next question:", r.status_code, r.json().get("text", "")[:80])

        # rebuild graph
        r = await c.post(f"{BASE}/api/rooms/{code}/graph/rebuild")
        print("graph rebuild:", r.status_code, "nodes=", len(r.json()["nodes"]), "edges=", len(r.json()["edges"]))

        # get graph
        r = await c.get(f"{BASE}/api/rooms/{code}/graph")
        print("graph get:", r.status_code, "nodes=", len(r.json()["nodes"]), "edges=", len(r.json()["edges"]))

        # graph page
        r = await c.get(f"{GRAPH}/graph/{code}")
        print("graph page:", r.status_code)

    print("ALL OK")
    return 0

import asyncio
sys.exit(asyncio.run(main()))
