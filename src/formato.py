"""Formatação de datas para exibição: ISO/UTC → horário de São Paulo (pt-BR)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

# Horário de Brasília/São Paulo. O Brasil não observa horário de verão desde 2019,
# então UTC-3 fixo é correto para datas atuais; se houver tzdata, usamos a zona IANA
# (que trata corretamente datas históricas com DST).
_FALLBACK_TZ = timezone(timedelta(hours=-3))
try:
    from zoneinfo import ZoneInfo

    _SP_TZ: timezone | ZoneInfo = ZoneInfo("America/Sao_Paulo")
except Exception:  # zoneinfo sem base de dados (ex.: Windows sem tzdata)
    _SP_TZ = _FALLBACK_TZ


def normalizar_para_iso(valor: object) -> str | None:
    """Converte datas de entrada para ISO (yyyy-mm-dd...). dd/mm/aaaa → yyyy-mm-dd.

    Valores já em ISO ou desconhecidos passam inalterados. None/vazio → None.
    """
    if valor is None or valor == "":
        return None
    s = str(valor).strip()
    if len(s) == 10 and s[2] == "/" and s[5] == "/":  # dd/mm/aaaa
        d, m, a = s.split("/")
        return f"{a}-{m}-{d}"
    return s


def data_br(valor: object, com_hora: bool = True) -> str:
    """ISO (UTC/offset) → 'dd/mm/aaaa HH:MM:SS' no fuso de São Paulo.

    None/vazio → '-'. Datas-só (yyyy-mm-dd) → 'dd/mm/aaaa' (sem conversão de fuso).
    Strings não reconhecidas voltam inalteradas.
    """
    if valor is None or valor == "":
        return "-"
    if isinstance(valor, datetime):
        dt = valor
    else:
        s = str(valor).strip()
        # Data pura (sem hora): não converte fuso para não "voltar" um dia.
        if len(s) == 10 and "T" not in s and s[4] == "-":
            try:
                d = datetime.strptime(s, "%Y-%m-%d")
                return d.strftime("%d/%m/%Y")
            except ValueError:
                return s
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            return s

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(_SP_TZ)
    return dt.strftime("%d/%m/%Y %H:%M:%S" if com_hora else "%d/%m/%Y")
