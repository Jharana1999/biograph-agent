from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from neo4j.graph import Node as NeoNode, Relationship as NeoRel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.agent_graph import run_agent
from app.db.neo4j import get_driver
from app.db.models import ChatMessage, ChatSession
from app.db.postgres import get_session
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    AgentPlan,
    GraphSummary,
    GraphNode,
    GraphEdge,
    EvaluationSummary,
)


router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, pg: AsyncSession = Depends(get_session)) -> ChatResponse:
    if req.session_id is None:
        s = ChatSession(title=req.question[:80])
        pg.add(s)
        await pg.commit()
        await pg.refresh(s)
        session_id = s.id
    else:
        session_id = req.session_id
        s = await pg.get(ChatSession, session_id)
        if not s:
            raise HTTPException(status_code=404, detail="session_id not found")

    pg.add(ChatMessage(session_id=session_id, role="user", content=req.question, meta={}))
    await pg.commit()

    state = await run_agent(question=req.question, pg=pg)

    answer = state.answer_markdown or ""
    pg.add(ChatMessage(session_id=session_id, role="assistant", content=answer, meta={"run_id": state.run_id}))
    await pg.commit()

    return ChatResponse(
        run_id=state.run_id,
        session_id=session_id,
        plan=AgentPlan(steps=state.plan_steps),
        answer_markdown=answer,
        ranked_targets=state.ranked_targets,
        citations=state.citations,
        evidence=state.evidence,
        graph=GraphSummary(
            nodes_added=state.graph_nodes_added,
            edges_added=state.graph_edges_added,
            focus_disease_id=state.disease_id,
            nodes=[GraphNode(**n) for n in state.graph_nodes],
            edges=[GraphEdge(**e) for e in state.graph_edges],
        ),
        evaluation=EvaluationSummary(
            passed=bool(state.evaluation.get("passed")),
            checks=state.evaluation.get("checks", {}),
            notes=state.evaluation.get("notes"),
        ),
    )


@router.get("/sessions/{session_id}")
async def get_session_messages(session_id: int, pg: AsyncSession = Depends(get_session)) -> dict:
    s = await pg.get(ChatSession, session_id)
    if not s:
        raise HTTPException(status_code=404, detail="not found")
    q = select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at.asc())
    rows = (await pg.execute(q)).scalars().all()
    return {
        "session_id": session_id,
        "title": s.title,
        "messages": [{"id": m.id, "role": m.role, "content": m.content, "created_at": m.created_at.isoformat()} for m in rows],
    }


def _node_to_dict(n: NeoNode) -> dict:
    return {
        "id": n.get("id"),
        "labels": list(n.labels),
        "properties": dict(n),
    }


def _rel_to_dict(r: NeoRel) -> dict:
    return {
        "type": r.type,
        "start": r.start_node.get("id"),
        "end": r.end_node.get("id"),
        "properties": dict(r),
    }


@router.get("/entities/{kind}/{entity_id}")
async def entity_profile(kind: str, entity_id: str) -> dict:
    label = {
        "disease": "Disease",
        "target": "Target",
        "gene": "Gene",
        "protein": "Protein",
        "drug": "Drug",
        "publication": "Publication",
        "evidence": "Evidence",
    }.get(kind.lower())
    if not label:
        raise HTTPException(status_code=400, detail="unknown kind")

    driver = get_driver()
    try:
        with driver.session() as s:
            rec = s.run(f"MATCH (n:{label} {{id: $id}}) RETURN n LIMIT 1", id=entity_id).single()
            if not rec:
                raise HTTPException(status_code=404, detail="not found")
            n = rec["n"]
            node = _node_to_dict(n)

            neighbours = s.run(
                "MATCH (n {id: $id})-[r]-(m) RETURN type(r) AS rel, m LIMIT 50",
                id=entity_id,
            )
            related = []
            for row in neighbours:
                related.append({
                    "relationship": row["rel"],
                    "node": _node_to_dict(row["m"]),
                })
            node["related"] = related
            return node
    finally:
        driver.close()


@router.get("/graph/traverse")
async def graph_traverse(
    entity_id: str = Query(..., description="Node id property"),
    depth: int = Query(2, ge=1, le=4),
    limit: int = Query(200, ge=10, le=2000),
) -> dict:
    driver = get_driver()
    try:
        with driver.session() as s:
            q = """
            MATCH (s {id: $id})
            CALL {
              WITH s
              MATCH p=(s)-[*1..$depth]-(n)
              RETURN p LIMIT $limit
            }
            UNWIND nodes(p) AS n
            UNWIND relationships(p) AS r
            RETURN collect(DISTINCT n) AS nodes, collect(DISTINCT r) AS rels
            """
            rec = s.run(q, id=entity_id, depth=depth, limit=limit).single()
            if not rec:
                raise HTTPException(status_code=404, detail="start node not found")
            nodes = [_node_to_dict(n) for n in (rec["nodes"] or [])]
            rels = [_rel_to_dict(r) for r in (rec["rels"] or [])]
            return {"start": entity_id, "depth": depth, "nodes": nodes, "edges": rels}
    finally:
        driver.close()


@router.get("/evidence")
async def evidence_lookup(
    target_id: str = Query(...),
    pg: AsyncSession = Depends(get_session),
) -> dict:
    from app.db.models import ToolCallLog

    q = select(ToolCallLog).where(
        ToolCallLog.tool_name.contains("opentargets"),
        ToolCallLog.request.contains(target_id) if hasattr(ToolCallLog.request, "contains") else True,
    ).order_by(ToolCallLog.created_at.desc()).limit(20)
    rows = (await pg.execute(q)).scalars().all()
    return {
        "target_id": target_id,
        "tool_calls": [
            {
                "tool": r.tool_name,
                "ok": r.ok,
                "request": r.request,
                "response": r.response,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }
