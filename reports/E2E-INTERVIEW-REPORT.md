# End-to-End Interview Simulation — Proof Report

**Room:** `5668XNQR` · **Generated:** 2026-10-28 14:02 UTC · **Stack:** FastAPI + Groq whisper-large-v3 (real STT) + OpenRouter/Groq LLM + React UI · **Driver:** Playwright + WebSocket WAV replay

Every claim below is backed by a screenshot in `evidence/`. All audio was real WAV speech (Windows SAPI TTS) pushed through the production WebSocket protocol — no mocks.

## 1. Verification results

| Check | Result | Detail |
|---|---|---|
| host created room via UI | ✅ PASS | code=5668XNQR |
| ws probe joined room | ✅ PASS | — |
| bundled test.wav through STT | ✅ PASS | {"status": null, "text": "Hello, my name is Alice, and I am interviewing you today.", "reason": null} |
| resume uploaded via copilot UI | ✅ PASS | skills=['Python', 'AWS', 'Docker', 'FastAPI', 'GitHub Actions', 'Kafka']… |
| 5 questions generated from resume (LLM) | ✅ PASS | n=5 sources=['resume'] |
| Q1 asked via wav -> transcript | ✅ PASS | sim=0.95 |
| A1 answered via wav -> transcript | ✅ PASS | sim=0.93 |
| adaptive follow-up after A1 | ✅ PASS | source=adaptive answer-overlap=['and', 'fastapi', 'the'] |
| Q2 asked via wav -> transcript | ✅ PASS | sim=1.00 |
| A2 answered via wav -> transcript | ✅ PASS | sim=0.96 |
| adaptive follow-up after A2 | ✅ PASS | source=adaptive answer-overlap=['and', 'helm', 'the'] |
| Q3 asked via wav -> transcript | ✅ PASS | sim=1.00 |
| A3 answered via wav -> transcript | ✅ PASS | sim=1.00 |
| adaptive follow-up after A3 | ✅ PASS | source=adaptive answer-overlap=['and', 'connection', 'exhaustion', 'pgbouncer'] |
| Q4 asked via wav -> transcript | ✅ PASS | sim=1.00 |
| A4 answered via wav -> transcript | ✅ PASS | sim=1.00 |
| adaptive follow-up after A4 | ✅ PASS | source=adaptive answer-overlap=['actions', 'and', 'github', 'the'] |
| Q5 asked via wav -> transcript | ✅ PASS | sim=0.89 |
| A5 answered via wav -> transcript | ✅ PASS | sim=1.00 |
| adaptive follow-up after A5 | ✅ PASS | source=adaptive answer-overlap=['and', 'feature', 'microservices', 'prototype'] |
| final adaptive question asked via wav -> transcript | ✅ PASS | sim=0.89 |
| contradiction answer -> transcript | ✅ PASS | sim=1.00 |
| graph rebuild from resume + transcript (UI) | ✅ PASS | Graph rebuilt: 41 nodes · 88 edges. |
| knowledge graph page renders nodes | ✅ PASS | ● LIVE · 41 NODES · 88 EDGES |
| all resume skills present as graph nodes | ✅ PASS | missing=none |
| transcript contributed nodes to the graph | ✅ PASS | 24 transcript-sourced nodes |
| claims extracted from answers | ✅ PASS | 16 claim nodes |
| contradiction (never ran k8s) produced a contradicts edge | ✅ PASS | 2 contradicts edges |
| graph grew from resume-only to resume+transcript | ✅ PASS | 17 -> 41 nodes |
| no uncaught browser errors | ✅ PASS | — |

## 2. Interview timeline (WAV → STT → transcript)

| Time (UTC) | Speaker | Transcribed utterance | Similarity | STT latency (ms) |
|---|---|---|---|---|
| 14:00:04 | Interviewer | `Question 1. What architectural decisions led you to choose FastAPI over Django for the payments API at Finlayt…` | 0.95 | 1276 |
| 14:00:06 | Candidate | `At Finlytics I built the Payments API with FastAPI and PostgreSQL. It processes about 2 million requests per d…` | 0.93 | 913 |
| 14:00:25 | Interviewer | `Question 2. Can you walk through the Redis caching strategy you implemented to reduce P95 latency, including k…` | 1.00 | 1210 |
| 14:00:28 | Candidate | `We scaled the service with Redis caching and Celery workers running on Kubernetes. I wrote the Helm charts mys…` | 0.96 | 1035 |
| 14:00:47 | Interviewer | `Question 3. Describe how you migrated Finlytics deployments to EKS using Terraform. What modules did you write…` | 1.00 | 1330 |
| 14:00:48 | Candidate | `During one outage I traced the problem to connection pool exhaustion in PostgreSQL. I added pgBouncer in front…` | 1.00 | 789 |
| 14:01:08 | Interviewer | `Question 4. How did you structure the Kafka ingestion pipelines at DataHive, and what techniques did you use t…` | 1.00 | 1193 |
| 14:01:11 | Candidate | `I own the GitHub Actions pipeline. Docker images are built with multi-stage builds, scanned with Trivy, and de…` | 1.00 | 952 |
| 14:01:30 | Interviewer | `Question 5. Explain the multistage Docker build process you configured in GitHub Actions, including any cachin…` | 0.89 | 1377 |
| 14:01:33 | Candidate | `Early at DataHive, I split a monolith into microservices too early, and it made the Kafka ingestion harder to …` | 1.00 | 898 |
| 14:02:00 | Interviewer | `Question 6. Can you describe the feature flag strategy you use to prototype new microservices, including the t…` | 0.89 | 2847 |
| 14:02:04 | Candidate | `To be honest, I have never actually run Kubernetes in production myself. At Finlytics, we used Docker Compose …` | 1.00 | 2769 |

