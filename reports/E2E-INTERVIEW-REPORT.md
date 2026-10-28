# End-to-End Interview Simulation — Proof Report

**Room:** `CF3S7WKX` · **Generated:** 2026-10-28 11:38 UTC · **Stack:** FastAPI + Groq whisper-large-v3 (real STT) + OpenRouter/Groq LLM + React UI · **Driver:** Playwright + WebSocket WAV replay

Every claim below is backed by a screenshot in `evidence/`. All audio was real WAV speech (Windows SAPI TTS) pushed through the production WebSocket protocol — no mocks.

## 1. Verification results

| Check | Result | Detail |
|---|---|---|
| host created room via UI | ✅ PASS | code=CF3S7WKX |
| ws probe joined room | ✅ PASS | — |
| bundled test.wav through STT | ✅ PASS | {"status": null, "text": "Hello, my name is Alice, and I am interviewing you today.", "reason": null} |
| resume uploaded via copilot UI | ✅ PASS | skills=['Python', 'AWS', 'Docker', 'FastAPI', 'GitHub Actions', 'Kafka']… |
| 5 questions generated from resume (LLM) | ✅ PASS | n=5 sources=['resume'] |
| Q1 asked via wav -> transcript | ✅ PASS | sim=1.00 |
| A1 answered via wav -> transcript | ✅ PASS | sim=0.93 |
| adaptive follow-up after A1 | ✅ PASS | source=adaptive answer-overlap=['and', 'api', 'fastapi', 'payments'] |
| Q2 asked via wav -> transcript | ✅ PASS | sim=1.00 |
| A2 answered via wav -> transcript | ✅ PASS | sim=0.96 |
| adaptive follow-up after A2 | ✅ PASS | source=adaptive answer-overlap=['and', 'celery', 'kubernetes', 'latency'] |
| Q3 asked via wav -> transcript | ✅ PASS | sim=0.94 |
| A3 answered via wav -> transcript | ✅ PASS | sim=1.00 |
| adaptive follow-up after A3 | ✅ PASS | source=adaptive answer-overlap=['and', 'connection', 'exhaustion', 'pgbouncer'] |
| Q4 asked via wav -> transcript | ✅ PASS | sim=1.00 |
| A4 answered via wav -> transcript | ✅ PASS | sim=1.00 |
| adaptive follow-up after A4 | ✅ PASS | source=adaptive answer-overlap=['and', 'builds', 'docker', 'multi'] |
| Q5 asked via wav -> transcript | ✅ PASS | sim=1.00 |
| A5 answered via wav -> transcript | ✅ PASS | sim=1.00 |
| adaptive follow-up after A5 | ✅ PASS | source=adaptive answer-overlap=['and', 'feature', 'flags', 'the'] |
| final adaptive question asked via wav -> transcript | ✅ PASS | sim=1.00 |
| contradiction answer -> transcript | ✅ PASS | sim=1.00 |
| graph rebuild from resume + transcript (UI) | ✅ PASS | Graph rebuilt: 41 nodes · 86 edges. |
| knowledge graph page renders nodes | ✅ PASS | ● LIVE · 41 NODES · 86 EDGES |
| all resume skills present as graph nodes | ✅ PASS | missing=none |
| transcript contributed nodes to the graph | ✅ PASS | 24 transcript-sourced nodes |
| claims extracted from answers | ✅ PASS | 17 claim nodes |
| contradiction (never ran k8s) produced a contradicts edge | ✅ PASS | 2 contradicts edges |
| graph grew from resume-only to resume+transcript | ✅ PASS | 17 -> 41 nodes |
| no uncaught browser errors | ✅ PASS | — |

## 2. Interview timeline (WAV → STT → transcript)

