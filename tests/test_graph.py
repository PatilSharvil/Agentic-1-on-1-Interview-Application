import pytest

from app.graph_builder import (
    GraphData,
    _evidence_in_transcript,
    add_llm_layer,
    build_graph_data,
    match_skills,
    parse_resume,
    summarise_for_questions,
)

RESUME = """Sharun Patil
Backend Engineer

Skills
Languages: Python, TypeScript, JavaScript, SQL
Frameworks: FastAPI, Django, React, Node.js
Databases: PostgreSQL, MySQL, Redis, MongoDB
Cloud & DevOps: AWS, Docker, Kubernetes, Terraform, GitHub Actions

Experience
Senior Backend Engineer at TechCorp | Jan 2022 - Present
- Built high-throughput REST APIs with FastAPI and PostgreSQL serving 2M requests/day.
- Deployed services on AWS using Docker and Kubernetes.

Software Engineer at DataWorks | Jun 2020 - Dec 2021
- Developed ETL pipelines with Python and Apache Kafka.

Projects
Realtime Analytics Platform: Built a streaming dashboard with Kafka, Python, and React.
Interview Copilot - FastAPI service that generates interview questions using LLMs.

Education
B.Tech in Computer Science, Pune University, 2020
"""

TRANSCRIPTS = [
    {"speaker": "Interviewer", "text": "Tell me about your work at TechCorp."},
    {"speaker": "Candidate", "text": "At TechCorp I built REST APIs with FastAPI and PostgreSQL, and I deployed them on AWS with Docker."},
    {"speaker": "Candidate", "text": "I have never used Kubernetes in production, so I am not familiar with cluster operations."},
    {"speaker": "Candidate", "text": "I reduced API latency by forty percent by adding a Redis cache in front of the database."},
]


def test_parse_resume_extracts_core_facts():
    p = parse_resume(RESUME)
    assert p.name == "Sharun Patil"
    for skill in ["Python", "FastAPI", "React", "Node.js", "PostgreSQL", "Docker", "Kubernetes", "AWS"]:
        assert skill in p.skills, skill
    assert "TechCorp" in p.companies
    assert "DataWorks" in p.companies
    project_names = [proj["name"] for proj in p.projects]
    assert "Realtime Analytics Platform" in project_names
    assert "Interview Copilot" in project_names


def test_skill_matching_ignores_common_english():
    assert "React" in match_skills("I built the UI in React and TypeScript.")
    assert "React" not in match_skills("I react quickly to incidents.")
    assert "Go" in match_skills("I write Go and Python services.")
    assert "Go" not in match_skills("I go to the office daily.")


def test_resume_only_graph_is_immediately_useful():
    g = build_graph_data(RESUME, [], use_llm=False)
    ids = {n["id"] for n in g["nodes"]}
    assert "person:candidate" in ids
    assert "skill:python" in ids
    assert "skill:fastapi" in ids
    assert "entity:techcorp" in ids

    rels = {(e["source"], e["target"], e["relation"]) for e in g["edges"]}
    # Every skill must be reachable — categorised ones via their category hub,
    # uncategorised ones via a direct candidate anchor edge (never orphans).
    skill_ids = {n["id"] for n in g["nodes"] if n["type"] == "skill"}
    reachable = set()
    for e in g["edges"]:
        reachable.add(e["target"])
        reachable.add(e["source"])
    assert skill_ids <= reachable
    assert ("person:candidate", "skill:python", "has_skill") in rels
    assert ("person:candidate", "entity:techcorp", "worked_at") in rels
    assert not any(e["relation"] == "contradicts" for e in g["edges"])


def test_transcript_adds_support_and_contradiction_edges():
    g = build_graph_data(RESUME, TRANSCRIPTS, "Interviewer", use_llm=False)
    rels = {(e["source"], e["target"], e["relation"]) for e in g["edges"]}
    assert ("person:candidate", "skill:kubernetes", "contradicts") in rels
    assert ("person:candidate", "skill:fastapi", "supports") in rels
    assert any(e["relation"] == "supports" and e["target"] == "skill:redis" for e in g["edges"])
    assert g["stats"]["contradictions"] >= 1
    assert g["stats"]["claims"] >= 2


def test_interviewer_lines_do_not_become_claims():
    transcripts = [
        {"speaker": "Interviewer", "text": "I have never used Kubernetes and I built nothing with FastAPI."},
        {"speaker": "Candidate", "text": "I built a REST API with FastAPI."},
    ]
    g = build_graph_data(RESUME, transcripts, "Interviewer", use_llm=False)
    contradiction_edges = [e for e in g["edges"] if e["relation"] == "contradicts"]
    assert not contradiction_edges


