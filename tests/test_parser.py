from src.datajud.parser import calcular_hash, consolidar, normalizar_data, parse_source

_SOURCE = {
    "numeroProcesso": "07223914020178070001",
    "tribunal": "TJDFT",
    "grau": "G1",
    "dataAjuizamento": "2017-08-21T10:05:32.000Z",
    "nivelSigilo": 0,
    "classe": {"codigo": 1116, "nome": "Execução Fiscal"},
    "sistema": {"codigo": 1, "nome": "Pje"},
    "formato": {"codigo": 1, "nome": "Eletrônico"},
    "orgaoJulgador": {"codigo": 13597, "nome": "VARA DE EXECUÇÃO FISCAL DO DF"},
    "assuntos": [[{"codigo": 6017, "nome": "Dívida Ativa (Execução Fiscal)"}]],
    "movimentos": [
        {
            "codigo": 26,
            "nome": "Distribuição",
            "dataHora": "2017-08-21T10:05:32.000Z",
            "complementosTabelados": [
                {"codigo": 2, "valor": 2, "nome": "sorteio", "descricao": "x"}
            ],
        },
        {"codigo": 51, "nome": "Conclusão", "dataHora": "2018-01-10T09:00:00.000Z"},
    ],
}


def test_parse_capa():
    capa = parse_source(_SOURCE)
    assert capa.numero_cnj == "07223914020178070001"
    assert capa.classe_codigo == 1116
    assert capa.classe_nome == "Execução Fiscal"
    assert capa.assunto_principal == "Dívida Ativa (Execução Fiscal)"
    assert capa.orgao_julgador == "VARA DE EXECUÇÃO FISCAL DO DF"
    assert capa.sistema == "Pje"
    assert capa.formato == "Eletrônico"
    assert capa.nivel_sigilo == 0
    assert len(capa.movimentos) == 2


def test_movimento_complementos_default_vazio():
    capa = parse_source(_SOURCE)
    assert capa.movimentos[1].complementos == []  # sem complementosTabelados


def test_hash_estavel_e_distinto():
    h1 = calcular_hash("123", 26, "2017-08-21T10:05:32.000Z", "Distribuição")
    h2 = calcular_hash("123", 26, "2017-08-21T10:05:32.000Z", "Distribuição")
    h3 = calcular_hash("123", 51, "2017-08-21T10:05:32.000Z", "Distribuição")
    assert h1 == h2  # determinístico
    assert h1 != h3  # código diferente → hash diferente


def test_normalizar_data():
    # Compacto (yyyyMMddHHmmss) — formato real do dataAjuizamento na API.
    assert normalizar_data("20170821100532") == "2017-08-21T10:05:32"
    # Compacto só data (yyyyMMdd).
    assert normalizar_data("20170821") == "2017-08-21"
    # ISO passa inalterado (preserva hashes existentes).
    assert normalizar_data("2024-08-26T19:55:51.000Z") == "2024-08-26T19:55:51.000Z"
    assert normalizar_data(None) is None
    assert normalizar_data("") is None


def test_data_ajuizamento_compacta_normalizada():
    src = dict(_SOURCE, dataAjuizamento="20170821100532")
    capa = parse_source(src)
    assert capa.data_ajuizamento == "2017-08-21T10:05:32"


def test_consolidar_deduplica_movimentos():
    # Mesmo processo retornado em dois graus, com um movimento repetido.
    src_g2 = dict(_SOURCE, grau="G2")
    capa = consolidar([_SOURCE, src_g2])
    # 2 movimentos únicos (os repetidos colapsam pelo hash).
    assert len(capa.movimentos) == 2
    assert capa.grau == "G2"  # capa principal = maior grau
