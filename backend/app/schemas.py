from typing import Literal
from pydantic import BaseModel, Field, HttpUrl


class IngestRequest(BaseModel):
    url: HttpUrl
    depth: int | None = Field(default=500, ge=1, le=100000)
    max_items: int | None = Field(default=100, ge=1, le=10000)


class JobResponse(BaseModel):
    job_id: str
    repo_key: str
    status: Literal["queued", "running", "paused", "completed", "failed"]
    stage: str
    progress: int = 0
    detail: str = ""


class RepoResponse(BaseModel):
    key: str
    owner: str
    repo: str
    url: str
    status: str
    indexed_at: str | None = None


class QueryRequest(BaseModel):
    repo_key: str
    question: str = Field(min_length=3, max_length=3000)
    temperature: float = Field(default=0.2, ge=0, le=1.5)


class Citation(BaseModel):
    id: str
    label: str
    url: str
    kind: Literal["commit", "pull_request", "issue", "file"]


class QueryResponse(BaseModel):
    answer: str
    citations: list[Citation] = []
    refused: bool = False
    reason: str | None = None