def test_claims_are_deduplicated_across_rebuilds():
    g1 = build_graph_data(RESUME, TRANSCRIPTS, "Interviewer", use_llm=False)
    claims1 = [n for n in g1["nodes"] if n["type"] == "claim"]
    g2 = build_graph_data(RESUME, TRANSCRIPTS + TRANSCRIPTS, "Interviewer", use_llm=False)
    claims2 = [n for n in g2["nodes"] if n["type"] == "claim"]
    assert len(claims2) == len(claims1)


def test_evidence_validation_rejects_fabrication():
    blob = "I built REST APIs with FastAPI and PostgreSQL and deployed them on AWS."
    assert _evidence_in_transcript("I built REST APIs with FastAPI and PostgreSQL", blob)
    assert not _evidence_in_transcript("I led a team of twenty engineers at Google", blob)
    assert not _evidence_in_transcript("short", blob)


def test_llm_layer_drops_unquoted_claims(monkeypatch):
    graph = GraphData()
    graph.add_node("person:candidate", "Candidate", "entity", {})
    graph.add_node("skill:python", "Python", "skill", {})
    fabricated = {
        "claims": [
            {
                "text": "Led a team of twenty engineers",
                "evidence": "I led a team of twenty engineers at Google",
                "skills": ["Python"],
                "verdict": "supports",
                "confidence": 0.9,
            }
        ]
    }
    monkeypatch.setattr("app.graph_builder._llm_claims", lambda *a, **k: fabricated["claims"])
    monkeypatch.setattr("app.graph_builder.settings.graph_llm_enrich", True)
    transcripts = [{"speaker": "Candidate", "text": "I built REST APIs with FastAPI and PostgreSQL."}]
    added = add_llm_layer(graph, RESUME, transcripts, "Candidate")
    assert added == 0
    assert not any(n["type"] == "claim" for n in graph.nodes.values())


def test_llm_layer_keeps_quoted_claims(monkeypatch):
    graph = GraphData()
    graph.add_node("person:candidate", "Candidate", "entity", {})
    claim = {
        "text": "Built REST APIs with FastAPI and PostgreSQL",
        "evidence": "I built REST APIs with FastAPI and PostgreSQL.",
        "skills": ["FastAPI", "PostgreSQL"],
        "verdict": "supports",
        "confidence": 0.9,
    }
    monkeypatch.setattr("app.graph_builder._llm_claims", lambda *a, **k: [claim])
    monkeypatch.setattr("app.graph_builder.settings.graph_llm_enrich", True)
    transcripts = [{"speaker": "Candidate", "text": "I built REST APIs with FastAPI and PostgreSQL."}]
    added = add_llm_layer(graph, RESUME, transcripts, "Candidate")
    assert added == 1
    claims = [n for n in graph.nodes.values() if n["type"] == "claim"]
    assert len(claims) == 1
    rels = {(e["source"], e["target"], e["relation"]) for e in graph.edges.values()}
    assert ("person:candidate", "skill:fastapi", "supports") in rels


def test_empty_resume_produces_safe_graph():
    g = build_graph_data("", [], use_llm=False)
    assert [n["id"] for n in g["nodes"]] == ["person:candidate"]
    assert g["edges"] == []


def test_summary_for_questions_is_compact():
    s = summarise_for_questions(RESUME)
    assert s["name"] == "Sharun Patil"
    assert 0 < len(s["skills"]) <= 15
    assert "TechCorp" in s["companies"]


def test_skill_keys_are_stable_across_builds():
    g1 = build_graph_data(RESUME, [], use_llm=False)
    g2 = build_graph_data(RESUME, [], use_llm=False)
    assert {n["id"] for n in g1["nodes"]} == {n["id"] for n in g2["nodes"]}
    assert {(e["source"], e["target"], e["relation"]) for e in g1["edges"]} == {
        (e["source"], e["target"], e["relation"]) for e in g2["edges"]
    }


@pytest.mark.parametrize(
    "resume",
    [
        "Skills: Python, Java, AWS",
        "Experience: 3 years at TechCorp",
        "Projects\nProject: Chat App - React and Node.js",
    ],
)
def test_odd_resume_formats_do_not_crash(resume):
    g = build_graph_data(resume, [], use_llm=False)
    assert any(n["id"] == "person:candidate" for n in g["nodes"])
