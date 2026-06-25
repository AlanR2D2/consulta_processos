-- ============================================================================
-- Migration 003: publicações/intimações do DJEN (Comunica API do CNJ)
-- Fonte complementar ao DataJud (quase tempo real; traz intimações que geram prazo).
-- Rodar no SQL Editor do Supabase (depois da 001 e 002).
-- ============================================================================

create table if not exists promad_publicacoes_djen (
  id                    uuid primary key default gen_random_uuid(),
  processo_id           uuid not null references promad_processos(id) on delete cascade,
  id_djen               bigint,                  -- id da comunicação no DJEN
  numero_comunicacao    bigint,
  data_disponibilizacao timestamptz,
  tipo_comunicacao      text,                    -- ex.: 'Intimação', 'Lista de distribuição'
  tipo_documento        text,
  nome_classe           text,
  codigo_classe         integer,
  nome_orgao            text,
  sigla_tribunal        text,
  meio                  text,
  link                  text,
  texto                 text,                    -- inteiro teor da publicação
  destinatarios         jsonb,                   -- partes
  advogados             jsonb,                   -- advogados (nome/OAB)
  status                text,
  hash_unico            text not null,           -- hash do DJEN (idempotência)
  created_at            timestamptz default now(),
  unique (processo_id, hash_unico)
);
create index if not exists idx_pub_djen_processo
  on promad_publicacoes_djen (processo_id, data_disponibilizacao desc);

-- Marcador de última publicação por processo (para status "com dados").
alter table promad_processos
  add column if not exists ultima_publicacao_data timestamptz;
