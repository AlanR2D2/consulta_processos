# Monitor de Processos Judiciais — DataJud → Supabase

Monitora processos judiciais consultando periodicamente a **API Pública do DataJud (CNJ)**,
detecta novas movimentações e persiste no **Supabase**, de forma idempotente.

> A documentação técnica viva do projeto está em [`CLAUDE.md`](CLAUDE.md).

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/macOS
pip install -r requirements.txt

cp .env.example .env            # e preencher SUPABASE_URL / SUPABASE_KEY
```

## Banco de dados (Supabase)

Crie as tabelas uma vez: abra o **SQL Editor** do seu projeto Supabase e cole o conteúdo de
[`migrations/001_init.sql`](migrations/001_init.sql). São 4 tabelas:
`tribunais`, `processos`, `movimentacoes`, `sync_runs`.

Depois, popule a referência de tribunais:

```bash
python -m scripts.seed_tribunais
```

## Uso (CLI)

```bash
python -m src.main add 0001234-56.2023.8.26.0100   # cadastra um processo
python -m src.main list                            # lista processos
python -m src.main sync                             # roda uma sincronização
python -m src.main seed                             # popula a tabela tribunais
```

## Agendamento (produção)

Exemplo cron (2x/dia):

```cron
0 8,18 * * * cd /caminho/projeto && .venv/bin/python -m src.main sync >> sync.log 2>&1
```

## Testes

```bash
python -m pytest        # roteamento, parser e idempotência (sem rede)
ruff check . && ruff format --check .
```

## Notas

- O backend usa a **service_role key** do Supabase (ignora RLS) — rode apenas server-side.
- A `DATAJUD_API_KEY` é uma **chave pública compartilhada** do CNJ e pode rotacionar; se a
  sincronização passar a retornar 401/403, atualize-a a partir da
  [wiki do CNJ](https://datajud-wiki.cnj.jus.br/api-publica/acesso).
- O DataJud **não é tempo real**: 1–2 sincronizações por dia costumam bastar.