| Time (UTC) | Speaker | Transcribed utterance | Similarity | STT latency (ms) |
|---|---|---|---|---|
| 11:36:43 | Interviewer | `Question 1. How did you architect the FastAPI Payments API to handle 2M requests per day, and what scaling str…` | 1.00 | 808 |
| 11:36:45 | Candidate | `At Finlytics I built the Payments API with FastAPI and PostgreSQL. It processes about 2 million requests per d…` | 0.93 | 889 |
| 11:37:03 | Interviewer | `Question 2. Can you walk through the Redis caching strategy you implemented for the Payments API and explain h…` | 1.00 | 825 |
| 11:37:04 | Candidate | `We scaled the service with Redis caching and Celery workers running on Kubernetes. I wrote the Helm charts mys…` | 0.96 | 1187 |
| 11:37:22 | Interviewer | `Question 3. Describe the Terraform configuration you used to deploy the Kubernetes cluster on AWS EKS for Finl…` | 0.94 | 920 |
| 11:37:24 | Candidate | `During one outage I traced the problem to connection pool exhaustion in PostgreSQL. I added pgBouncer in front…` | 1.00 | 832 |
| 11:37:42 | Interviewer | `Question 4. What was your role in designing the Kafka ingestion pipelines at DataHive, and how did you ensure …` | 1.00 | 752 |
| 11:37:44 | Candidate | `I own the GitHub Actions pipeline. Docker images are built with multi-stage builds, scanned with Trivy, and de…` | 1.00 | 1168 |
| 11:38:02 | Interviewer | `Question 5. Explain the multi-stage Docker build process you set up in GitHub Actions for DataHive. How did it…` | 1.00 | 930 |
| 11:38:04 | Candidate | `Early at DataHive, I split a monolith into microservices too early, and it made the Kafka ingestion harder to …` | 1.00 | 1107 |
| 11:38:22 | Interviewer | `Question 6. Can you describe how you implemented feature flags for the new payment endpoint, including the fla…` | 1.00 | 1007 |
| 11:38:24 | Candidate | `To be honest, I have never actually run Kubernetes in production myself. At Finlytics, we used Docker Compose …` | 1.00 | 944 |

## 3. Resume-seeded questions

| # | Question (from /api/rooms/{code}/questions) | Source |
|---|---|---|
| 1 | `How did you architect the FastAPI payments API to handle 2M requests/day, and what scaling strategies did you employ?` | resume |
| 2 | `Can you walk through the Redis caching strategy you implemented for the payments API and explain how it reduced p95 late` | resume |
| 3 | `Describe the Terraform configuration you used to deploy the Kubernetes cluster on AWS EKS for Finlytics. What challenges` | resume |
| 4 | `What was your role in designing the Kafka ingestion pipelines at DataHive, and how did you ensure reliability and fault ` | resume |
| 5 | `Explain the multi-stage Docker build process you set up in GitHub Actions for DataHive. How did it improve build times o` | resume |

## 4. Adaptive question generation (from the transcript)

| After answer # | Adaptive follow-up generated | Source |
|---|---|---|
| 1 | `How did you instrument the FastAPI Payments API for observability, and what metrics did you expose to Grafana to monitor latency a` | adaptive |
| 2 | `How did you configure the Kubernetes HPA for the Celery workers to react to the P95 latency metric, and what thresholds did you se` | adaptive |
| 3 | `What were the specific configuration parameters you set for pgBouncer (pool size, timeout, etc.) to prevent connection pool exhaus` | adaptive |
| 4 | `How did you configure Trivy to scan for vulnerabilities in your multi-stage Docker builds, and what remediation steps did you take` | adaptive |
| 5 | `Can you describe how you implemented feature flags for the new payment endpoint, including the flag management tool you used and h` | adaptive |

## 5. Knowledge graph growth

| Stage | Nodes | Edges |
|---|---|---|
| resume upload | 17 | 16 |
| answer 1 | 24 | 32 |
| answer 2 | 28 | 45 |
| answer 3 | 32 | 54 |
| answer 4 | 35 | 67 |
| answer 5 | 38 | 77 |
| final rebuild | 41 | 86 |

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
