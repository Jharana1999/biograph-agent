from __future__ import annotations

from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential


UNIPROT_REST = "https://rest.uniprot.org"


class UniProtClient:
    def __init__(self, http: httpx.AsyncClient):
        self.http = http

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    async def get_protein(self, accession: str) -> dict[str, Any] | None:
        r = await self.http.get(f"{UNIPROT_REST}/uniprotkb/{accession}.json")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

