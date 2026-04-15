from __future__ import annotations

from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential


ENSEMBL_REST = "https://rest.ensembl.org"


class EnsemblClient:
    def __init__(self, http: httpx.AsyncClient):
        self.http = http

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    async def lookup_gene(self, ensembl_id: str) -> dict[str, Any] | None:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        r = await self.http.get(f"{ENSEMBL_REST}/lookup/id/{ensembl_id}", headers=headers)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

