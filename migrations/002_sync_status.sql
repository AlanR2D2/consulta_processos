-- ============================================================================
-- Migration 002: status da última sincronização por processo
-- Rodar no SQL Editor do Supabase (depois da 001).
-- ============================================================================

alter table promad_processos
  add column if not exists ultimo_sync_status  text,   -- ok | sigiloso | sem_dados | erro
  add column if not exists ultimo_sync_detalhe text;   -- mensagem (sigilo/erro), quando houver
