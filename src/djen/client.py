"""Cliente da API pública Comunica/DJEN (CNJ).

Consulta publicações/intimações por número de processo. Sem autenticação
(consulta pública do Diário de Justiça Eletrônico Nacional).
Fonte: https://comunica.pje.jus.br  | API: https://comunicaapi.pje.jus.br/api/v1
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

from src.config import settings

logger = logging.getLogger(__name__)

_BASE_URL = "https://comunicaapi.pje.jus.br/api/v1/comunicacao"
_ITENS_POR_PAGINA = 100


class DJENError(RuntimeError):
    """Falha ao consultar a Comunica API."""


class DJENClient:
    def __init__(
        self,
        base_url: str = _BASE_URL,
        timeout: int | None = None,
        max_retries: int | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout = timeout or settings.request_timeout
        self.max_retries = max_retries or settings.max_retries
        self.session = session or requests.Session()

    def _get(self, params: dict[str, Any]) -> dict[str, Any]:
        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.session.get(self.base_url, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                last_exc = exc
            else:
                if resp.status_code == 200:
                    return resp.json()
                if resp.status_code == 429 or resp.status_code >= 500:
                    last_exc = DJENError(f"HTTP {resp.status_code}")
                else:
                    raise DJENError(f"HTTP {resp.status_code}: {resp.text[:200]}")
            if attempt < self.max_retries:
                time.sleep(2 ** (attempt - 1))
        raise DJENError(f"Falha após {self.max_retries} tentativas: {last_exc}")

    @staticmethod
    def _itens(data: Any) -> list[dict[str, Any]]:
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("items") or data.get("content") or []
        return []

    def _paginar(self, params: dict[str, Any], rotulo: str) -> list[dict[str, Any]]:
        publicacoes: list[dict[str, Any]] = []
        pagina = 1
        while True:
            data = self._get({**params, "pagina": pagina, "itensPorPagina": _ITENS_POR_PAGINA})
            itens = self._itens(data)
            if not itens:
                break
            publicacoes.extend(itens)
            if len(itens) < _ITENS_POR_PAGINA:
                break
            pagina += 1
        logger.info("DJEN: %d publicação(ões) para %s", len(publicacoes), rotulo)
        return publicacoes

    def buscar_por_processo(self, numero_cnj: str) -> list[dict[str, Any]]:
        """Retorna as publicações/intimações do processo (com paginação)."""
        return self._paginar({"numeroProcesso": numero_cnj}, numero_cnj)

    def buscar_por_oab(
        self, numero_oab: str, uf_oab: str, data_inicio: str, data_fim: str
    ) -> list[dict[str, Any]]:
        """Publicações de uma OAB num intervalo de datas (uma consulta para vários processos).

        `data_inicio`/`data_fim` no formato ISO (yyyy-mm-dd).
        """
        return self._paginar(
            {
                "numeroOab": numero_oab,
                "ufOab": uf_oab,
                "dataDisponibilizacaoInicio": data_inicio,
                "dataDisponibilizacaoFim": data_fim,
            },
            f"OAB {numero_oab}/{uf_oab}",
        )
