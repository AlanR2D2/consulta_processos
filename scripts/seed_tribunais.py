"""Popula a tabela `tribunais` no Supabase a partir do mapa de roteamento.

Fonte de verdade: src/datajud/endpoints.py (listar_todos_tribunais()).
Idempotente: upsert por alias (PK).

Uso: python -m scripts.seed_tribunais
"""

from __future__ import annotations

import logging

from src.config import configure_logging
from src.datajud.endpoints import listar_todos_tribunais, nome_segmento
from src.supabase_client import get_client

logger = logging.getLogger(__name__)


def seed() -> int:
    """Faz upsert de todos os tribunais. Retorna a quantidade gravada."""
    tribunais = listar_todos_tribunais()
    payload = [
        {
            "alias": t.alias,
            "nome": f"{t.alias.upper()} — {nome_segmento(t.segmento)}",
            "segmento": t.segmento,
            "codigo_j": t.codigo_j,
            "codigo_tr": t.codigo_tr,
            "ativo": True,
        }
        for t in tribunais
    ]
    get_client().table("promad_tribunais").upsert(payload, on_conflict="alias").execute()
    logger.info("Seed de tribunais: %d registros.", len(payload))
    return len(payload)


if __name__ == "__main__":
    configure_logging()
    total = seed()
    print(f"Seed concluído: {total} tribunais.")
