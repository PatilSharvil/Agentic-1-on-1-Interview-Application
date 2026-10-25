"""Knowledge-graph construction.

Design goals:
  * always produce a useful graph from the resume alone (no LLM required),
  * only add transcript claims that are backed by a verbatim quote,
  * merge/dedupe deterministically so repeated rebuilds are stable,
  * never let an LLM invent nodes that are not in the source text.

The graph is built from three layers:
  1. deterministic resume parsing (skills, companies, projects, education),
  2. deterministic transcript analysis (affirmation/contradiction of resume skills),
  3. optional LLM claim extraction, where every claim must quote the transcript.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from app.config import settings

# --------------------------------------------------------------------------- #
# Skill lexicon (canonical name -> aliases). Ambiguous aliases are matched
# case-sensitively so ordinary English ("I react quickly") is not a skill.
# --------------------------------------------------------------------------- #

_SAFE_SKILLS: dict[str, tuple[str, ...]] = {
    "Python": ("python", "python3"),
    "Java": ("java",),
    "JavaScript": ("javascript", "java script", "js"),
    "TypeScript": ("typescript", "type script", "ts"),
    "C++": ("c++", "cpp"),
    "C#": ("c#", "csharp", "c sharp"),
    "Go": ("golang",),
    "Kotlin": ("kotlin",),
    "PHP": ("php",),
    "Ruby": ("ruby", "ruby on rails"),
    "Scala": ("scala",),
    "MATLAB": ("matlab",),
    "SQL": ("sql", "structured query language"),
    "NoSQL": ("nosql",),
    "PostgreSQL": ("postgresql", "postgres", "post gres", "postgres sql"),
    "MySQL": ("mysql", "my sql"),
    "SQLite": ("sqlite",),
    "MongoDB": ("mongodb", "mongo db", "mongo"),
    "Redis": ("redis",),
    "Cassandra": ("cassandra",),
    "DynamoDB": ("dynamodb", "dynamo db"),
    "Elasticsearch": ("elasticsearch", "elastic search"),
    "Oracle": ("oracle db", "oracle database"),
    "Snowflake": ("snowflake",),
    "BigQuery": ("bigquery", "big query"),
    "Kafka": ("kafka", "apache kafka"),
    "RabbitMQ": ("rabbitmq", "rabbit mq"),
    "Spark": ("apache spark", "pyspark"),
    "Hadoop": ("hadoop",),
    "dbt": ("dbt",),
    "Databricks": ("databricks",),
    "React": ("react.js", "reactjs", "react js"),
    "Next.js": ("next.js", "nextjs", "next js"),
    "Vue": ("vue", "vue.js", "vuejs"),
    "Angular": ("angular", "angularjs"),
    "Svelte": ("svelte", "sveltekit"),
    "Node.js": ("node.js", "nodejs", "node js"),
    "Express": ("express.js", "expressjs", "express js"),
    "FastAPI": ("fastapi", "fast api"),
    "Django": ("django",),
    "Flask": ("flask",),
    "Spring Boot": ("spring boot", "springboot", "spring-boot"),
    ".NET": (".net", "dotnet", "asp.net"),
    "Laravel": ("laravel",),
    "GraphQL": ("graphql", "graph ql"),
    "REST API": ("rest api", "restful", "rest apis"),
    "gRPC": ("grpc",),
    "WebSocket": ("websocket", "websockets", "web socket"),
    "HTML": ("html", "html5"),
    "CSS": ("css", "css3"),
    "Tailwind CSS": ("tailwind", "tailwindcss", "tailwind css"),
    "Redux": ("redux",),
    "React Native": ("react native",),
    "Flutter": ("flutter",),
    "Docker": ("docker",),
    "Kubernetes": ("kubernetes", "k8s", "k eight s"),
    "Terraform": ("terraform",),
    "Ansible": ("ansible",),
    "Jenkins": ("jenkins",),
    "GitHub Actions": ("github actions",),
    "GitLab CI": ("gitlab ci", "gitlab-ci"),
    "CircleCI": ("circleci", "circle ci"),
    "ArgoCD": ("argocd", "argo cd"),
    "Helm": ("helm charts", "helm chart"),
    "AWS": ("aws", "amazon web services"),
    "GCP": ("gcp", "google cloud platform", "google cloud"),
    "Azure": ("azure", "microsoft azure"),
    "Lambda": ("aws lambda",),
    "S3": ("amazon s3", "aws s3"),
    "EC2": ("aws ec2",),
    "CloudFormation": ("cloudformation", "cloud formation"),
    "Prometheus": ("prometheus",),
    "Grafana": ("grafana",),
    "Datadog": ("datadog", "data dog"),
    "Nginx": ("nginx",),
    "Linux": ("linux",),
    "Bash": ("bash", "shell scripting"),
    "Git": ("git",),
    "GitHub": ("github",),
    "GitLab": ("gitlab",),
    "Machine Learning": ("machine learning", "ml models"),
    "Deep Learning": ("deep learning",),
    "TensorFlow": ("tensorflow", "tensor flow"),
    "PyTorch": ("pytorch", "py torch"),
    "scikit-learn": ("scikit-learn", "scikit learn", "sklearn"),
    "Pandas": ("pandas",),
    "NumPy": ("numpy",),
    "OpenCV": ("opencv", "open cv"),
    "NLP": ("nlp", "natural language processing"),
    "LLM": ("llm", "llms", "large language model"),
    "RAG": ("rag", "retrieval augmented generation", "retrieval-augmented generation"),
    "LangChain": ("langchain", "lang chain"),
    "Hugging Face": ("hugging face", "huggingface"),
    "Microservices": ("microservices", "micro services", "microservice"),
    "System Design": ("system design", "distributed systems"),
    "Data Structures": ("data structures",),
    "Algorithms": ("algorithms",),
    "OOP": ("oop", "object oriented", "object-oriented"),
    "Design Patterns": ("design patterns",),
    "Agile": ("agile",),
    "Scrum": ("scrum",),
    "Jira": ("jira",),
    "Cybersecurity": ("cybersecurity", "cyber security", "application security", "appsec"),
    "OAuth": ("oauth", "oauth2", "oauth 2"),
    "JWT": ("jwt", "json web token"),
    "Encryption": ("encryption", "cryptography"),
    "Figma": ("figma",),
    "Jest": ("jest",),
    "Pytest": ("pytest",),
    "Playwright": ("playwright",),
    "Cypress": ("cypress",),
    "Selenium": ("selenium",),
    "Power BI": ("power bi", "powerbi"),
    "Tableau": ("tableau",),
    "Salesforce": ("salesforce",),
    "SAP": ("sap",),
    "Solidity": ("solidity",),
    "Unity": ("unity engine", "unity3d"),
    "Unreal Engine": ("unreal engine", "unreal"),
}

# Case-sensitive canonical words: matching lowercase English words would be wrong.
_CASE_SENSITIVE_SKILLS: dict[str, tuple[str, ...]] = {
    "Go": ("Golang", "GOLANG", "Go"),
    "C": ("C language", "C programming"),
    "R": ("R programming", "R language"),
    "React": ("React", "REACT"),
    "Rust": ("Rust", "RUST"),
    "Swift": ("Swift", "SWIFT"),
    "Spark": ("Spark", "PySpark"),
    "Airflow": ("Airflow", "AirFlow"),
    "Unity": ("Unity", "UNITY"),
}

_ALIAS_TO_CANONICAL: dict[str, str] = {}
_ALIAS_TO_CANONICAL_CS: dict[str, str] = {}
for _canon, _aliases in _SAFE_SKILLS.items():
    for _a in _aliases:
        _ALIAS_TO_CANONICAL[_a.lower()] = _canon
for _canon, _aliases in _CASE_SENSITIVE_SKILLS.items():
    for _a in _aliases:
        _ALIAS_TO_CANONICAL_CS[_a] = _canon


def _build_matcher() -> tuple[re.Pattern, re.Pattern]:
    ci = "|".join(re.escape(a) for a in sorted(_ALIAS_TO_CANONICAL, key=len, reverse=True))
    cs = "|".join(re.escape(a) for a in sorted(_ALIAS_TO_CANONICAL_CS, key=len, reverse=True))
    bound_l = r"(?<![A-Za-z0-9+#.])"
    bound_r = r"(?![A-Za-z0-9+#])"
    return (
        re.compile(bound_l + f"(?i:{ci})" + bound_r),
        re.compile(bound_l + f"(?:{cs})" + bound_r),
    )


_CI_RE, _CS_RE = _build_matcher()


def canonical_skill(name: str) -> str | None:
    raw = name.strip()
    if not raw:
        return None
    low = raw.lower()
    if low in _ALIAS_TO_CANONICAL:
        return _ALIAS_TO_CANONICAL[low]
    if raw in _ALIAS_TO_CANONICAL_CS:
        return _ALIAS_TO_CANONICAL_CS[raw]
    # already canonical?
    for canon in list(_SAFE_SKILLS) + list(_CASE_SENSITIVE_SKILLS):
        if canon.lower() == low:
            return canon
    return None


def match_skills(text: str) -> list[str]:
    found: dict[str, int] = {}
    for m in _CI_RE.finditer(text):
        canon = _ALIAS_TO_CANONICAL.get(m.group(0).lower())
        if canon:
            found[canon] = found.get(canon, 0) + 1
    for m in _CS_RE.finditer(text):
        canon = _ALIAS_TO_CANONICAL_CS.get(m.group(0))
        if canon:
            found[canon] = found.get(canon, 0) + 1
    return [k for k, _ in sorted(found.items(), key=lambda kv: (-kv[1], kv[0]))]


# --------------------------------------------------------------------------- #
# Resume parsing
# --------------------------------------------------------------------------- #

_SECTION_ALIASES = {
    "summary": ("summary", "profile", "objective", "about me", "professional summary"),
    "skills": ("skills", "technical skills", "core skills", "core competencies", "technologies", "tech stack", "technical proficiencies", "expertise"),
    "experience": ("experience", "work experience", "professional experience", "employment", "employment history", "work history"),
    "projects": ("projects", "personal projects", "academic projects", "selected projects", "key projects"),
    "education": ("education", "academics", "academic background", "qualifications"),
    "certifications": ("certifications", "certificates", "licenses"),
    "awards": ("awards", "achievements", "honors"),
}

_HEADER_LOOKUP: dict[str, str] = {}
for _section, _names in _SECTION_ALIASES.items():
    for _n in _names:
        _HEADER_LOOKUP[_n] = _section


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or hashlib.sha1(text.encode("utf-8", "ignore")).hexdigest()[:8]


def _clean_line(line: str) -> str:
    return re.sub(r"^[\s•·▪◦\-–—*]+", "", line).strip()


def _sectionise(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {k: [] for k in _SECTION_ALIASES}
    sections["_other"] = []
    current = "_other"
    for raw_line in (text or "").splitlines():
        line = _clean_line(raw_line)
        if not line:
            continue
        probe = re.sub(r"[:\-–—]+$", "", line).strip().lower()
        probe = re.sub(r"\s+", " ", probe)
        if len(line) <= 60 and probe in _HEADER_LOOKUP:
            # "Tech Stack:" / "Technologies:" lines belong to the last project /
            # experience entry, they must not hijack the whole section.
            if not (probe in _META_LABELS and current in {"experience", "projects"}):
                current = _HEADER_LOOKUP[probe]
                continue
        # "Skills: Python, Docker"
        inline = re.match(r"^([A-Za-z&/ ]{2,40})\s*[:\-–—]\s*(.+)$", line)
        if inline and inline.group(1).strip().lower() in _HEADER_LOOKUP:
            label = inline.group(1).strip().lower()
            if label in _META_LABELS and current in {"experience", "projects"}:
                sections[current].append(line)
            else:
                current = _HEADER_LOOKUP[label]
                sections[current].append(inline.group(2).strip())
            continue
        sections[current].append(line)
    return sections


def _find_name(text: str) -> str | None:
    for line in (text or "").splitlines()[:10]:
        candidate = _clean_line(line)
        if not candidate or len(candidate) > 50:
            continue
        low = candidate.lower()
        if any(tok in low for tok in ("resume", "curriculum", "vitae", "@", "http", "linkedin", "github")):
            continue
        if re.fullmatch(r"[A-Z][a-zA-Z'’.-]+(?:\s+[A-Z][a-zA-Z'’.-]+){1,2}", candidate):
            return candidate
    return None


_DATE_TOKENS = r"jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec"
_MONTH_RANGE_RE = re.compile(
    rf"^(?:{_DATE_TOKENS})[a-z]*\.?\s*\d{{4}}(?:\s*[–—-]\s*(?:\d{{4}}|present))?(?:\s*[–—-]\s*\d{{4}})?$",
    re.I,
)
_YEAR_RANGE_RE = re.compile(r"^\d{4}\s*[–—-]?\s*(?:\d{4}|present)?$", re.I)
_META_LABELS = {"tech stack", "technologies", "technologies used", "tools", "tools used", "tools & technologies"}


def _looks_like_date(text: str) -> bool:
    s = re.sub(r"\s+", " ", text.strip()).strip(" .")
    return bool(_MONTH_RANGE_RE.match(s) or _YEAR_RANGE_RE.match(s))


_ENTITY_STOPWORDS = {
    "the", "a", "an", "scale", "least", "work", "my", "our", "this", "that", "present",
    "current", "home", "remote", "hybrid", "onsite", "company", "client", "employer",
    "university", "college", "school", "internship", "freelance", "contract",
    "certificate", "certificates", "certification", "certifications", "link", "links",
    "projects", "project", "experience", "work experience", "achievements",
    "open source contributions", "contributions", "portfolio", "resume",
    "curriculum", "tech",
}


def _clean_entity(name: str) -> str | None:
    candidate = re.sub(r"\s+", " ", name).strip(" .,|·-–—")
    candidate = re.sub(r"\b(?:remote|hybrid|onsite|on-site)\b", "", candidate, flags=re.I).strip(" ,.-")
    candidate = re.sub(r"\s*\((?:[^)]*)\)\s*", " ", candidate).strip()
    if not candidate or len(candidate) < 2 or len(candidate) > 48:
        return None
    if candidate.lower() in _ENTITY_STOPWORDS:
        return None
    if _looks_like_date(candidate):
        return None
    if re.fullmatch(r"[\d\s.,/\-–—]+", candidate):
        return None
    if re.search(r"\b(?:engineer|developer|manager|intern|analyst|consultant|architect|specialist|scientist)\b", candidate, re.I):
        return None
    if len(candidate.split()) > 5:
        return None
    return candidate


_ROLE_WORDS_RE = re.compile(
    r"\b(?:developer|engineer|intern|internship|manager|analyst|consultant|architect|"
    r"specialist|scientist|freelancer|associate|trainee|contributor)\b",
    re.I,
)


def _extract_companies(sections: dict[str, list[str]], full_text: str) -> list[str]:
    """Parse the experience section line-block wise.

    Real resumes look like:
        Full Stack Developer            <- role
        Shree Science Academy (Sponsored Project)   <- organisation
        Mar 2026 – May 2026             <- dates
        • Built ...                     <- description

    Dates must never become companies, and a bare role line is followed by the
    organisation name.
    """
    found: list[str] = []
    seen: set[str] = set()

    def add(company: str | None) -> None:
        if not company:
            return
        key = re.sub(r"[^a-z0-9]+", "", company.lower())
        if key and key not in seen:
            seen.add(key)
            found.append(company)

    def try_add(raw: str) -> bool:
        company = _clean_entity(raw)
        if company and company.lower() not in {"the", "a", "an", "and"}:
            add(company)
            return True
        return False

    for section in ("experience", "_other"):
        prev_role = False
        for raw_line in sections.get(section, []):
            line = _clean_line(raw_line)
            stripped = line.strip()
            if not stripped:
                continue
            low = re.sub(r"\s+", " ", stripped.lower()).strip().strip(":")
            if _looks_like_date(stripped) or low in _ENTITY_STOPWORDS:
                prev_role = False
                continue

            added = False
            # "Company: X" label style
            m = re.search(r"(?:Company|Employer|Organization|Client)\s*[:\-–—]\s*([^,;|()\[\]]{2,48})", stripped)
            if m:
                added = try_add(m.group(1))

            # "Company | Jan 2024" / "Company - Software Engineer" header style
            m = re.match(
                r"^\s*([A-Z][A-Za-z0-9&.'\- ]{1,40})\s*(?:[|·–—]|,\s*)\s*"
                r"(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*|\d{4})",
                stripped,
            )
            if not added and m:
                added = try_add(m.group(1))

            # "... at Company" style
            if not added:
                m = re.search(r"\bat\s+([A-Z][A-Za-z0-9&.'\- ]{1,40})", stripped)
                if m:
                    added = try_add(m.group(1))
            if added:
                prev_role = False
                continue

            if _ROLE_WORDS_RE.search(stripped) and len(stripped.split()) <= 8:
                prev_role = True
                continue

            # The line directly after a role line is usually the organisation.
            if prev_role and re.match(r"^[A-Z]", stripped):
                org = _clean_entity(stripped)
                if org:
                    add(org)
            prev_role = False

    if not found:
        # last resort: "Experience: 3 years at TechCorp"
        for m in re.finditer(r"\bat\s+([A-Z][A-Za-z0-9&.'\-]{1,30})", full_text):
            company = _clean_entity(m.group(1))
            if company:
                add(company)
    return found[:6]


def _extract_projects(sections: dict[str, list[str]]) -> list[dict]:
    """Walk the projects section, pairing each project title with its
    "Tech Stack:" line and description bullets.

    Returns a list of {"name", "description", "skills"}.
    """
    entries: list[dict] = []
    current: dict | None = None

    def finalise() -> None:
        nonlocal current
        if current and current["name"]:
            current["skills"] = _unique(current["skills"])
            entries.append(current)
        current = None

    for raw_line in sections.get("projects", []):
        line = raw_line.strip()
        stripped = _clean_line(line)
        if not stripped:
            continue
        low = re.sub(r"\s+", " ", stripped.lower()).strip().strip(":")

        if low in {"link", "links", "demo", "source", "code"} or _looks_like_date(stripped):
            continue

        m_tech = re.match(r"^(?:tech\s*stack|technologies(?:\s+used)?|tools(?:\s+used)?)\s*[:\-–—]\s*(.+)$", low)
        if m_tech:
            if current is not None:
                current["skills"].extend(match_skills(line))
                current["skills"].extend(_skill_list_from_fragment(m_tech.group(1)))
            continue

        is_bullet = bool(re.match(r"^[•·▪◦\-–—*]", line)) and not re.match(r"^[A-Z]", stripped)
        if is_bullet:
            if current is not None:
                current["description"].append(stripped)
                current["skills"].extend(match_skills(stripped))
            continue

        # Otherwise: a brand-new project title line — but a continuation
        # fragment from PDF text extraction (e.g. a stray "broadcasts." after a
        # wrapped bullet) must be appended to the current project, not start one.
        first_alpha_m = re.search(r"[A-Za-z]", stripped)
        starts_lower = bool(first_alpha_m) and first_alpha_m.group(0).islower()
        if current is not None and (starts_lower or len(stripped.split()) < 3):
            current["description"].append(stripped)
            current["skills"].extend(match_skills(stripped))
            continue
        if starts_lower or len(stripped.split()) < 3:
            continue
        finalise()
        title = re.sub(r"^(?:project|projects|title)\s*[:\-–—]\s*", "", stripped, flags=re.I).strip()
        name = title
        if ":" in name and len(name.split(":", 1)[0].split()) <= 6:
            name = name.split(":", 1)[0].strip()
        dash_parts = re.split(r"\s+-\s+", name, maxsplit=1)
        if len(dash_parts) == 2 and len(dash_parts[0].split()) <= 6:
            name = dash_parts[0].strip()
        name = name.strip(" .,|·-–—")
        if not (2 <= len(name) <= 60) or re.fullmatch(r"[\d\W]+", name):
            current = {"name": None, "description": [], "skills": []}
            continue
        current = {
            "name": name,
            "description": [title],
            "skills": match_skills(title),
        }
    finalise()

    out: list[dict] = []
    seen: set[str] = set()
    for e in entries:
        key = re.sub(r"[^a-z0-9]+", "", e["name"].lower())
        if key and key not in seen:
            seen.add(key)
            out.append(e)
    return out[:6]


def _skill_list_from_fragment(fragment: str) -> list[str]:
    """Canonicalise comma-separated tech-stack items ("Python, FastMCP, Docker")."""
    out: list[str] = []
    for part in re.split(r"[,;|•·]", fragment):
        token = part.strip(" .-–—")
        if 1 < len(token) <= 30:
            canon = canonical_skill(token)
            if canon:
                out.append(canon)
    return out


def _extract_education(sections: dict[str, list[str]]) -> list[dict]:
    """Return [{"name": institution, "degree": "..."}] pairing the degree with
    the institution instead of creating two disconnected entities."""
    entries: list[dict] = []
    current: dict | None = None

    def finalise() -> None:
        nonlocal current
        if current:
            entries.append(current)
        current = None

    for raw_line in sections.get("education", []) + sections.get("_other", []):
        line = _clean_line(raw_line)
        stripped = re.sub(r"\s+", " ", line).strip()
        if not stripped or _looks_like_date(stripped):
            continue
        month_year = re.match(r"^(?:19|20)\d{2}", stripped)
        if month_year and len(stripped) < 22:
            continue

        inst_m = re.search(
            r"[A-Z][A-Za-z.'&\- ]{2,60}?(?:University|College|Institute|School)[A-Za-z ,.'&\-]{0,30}",
            stripped,
        )
        degree_m = re.search(
            r"(?:B\.?Tech|M\.?Tech|B\.?E\.?|M\.?E\.?|B\.?S\.?|M\.?S\.?|Bachelor(?:'s)?|Master(?:'s)?|PhD|Ph\.D|MBA)[A-Za-z .,&\-]{0,60}",
            stripped,
            re.I,
        )
        if inst_m:
            finalise()
            name = re.sub(r"\s+", " ", inst_m.group(0)).strip(" .,|·-–—,").rstrip(",")
            current = {"name": name, "degree": None}
            if degree_m:
                degree = re.sub(r"\s+", " ", degree_m.group(0)).strip(" .,|")
                if any(ch.isalpha() for ch in degree):
                    current["degree"] = degree.rstrip(",")
        elif degree_m and current is not None and current["degree"] is None:
            degree = re.sub(r"\s+", " ", degree_m.group(0)).strip(" .,|")
            if any(ch.isalpha() for ch in degree):
                current["degree"] = degree
        elif not inst_m and not degree_m:
            finalise()
    finalise()

    out: list[dict] = []
    seen: set[str] = set()
    for e in entries:
        key = re.sub(r"[^a-z0-9]+", "", e["name"].lower())
        if key and key not in seen and 3 <= len(e["name"]) <= 70:
            seen.add(key)
            out.append(e)
    return out[:3]


def _unique(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        key = re.sub(r"[^a-z0-9]+", "", item.lower())
        if key and key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _extract_skills_from_sections(sections: dict[str, list[str]]) -> tuple[list[str], dict[str, str]]:
    """Extract skills, tracking the resume's own category labels
    ("Languages & Core: Python, SQL" -> category "Languages & Core").

    Returns (ordered skills, {skill_label -> category_label}).
    """
    found: list[str] = []
    category_of: dict[str, str] = {}
    current_cat: str | None = None
    _CAT_JUNK = {
        "skills", "technical skills", "core skills", "core competencies", "languages",
        "backend", "frontend", "databases", "cloud", "devops", "testing", "ai",
        "with", "and", "etc", "others", "frameworks", "tools", "libraries",
        "core", "systems", "tech stack", "technologies", "general",
    }
    for line in sections.get("skills", []):
        body = line
        cat = current_cat
        inline = re.match(r"^([A-Za-z&/,.\- ]{2,44})\s*[:\-–—]\s*(.+)$", body.strip())
        if inline and inline.group(1).strip().lower() not in _CAT_JUNK:
            cat = re.sub(r"\s+", " ", inline.group(1).strip())
            body = inline.group(2)
            current_cat = cat
        for part in re.split(r"[,;|•·]|\s{2,}", body):
            token = re.sub(r"\([^)]*\)", "", part).strip(" .-–—\t")
            if not (1 < len(token) <= 30):
                continue
            label = canonical_skill(token)
            if not label and (
                re.fullmatch(r"[A-Za-z][A-Za-z0-9.+#/ -]{1,28}", token)
                and token.lower() not in _CAT_JUNK
                and len(token.split()) <= 3
            ):
                label = token
            if label and label not in category_of:
                category_of[label] = cat or ""
                if cat:
                    current_cat = cat
            if label:
                found.append(label)
    return _unique(found), category_of


@dataclass
class ResumeProfile:
    name: str | None = None
    skills: list[str] = field(default_factory=list)
    skill_categories: dict[str, str] = field(default_factory=dict)
    companies: list[str] = field(default_factory=list)
    projects: list[dict] = field(default_factory=list)
    education: list[dict] = field(default_factory=list)
    sections: dict[str, list[str]] = field(default_factory=dict)


def parse_resume(text: str) -> ResumeProfile:
    sections = _sectionise(text or "")
    profile = ResumeProfile(
        name=_find_name(text or ""),
        companies=_extract_companies(sections, text or ""),
        projects=_extract_projects(sections),
        education=_extract_education(sections),
        sections=sections,
    )
    skills, category_of = _extract_skills_from_sections(sections)
    for skill in match_skills(text or ""):
        if skill not in skills:
            skills.append(skill)
    profile.skills = skills[:40]
    profile.skill_categories = {s: category_of.get(s, "") for s in profile.skills}
    return profile


def summarise_for_questions(text: str) -> dict:
    profile = parse_resume(text)
    return {
        "name": profile.name,
        "skills": profile.skills[:15],
        "companies": profile.companies[:5],
        "projects": [p.get("name") for p in profile.projects[:5] if p.get("name")],
        "education": [e.get("name") for e in profile.education[:3] if e.get("name")],
    }


# --------------------------------------------------------------------------- #
# Graph data model
# --------------------------------------------------------------------------- #

_RELATION_WEIGHT = {
    "contradicts": 0.95,
    "supports": 0.9,
    "has_skill": 0.9,
    "worked_at": 0.9,
    "used_skill": 0.75,
    "studied_at": 0.8,
    "built_with": 0.7,
    "mentions": 0.6,
    "includes": 0.5,
    "related": 0.45,
}
_RELATION_PRIORITY = {name: i for i, name in enumerate(_RELATION_WEIGHT)}


@dataclass
class GraphData:
    nodes: dict[str, dict] = field(default_factory=dict)
    edges: dict[tuple[str, str, str], dict] = field(default_factory=dict)
    profile: dict = field(default_factory=dict)
    stats: dict = field(default_factory=dict)

    def add_node(self, key: str, label: str, ntype: str, meta: dict | None = None) -> str:
        label = re.sub(r"\s+", " ", (label or "").strip())[:180]
        if not label:
            return key
        existing = self.nodes.get(key)
        if existing:
            if meta:
                merged = {**(existing.get("meta") or {}), **{k: v for k, v in meta.items() if v is not None}}
                existing["meta"] = merged
            return key
        self.nodes[key] = {"id": key, "label": label, "type": ntype, "meta": meta or {}}
        return key

    def add_edge(self, source: str, target: str, relation: str, meta: dict | None = None) -> None:
        if source == target or source not in self.nodes or target not in self.nodes:
            return
        key = (source, target, relation)
        weight = _RELATION_WEIGHT.get(relation, 0.5)
        if key in self.edges:
            if meta:
                self.edges[key]["meta"] = {**self.edges[key].get("meta", {}), **meta}
            return
        self.edges[key] = {
            "source": source,
            "target": target,
            "relation": relation,
            "weight": weight,
            "meta": meta or {},
        }

    # -- export ---------------------------------------------------------- #
    def names_by_skill(self) -> dict[str, str]:
        return {n["label"].lower(): key for key, n in self.nodes.items() if n["type"] == "skill"}

    def find_similar_claim(self, evidence: str, threshold: float = 0.72) -> str | None:
        """Return an existing claim key whose evidence closely matches."""
        tokens = set(re.findall(r"[a-z0-9]+", evidence.lower()))
        tokens = {t for t in tokens if len(t) > 2}
        if not tokens:
            return None
        for key, node in self.nodes.items():
            if node["type"] != "claim":
                continue
            other = set(re.findall(r"[a-z0-9]+", (node.get("meta", {}).get("evidence") or node["label"]).lower()))
            other = {t for t in other if len(t) > 2}
            if not other:
                continue
            score = len(tokens & other) / len(tokens | other)
            if score >= threshold:
                return key
        return None

    def finalize(self, max_nodes: int, max_edges: int) -> "GraphData":
        # Drop edges pointing at missing nodes (defence against future changes).
        for key in list(self.edges):
            s, t, _ = key
            if s not in self.nodes or t not in self.nodes:
                del self.edges[key]

        ordered_edges = sorted(
            self.edges.values(),
            key=lambda e: (_RELATION_PRIORITY.get(e["relation"], 99), -float(e.get("weight", 0))),
        )[:max_edges]

        keep: set[str] = set()
        for edge in ordered_edges:
            keep.add(edge["source"])
            keep.add(edge["target"])
        if "person:candidate" in self.nodes:
            keep.add("person:candidate")
        # never drop skills/entities that the resume established unless we must
        if len(keep) > max_nodes:
            for edge in ordered_edges:
                if len(keep) <= max_nodes:
                    break
                if edge["source"] != "person:candidate" and edge["target"] != "person:candidate":
                    keep.discard(edge["source"])
                    keep.discard(edge["target"])

        nodes = {k: v for k, v in self.nodes.items() if k in keep}
        edges = {(e["source"], e["target"], e["relation"]): e for e in ordered_edges if e["source"] in nodes and e["target"] in nodes}
        self.nodes = nodes
        self.edges = edges
        return self

    def as_dict(self) -> dict:
        return {
            "nodes": list(self.nodes.values()),
            "edges": list(self.edges.values()),
            "profile": self.profile,
            "stats": self.stats,
        }


# --------------------------------------------------------------------------- #
# Layer 1: resume
# --------------------------------------------------------------------------- #

def add_resume_layer(graph: GraphData, resume_text: str, candidate_name: str | None = None) -> ResumeProfile:
    profile = parse_resume(resume_text)
    name = candidate_name or profile.name or "Candidate"
    graph.add_node("person:candidate", name, "entity", {"source": "resume", "role": "candidate"})

    known_skill_keys: dict[str, str] = {}

    def skill_node(label: str) -> str:
        key = "skill:" + _slug(label)
        if key not in graph.nodes:
            graph.add_node(key, label, "skill", {"source": "resume"})
        known_skill_keys[label] = key
        return key

    # ---- skills, grouped into category hubs so the graph clusters ---- #
    # Categorised skills hang off their category hub; skills without a category
    # connect straight to the candidate so they can never end up isolated.
    group_of_cat: dict[str, str] = {}
    for skill in profile.skills:
        cat = (profile.skill_categories or {}).get(skill, "")
        key = skill_node(skill)
        if cat:
            gkey = group_of_cat.get(cat)
            if gkey is None:
                gkey = "group:" + _slug(cat)
                group_of_cat[cat] = gkey
                graph.add_node(gkey, cat, "group", {"source": "resume", "kind": "skill_category"})
                graph.add_edge("person:candidate", gkey, "has_skill", {"evidence": f"Category on resume: {cat}"})
            graph.add_edge(gkey, key, "includes", {"evidence": f"{cat}: {skill}"})
        else:
            graph.add_edge(
                "person:candidate", key, "has_skill",
                {"evidence": f"Listed on resume: {skill}"},
            )

    for company in profile.companies:
        key = "entity:" + _slug(company)
        graph.add_node(key, company, "entity", {"source": "resume", "kind": "company"})
        graph.add_edge("person:candidate", key, "worked_at", {"evidence": f"Experience at {company}"})

    for project in profile.projects:
        if not project.get("name"):
            continue
        pname = project["name"]
        key = "topic:" + _slug(pname)
        desc = " ".join(project.get("description", []))[:400]
        graph.add_node(key, pname, "topic", {"source": "resume", "kind": "project", "description": desc})
        graph.add_edge(
            "person:candidate", key, "mentions",
            {"evidence": f"Project on resume: {desc or pname}"[:400]},
        )
        pkey = key
        for skill in _unique(project.get("skills", []))[:8]:
            skey = skill_node(skill)
            graph.add_edge(pkey, skey, "built_with", {"evidence": f"{pname} tech stack: {skill}"})

    for edu in profile.education:
        name_e = edu.get("name")
        if not name_e:
            continue
        key = "entity:" + _slug(name_e)
        graph.add_node(key, name_e, "entity", {"source": "resume", "kind": "education", "degree": edu.get("degree")})
        graph.add_edge("person:candidate", key, "studied_at", {"evidence": edu.get("degree") or name_e})

    # Experience bullets associate skills with the surrounding company.
    exp_lines = profile.sections.get("experience", [])
    current_company: str | None = None
    company_heads = {
        re.sub(r"\s+", " ", c.lower()).split("(")[0].strip(): c
        for c in profile.companies
        if c
    }
    for raw_line in exp_lines:
        line = _clean_line(raw_line)
        stripped = line.strip()
        if not stripped or _looks_like_date(stripped):
            continue
        low = re.sub(r"\s+", " ", stripped.lower()).strip()

        if low in _ENTITY_STOPWORDS or low in _META_LABELS or low in {"open source contributions", "contributions"}:
            current_company = None
            continue

        matched = False
        for head, company in company_heads.items():
            if head and head in low:
                current_company = company
                matched = True
                break

        if matched:
            continue

        if current_company and not _ROLE_WORDS_RE.search(stripped):
            found = _unique(match_skills(stripped))[:6]
            if found:
                ckey = "entity:" + _slug(current_company)
                for skill in found:
                    skey = skill_node(skill)
                    graph.add_edge(ckey, skey, "used_skill", {"evidence": stripped[:220]})

    graph.profile = {
        "name": name,
        "skills": profile.skills,
        "companies": profile.companies,
        "projects": [p.get("name") for p in profile.projects if p.get("name")],
        "education": [e.get("name") for e in profile.education if e.get("name")],
    }
    graph.stats["resume_skills"] = len(profile.skills)
    return profile


# --------------------------------------------------------------------------- #
# Layer 2: transcript (deterministic)
# --------------------------------------------------------------------------- #

_NEGATION = re.compile(
    r"\b(?:never|not|no experience|haven'?t|hasn'?t|didn'?t|don'?t|doesn'?t|"
    r"not familiar|not comfortable|struggl\w*|weak(?:est)?|limited)\b",
    re.I,
)
_AFFIRM = re.compile(
    r"\b(?:used|using|use|worked|working|built|build|developed|develop|implemented|implement|"
    r"deployed|deploy|wrote|write|created|create|migrated|migrate|designed|design|led|lead|"
    r"proficient|familiar|experience|hands-on|expert|strong)\b",
    re.I,
)
_CLAIM_HINT = re.compile(
    r"\b(?:i|we)\s+(?:have\s+)?(?:built|developed|implemented|designed|led|created|deployed|"
    r"migrated|reduced|improved|increased|optimized|automated|scaled|wrote|worked)\b",
    re.I,
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def _sentence_spans(text: str) -> list[str]:
    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(text or "") if s and s.strip()]
    if not sentences:
        return []
    return sentences


def _claim_key(text: str) -> str:
    normalized = re.sub(r"\W+", " ", text.lower()).strip()
    return "claim:" + hashlib.sha1(normalized.encode()).hexdigest()[:12]


def _strip_speaker_prefix(text: str) -> str:
    return re.sub(r"^\s*\[[^\]]{1,40}\]\s*", "", text or "").strip()


def _skill_evidence(sentence: str, skill: str) -> tuple[str, str] | None:
    if not re.search(re.escape(skill.split()[0]), sentence, re.I):
        return None
    neg = _NEGATION.search(sentence)
    aff = _AFFIRM.search(sentence)
    if neg and (not aff or neg.start() < aff.start()):
        return "contradicts", sentence
    if aff:
        return "supports", sentence
    return "mentions", sentence


def add_transcript_layer(graph: GraphData, transcripts: list[dict], interviewer_name: str | None = None) -> None:
    candidate_lines: list[tuple[dict, str]] = []
    for t in transcripts:
        speaker = (t.get("speaker") or "").strip()
        text = (t.get("text") or "").strip()
        if not text:
            continue
        is_interviewer = speaker.lower() in {"interviewer", "host", "graph-viewer"} or (
            interviewer_name and speaker.lower() == interviewer_name.lower()
        )
        if is_interviewer:
            continue
        candidate_lines.append((t, text))

    if not candidate_lines:
        graph.stats["candidate_lines"] = 0
        return

    known_skills = {n["label"]: k for k, n in graph.nodes.items() if n["type"] == "skill"}
    claims_added = 0
    contradicting = 0

    for t, text in candidate_lines:
        for sentence in _sentence_spans(text):
            if len(sentence) < 8:
                continue
            sentence_skills = match_skills(sentence)
            verdict_for_sentence: str | None = None
            matched_skills: list[str] = []
            for skill in sentence_skills:
                ev = _skill_evidence(sentence, skill)
                if ev is None:
                    continue
                relation, quote = ev
                matched_skills.append(skill)
                verdict_for_sentence = relation if relation != "mentions" else verdict_for_sentence or relation
                skey = known_skills.get(skill) or ("skill:" + _slug(skill))
                if skey not in graph.nodes:
                    graph.add_node(skey, skill, "skill", {"source": "transcript"})
                    known_skills[skill] = skey
                if relation == "mentions" and skey in graph.nodes:
                    # keep resume "has_skill" edges intact; only add a light trace
                    graph.add_edge("person:candidate", skey, "mentions", {"evidence": quote[:220]})
                else:
                    if relation == "contradicts":
                        contradicting += 1
                    graph.add_edge("person:candidate", skey, relation, {"evidence": quote[:220], "speaker": t.get("speaker")})

            # a claim node for first-person achievement statements
            if (len(sentence) >= 25 and (_CLAIM_HINT.search(sentence) or matched_skills)) and claims_added < 18:
                claim_label = sentence if len(sentence) <= 120 else sentence[:117].rstrip() + "..."
                ckey = graph.find_similar_claim(sentence) or _claim_key(sentence)
                graph.add_node(
                    ckey,
                    claim_label,
                    "claim",
                    {
                        "source": "transcript",
                        "speaker": t.get("speaker"),
                        "evidence": sentence[:400],
                        "verdict": verdict_for_sentence or "mentions",
                    },
                )
                graph.add_edge("person:candidate", ckey, "mentions", {"evidence": sentence[:220]})
                for skill in matched_skills:
                    skey = known_skills.get(skill) or ("skill:" + _slug(skill))
                    rel = "contradicts" if verdict_for_sentence == "contradicts" else "supports"
                    graph.add_edge(ckey, skey, rel, {"evidence": sentence[:220]})
                claims_added += 1

    graph.stats.update({"candidate_lines": len(candidate_lines), "claims": claims_added, "contradictions": contradicting})


# --------------------------------------------------------------------------- #
# Layer 3: LLM claims (strictly evidence-validated)
# --------------------------------------------------------------------------- #

_ENRICH_SYSTEM = "You are a strict fact extractor. You output only valid JSON."


def _token_overlap(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _evidence_in_transcript(evidence: str, transcript_text: str) -> bool:
    ev_norm = re.sub(r"\W+", " ", evidence.lower()).strip()
    tx_norm = re.sub(r"\W+", " ", transcript_text.lower()).strip()
    if not ev_norm or len(ev_norm) < 12:
        return False
    if ev_norm in tx_norm:
        return True
    ev_tokens = ev_norm.split()
    tx_tokens = tx_norm.split()
    if not ev_tokens or not tx_tokens:
        return False
    window = len(ev_tokens)
    best = 0.0
    step = max(1, window // 4)
    for i in range(0, max(1, len(tx_tokens) - window + 1), step):
        score = _token_overlap(ev_tokens, tx_tokens[i : i + window])
        if score > best:
            best = score
            if best >= 0.78:
                return True
    return best >= 0.78


def _llm_claims(resume_text: str, transcripts: list[dict], known_skills: list[str], candidate_name: str | None) -> list[dict]:
    from app.llm import chat_json_sync

    candidate_text = "\n".join(
        f"[{t.get('speaker', 'Candidate')}] {t.get('text', '')}"
        for t in transcripts
        if (t.get("speaker") or "").lower() not in {"interviewer", "host", "graph-viewer"}
    )[-7000:]
    if len(candidate_text.strip()) < 40:
        return []

    prompt = f"""Build an evidence-backed knowledge graph of this interview candidate.

