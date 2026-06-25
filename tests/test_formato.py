from src.formato import data_br


def test_iso_utc_para_sao_paulo():
    # 20:33 UTC → 17:33 em São Paulo (UTC-3).
    assert data_br("2026-06-23T20:33:50.862296+00:00") == "23/06/2026 17:33:50"


def test_sem_hora():
    assert data_br("2026-06-23T20:33:50+00:00", com_hora=False) == "23/06/2026"


def test_data_pura_nao_converte_fuso():
    # Data sem hora não deve "voltar" um dia por conversão de fuso.
    assert data_br("2017-08-21") == "21/08/2017"


def test_vazio_e_none():
    assert data_br(None) == "-"
    assert data_br("") == "-"


def test_string_nao_data_volta_inalterada():
    assert data_br("sem data") == "sem data"
