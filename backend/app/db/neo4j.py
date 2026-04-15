from __future__ import annotations

from dataclasses import dataclass

from neo4j import GraphDatabase, Driver

from app.core.config import settings


@dataclass(frozen=True)
class Neo4jConfig:
    uri: str
    user: str
    password: str


def get_driver(cfg: Neo4jConfig | None = None) -> Driver:
    cfg = cfg or Neo4jConfig(
        uri=settings.neo4j_uri,
        user=settings.neo4j_user,
        password=settings.neo4j_password,
    )
    return GraphDatabase.driver(cfg.uri, auth=(cfg.user, cfg.password))


async def ensure_constraints(driver: Driver) -> None:
    cypher = [
        "CREATE CONSTRAINT disease_id IF NOT EXISTS FOR (n:Disease) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT target_id IF NOT EXISTS FOR (n:Target) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT gene_id IF NOT EXISTS FOR (n:Gene) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT protein_id IF NOT EXISTS FOR (n:Protein) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT drug_id IF NOT EXISTS FOR (n:Drug) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT publication_id IF NOT EXISTS FOR (n:Publication) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT evidence_id IF NOT EXISTS FOR (n:Evidence) REQUIRE n.id IS UNIQUE",
    ]
    with driver.session() as s:
        for q in cypher:
            s.run(q)

