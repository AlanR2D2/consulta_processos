"""Entrypoint CLI: add / importar / list / sync / seed.

Uso:
    python -m src.main add 00012345620238260100
    python -m src.main importar processos.md
    python -m src.main list
    python -m src.main sync
    python -m src.main seed
"""

from __future__ import annotations

import argparse
import sys

from src.config import configure_logging
from src.datajud.endpoints import CNJInvalido, SegmentoNaoSuportado


def _cmd_add(args: argparse.Namespace) -> int:
    from src.repository import processos as repo_proc

    try:
        row = repo_proc.adicionar(args.numero, cliente_id=args.cliente_id)
    except (CNJInvalido, SegmentoNaoSuportado) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 2
    print(f"Cadastrado: {row['numero_formatado']} → {row['tribunal_alias']} (id={row['id']})")
    return 0


def _cmd_list(_args: argparse.Namespace) -> int:
    from src.formato import data_br
    from src.repository import processos as repo_proc

    rows = repo_proc.listar_todos()
    if not rows:
        print("Nenhum processo cadastrado.")
        return 0
    print(f"{'NÚMERO':<27} {'TRIBUNAL':<10} {'ÚLT. SYNC':<20} ATIVO")
    for r in rows:
        print(
            f"{(r.get('numero_formatado') or r['numero_cnj']):<27} "
            f"{(r.get('tribunal_alias') or '-'):<10} "
            f"{data_br(r.get('ultima_sincronizacao')):<20} "
            f"{r.get('ativo')}"
        )
    return 0


def _cmd_sync(_args: argparse.Namespace) -> int:
    from src.services.sincronizador import sincronizar

    resumo = sincronizar()
    print(
        f"Sync {resumo['status']}: {resumo['processos_consultados']} processo(s), "
        f"{resumo['movimentacoes_novas']} movimentação(ões) nova(s), "
        f"{resumo['erros']} erro(s)."
    )
    return 0 if resumo["status"] in ("success", "partial") else 1


def _cmd_seed(_args: argparse.Namespace) -> int:
    from scripts.seed_tribunais import seed

    total = seed()
    print(f"Seed concluído: {total} tribunais.")
    return 0


def _cmd_sync_djen(args: argparse.Namespace) -> int:
    from src.services.sincronizador import sincronizar_djen_por_oab

    resumo = sincronizar_djen_por_oab(dias=args.dias)
    print(f"DJEN por OAB: {resumo}")
    return 0


def _cmd_oab(args: argparse.Namespace) -> int:
    from src.repository import oabs as repo_oab

    if args.acao == "add":
        if not args.numero or not args.uf:
            print("Uso: oab add <numero> <uf> [--nome NOME]", file=sys.stderr)
            return 2
        row = repo_oab.adicionar(args.numero, args.uf, nome=args.nome)
        print(f"OAB cadastrada: {row['numero']}/{row['uf']}")
    elif args.acao == "list":
        for o in repo_oab.listar_ativas():
            print(f"  {o['numero']}/{o['uf']}  {o.get('nome') or ''}")
    elif args.acao == "seed":
        n = repo_oab.seed_de_publicacoes()
        print(f"OABs registradas a partir das publicações DJEN: {n}")
    return 0


def _cmd_importar(args: argparse.Namespace) -> int:
    from pathlib import Path

    from src.repository import processos as repo_proc

    arquivo = Path(args.arquivo)
    if not arquivo.is_file():
        print(f"Erro: arquivo não encontrado: {arquivo}", file=sys.stderr)
        return 2

    numeros = arquivo.read_text(encoding="utf-8").splitlines()
    res = repo_proc.cadastrar_em_lote(numeros, cliente_id=args.cliente_id)
    print(
        f"Importação de {arquivo.name}: {res['cadastrados']} cadastrado(s), "
        f"{res['duplicados']} duplicado(s), {len(res['invalidos'])} inválido(s), "
        f"{len(res['nao_suportados'])} não suportado(s) "
        f"(de {res['total_lidos']} linha(s))."
    )
    if res["invalidos"]:
        print(f"  Inválidos (amostra): {res['invalidos'][:5]}")
    if res["nao_suportados"]:
        print(f"  Não suportados (amostra): {res['nao_suportados'][:5]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="monitor-datajud")
    sub = parser.add_subparsers(dest="comando", required=True)

    p_add = sub.add_parser("add", help="Cadastra um processo pelo número CNJ.")
    p_add.add_argument("numero", help="Número CNJ (com ou sem máscara).")
    p_add.add_argument("--cliente-id", default=None, help="UUID do cliente dono.")
    p_add.set_defaults(func=_cmd_add)

    p_imp = sub.add_parser("importar", help="Cadastra processos em lote a partir de um arquivo.")
    p_imp.add_argument("arquivo", help="Arquivo texto com um número CNJ por linha.")
    p_imp.add_argument("--cliente-id", default=None, help="UUID do cliente dono.")
    p_imp.set_defaults(func=_cmd_importar)

    sub.add_parser("list", help="Lista processos monitorados.").set_defaults(func=_cmd_list)
    sub.add_parser("sync", help="Sincroniza movimentos (DataJud, em lote).").set_defaults(
        func=_cmd_sync
    )
    sub.add_parser("seed", help="Popula a tabela tribunais.").set_defaults(func=_cmd_seed)

    p_sd = sub.add_parser("sync-djen", help="Sincroniza publicações DJEN por OAB (em lote).")
    p_sd.add_argument("--dias", type=int, default=7, help="Janela de dias (padrão: 7).")
    p_sd.set_defaults(func=_cmd_sync_djen)

    p_oab = sub.add_parser("oab", help="Gerencia OABs monitoradas (add|list|seed).")
    p_oab.add_argument("acao", choices=["add", "list", "seed"])
    p_oab.add_argument("numero", nargs="?", help="Número da OAB (para add).")
    p_oab.add_argument("uf", nargs="?", help="UF da OAB (para add).")
    p_oab.add_argument("--nome", default=None, help="Nome do advogado (opcional).")
    p_oab.set_defaults(func=_cmd_oab)
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
