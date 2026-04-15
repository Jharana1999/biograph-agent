from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import RankedTarget, Citation, EvidenceItem


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=5, max_length=4000)
    session_id: int | None = None


class AgentPlan(BaseModel):
    steps: list[str] = []


class GraphNode(BaseModel):
    id: str
    label: str
    name: str | None = None
    score: float | None = None


class GraphEdge(BaseModel):
    source: str
    target: str
    type: str


class GraphSummary(BaseModel):
    nodes_added: int = 0
    edges_added: int = 0
    focus_disease_id: str | None = None
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []


class EvaluationSummary(BaseModel):
    passed: bool
    checks: dict[str, Any]
    notes: str | None = None


class ChatResponse(BaseModel):
    run_id: str
    session_id: int
    plan: AgentPlan
    answer_markdown: str
    ranked_targets: list[RankedTarget] = []
    citations: list[Citation] = []
    evidence: list[EvidenceItem] = []
    graph: GraphSummary
    evaluation: EvaluationSummary
