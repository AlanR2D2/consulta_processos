"""CRUD da tabela `promad_oabs` (OABs monitoradas no DJEN)."""

from __future__ import annotations

from typing import Any

from src.supabase_client import get_client

_TABELA = "promad_oabs"


def _norm(numero: str) -> str:
    return "".join(ch for ch in (numero or "") if ch.isdigit())


def adicionar(numero: str, uf: str, nome: str | None = None) -> dict[str, Any]:
    payload = {
        "numero": _norm(numero),
        "uf": (uf or "").strip().upper(),
        "nome": nome,
        "ativo": True,
    }
    resp = get_client().table(_TABELA).upsert(payload, on_conflict="numero,uf").execute()
    return resp.data[0]


def listar_ativas() -> list[dict[str, Any]]:
    resp = get_client().table(_TABELA).select("*").eq("ativo", True).order("numero").execute()
    return resp.data or []


def remover(numero: str, uf: str) -> None:
    (
        get_client()
        .table(_TABELA)
        .delete()
        .eq("numero", _norm(numero))
        .eq("uf", (uf or "").strip().upper())
        .execute()
    )


def seed_de_publicacoes() -> int:
    """Popula promad_oabs a partir dos advogados já presentes nas publicações DJEN.

    Bootstrap: extrai OAB/UF distintos do jsonb `advogados` de promad_publicacoes_djen.
    Retorna a quantidade de OABs registradas.
    """
    client = get_client()
    vistos: dict[tuple[str, str], str | None] = {}
    offset = 0
    while True:
        rows = (
            client.table("promad_publicacoes_djen")
            .select("advogados")
            .range(offset, offset + 999)
            .execute()
            .data
        )
        if not rows:
            break
        for r in rows:
            for adv in r.get("advogados") or []:
                a = adv.get("advogado") if isinstance(adv, dict) else None
                if not a:
                    continue
                numero = _norm(str(a.get("numero_oab") or ""))
                uf = (a.get("uf_oab") or "").strip().upper()
                if numero and uf:
                    vistos.setdefault((numero, uf), a.get("nome"))
        if len(rows) < 1000:
            break
        offset += 1000

    payload = [
        {"numero": num, "uf": uf, "nome": nome, "ativo": True}
        for (num, uf), nome in vistos.items()
    ]
    if payload:
        client.table(_TABELA).upsert(payload, on_conflict="numero,uf").execute()
    return len(payload)
