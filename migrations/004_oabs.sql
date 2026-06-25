-- ============================================================================
-- Migration 004: OABs monitoradas (sync DJEN por advogado, em lote)
-- Rodar no SQL Editor do Supabase (depois da 003).
-- ============================================================================

create table if not exists promad_oabs (
  id         uuid primary key default gen_random_uuid(),
  numero     text not null,            -- número da OAB (só dígitos)
  uf         text not null,            -- UF da OAB (ex.: 'SP')
  nome       text,                     -- nome do advogado (opcional)
  ativo      boolean default true,
  created_at timestamptz default now(),
  unique (numero, uf)
);
