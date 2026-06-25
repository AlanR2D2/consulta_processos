"""CRUD da tabela `processos`."""

from __future__ import annotations

import logging
from typing import Any

from src.datajud.endpoints import (
    CNJInvalido,
    SegmentoNaoSuportado,
    formatar_numero,
    limpar_numero,
    rotear,
)
from src.datajud.parser import CapaProcesso
from src.supabase_client import get_client

logger = logging.getLogger(__name__)

_TABELA = "promad_processos"


def adicionar(numero_cnj: str, cliente_id: str | None = None) -> dict[str, Any]:
    """Cadastra um processo (idempotente por numero_cnj). Retorna a linha."""
    numero = limpar_numero(numero_cnj)
    info = rotear(numero)  # valida segmento e deriva alias
    payload = {
        "numero_cnj": numero,
        "numero_formatado": formatar_numero(numero),
        "tribunal_alias": info.alias,
        "cliente_id": cliente_id,
        "ativo": True,
    }
    resp = get_client().table(_TABELA).upsert(payload, on_conflict="numero_cnj").execute()
    return resp.data[0]


def cadastrar_em_lote(
    numeros: list[str], cliente_id: str | None = None, chunk: int = 500
) -> dict[str, Any]:
    """Cadastra vários processos de uma vez (upsert idempotente em chunks).

    Valida e roteia cada número; deduplica; pula inválidos (não-20-dígitos) e
    segmentos não suportados (ex.: STF), reportando-os. Retorna um resumo.
    """
    validos: list[dict[str, Any]] = []
    invalidos: list[str] = []
    nao_suportados: list[str] = []
    vistos: set[str] = set()
    total_lidos = 0

    for raw in numeros:
        bruto = (raw or "").strip()
        if not bruto:
            continue
        total_lidos += 1
        try:
            numero = limpar_numero(bruto)
        except CNJInvalido:
            invalidos.append(bruto)
            continue
        if numero in vistos:
            continue
        vistos.add(numero)
        try:
            info = rotear(numero)
        except SegmentoNaoSuportado:
            nao_suportados.append(bruto)
            continue
        validos.append(
            {
                "numero_cnj": numero,
                "numero_formatado": formatar_numero(numero),
                "tribunal_alias": info.alias,
                "cliente_id": cliente_id,
                "ativo": True,
            }
        )

    cadastrados = 0
    client = get_client()
    for i in range(0, len(validos), chunk):
        lote = validos[i : i + chunk]
        client.table(_TABELA).upsert(lote, on_conflict="numero_cnj").execute()
        cadastrados += len(lote)

    return {
        "total_lidos": total_lidos,
        "cadastrados": cadastrados,
        "duplicados": total_lidos - len(invalidos) - len(nao_suportados) - len(validos),
        "invalidos": invalidos,
        "nao_suportados": nao_suportados,
    }


def listar_ativos(limite: int, offset: int = 0) -> list[dict[str, Any]]:
    """Processos com ativo=true, paginados."""
    resp = (
        get_client()
        .table(_TABELA)
        .select("*")
        .eq("ativo", True)
        .order("created_at")
        .range(offset, offset + limite - 1)
        .execute()
    )
    return resp.data or []


def derivar_status(processo: dict[str, Any]) -> str:
    """Classifica um processo pela presença real de dados (não pela string salva).

    "Com dados" = tem ≥1 movimentação (DataJud) OU ≥1 publicação (DJEN).
    Retorna: sigilo | com_dados | sem_dados | nao_sync.
    """
    if not processo.get("ultima_sincronizacao"):
        return "nao_sync"
    if (processo.get("nivel_sigilo") or 0) > 0:
        return "sigilo"
    if processo.get("ultima_movimentacao_data") or processo.get("ultima_publicacao_data"):
        return "com_dados"
    return "sem_dados"


def _filtrar_status(query: Any, status: str) -> Any:
    """Aplica a condição SQL de um grupo de status (baseado em colunas reais)."""
    if status == "com_dados":  # tem >= 1 movimentação OU >= 1 publicação
        return query.or_(
            "ultima_movimentacao_data.not.is.null,ultima_publicacao_data.not.is.null"
        )
    if status == "sem_dados":  # sincronizado, porém sem movimentação e sem publicação
        return (
            query.not_.is_("ultima_sincronizacao", "null")
            .is_("ultima_movimentacao_data", "null")
            .is_("ultima_publicacao_data", "null")
        )
    if status == "sigilo":  # nível de sigilo > 0
        return query.gt("nivel_sigilo", 0)
    if status == "nao_sync":  # nunca sincronizado
        return query.is_("ultima_sincronizacao", "null")
    return query


def _aplicar_filtros(query: Any, filtros: dict[str, str | None]) -> Any:
    """Aplica filtros opcionais (numero, tribunal, classe, status) a uma query."""
    numero = (filtros.get("numero") or "").strip()
    if numero:
        digitos = "".join(ch for ch in numero if ch.isdigit())
        query = query.ilike("numero_cnj", f"%{digitos or numero}%")

    tribunal = (filtros.get("tribunal") or "").strip()
    if tribunal:
        query = query.eq("tribunal_alias", tribunal)

    classe = (filtros.get("classe") or "").strip()
    if classe:
        query = query.ilike("classe_nome", f"%{classe}%")

    status = (filtros.get("status") or "").strip()
    if status:
        query = _filtrar_status(query, status)
    return query


