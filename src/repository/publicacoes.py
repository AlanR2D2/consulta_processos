"""Upsert idempotente das publicações DJEN (tabela promad_publicacoes_djen)."""

from __future__ import annotations

from typing import Any

from src.djen.parser import Publicacao
from src.supabase_client import get_client

_TABELA = "promad_publicacoes_djen"


def hashes_existentes(processo_id: str) -> set[str]:
    resp = (
        get_client()
        .table(_TABELA)
        .select("hash_unico")
        .eq("processo_id", processo_id)
        .execute()
    )
    return {r["hash_unico"] for r in (resp.data or [])}


def listar_por_processo(processo_id: str, limite: int = 200) -> list[dict[str, Any]]:
    resp = (
        get_client()
        .table(_TABELA)
        .select("*")
        .eq("processo_id", processo_id)
        .order("data_disponibilizacao", desc=True)
        .limit(limite)
        .execute()
    )
    return resp.data or []


def upsert_publicacoes(processo_id: str, publicacoes: list[Publicacao]) -> int:
    """Insere publicações novas (idempotente por processo_id+hash_unico).

    Retorna a quantidade de publicações novas gravadas.
    """
    if not publicacoes:
        return 0

    existentes = hashes_existentes(processo_id)
    novas = [p for p in publicacoes if p.hash_unico not in existentes]
    if not novas:
        return 0

    payload: list[dict[str, Any]] = [
        {
            "processo_id": processo_id,
            "id_djen": p.id_djen,
            "numero_comunicacao": p.numero_comunicacao,
            "data_disponibilizacao": p.data_disponibilizacao,
            "tipo_comunicacao": p.tipo_comunicacao,
            "tipo_documento": p.tipo_documento,
            "nome_classe": p.nome_classe,
            "codigo_classe": p.codigo_classe,
            "nome_orgao": p.nome_orgao,
            "sigla_tribunal": p.sigla_tribunal,
            "meio": p.meio,
            "link": p.link,
            "texto": p.texto,
            "destinatarios": p.destinatarios,
            "advogados": p.advogados,
            "status": p.status,
            "hash_unico": p.hash_unico,
        }
        for p in novas
    ]
    (
        get_client()
        .table(_TABELA)
        .upsert(payload, on_conflict="processo_id,hash_unico", ignore_duplicates=True)
        .execute()
    )
    return len(novas)
