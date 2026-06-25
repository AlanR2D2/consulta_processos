import pytest

from src.datajud.endpoints import (
    CNJInvalido,
    SegmentoNaoSuportado,
    alias_de,
    formatar_numero,
    limpar_numero,
    listar_todos_tribunais,
)

# Números construídos com J e TR específicos (posições 13 e 14-15 dos 20 dígitos).
# Layout: 0000000_00_0000_J_TR_0000


def _num(j: int, tr: int) -> str:
    return f"0000000000000{j}{tr:02d}0000"


def test_limpar_numero_remove_mascara():
    assert limpar_numero("0001234-56.2023.8.26.0100") == "00012345620238260100"


def test_limpar_numero_invalido():
    with pytest.raises(CNJInvalido):
        limpar_numero("123")


def test_formatar_numero():
    assert formatar_numero("00012345620238260100") == "0001234-56.2023.8.26.0100"


@pytest.mark.parametrize(
    "j,tr,esperado",
    [
        (3, 0, "stj"),
        (4, 1, "trf1"),
        (4, 6, "trf6"),
        (5, 0, "tst"),
        (5, 2, "trt2"),
        (6, 0, "tse"),
        (6, 26, "tre-sp"),
        (7, 0, "stm"),
        (8, 26, "tjsp"),
        (8, 1, "tjac"),
        (8, 7, "tjdft"),
        (9, 13, "tjmmg"),
        (9, 26, "tjmsp"),
    ],
)
def test_roteamento(j, tr, esperado):
    assert alias_de(_num(j, tr)) == esperado


def test_stf_nao_suportado():
    with pytest.raises(SegmentoNaoSuportado):
        alias_de(_num(1, 0))


def test_tr_inexistente():
    with pytest.raises(SegmentoNaoSuportado):
        alias_de(_num(4, 9))  # TRF9 não existe


def test_seed_tem_91_tribunais():
    aliases = [t.alias for t in listar_todos_tribunais()]
    # 4 superiores + 6 TRF + 24 TRT + 27 TJ + 27 TRE + 3 militar estadual = 91
    assert len(aliases) == 91
    assert len(set(aliases)) == 91  # sem duplicatas
    assert "tjsp" in aliases
    assert "tre-sp" in aliases
    assert "stj" in aliases