CANDIDATE: {candidate_name or "unknown"}
RESUME SKILLS: {", ".join(known_skills[:40]) or "(none detected)"}

RESUME (excerpt):
{(resume_text or "")[:3000]}

CANDIDATE TRANSCRIPT (verbatim):
{candidate_text}

TASK: Extract claims the candidate actually made about their skills, projects or experience.

STRICT RULES:
1. "evidence" MUST be copied verbatim from the CANDIDATE TRANSCRIPT, 8-40 words. No paraphrasing.
2. "skills" must be explicitly named in that evidence.
3. "verdict" is:
   - "supports" if the evidence confirms a resume skill/claim,
   - "contradicts" if the resume lists the skill but the evidence denies/minimises it, or facts conflict,
   - "new" if the skill is not on the resume.
4. Do not infer, guess, or add anything not stated. Omit weak evidence.
5. Maximum 12 claims. It is fine to return an empty list.

Return ONLY JSON:
{{"claims":[{{"text":"short neutral claim","evidence":"verbatim quote","skills":["Python"],"verdict":"supports","confidence":0.9}}]}}"""

    try:
        data = chat_json_sync(
            prompt,
            system=_ENRICH_SYSTEM,
            model=settings.llm_graph_model,
            max_tokens=1600,
            temperature=0.1,
        )
    except Exception as e:  # noqa: BLE001
        print(f"[graph] LLM enrichment unavailable: {e}")
        return []

    if not isinstance(data, dict):
        return []
    claims = data.get("claims")
    return claims if isinstance(claims, list) else []


def add_llm_layer(graph: GraphData, resume_text: str, transcripts: list[dict], candidate_name: str | None) -> int:
    if not settings.graph_llm_enrich or not transcripts:
        return 0
    known = [n["label"] for n in graph.nodes.values() if n["type"] == "skill"]
    claims = _llm_claims(resume_text, transcripts, known, candidate_name)
    transcript_blob = "\n".join(t.get("text", "") for t in transcripts)
    added = 0
    for item in claims[:12]:
        if not isinstance(item, dict):
            continue
        evidence = _strip_speaker_prefix(str(item.get("evidence", "")).strip())
        verdict = str(item.get("verdict", "new")).lower()
        if verdict not in {"supports", "contradicts", "new"}:
            verdict = "new"
        try:
            confidence = float(item.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence and confidence < 0.55:
            continue
        if not _evidence_in_transcript(evidence, transcript_blob):
            print(f"[graph] dropped unverifiable claim: {evidence[:60]!r}")
            continue
        skills_raw = item.get("skills") or []
        if not isinstance(skills_raw, list):
            skills_raw = [skills_raw]
        skills: list[str] = []
        for raw in skills_raw[:4]:
            name = str(raw).strip()
            if not name or name.lower() not in evidence.lower():
                continue
            skills.append(canonical_skill(name) or name.title())
        if not skills:
            continue
        label = str(item.get("text", "")).strip() or evidence
        label = label if len(label) <= 120 else label[:117].rstrip() + "..."
        ckey = graph.find_similar_claim(evidence) or _claim_key(evidence)
        graph.add_node(
            ckey,
            label,
            "claim",
            {
                "source": "transcript",
                "evidence": evidence[:400],
                "verdict": verdict,
                "confidence": item.get("confidence"),
                "llm": True,
            },
        )
        graph.add_edge("person:candidate", ckey, "mentions", {"evidence": evidence[:220]})
        for skill in skills:
            skey = "skill:" + _slug(skill)
            if skey not in graph.nodes:
                graph.add_node(skey, skill, "skill", {"source": "transcript"})
            relation = "contradicts" if verdict == "contradicts" else "supports"
            graph.add_edge(ckey, skey, relation, {"evidence": evidence[:220]})
            if verdict == "supports":
                graph.add_edge("person:candidate", skey, "supports", {"evidence": evidence[:220]})
        added += 1
    graph.stats["llm_claims"] = added
    return added


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def build_graph_data(
    resume_text: str,
    transcripts: list[dict] | None = None,
    interviewer_name: str | None = None,
    candidate_name: str | None = None,
    use_llm: bool = True,
) -> dict:
    graph = GraphData()
    add_resume_layer(graph, resume_text or "", candidate_name)
    add_transcript_layer(graph, transcripts or [], interviewer_name)
    if use_llm:
        add_llm_layer(graph, resume_text or "", transcripts or [], candidate_name)
    graph.finalize(settings.graph_max_nodes, settings.graph_max_edges)
    return graph.as_dict()
