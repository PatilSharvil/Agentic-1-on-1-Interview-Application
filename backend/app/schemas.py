from datetime import datetime
from pydantic import BaseModel, Field


class RoomCreate(BaseModel):
    host_name: str = Field(min_length=1, max_length=120)


class RoomOut(BaseModel):
    code: str
    host_name: str
    status: str
    created_at: datetime
    participant_count: int = 0


class JoinRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)


class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


class MessageOut(BaseModel):
    id: str
    sender: str
    body: str
    created_at: datetime


class TranscriptOut(BaseModel):
    id: str
    speaker: str
    text: str
    raw_text: str | None = None
    start_ms: int
    end_ms: int
    created_at: datetime


class UserRegister(BaseModel):
    email: str
    name: str
    password: str = Field(min_length=6)


class UserLogin(BaseModel):
    email: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ResumeOut(BaseModel):
    id: str
    filename: str
    text_preview: str
    parsed_at: datetime
    graph_built: bool = False
    skills: list[str] = []


class QuestionOut(BaseModel):
    id: str
    text: str
    source: str
    parent_id: str | None = None
    created_at: datetime


class QuestionGenerateRequest(BaseModel):
    job_title: str | None = None
    count: int = 5


class NextQuestionRequest(BaseModel):
    previous_answer: str | None = None


class GraphNodeOut(BaseModel):
    id: str
    label: str
    type: str
    meta: dict | None = None


class GraphEdgeOut(BaseModel):
    id: str
    source: str
    target: str
    relation: str
    weight: float


class GraphOut(BaseModel):
    nodes: list[GraphNodeOut]
    edges: list[GraphEdgeOut]