"""Roteamento do número único CNJ → alias do tribunal na API DataJud.

Formato do número único: NNNNNNN-DD.AAAA.J.TR.OOOO (20 dígitos sem máscara)
  - J  (posição 13, 1 dígito)  = segmento do Judiciário
  - TR (posições 14-15, 2 dígitos) = tribunal dentro do segmento

A tabela aqui é a fonte de verdade do roteamento e também alimenta o seed da
tabela `tribunais` no Supabase (scripts/seed_tribunais.py).

Aliases confirmados contra a lista oficial:
  https://datajud-wiki.cnj.jus.br/api-publica/endpoints/
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# UF por código TR, ordenação alfabética (Resolução CNJ 65/2008).
# Usado tanto para J=8 (Justiça Estadual, prefixo 'tj') quanto para
# J=6 (Justiça Eleitoral, prefixo 'tre-').
# NOTA: a ordenação eleitoral (J=6) precisa de confirmação final contra a
# fonte oficial; a estadual (J=8) está confirmada.
_UF_BY_TR: dict[int, str] = {
    1: "ac",
    2: "al",
    3: "ap",
    4: "am",
    5: "ba",
    6: "ce",
    7: "dft",
    8: "es",
    9: "go",
    10: "ma",
    11: "mt",
    12: "ms",
    13: "mg",
    14: "pa",
    15: "pb",
    16: "pr",
    17: "pe",
    18: "pi",
    19: "rj",
    20: "rn",
    21: "rs",
    22: "ro",
    23: "rr",
    24: "sc",
    25: "se",
    26: "sp",
    27: "to",
}

# Justiça Militar Estadual (J=9): só 3 estados têm TJM próprio.
_MILITAR_ESTADUAL: dict[int, str] = {13: "tjmmg", 21: "tjmrs", 26: "tjmsp"}

_SEGMENTO_NOME = {
    "estadual": "Justiça Estadual",
    "federal": "Justiça Federal",
    "trabalho": "Justiça do Trabalho",
    "eleitoral": "Justiça Eleitoral",
    "militar": "Justiça Militar",
    "superior": "Tribunal Superior",
}


class CNJInvalido(ValueError):
    """Número CNJ malformado (não tem 20 dígitos)."""


class SegmentoNaoSuportado(ValueError):
    """Segmento sem endpoint na API pública (ex.: STF) ou TR inexistente."""


@dataclass(frozen=True)
class TribunalInfo:
    alias: str
    segmento: str
    codigo_j: int
    codigo_tr: int


def limpar_numero(numero: str) -> str:
    """Remove máscara e espaços; retorna 20 dígitos. Levanta CNJInvalido."""
    digits = re.sub(r"\D", "", numero or "")
    if len(digits) != 20:
        raise CNJInvalido(f"Número CNJ deve ter 20 dígitos; recebido {len(digits)}: {numero!r}")
    return digits


def formatar_numero(numero: str) -> str:
    """20 dígitos → NNNNNNN-DD.AAAA.J.TR.OOOO."""
    d = limpar_numero(numero)
    return f"{d[0:7]}-{d[7:9]}.{d[9:13]}.{d[13]}.{d[14:16]}.{d[16:20]}"


def _partes(numero: str) -> tuple[int, int]:
    """Retorna (J, TR) a partir do número de 20 dígitos."""
    d = limpar_numero(numero)
    return int(d[13]), int(d[14:16])


def rotear(numero: str) -> TribunalInfo:
    """Mapeia o número CNJ para o tribunal/alias da API DataJud.

    Levanta SegmentoNaoSuportado para STF (J=1) e TRs inexistentes.
    """
    j, tr = _partes(numero)

    if j == 1:
        raise SegmentoNaoSuportado("STF (J=1) não está disponível na API pública.")

    if j == 3:  # Superior Tribunal de Justiça
        return TribunalInfo("stj", "superior", j, tr)

    if j == 4:  # Justiça Federal
        if not 1 <= tr <= 6:
            raise SegmentoNaoSuportado(f"TRF inexistente para TR={tr:02d}.")
        return TribunalInfo(f"trf{tr}", "federal", j, tr)

    if j == 5:  # Justiça do Trabalho (TR=00 → TST)
        if tr == 0:
            return TribunalInfo("tst", "superior", j, tr)
        if not 1 <= tr <= 24:
            raise SegmentoNaoSuportado(f"TRT inexistente para TR={tr:02d}.")
        return TribunalInfo(f"trt{tr}", "trabalho", j, tr)

    if j == 6:  # Justiça Eleitoral (TR=00 → TSE)
        if tr == 0:
            return TribunalInfo("tse", "superior", j, tr)
        uf = _UF_BY_TR.get(tr)
        if uf is None:
            raise SegmentoNaoSuportado(f"TRE inexistente para TR={tr:02d}.")
        return TribunalInfo(f"tre-{uf}", "eleitoral", j, tr)

    if j == 7:  # Justiça Militar da União
        return TribunalInfo("stm", "militar", j, tr)

    if j == 8:  # Justiça Estadual
        uf = _UF_BY_TR.get(tr)
        if uf is None:
            raise SegmentoNaoSuportado(f"TJ inexistente para TR={tr:02d}.")
        return TribunalInfo(f"tj{uf}", "estadual", j, tr)

    if j == 9:  # Justiça Militar Estadual
        alias = _MILITAR_ESTADUAL.get(tr)
        if alias is None:
            raise SegmentoNaoSuportado(f"Justiça Militar Estadual inexistente para TR={tr:02d}.")
        return TribunalInfo(alias, "militar", j, tr)

    raise SegmentoNaoSuportado(f"Segmento J={j} desconhecido.")


def alias_de(numero: str) -> str:
    """Atalho: número CNJ → alias (string)."""
    return rotear(numero).alias


def listar_todos_tribunais() -> list[TribunalInfo]:
    """Gera a lista completa de tribunais para o seed da tabela `tribunais`."""
    tribunais: list[TribunalInfo] = []

    # Superiores
    tribunais.append(TribunalInfo("stj", "superior", 3, 0))
    tribunais.append(TribunalInfo("tst", "superior", 5, 0))
    tribunais.append(TribunalInfo("tse", "superior", 6, 0))
    tribunais.append(TribunalInfo("stm", "militar", 7, 0))

    # Justiça Federal
    for tr in range(1, 7):
        tribunais.append(TribunalInfo(f"trf{tr}", "federal", 4, tr))

    # Justiça do Trabalho
    for tr in range(1, 25):
        tribunais.append(TribunalInfo(f"trt{tr}", "trabalho", 5, tr))

    # Justiça Estadual e Eleitoral (mesma tabela de UFs)
    for tr, uf in _UF_BY_TR.items():
        tribunais.append(TribunalInfo(f"tj{uf}", "estadual", 8, tr))
        tribunais.append(TribunalInfo(f"tre-{uf}", "eleitoral", 6, tr))

    # Justiça Militar Estadual
    for tr, alias in _MILITAR_ESTADUAL.items():
        tribunais.append(TribunalInfo(alias, "militar", 9, tr))

    return tribunais


def nome_segmento(segmento: str) -> str:
    return _SEGMENTO_NOME.get(segmento, segmento)