## 3. Resume-seeded questions

| # | Question (from /api/rooms/{code}/questions) | Source |
|---|---|---|
| 1 | `What architectural decisions led you to choose FastAPI over Django for the payments API at Finlytics, and how did you ha` | resume |
| 2 | `Can you walk through the Redis caching strategy you implemented to reduce p95 latency, including key design and eviction` | resume |
| 3 | `Describe how you migrated Finlytics’ deployments to EKS using Terraform—what modules did you write and how did you manag` | resume |
| 4 | `How did you structure the Kafka ingestion pipelines at DataHive, and what techniques did you use to ensure message order` | resume |
| 5 | `Explain the multi‑stage Docker build process you configured in GitHub Actions, including any caching strategies and how ` | resume |

## 4. Adaptive question generation (from the transcript)

| After answer # | Adaptive follow-up generated | Source |
|---|---|---|
| 1 | `How did you instrument the FastAPI payment endpoints for observability, and what metrics or alerts did you set up to detect latenc` | adaptive |
| 2 | `How did you validate the Helm chart deployments before rolling them out to production, and what rollback strategy did you implemen` | adaptive |
| 3 | `How did you configure pgBouncer’s connection limits and pooling mode to prevent exhaustion, and what metrics did you monitor to va` | adaptive |
| 4 | `How do you handle failures in the Trivy image scans during the GitHub Actions workflow, and what remediation steps do you trigger ` | adaptive |
| 5 | `Can you describe the feature‑flag strategy you use to prototype new microservices, including the tooling and how you ensure safe r` | adaptive |

## 5. Knowledge graph growth

| Stage | Nodes | Edges |
|---|---|---|
| resume upload | 17 | 16 |
| answer 1 | 19 | 24 |
| answer 2 | 28 | 45 |
| answer 3 | 30 | 52 |
| answer 4 | 37 | 75 |
| answer 5 | 42 | 84 |
| final rebuild | 41 | 88 |

## 6. Proof — screenshots


### Landing page (redesigned UI)

![01-landing.png](evidence/01-landing.png)


### Host creates the room

![02-room-created.png](evidence/02-room-created.png)


### Resume uploaded via Copilot — skills detected, graph seeded

![03-resume-uploaded.png](evidence/03-resume-uploaded.png)


### Questions generated from the resume (LLM)

![04-questions-generated.png](evidence/04-questions-generated.png)


### Interview round 1: question asked (WAV) → live transcript, candidate answers (WAV) → live transcript, adaptive follow-up generated

![q1-asked.png](evidence/q1-asked.png)

![a1-answered.png](evidence/a1-answered.png)

![adaptive-1.png](evidence/adaptive-1.png)


### Interview round 2: question asked (WAV) → live transcript, candidate answers (WAV) → live transcript, adaptive follow-up generated

![q2-asked.png](evidence/q2-asked.png)

![a2-answered.png](evidence/a2-answered.png)

![adaptive-2.png](evidence/adaptive-2.png)


### Interview round 3: question asked (WAV) → live transcript, candidate answers (WAV) → live transcript, adaptive follow-up generated

![q3-asked.png](evidence/q3-asked.png)

![a3-answered.png](evidence/a3-answered.png)

![adaptive-3.png](evidence/adaptive-3.png)


### Interview round 4: question asked (WAV) → live transcript, candidate answers (WAV) → live transcript, adaptive follow-up generated

![q4-asked.png](evidence/q4-asked.png)

![a4-answered.png](evidence/a4-answered.png)

![adaptive-4.png](evidence/adaptive-4.png)


### Interview round 5: question asked (WAV) → live transcript, candidate answers (WAV) → live transcript, adaptive follow-up generated

![q5-asked.png](evidence/q5-asked.png)

![a5-answered.png](evidence/a5-answered.png)

![adaptive-5.png](evidence/adaptive-5.png)


### Final adaptive question asked and answered with the deliberate contradiction

![adaptive-final-asked.png](evidence/adaptive-final-asked.png)

![contradiction-answered.png](evidence/contradiction-answered.png)


### Full transcript at the end of the interview

![transcript-final.png](evidence/transcript-final.png)


### Graph rebuild from resume + transcript (Copilot banner)

![graph-rebuilt.png](evidence/graph-rebuilt.png)


### Live knowledge graph (D3 render)

![graph-view.png](evidence/graph-view.png)

![graph-view-settled.png](evidence/graph-view-settled.png)


### Copilot panel after the full interview

![copilot-final.png](evidence/copilot-final.png)


## 7. Raw evidence

- `evidence/graph_final.json` — final graph (nodes, edges, relations, evidence spans)
- `evidence/transcript_dump.json` — every transcribed utterance with STT latency
- `evidence/questions_final.json` — full question list incl. adaptive follow-ups
- `evidence/summary.json` — machine-readable check results
