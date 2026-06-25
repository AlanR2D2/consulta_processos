"""Normalização de itens da Comunica/DJEN → registro de publicação + hash."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from src.formato import normalizar_para_iso


@dataclass
class Publicacao:
    id_djen: int | None
    numero_comunicacao: int | None
    data_disponibilizacao: str | None
    tipo_comunicacao: str | None
    tipo_documento: str | None
    nome_classe: str | None
    codigo_classe: int | None
    nome_orgao: str | None
    sigla_tribunal: str | None
    meio: str | None
    link: str | None
    texto: str | None
    destinatarios: list[dict[str, Any]]
    advogados: list[dict[str, Any]]
    status: str | None
    hash_unico: str


def _hash(item: dict[str, Any]) -> str:
    """Usa o hash do próprio DJEN; se faltar, deriva de id/numero/data."""
    h = item.get("hash")
    if h:
        return str(h)
    base = f"{item.get('id')}|{item.get('numeroComunicacao')}|{item.get('data_disponibilizacao')}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def parse_item(item: dict[str, Any]) -> Publicacao:
    return Publicacao(
        id_djen=item.get("id"),
        numero_comunicacao=item.get("numeroComunicacao"),
        data_disponibilizacao=normalizar_para_iso(item.get("data_disponibilizacao")),
        tipo_comunicacao=item.get("tipoComunicacao"),
        tipo_documento=item.get("tipoDocumento"),
        nome_classe=item.get("nomeClasse"),
        codigo_classe=item.get("codigoClasse"),
        nome_orgao=item.get("nomeOrgao"),
        sigla_tribunal=item.get("siglaTribunal"),
        meio=item.get("meio") or item.get("meiocompleto"),
        link=item.get("link"),
        texto=item.get("texto"),
        destinatarios=item.get("destinatarios") or [],
        advogados=item.get("destinatarioadvogados") or [],
        status=item.get("status"),
        hash_unico=_hash(item),
    )


def parse_lista(itens: list[dict[str, Any]]) -> list[Publicacao]:
    return [parse_item(i) for i in itens]
