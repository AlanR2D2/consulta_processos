"""Cliente HTTP da API Pública do DataJud (CNJ).

- Autenticação por header `Authorization: APIKey <chave>` (chave pública compartilhada).
- Busca por `numeroProcesso` via Elasticsearch DSL (POST _search).
- Paginação por `search_after`.
- Retry com backoff exponencial em erros de rede / 5xx / 429.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

from src.config import settings
from src.datajud.endpoints import alias_de, limpar_numero

logger = logging.getLogger(__name__)

_PAGE_SIZE = 100
# Lote: páginas maiores p/ caber muitos processos (e graus) numa só resposta.
_BULK_PAGE_SIZE = 1000
# Respostas em lote são pesadas (muitas movimentações); timeout mais folgado.
_BULK_TIMEOUT = 120


class DataJudError(RuntimeError):
    """Falha irrecuperável ao consultar o DataJud."""


class DataJudAuthError(DataJudError):
    """401/403 — provável chave inválida/rotacionada."""


class DataJudClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: int | None = None,
        max_retries: int | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.api_key = api_key or settings.datajud_api_key
        self.base_url = (base_url or settings.datajud_base_url).rstrip("/")
        self.timeout = timeout or settings.request_timeout
        self.max_retries = max_retries or settings.max_retries
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"APIKey {self.api_key}",
                "Content-Type": "application/json",
            }
        )

    def _endpoint(self, alias: str) -> str:
        return f"{self.base_url}/api_publica_{alias}/_search"

    def _post(
        self, url: str, body: dict[str, Any], timeout: int | None = None
    ) -> dict[str, Any]:
        """POST com retry/backoff. Levanta DataJudError/DataJudAuthError."""
        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.session.post(url, json=body, timeout=timeout or self.timeout)
            except requests.RequestException as exc:
                last_exc = exc
                self._sleep_backoff(attempt, f"erro de rede: {exc}")
                continue

            if resp.status_code in (401, 403):
                raise DataJudAuthError(
                    "DataJud retornou "
                    f"{resp.status_code}: a chave pode ter sido rotacionada. "
                    "Atualize DATAJUD_API_KEY a partir de "
                    "https://datajud-wiki.cnj.jus.br/api-publica/acesso"
                )
            if resp.status_code == 429 or resp.status_code >= 500:
                last_exc = DataJudError(f"HTTP {resp.status_code}")
                self._sleep_backoff(attempt, f"HTTP {resp.status_code}")
                continue
            if resp.status_code != 200:
                raise DataJudError(f"HTTP {resp.status_code}: {resp.text[:300]}")

            return resp.json()

        raise DataJudError(f"Falha após {self.max_retries} tentativas em {url}: {last_exc}")

    def _sleep_backoff(self, attempt: int, motivo: str) -> None:
        if attempt >= self.max_retries:
            return
        espera = 2 ** (attempt - 1)
        logger.warning("Tentativa %d falhou (%s); aguardando %ds", attempt, motivo, espera)
        time.sleep(espera)

    def buscar_processo(self, numero_cnj: str) -> list[dict[str, Any]]:
        """Retorna os `_source` de todos os hits do processo (com paginação).

        Normalmente é 1 hit por (grau), mas paginamos para garantir completude.
        Processo sigiloso/sem retorno → lista vazia (resultado válido).
        """
        numero = limpar_numero(numero_cnj)
        alias = alias_de(numero)
        url = self._endpoint(alias)

        sources: list[dict[str, Any]] = []
        search_after: list[Any] | None = None

        while True:
            body: dict[str, Any] = {
                "size": _PAGE_SIZE,
                "query": {"match": {"numeroProcesso": numero}},
                # Sort só por @timestamp: o índice DataJud não permite fielddata em _id.
                "sort": [{"@timestamp": {"order": "asc"}}],
            }
            if search_after is not None:
                body["search_after"] = search_after

            data = self._post(url, body)
            hits = data.get("hits", {}).get("hits", [])
            if not hits:
                break

            for hit in hits:
                src = hit.get("_source")
                if src is not None:
                    sources.append(src)

            if len(hits) < _PAGE_SIZE:
                break
            search_after = hits[-1].get("sort")
            if not search_after:
                break

        logger.info("DataJud %s: %d documento(s) para %s", alias, len(sources), numero)
        return sources

    def buscar_lote(self, alias: str, numeros: list[str]) -> dict[str, list[dict[str, Any]]]:
        """Consulta vários processos do MESMO tribunal numa só query (terms).

        Retorna {numeroProcesso: [_source, ...]}. Processos sigilosos/sem dados
        simplesmente não aparecem no dicionário (resultado válido).
        """
        if not numeros:
            return {}
        url = self._endpoint(alias)
        resultado: dict[str, list[dict[str, Any]]] = {}
        search_after: list[Any] | None = None

        while True:
            body: dict[str, Any] = {
                "size": _BULK_PAGE_SIZE,
                "query": {"terms": {"numeroProcesso": numeros}},
                "sort": [{"@timestamp": {"order": "asc"}}],
            }
            if search_after is not None:
                body["search_after"] = search_after

            data = self._post(url, body, timeout=_BULK_TIMEOUT)
            hits = data.get("hits", {}).get("hits", [])
            if not hits:
                break

            for hit in hits:
                src = hit.get("_source")
                if src is None:
                    continue
                num = src.get("numeroProcesso")
                if num is not None:
                    resultado.setdefault(num, []).append(src)

            if len(hits) < _BULK_PAGE_SIZE:
                break
            search_after = hits[-1].get("sort")
            if not search_after:
                break

        logger.info(
            "DataJud %s: %d processo(s) com dados em lote de %d.",
            alias,
            len(resultado),
            len(numeros),
        )
        return resultado
