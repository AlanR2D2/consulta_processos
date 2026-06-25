"""Carrega o .env e expõe as configurações tipadas do projeto.

Nunca logar SUPABASE_KEY nem DATAJUD_API_KEY.
"""

from __future__ import annotations

import contextlib
import logging
import os
import sys
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

# Chave pública conhecida do DataJud (compartilhada, pode rotacionar).
# Fonte: https://datajud-wiki.cnj.jus.br/api-publica/acesso
_DATAJUD_PUBLIC_KEY_FALLBACK = "cDZHYzlZa0JadVREZDJCendQbXY6SkJlTzNjLV9TRENyQk1RdnFKZGRQdw=="


def _clean(value: str | None) -> str | None:
    """Remove aspas e espaços acidentais (o .env às vezes traz `KEY = 'valor'`)."""
    if value is None:
        return None
    return value.strip().strip("'").strip('"').strip()


def _get(*names: str, default: str | None = None) -> str | None:
    """Retorna o primeiro env var não-vazio entre `names`."""
    for name in names:
        val = _clean(os.getenv(name))
        if val:
            return val
    return default


@dataclass(frozen=True)
class Settings:
    supabase_url: str
    supabase_key: str
    datajud_api_key: str
    datajud_base_url: str
    log_level: str
    sync_batch_size: int
    request_timeout: int
    max_retries: int
    auth_email: str
    auth_password: str

    def validate(self) -> None:
        """Falha cedo se faltar credencial essencial do Supabase."""
        missing = [
            name
            for name, val in (
                ("SUPABASE_URL", self.supabase_url),
                ("SUPABASE_KEY/SUPABASE_SERVICE_KEY", self.supabase_key),
            )
            if not val
        ]
        if missing:
            raise RuntimeError(
                "Variáveis de ambiente faltando: " + ", ".join(missing) + ". "
                "Preencha o .env (veja .env.example)."
            )


def load_settings() -> Settings:
    return Settings(
        supabase_url=_get("SUPABASE_URL") or "",
        # Aceita tanto SUPABASE_KEY (atual) quanto SUPABASE_SERVICE_KEY (CLAUDE.md).
        supabase_key=_get("SUPABASE_SERVICE_KEY", "SUPABASE_KEY") or "",
        datajud_api_key=_get("DATAJUD_API_KEY") or _DATAJUD_PUBLIC_KEY_FALLBACK,
        datajud_base_url=_get("DATAJUD_BASE_URL") or "https://api-publica.datajud.cnj.jus.br",
        log_level=_get("LOG_LEVEL") or "INFO",
        sync_batch_size=int(_get("SYNC_BATCH_SIZE") or "50"),
        request_timeout=int(_get("REQUEST_TIMEOUT") or "30"),
        max_retries=int(_get("MAX_RETRIES") or "3"),
        auth_email=_get("AUTH_EMAIL") or "",
        auth_password=_get("AUTH_PASSWORD") or "",
    )


settings = load_settings()


def configure_logging() -> None:
    # Força UTF-8 na saída para não quebrar em consoles Windows (cp1252) com
    # acentos/setas. Sem isso, prints com '→' levantam UnicodeEncodeError.
    for stream in (sys.stdout, sys.stderr):
        reconfig = getattr(stream, "reconfigure", None)
        if reconfig:
            with contextlib.suppress(ValueError, OSError):
                reconfig(encoding="utf-8")

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    )
