"""Cliente Supabase singleton (usa a service_role key — somente backend)."""

from __future__ import annotations

from functools import lru_cache

from supabase import Client, create_client

from src.config import settings


@lru_cache(maxsize=1)
def get_client() -> Client:
    settings.validate()
    return create_client(settings.supabase_url, settings.supabase_key)
