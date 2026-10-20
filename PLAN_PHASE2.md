# Phase 2 — Agentic AI Interviewing Layer (Plan)

Base (Phase 1) is complete and tested. This phase adds the copilot, adaptive questioning, and live knowledge graph. Chatting through design before coding.

## Requirements (from you)
1. **Copilot sidebar** — visible only to the interviewer (host). Contains: resume upload, generated questions, "next question" button, link to the live knowledge graph.
2. **Resume → questions** — upload a resume (PDF/text); LLM generates interview questions from it.
3. **Adaptive questioning** — interviewer clicks "get next question" based on the candidate's previous answer → LLM generates an adaptive follow-up question.
4. **Knowledge graph** — nodes/edges built from the resume + candidate answers. Edges encode relevance (does answer match resume?) and truthfulness (is the candidate consistent?). Shown to interviewer only, on a **separate port** (e.g. 5133), **updated in real time**.
5. **LLM provider**: OpenRouter (free models, 1000 req/day). New env: `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`.

## Architecture

```
React copilot (host only)  <--REST/WS-->  FastAPI backend (port 8000)
   |                                            |
   | resume upload, questions, graph API         | OpenRouter LLM
   |                                            | SQLite (rooms, transcripts, questions, graph)
   v                                            v
Knowledge graph page (port 5133)  <--WS (real-time graph updates)-->  main backend
```

The graph page is a separate lightweight server on port 5133 serving a D3.js force-directed graph that subscribes to the main backend's WebSocket for live node/edge updates.

## Data model additions
- `Resume(id, room_id, filename, text, parsed_at)`
- `Question(id, room_id, text, source: resume|adaptive, parent_id?, created_at)`
- `GraphNode(id, room_id, label, type: skill|topic|claim|entity, meta JSON)`
- `GraphEdge(id, room_id, source_node, target_node, relation: supports|contradicts|mentions|related, weight float)`

## Backend additions
- `app/openrouter.py` — OpenAI-SDK client pointed at `https://openrouter.ai/api/v1` with `OPENROUTER_API_KEY` / `OPENROUTER_MODEL`.
- `POST /api/rooms/{code}/resume` — multipart upload, extract text (pdfminer for PDF, plain text otherwise), store Resume.
- `POST /api/rooms/{code}/questions/generate` — LLM generates N questions from resume text (+ optional job title). Stores Question rows, returns list.
- `POST /api/rooms/{code}/questions/next` — body: `{ previous_answer }` (or pulls latest transcript). LLM generates one adaptive follow-up. Stores + returns.
- `GET /api/rooms/{code}/questions` — list questions.
- `GET /api/rooms/{code}/graph` — nodes + edges.
- `POST /api/rooms/{code}/graph/rebuild` — LLM extracts entities/claims from resume + transcripts, evaluates relevance & truthfulness, writes nodes/edges. Broadcasts `graph-update` over WS.
- WS events: `graph-update` (payload: {nodes, edges}), `question` (new question generated).

## LLM prompts (OpenRouter free model)
- Question gen: "Given this resume and role, generate 5 interview questions as JSON array."
- Adaptive: "Given the candidate's last answer and resume, generate one deeper follow-up question."
- Graph extraction: "Extract entities (skills, projects, companies, claims) from resume+answers. For each candidate claim, mark supports/contradicts vs resume. Return JSON {nodes:[{id,label,type}], edges:[{source,target,relation,weight}]}."

Free model pick: `openrouter/free` (router, auto-picks best available free model). Fallback: `nvidia/nemotron-3-ultra-550b-a55b:free`. Both verified available on OpenRouter.

## Frontend additions (React)
- Copilot sidebar (only when `role === 'host'`): collapsible panel on the right.
  - Resume upload widget.
  - "Generate questions" button → list of questions.
  - "Get next question" button → appends adaptive question.
  - "Rebuild knowledge graph" button.
  - iframe/link to `http://localhost:5133/graph/{code}`.
- Knowledge graph page (port 5133): D3.js force-directed graph, nodes colored by type, edges colored by relation (green=supports, red=contradicts, gray=mentions). Subscribes to WS `graph-update` for live updates.

## Separate graph server
- `graph_server.py` on port 5133: FastAPI serving `graph.html` (D3). The page opens a WebSocket to `ws://localhost:8000/ws/{code}` and listens for `graph-update`. On receipt, re-renders the graph. This keeps the graph "hosted on a separate port" and dynamically updated.

## Resolved (from your answers)
1. **OpenRouter API key**: you have one → add `OPENROUTER_API_KEY` to `.env`.
2. **Free model**: `llama-3.3-70b-instruct:free` etc. are no longer available. Use `openrouter/free` (router) as default, with `nvidia/nemotron-3-ultra-550b-a55b:free` as fallback. Configurable via `OPENROUTER_MODEL`.
3. **Graph trigger**: auto-rebuild after each candidate answer (recommended) + manual "Rebuild graph" button.
4. **Knowledge graph page port**: 5133.
5. **Resume parsing**: PDF (pdfminer, already installed) + plain text. DOCX later.
6. **Copilot placement**: right sidebar (collapsible, host only).

## Phases
A. OpenRouter client + resume upload + question gen + tests.
B. Adaptive "next question" endpoint + copilot UI (host only).
C. Knowledge graph data model + rebuild API + WS broadcast.
D. Graph visualization page + separate server on 5133.
E. Polish: real-time auto-rebuild, styling, README.

## Risks
- OpenRouter free models have rate limits (~20 req/min) and occasional downtime. Add fallback to Groq Llama/Qwen if OpenRouter fails.
- JSON parsing from LLM can be malformed → validate with pydantic, retry once.
- Graph can grow large → cap nodes/edges (e.g., 50 nodes, 100 edges) per room.

## Next step
Reply "go" (or adjust open questions) and I'll implement Phase A + B first, then C + D.