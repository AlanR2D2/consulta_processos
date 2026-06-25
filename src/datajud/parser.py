"""Normalização da resposta DataJud → capa + movimentações com hash idempotente."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

_COMPACT_DATETIME = re.compile(r"^\d{14}$")  # yyyyMMddHHmmss
_COMPACT_DATE = re.compile(r"^\d{8}$")  # yyyyMMdd


def normalizar_data(value: Any) -> str | None:
    """Normaliza datas do DataJud para ISO 8601.

    A API real é inconsistente: `dataHora` costuma vir ISO, mas `dataAjuizamento`
    pode vir compacto (`yyyyMMddHHmmss`), que o Postgres rejeita em timestamptz.
    Valores já em ISO passam inalterados (preserva hashes existentes).
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if _COMPACT_DATETIME.match(s):
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}T{s[8:10]}:{s[10:12]}:{s[12:14]}"
    if _COMPACT_DATE.match(s):
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    return s


@dataclass
class Movimentacao:
    codigo_movimento: int | None
    nome_movimento: str | None
    data_movimento: str | None  # ISO 8601 (dataHora original)
    complementos: list[dict[str, Any]]
    hash_unico: str


@dataclass
class CapaProcesso:
    numero_cnj: str | None = None
    tribunal: str | None = None
    grau: str | None = None
    classe_codigo: int | None = None
    classe_nome: str | None = None
    assunto_principal: str | None = None
    orgao_julgador: str | None = None
    sistema: str | None = None
    formato: str | None = None
    nivel_sigilo: int | None = None
    data_ajuizamento: str | None = None
    movimentos: list[Movimentacao] = field(default_factory=list)


def calcular_hash(numero_cnj: str, codigo: Any, data_hora: Any, nome: Any) -> str:
    """sha256(numero_cnj + codigo + dataHora + nome). Estável e idempotente."""
    base = f"{numero_cnj}|{codigo}|{data_hora}|{nome}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def _primeiro_assunto(assuntos: Any) -> str | None:
    """assuntos vem como lista (às vezes aninhada) de {codigo, nome}."""
    if not assuntos:
        return None
    item = assuntos
    # Desempacota aninhamentos (ex.: [[{...}]]).
    while isinstance(item, list) and item:
        item = item[0]
    if isinstance(item, dict):
        return item.get("nome")
    return None


def parse_source(source: dict[str, Any]) -> CapaProcesso:
    """Converte um `_source` do DataJud em capa + movimentações normalizadas."""
    numero = source.get("numeroProcesso")
    classe = source.get("classe") or {}
    sistema = source.get("sistema") or {}
    formato = source.get("formato") or {}
    orgao = source.get("orgaoJulgador") or {}

    capa = CapaProcesso(
        numero_cnj=numero,
        tribunal=source.get("tribunal"),
        grau=source.get("grau"),
        classe_codigo=classe.get("codigo"),
        classe_nome=classe.get("nome"),
        assunto_principal=_primeiro_assunto(source.get("assuntos")),
        orgao_julgador=orgao.get("nome"),
        sistema=sistema.get("nome"),
        formato=formato.get("nome"),
        nivel_sigilo=source.get("nivelSigilo"),
        data_ajuizamento=normalizar_data(source.get("dataAjuizamento")),
    )

    for mov in source.get("movimentos") or []:
        codigo = mov.get("codigo")
        nome = mov.get("nome")
        data_hora = normalizar_data(mov.get("dataHora"))
        capa.movimentos.append(
            Movimentacao(
                codigo_movimento=codigo,
                nome_movimento=nome,
                data_movimento=data_hora,
                complementos=mov.get("complementosTabelados") or [],
                hash_unico=calcular_hash(numero, codigo, data_hora, nome),
            )
        )
    return capa


def consolidar(sources: list[dict[str, Any]]) -> CapaProcesso:
    """Funde múltiplos documentos (graus) num processo único, deduplicando movimentos.

    A capa é tomada do documento de maior grau disponível (último ordenado).
    """
    if not sources:
        return CapaProcesso()

    capas = [parse_source(s) for s in sources]
    # Capa principal: prioriza maior grau (G2 > G1); fallback no primeiro.
    principal = max(capas, key=lambda c: (c.grau or ""))

    vistos: set[str] = set()
    movimentos: list[Movimentacao] = []
    for capa in capas:
        for mov in capa.movimentos:
            if mov.hash_unico in vistos:
                continue
            vistos.add(mov.hash_unico)
            movimentos.append(mov)

    principal.movimentos = movimentos
    return principal