def listar_filtrado(
    limite: int, offset: int, filtros: dict[str, str | None]
) -> list[dict[str, Any]]:
    """Lista processos ativos aplicando filtros, paginado."""
    query = get_client().table(_TABELA).select("*").eq("ativo", True)
    query = _aplicar_filtros(query, filtros)
    resp = query.order("created_at").range(offset, offset + limite - 1).execute()
    return resp.data or []


def contar_filtrado(filtros: dict[str, str | None]) -> int:
    """Conta processos ativos que batem os filtros."""
    query = get_client().table(_TABELA).select("id", count="exact").eq("ativo", True)
    query = _aplicar_filtros(query, filtros)
    resp = query.limit(1).execute()
    return resp.count or 0


def _contar(query_builder: Any) -> int:
    return query_builder.limit(1).execute().count or 0


def resumo_status() -> dict[str, int]:
    """Contagens globais por presença real de dados (colunas, não a string salva).

    com_dados + sem_dados + nao_sync = total. `sigilo` é informativo (pode
    sobrepor com_dados).
    """
    c = get_client()

    def base() -> Any:
        return c.table(_TABELA).select("id", count="exact").eq("ativo", True)

    return {
        "total": _contar(base()),
        "com_dados": _contar(_filtrar_status(base(), "com_dados")),
        "sem_dados": _contar(_filtrar_status(base(), "sem_dados")),
        "sigilo": _contar(_filtrar_status(base(), "sigilo")),
        "nao_sync": _contar(_filtrar_status(base(), "nao_sync")),
    }


def listar_todos() -> list[dict[str, Any]]:
    resp = get_client().table(_TABELA).select("*").order("created_at").execute()
    return resp.data or []


def contar() -> int:
    """Total de processos cadastrados."""
    resp = get_client().table(_TABELA).select("id", count="exact").limit(1).execute()
    return resp.count or 0


def obter(processo_id: str) -> dict[str, Any] | None:
    """Retorna um processo pelo id, ou None."""
    resp = get_client().table(_TABELA).select("*").eq("id", processo_id).limit(1).execute()
    return resp.data[0] if resp.data else None


def mapear_por_numero(numeros: list[str], chunk: int = 200) -> dict[str, str]:
    """Mapeia numero_cnj → id para os números informados (em chunks)."""
    mapa: dict[str, str] = {}
    unicos = list({n for n in numeros if n})
    client = get_client()
    for i in range(0, len(unicos), chunk):
        lote = unicos[i : i + chunk]
        rows = client.table(_TABELA).select("id,numero_cnj").in_("numero_cnj", lote).execute().data
        for r in rows or []:
            mapa[r["numero_cnj"]] = r["id"]
    return mapa


_aviso_status_emitido = False


def marcar_status(processo_id: str, status: str, detalhe: str | None = None) -> bool:
    """Grava o resultado da última sincronização (ok|sigiloso|sem_dados|erro).

    Resiliente: se as colunas da migration 002 ainda não existirem, apenas
    registra um aviso (uma vez) e segue — não derruba a sincronização.
    """
    global _aviso_status_emitido
    try:
        (
            get_client()
            .table(_TABELA)
            .update({"ultimo_sync_status": status, "ultimo_sync_detalhe": detalhe})
            .eq("id", processo_id)
            .execute()
        )
        return True
    except Exception as exc:  # provável coluna inexistente (migration 002 não aplicada)
        if not _aviso_status_emitido:
            logger.warning(
                "Não consegui gravar ultimo_sync_status (%s). "
                "Rode migrations/002_sync_status.sql no Supabase para habilitar o status.",
                exc,
            )
            _aviso_status_emitido = True
        return False


def atualizar_capa_e_sync(
    processo_id: str,
    capa: CapaProcesso,
    ultima_sincronizacao: str,
    ultima_movimentacao_data: str | None,
) -> None:
    """Atualiza campos de capa + marcadores de sincronização."""
    payload: dict[str, Any] = {
        "ultima_sincronizacao": ultima_sincronizacao,
        "classe_codigo": capa.classe_codigo,
        "classe_nome": capa.classe_nome,
        "assunto_principal": capa.assunto_principal,
        "orgao_julgador": capa.orgao_julgador,
        "grau": capa.grau,
        "sistema": capa.sistema,
        "formato": capa.formato,
        "nivel_sigilo": capa.nivel_sigilo,
        "data_ajuizamento": capa.data_ajuizamento,
    }
    if ultima_movimentacao_data:
        payload["ultima_movimentacao_data"] = ultima_movimentacao_data
    # Remove chaves None para não sobrescrever capa existente com vazio.
    payload = {k: v for k, v in payload.items() if v is not None}
    get_client().table(_TABELA).update(payload).eq("id", processo_id).execute()


def marcar_sincronizacao(processo_id: str, ultima_sincronizacao: str) -> None:
    """Atualiza apenas o timestamp de sincronização (ex.: processo sem retorno)."""
    (
        get_client()
        .table(_TABELA)
        .update({"ultima_sincronizacao": ultima_sincronizacao})
        .eq("id", processo_id)
        .execute()
    )


def marcar_ultima_publicacao(processo_id: str, ultima_publicacao_data: str | None) -> None:
    """Atualiza o marcador da última publicação DJEN do processo."""
    if not ultima_publicacao_data:
        return
    (
        get_client()
        .table(_TABELA)
        .update({"ultima_publicacao_data": ultima_publicacao_data})
        .eq("id", processo_id)
        .execute()
    )
