"""Upsert idempotente da tabela `movimentacoes`."""

from __future__ import annotations

from typing import Any

from src.datajud.parser import Movimentacao
from src.supabase_client import get_client

_TABELA = "promad_movimentacoes"


def hashes_existentes(processo_id: str) -> set[str]:
    """Hashes já gravados para o processo (para contar quantas são novas)."""
    resp = get_client().table(_TABELA).select("hash_unico").eq("processo_id", processo_id).execute()
    return {r["hash_unico"] for r in (resp.data or [])}


def listar_por_processo(processo_id: str, limite: int = 200) -> list[dict[str, Any]]:
    """Movimentações do processo, mais recentes primeiro."""
    resp = (
        get_client()
        .table(_TABELA)
        .select("*")
        .eq("processo_id", processo_id)
        .order("data_movimento", desc=True)
        .limit(limite)
        .execute()
    )
    return resp.data or []


def upsert_movimentacoes(processo_id: str, movimentos: list[Movimentacao]) -> int:
    """Insere movimentações ignorando duplicatas (unique processo_id+hash_unico).

    Retorna a quantidade de movimentações *novas* gravadas.
    """
    if not movimentos:
        return 0

    existentes = hashes_existentes(processo_id)
    novos = [m for m in movimentos if m.hash_unico not in existentes]
    if not novos:
        return 0

    payload: list[dict[str, Any]] = [
        {
            "processo_id": processo_id,
            "codigo_movimento": m.codigo_movimento,
            "nome_movimento": m.nome_movimento,
            "data_movimento": m.data_movimento,
            "complementos": m.complementos,
            "hash_unico": m.hash_unico,
        }
        for m in novos
    ]

    # on_conflict garante idempotência mesmo em corrida; ignore_duplicates evita erro.
    (
        get_client()
        .table(_TABELA)
        .upsert(payload, on_conflict="processo_id,hash_unico", ignore_duplicates=True)
        .execute()
    )
    return len(novos)
