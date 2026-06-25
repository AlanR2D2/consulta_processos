"""Orquestra o ciclo de sincronização DataJud → Supabase.

1. Lê todos os processos ativos.
2. Agrupa por tribunal e consulta o DataJud EM LOTE (uma query `terms` por chunk),
   reduzindo milhares de requisições para ~dezenas.
3. Normaliza, deduplica e faz upsert idempotente das movimentações.
4. Atualiza capa + marcadores de sincronização do processo.
5. Registra a execução em `sync_runs` (isolando falhas por processo/lote).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from src.config import settings
from src.datajud.client import DataJudAuthError, DataJudClient
from src.datajud.endpoints import limpar_numero
from src.datajud.parser import consolidar
from src.djen.client import DJENClient
from src.djen.parser import parse_lista
from src.repository import movimentacoes as repo_mov
from src.repository import oabs as repo_oab
from src.repository import processos as repo_proc
from src.repository import publicacoes as repo_pub
from src.supabase_client import get_client

logger = logging.getLogger(__name__)

# Quantos processos por query `terms`. Menor = respostas mais leves (menos timeout).
_CHUNK_LOTE = 50
# Limite de erros detalhados gravados em sync_runs.detalhe_erros (evita jsonb gigante).
_MAX_ERROS_DETALHE = 100


def _agora() -> str:
    return datetime.now(UTC).isoformat()


def _abrir_run() -> str:
    resp = get_client().table("promad_sync_runs").insert({"status": "running"}).execute()
    return resp.data[0]["id"]


def _fechar_run(
    run_id: str,
    consultados: int,
    novas: int,
    erros: list[dict[str, Any]],
) -> str:
    status = "failed" if erros and consultados == 0 else ("partial" if erros else "success")
    (
        get_client()
        .table("promad_sync_runs")
        .update(
            {
                "finished_at": _agora(),
                "processos_consultados": consultados,
                "movimentacoes_novas": novas,
                "erros": len(erros),
                "detalhe_erros": erros[:_MAX_ERROS_DETALHE] or None,
                "status": status,
            }
        )
        .eq("id", run_id)
        .execute()
    )
    return status


def _carregar_ativos() -> list[dict[str, Any]]:
    """Carrega todos os processos ativos (paginando o Supabase)."""
    processos: list[dict[str, Any]] = []
    offset = 0
    batch = max(settings.sync_batch_size, 1000)
    while True:
        lote = repo_proc.listar_ativos(batch, offset)
        if not lote:
            break
        processos.extend(lote)
        if len(lote) < batch:
            break
        offset += batch
    return processos


_SEM_DADOS_DETALHE = (
    "Nenhum documento retornado pelo DataJud — pode ser segredo de justiça/sigilo "
    "ou a base do tribunal ainda não foi alimentada."
)


def _aplicar_resultado(
    processo: dict[str, Any], sources: list[dict[str, Any]], agora: str
) -> tuple[int, str, str | None]:
    """Grava capa + movimentações e o status do processo.

    Retorna (movimentações_novas, status, detalhe). Status: ok|sigiloso|sem_dados.
    """
    if not sources:
        repo_proc.marcar_sincronizacao(processo["id"], agora)
        repo_proc.marcar_status(processo["id"], "sem_dados", _SEM_DADOS_DETALHE)
        return 0, "sem_dados", _SEM_DADOS_DETALHE

    capa = consolidar(sources)
    novas = repo_mov.upsert_movimentacoes(processo["id"], capa.movimentos)
    ultima_mov = max(
        (m.data_movimento for m in capa.movimentos if m.data_movimento),
        default=None,
    )
    repo_proc.atualizar_capa_e_sync(processo["id"], capa, agora, ultima_mov)

    if capa.nivel_sigilo and capa.nivel_sigilo > 0:
        status, detalhe = "sigiloso", f"Processo com nível de sigilo {capa.nivel_sigilo}."
    else:
        status, detalhe = "ok", None
    repo_proc.marcar_status(processo["id"], status, detalhe)
    return novas, status, detalhe


def _sincronizar_djen(
    processo: dict[str, Any], client: DJENClient | None = None
) -> int:
    """Busca publicações/intimações no DJEN e faz upsert. Retorna nº de novas.

    Resiliente: se a tabela/coluna do DJEN (migration 003) não existir, registra
    aviso e segue sem quebrar o sync do DataJud.
    """
    client = client or DJENClient()
    try:
        itens = client.buscar_por_processo(processo["numero_cnj"])
        publicacoes = parse_lista(itens)
        novas = repo_pub.upsert_publicacoes(processo["id"], publicacoes)
        ultima = max(
            (p.data_disponibilizacao for p in publicacoes if p.data_disponibilizacao),
            default=None,
        )
        repo_proc.marcar_ultima_publicacao(processo["id"], ultima)
        return novas
    except Exception as exc:
        logger.warning(
            "DJEN falhou para %s (%s). Rode migrations/003_djen.sql se ainda não rodou.",
            processo.get("numero_cnj"),
            exc,
        )
        return 0


def sincronizar_um(processo_id: str) -> dict[str, Any]:
    """Sincroniza UM processo (sync unitário): DataJud + DJEN."""
    processo = repo_proc.obter(processo_id)
    if not processo:
        return {"status": "erro", "detalhe": "Processo não encontrado.", "movimentacoes_novas": 0}

    numero = processo["numero_cnj"]
    agora = _agora()
    try:
        sources = DataJudClient().buscar_processo(numero)
    except Exception as exc:
        logger.error("Erro no sync unitário de %s: %s", numero, exc)
        repo_proc.marcar_status(processo_id, "erro", str(exc))
        return {"status": "erro", "detalhe": str(exc), "movimentacoes_novas": 0}

    novas, _status, detalhe = _aplicar_resultado(processo, sources, agora)
    pubs_novas = _sincronizar_djen(processo)
    # Status final considera DataJud + DJEN (com_dados se houver movimentação OU publicação).
    status = repo_proc.derivar_status(repo_proc.obter(processo_id) or processo)
    if status == "com_dados":
        detalhe = None  # tem dados (DJEN e/ou DataJud); detalhe de "sem retorno" não se aplica
    resumo = {
        "status": status,
        "detalhe": detalhe,
        "movimentacoes_novas": novas,
        "publicacoes_novas": pubs_novas,
    }
    logger.info("Sync unitário %s: %s", numero, resumo)
    return resumo


def sincronizar(incluir_djen: bool = False) -> dict[str, Any]:
    """Executa um ciclo completo de sincronização, consultando o DataJud em lote.

    Agrupa os processos ativos por tribunal e dispara uma query `terms` por chunk
    de até _CHUNK_LOTE números — muito mais rápido que 1 requisição por processo.
    `incluir_djen=True` consulta o DJEN por processo (lento, 1 req/processo); para a
    carteira inteira prefira `sincronizar_djen_por_oab()` (consulta em lote por OAB).
    """
    client = DataJudClient()
    djen = DJENClient() if incluir_djen else None
    run_id = _abrir_run()
    consultados = 0
    total_novas = 0
    total_pubs = 0
    erros: list[dict[str, Any]] = []

    processos = _carregar_ativos()
    por_alias: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for p in processos:
        alias = p.get("tribunal_alias")
        if not alias:
            erros.append({"numero_cnj": p.get("numero_cnj"), "erro": "sem tribunal_alias"})
            continue
        por_alias[alias].append(p)

    logger.info(
        "Sincronizando %d processo(s) em %d tribunal(is).", len(processos), len(por_alias)
    )

    try:
        for alias, procs in por_alias.items():
            por_numero = {p["numero_cnj"]: p for p in procs}
            numeros = list(por_numero)
            for i in range(0, len(numeros), _CHUNK_LOTE):
                chunk = numeros[i : i + _CHUNK_LOTE]
                try:
                    docs = client.buscar_lote(alias, chunk)
                except DataJudAuthError:
                    raise  # aborta tudo: chave inválida/rotacionada
                except Exception as exc:  # falha do chunk: registra e segue
                    logger.error("Erro no lote %s (%d processos): %s", alias, len(chunk), exc)
                    erros.append({"tribunal": alias, "qtd": len(chunk), "erro": str(exc)})
                    continue

                agora = _agora()
                for numero in chunk:
                    consultados += 1
                    processo = por_numero[numero]
                    try:
                        novas, _status, _detalhe = _aplicar_resultado(
                            processo, docs.get(numero, []), agora
                        )
                        total_novas += novas
                    except Exception as exc:  # isolamento por processo
                        logger.error("Erro ao gravar %s: %s", numero, exc)
                        erros.append({"numero_cnj": numero, "erro": str(exc)})
                        repo_proc.marcar_status(processo["id"], "erro", str(exc))
                    if djen is not None:
                        total_pubs += _sincronizar_djen(processo, djen)
    except DataJudAuthError as exc:
        logger.error("Sincronização abortada (auth): %s", exc)
        erros.append({"erro": str(exc), "fatal": True})

    status = _fechar_run(run_id, consultados, total_novas, erros)
    resumo = {
        "run_id": run_id,
        "processos_consultados": consultados,
        "movimentacoes_novas": total_novas,
        "publicacoes_novas": total_pubs,
        "erros": len(erros),
        "status": status,
    }
    logger.info("Sincronização concluída: %s", resumo)
    return resumo


def sincronizar_djen_por_oab(dias: int = 7) -> dict[str, Any]:
    """Sincroniza publicações do DJEN em LOTE, por OAB monitorada (eficiente).

    Para cada OAB ativa em promad_oabs, consulta o DJEN nos últimos `dias` dias
    (uma requisição traz todas as intimações de todos os processos daquela OAB),
    casa cada publicação ao processo cadastrado e faz upsert idempotente.
    """
    oabs = repo_oab.listar_ativas()
    if not oabs:
        return {"status": "vazio", "detalhe": "Nenhuma OAB cadastrada (promad_oabs).", "oabs": 0}

    hoje = datetime.now(UTC).date()
    inicio = (hoje - timedelta(days=dias)).isoformat()
    fim = hoje.isoformat()
    client = DJENClient()

    # 1) Coleta as publicações de todas as OABs.
    itens_por_numero: dict[str, list[dict[str, Any]]] = defaultdict(list)
    erros: list[dict[str, Any]] = []
    for oab in oabs:
        try:
            itens = client.buscar_por_oab(oab["numero"], oab["uf"], inicio, fim)
        except Exception as exc:
            logger.error("DJEN OAB %s/%s falhou: %s", oab["numero"], oab["uf"], exc)
            erros.append({"oab": f"{oab['numero']}/{oab['uf']}", "erro": str(exc)})
            continue
        for it in itens:
            try:
                numero = limpar_numero(it.get("numero_processo") or "")
            except Exception:
                continue
            itens_por_numero[numero].append(it)

    # 2) Mapeia números → processos cadastrados.
    mapa = repo_proc.mapear_por_numero(list(itens_por_numero))
    pubs_novas = 0
    processos_atualizados = 0
    nao_cadastrados = 0

    for numero, itens in itens_por_numero.items():
        processo_id = mapa.get(numero)
        if not processo_id:
            nao_cadastrados += 1
            continue
        publicacoes = parse_lista(itens)
        novas = repo_pub.upsert_publicacoes(processo_id, publicacoes)
        ultima = max(
            (p.data_disponibilizacao for p in publicacoes if p.data_disponibilizacao),
            default=None,
        )
        repo_proc.marcar_ultima_publicacao(processo_id, ultima)
        if novas:
            pubs_novas += novas
            processos_atualizados += 1

    resumo = {
        "status": "success" if not erros else "partial",
        "oabs": len(oabs),
        "periodo": f"{inicio}..{fim}",
        "processos_com_publicacao": len(itens_por_numero),
        "processos_cadastrados_atualizados": processos_atualizados,
        "publicacoes_novas": pubs_novas,
        "processos_nao_cadastrados": nao_cadastrados,
        "erros": len(erros),
    }
    logger.info("DJEN por OAB concluído: %s", resumo)
    return resumo
