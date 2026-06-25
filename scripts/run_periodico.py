"""Agendador local: roda a sincronização em loop, num intervalo fixo.

Alternativa simples ao cron/Actions para rodar na sua máquina. Para produção
"de verdade", prefira um agendador do SO (Task Scheduler / cron) chamando
`python -m src.main sync`.

Uso:
    python -m scripts.run_periodico                 # intervalo padrão (12h)
    python -m scripts.run_periodico --intervalo 30  # a cada 30 segundos (demo)
    python -m scripts.run_periodico --ciclos 2      # roda só N ciclos e para

Interrompa com Ctrl+C.
"""

from __future__ import annotations

import argparse
import logging
import time

from src.config import configure_logging
from src.services.sincronizador import sincronizar

logger = logging.getLogger("run_periodico")

_INTERVALO_PADRAO = 12 * 60 * 60  # 12 horas


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(prog="run_periodico")
    parser.add_argument(
        "--intervalo",
        type=int,
        default=_INTERVALO_PADRAO,
        help="Segundos entre execuções (padrão: 43200 = 12h).",
    )
    parser.add_argument(
        "--ciclos",
        type=int,
        default=0,
        help="Número de ciclos a rodar (0 = infinito).",
    )
    args = parser.parse_args(argv)

    logger.info(
        "Agendador local iniciado (intervalo=%ds, ciclos=%s). Ctrl+C para parar.",
        args.intervalo,
        args.ciclos or "infinito",
    )

    ciclo = 0
    try:
        while True:
            ciclo += 1
            logger.info("─── Ciclo %d ───", ciclo)
            resumo = sincronizar()
            logger.info(
                "Ciclo %d: %s (%d processo(s), %d nova(s), %d erro(s)).",
                ciclo,
                resumo["status"],
                resumo["processos_consultados"],
                resumo["movimentacoes_novas"],
                resumo["erros"],
            )
            if args.ciclos and ciclo >= args.ciclos:
                logger.info("Atingiu %d ciclo(s); encerrando.", args.ciclos)
                break
            time.sleep(args.intervalo)
    except KeyboardInterrupt:
        logger.info("Interrompido pelo usuário. Encerrando.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
