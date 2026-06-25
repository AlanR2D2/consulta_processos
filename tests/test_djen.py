from src.djen.parser import parse_item, parse_lista

_ITEM = {
    "id": 648563178,
    "numeroComunicacao": 12345,
    "data_disponibilizacao": "2026-06-23",
    "datadisponibilizacao": "23/06/2026",
    "tipoComunicacao": "Intimação",
    "tipoDocumento": "Intimação",
    "nomeClasse": "PROCEDIMENTO DO JUIZADO ESPECIAL CÍVEL",
    "codigoClasse": 436,
    "nomeOrgao": "Vara do Juizado Especial Cível e Criminal",
    "siglaTribunal": "TJSP",
    "meio": "D",
    "link": "https://comunica.pje.jus.br/...",
    "texto": "Conteúdo da intimação",
    "hash": "mMg9oWrBZ9XspqVcjTpDEav6zwDv82",
    "status": "P",
    "destinatarios": [{"polo": "A", "nome": "ADRIANA PEREIRA"}],
    "destinatarioadvogados": [{"advogado": {"nome": "ALINE", "numero_oab": "516085"}}],
}


def test_parse_item():
    p = parse_item(_ITEM)
    assert p.id_djen == 648563178
    assert p.data_disponibilizacao == "2026-06-23"
    assert p.tipo_comunicacao == "Intimação"
    assert p.sigla_tribunal == "TJSP"
    assert p.hash_unico == "mMg9oWrBZ9XspqVcjTpDEav6zwDv82"
    assert len(p.destinatarios) == 1
    assert len(p.advogados) == 1


def test_data_br_format_pt():
    # data em dd/mm/aaaa deve virar ISO no parser
    item = dict(_ITEM, data_disponibilizacao="23/06/2026")
    assert parse_item(item).data_disponibilizacao == "2026-06-23"


def test_hash_fallback_sem_campo_hash():
    item = {k: v for k, v in _ITEM.items() if k != "hash"}
    p = parse_item(item)
    assert p.hash_unico and len(p.hash_unico) == 64  # sha256 hex


def test_parse_lista():
    assert len(parse_lista([_ITEM, _ITEM])) == 2
