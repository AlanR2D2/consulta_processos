-- ============================================================================
-- Monitor de Processos Judiciais — DataJud → Supabase
-- Migration 001: schema inicial (4 tabelas)
-- Rodar uma vez no SQL Editor do Supabase.
-- Schema enriquecido com a capa real do _source da API DataJud.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Tribunais — referência de roteamento (seed via scripts/seed_tribunais.py)
-- ----------------------------------------------------------------------------
create table if not exists promad_tribunais (
  alias      text primary key,            -- ex.: 'tjsp'
  nome       text not null,
  segmento   text not null,               -- estadual|federal|trabalho|eleitoral|militar|superior
  codigo_j   smallint,                     -- segmento (1..9)
  codigo_tr  smallint,                     -- tribunal dentro do segmento
  ativo      boolean default true
);

-- ----------------------------------------------------------------------------
-- Processos monitorados (capa processual)
-- ----------------------------------------------------------------------------
create table if not exists promad_processos (
  id                       uuid primary key default gen_random_uuid(),
  numero_cnj               text not null unique,        -- 20 dígitos, sem máscara
  numero_formatado         text,                        -- com máscara, para exibição
  tribunal_alias           text references promad_tribunais(alias),
  cliente_id               uuid,                        -- dono/cliente (ajustar à app)

  -- Capa (preenchida a partir do _source do DataJud)
  classe_codigo            integer,
  classe_nome              text,
  assunto_principal        text,
  orgao_julgador           text,
  grau                     text,                        -- ex.: 'G1', 'G2'
  sistema                  text,                        -- ex.: 'Pje'
  formato                  text,                        -- ex.: 'Eletrônico'
  nivel_sigilo             smallint,                    -- 0 = público
  data_ajuizamento         timestamptz,

  status                   text default 'ativo',
  ultima_sincronizacao     timestamptz,
  ultima_movimentacao_data timestamptz,
  ativo                    boolean default true,
  created_at               timestamptz default now(),
  updated_at               timestamptz default now()
);
create index if not exists idx_processos_ativo on promad_processos (ativo) where ativo = true;

-- ----------------------------------------------------------------------------
-- Movimentações (andamentos) — idempotência via hash_unico
-- ----------------------------------------------------------------------------
create table if not exists promad_movimentacoes (
  id               uuid primary key default gen_random_uuid(),
  processo_id      uuid not null references promad_processos(id) on delete cascade,
  codigo_movimento integer,
  nome_movimento   text,
  data_movimento   timestamptz,
  complementos     jsonb,                       -- complementosTabelados do DataJud
  hash_unico       text not null,               -- sha256(numero_cnj + codigo + dataHora + nome)
  created_at       timestamptz default now(),
  unique (processo_id, hash_unico)              -- garante upsert idempotente
);
create index if not exists idx_mov_processo
  on promad_movimentacoes (processo_id, data_movimento desc);

-- ----------------------------------------------------------------------------
-- Log de execuções da sincronização (observabilidade)
-- ----------------------------------------------------------------------------
create table if not exists promad_sync_runs (
  id                    uuid primary key default gen_random_uuid(),
  started_at            timestamptz default now(),
  finished_at           timestamptz,
  processos_consultados integer default 0,
  movimentacoes_novas   integer default 0,
  erros                 integer default 0,
  detalhe_erros         jsonb,
  status                text default 'running'  -- running|success|partial|failed
);
