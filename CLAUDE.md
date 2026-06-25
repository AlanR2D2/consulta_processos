# Monitor de Processos Judiciais — DataJud → Supabase

Sistema em Python que monitora processos judiciais cadastrados, consultando
periodicamente a **API Pública do DataJud (CNJ)**, detectando novas movimentações
e persistindo tudo no **Supabase**. Sem scraping de portais e sem certificado digital:
trabalha apenas com metadados públicos (capa processual + movimentações).

> Nome de repositório sugerido: `monitor-processos-datajud` (ajuste à vontade).

---

## ⚠️ INSTRUÇÃO PERMANENTE PARA O AGENTE

**Este arquivo (`CLAUDE.md`) é a fonte de verdade do projeto. Mantenha-o sempre atualizado.**

Sempre que você (agente) fizer qualquer uma destas coisas, atualize este arquivo **na mesma tarefa, antes de finalizar**:

- Criar, renomear ou remover um módulo/arquivo → atualizar a seção **Estrutura de arquivos**
- Alterar o schema do banco → atualizar a seção **Modelo de dados (Supabase)**
- Mudar um comando de execução/setup → atualizar a seção **Como rodar**
- Tomar uma decisão técnica relevante (escolha de lib, padrão, trade-off) → registrar em **Decisões técnicas**
- Concluir ou repriorizar um item → atualizar **Estado atual** e **Roadmap**
- Qualquer mudança → adicionar uma entrada datada no **Changelog**

Não deixe o `CLAUDE.md` divergir do código. Se notar divergência, corrija o arquivo antes de prosseguir. O objetivo é que **outro agente leia este arquivo do topo e continue o trabalho em minutos**.

---

## 🚀 Para o próximo agente: comece aqui

1. Leia este arquivo inteiro (especialmente **Estado atual** no fim).
2. Confirme que existe um `.env` na raiz com as variáveis listadas em **Variáveis de ambiente**. As credenciais reais ficam no `.env` (não versionado); há um `.env.example` como referência.
3. Rode o setup (**Como rodar**) e execute uma sincronização de teste.
4. Veja o **Roadmap** para o próximo passo pendente.
5. Ao terminar qualquer mudança, atualize este arquivo (ver instrução permanente acima).

---

## Visão geral

**Objetivo:** dado um conjunto de processos cadastrados (por número único CNJ), consultar
o DataJud em intervalos regulares, identificar movimentações novas e gravá-las no Supabase,
permitindo que a aplicação/cliente seja notificada das atualizações.

**Escopo (o que ESTÁ no projeto):**
- Consulta de metadados públicos via API DataJud (capa + movimentações).
- Roteamento automático do número CNJ para o tribunal correto.
- Deduplicação e persistência idempotente no Supabase.
- Observabilidade básica (log de execuções e erros por processo).

**Fora de escopo (NÃO fazer):**
- Scraping de portais (PJe, e-SAJ, eproc, Projudi).
- Acesso a autos restritos, processos em segredo de justiça ou peticionamento (exigiriam certificado digital A3 / gov.br — não é o caso aqui).
- Scraping de portais/PJe para autos restritos. (Publicações/intimações públicas **estão** no escopo via API do DJEN/Comunica — ver `src/djen/`.)

---

## Arquitetura e fluxo de dados

```
┌─────────────┐     1. lê processos ativos      ┌──────────────────┐
│  Supabase   │ ──────────────────────────────▶ │   Sincronizador  │
│ (Postgres)  │                                  │     (Python)     │
│             │ ◀── 4. upsert movimentações ──── │                  │
└─────────────┘                                  └────────┬─────────┘
                                                          │ 2. roteia nº CNJ → endpoint
                                                          │ 3. consulta (POST + paginação)
                                                          ▼
                                              ┌───────────────────────┐
                                              │  API Pública DataJud   │
                                              │ api-publica.datajud... │
                                              └───────────────────────┘
```

**Ciclo de sincronização (`services/sincronizador.py`):**
1. Buscar no Supabase os processos com `ativo = true`, em lotes (`SYNC_BATCH_SIZE`).
2. Para cada processo, derivar o `alias` do tribunal a partir do número CNJ (ver **Roteamento**).
3. Consultar o endpoint do tribunal (POST, autenticado, com paginação `search_after`).
4. Normalizar as movimentações, calcular hash de cada uma e fazer `upsert` (ignora as já existentes).
5. Atualizar `processos.ultima_sincronizacao` e, se houver, `ultima_movimentacao_data`.
6. Registrar a execução em `sync_runs` (totais, erros, status).

---

## Fonte de dados: API Pública DataJud (CNJ)

- **Base URL:** `https://api-publica.datajud.cnj.jus.br`
- **Endpoint por tribunal:** `{BASE}/api_publica_{alias}/_search` — método **POST**, corpo JSON (Elasticsearch DSL).
- **Autenticação:** header `Authorization: APIKey <chave>`. É uma **chave pública única e compartilhada** (não é MFA, não é por usuário).
  - A chave **pode ser rotacionada pelo CNJ a qualquer momento**. **Não hardcode.** Guarde em `DATAJUD_API_KEY` no `.env` e documente a fonte: `https://datajud-wiki.cnj.jus.br/api-publica/acesso`.
- **Cobertura:** ~91 tribunais. Retorna capa processual e movimentações; respeita sigilo (processos sigilosos não retornam conteúdo).
- **Não é tempo real:** os tribunais alimentam o DataJud periodicamente. Defina a frequência de sincronização levando isso em conta (ex.: 1–2x/dia já é suficiente).
- **Busca por número:** a consulta é feita pelo `numeroProcesso` (20 dígitos, sem máscara). CPF/CNPJ **não** são campos pesquisáveis na API pública.

### Roteamento: número CNJ → alias do tribunal

Formato do número único: `NNNNNNN-DD.AAAA.J.TR.OOOO`
- **J** (1 dígito) = segmento do Judiciário
- **TR** (2 dígitos) = tribunal dentro do segmento

Regra de mapeamento a implementar em `datajud/endpoints.py`:

| J | Segmento | Regra de alias |
|---|----------|----------------|
| 3 | STJ | `stj` (TR = 00) |
| 4 | Justiça Federal | `trf{int(TR)}` → trf1..trf6 |
| 5 | Justiça do Trabalho | `trt{int(TR)}` → trt1..trt24 (TR=00 → `tst`) |
| 6 | Justiça Eleitoral | `tre-{uf}` (mapear TR→UF; TR=00 → `tse`) |
| 7 | Justiça Militar da União | `stm` |
| 8 | Justiça Estadual | tabela TR→TJ (abaixo) |
| 9 | Justiça Militar Estadual | `tjmmg` (13), `tjmrs` (21), `tjmsp` (26) |
| 1 | STF | **não disponível** na API pública — tratar como exceção/log |

**Tabela J=8 (Justiça Estadual)** — ponto de partida, **CONFIRMAR contra a Resolução CNJ 65/2008 e a lista oficial de endpoints** antes de confiar 100%:

```
01 tjac  02 tjal  03 tjap  04 tjam  05 tjba  06 tjce  07 tjdft
08 tjes  09 tjgo  10 tjma  11 tjmt  12 tjms  13 tjmg  14 tjpa
15 tjpb  16 tjpr  17 tjpe  18 tjpi  19 tjrj  20 tjrn  21 tjrs
22 tjro  23 tjrr  24 tjsc  25 tjse  26 tjsp  27 tjto
```

> **Recomendado:** materializar esse mapa na tabela `tribunais` do Supabase (seed via `scripts/seed_tribunais.py`) e ler de lá, em vez de manter o dicionário só em código. Assim a fonte de verdade do roteamento fica versionada no banco e auditável.

---

## Modelo de dados (Supabase)

DDL inicial (rodar como migration no Supabase). Ajuste tipos/colunas conforme necessário e **atualize esta seção se mudar**.

> **Prefixo de tabelas:** todas as tabelas usam o prefixo **`promad_`** (`promad_tribunais`,
> `promad_processos`, `promad_movimentacoes`, `promad_sync_runs`). A fonte de verdade do DDL é
> [`migrations/001_init.sql`](migrations/001_init.sql); o bloco abaixo é ilustrativo.

```sql
-- Tabela de referência dos tribunais (seed a partir da lista oficial)
create table promad_tribunais (
  alias          text primary key,          -- ex.: 'tjsp'
  nome           text not null,
  segmento       text not null,             -- 'estadual' | 'federal' | 'trabalho' | 'eleitoral' | 'militar' | 'superior'
  codigo_j       smallint,                  -- segmento (1..9)
  codigo_tr      smallint,                  -- tribunal dentro do segmento
  ativo          boolean default true
);

-- Processos monitorados (capa enriquecida a partir do _source real do DataJud)
create table promad_processos (
  id                       uuid primary key default gen_random_uuid(),
  numero_cnj               text not null unique,        -- 20 dígitos, sem máscara
  numero_formatado         text,                        -- com máscara, para exibição
  tribunal_alias           text references promad_tribunais(alias),
  cliente_id               uuid,                        -- dono/cliente (ajustar à sua app)
  -- Capa (preenchida na sincronização)
  classe_codigo            integer,
  classe_nome              text,
  assunto_principal        text,
  orgao_julgador           text,
  grau                     text,                        -- 'G1', 'G2', ...
  sistema                  text,                        -- ex.: 'Pje'
  formato                  text,                        -- ex.: 'Eletrônico'
  nivel_sigilo             smallint,                    -- 0 = público
  data_ajuizamento         timestamptz,
  status                   text default 'ativo',
  ultimo_sync_status       text,                        -- ok|sigiloso|sem_dados|erro (migration 002)
  ultimo_sync_detalhe      text,                        -- mensagem de sigilo/erro (migration 002)
  ultima_sincronizacao     timestamptz,
  ultima_movimentacao_data timestamptz,
  ativo                    boolean default true,
  created_at               timestamptz default now(),
  updated_at               timestamptz default now()
);
create index idx_processos_ativo on promad_processos (ativo) where ativo = true;

-- Movimentações (andamentos) — idempotência via hash_unico
create table promad_movimentacoes (
  id              uuid primary key default gen_random_uuid(),
  processo_id     uuid not null references promad_processos(id) on delete cascade,
  codigo_movimento integer,
  nome_movimento  text,
  data_movimento  timestamptz,
  complementos    jsonb,
  hash_unico      text not null,            -- sha256(numero_cnj + codigo + dataHora + nome)
  created_at      timestamptz default now(),
  unique (processo_id, hash_unico)          -- garante upsert idempotente
);
create index idx_mov_processo on promad_movimentacoes (processo_id, data_movimento desc);

-- Log de execuções da sincronização (observabilidade)
create table promad_sync_runs (
  id                    uuid primary key default gen_random_uuid(),
  started_at            timestamptz default now(),
  finished_at           timestamptz,
  processos_consultados integer default 0,
  movimentacoes_novas   integer default 0,
  erros                 integer default 0,
  detalhe_erros         jsonb,
  status                text default 'running'  -- 'running' | 'success' | 'partial' | 'failed'
);
```

**Observações de segurança:**
- O backend usa a **service_role key** (`SUPABASE_SERVICE_KEY`), que **ignora RLS** — por isso o extrator roda apenas server-side, nunca no cliente.
- Se a app/cliente for ler essas tabelas, ative **RLS** e crie policies por `cliente_id`.

---

## Variáveis de ambiente (`.env` na raiz)

Carregar com `python-dotenv`. **Nunca** versionar o `.env`; manter `.env.example` versionado e `.env` no `.gitignore`.

```dotenv
# Supabase
SUPABASE_URL=
SUPABASE_SERVICE_KEY=        # service_role — somente backend (ignora RLS)

# DataJud (CNJ)
DATAJUD_API_KEY=             # chave pública atual (base64). Fonte: datajud-wiki.cnj.jus.br/api-publica/acesso
DATAJUD_BASE_URL=https://api-publica.datajud.cnj.jus.br

# Execução
LOG_LEVEL=INFO
SYNC_BATCH_SIZE=50
REQUEST_TIMEOUT=30
MAX_RETRIES=3
```

---

## Estrutura de arquivos

> **Manter atualizada.** Estrutura atual (criada em 2026-06-22):

```
.
├── CLAUDE.md                 # este arquivo (instruções + contexto vivo)
├── README.md                 # instruções para humanos
├── .env                      # NÃO versionar (já tem credenciais Supabase + DataJud)
├── .env.example
├── .gitignore
├── requirements.txt          # versões fixadas (inclui gunicorn p/ prod)
├── pyproject.toml            # config Ruff + pytest (pythonpath = ".")
├── Dockerfile                # imagem prod (gunicorn) — src/web:app
├── docker-compose.yml        # deploy (porta/bind via WEB_PORT/WEB_BIND no .env)
├── .dockerignore
├── migrations/
│   ├── 001_init.sql          # DDL das 4 tabelas (rodar no SQL Editor do Supabase)
│   ├── 002_sync_status.sql   # + colunas ultimo_sync_status / ultimo_sync_detalhe
│   ├── 003_djen.sql          # tabela promad_publicacoes_djen + coluna ultima_publicacao_data
│   └── 004_oabs.sql          # tabela promad_oabs (OABs monitoradas p/ sync DJEN em lote)
├── src/
│   ├── config.py             # carrega .env; aceita SUPABASE_KEY|SUPABASE_SERVICE_KEY
│   ├── formato.py            # data_br(): ISO/UTC → dd/mm/aaaa HH:MM:SS (fuso São Paulo)
│   ├── supabase_client.py    # cliente Supabase singleton (lru_cache)
│   ├── datajud/
│   │   ├── client.py         # auth APIKey, POST _search, paginação search_after, retry/backoff
│   │   ├── endpoints.py      # roteamento J+TR → alias; listar_todos_tribunais() (seed)
│   │   └── parser.py         # _source → capa + movimentações normalizadas + hash; consolidar()
│   ├── djen/                 # fonte complementar: publicações/intimações (DJEN/Comunica CNJ)
│   │   ├── client.py         # GET comunicaapi.pje.jus.br (consulta pública por nº processo)
│   │   └── parser.py         # item DJEN → Publicacao normalizada + hash
│   ├── repository/
│   │   ├── processos.py      # CRUD + capa/sync/status + filtros/resumo + derivar_status + mapear_por_numero
│   │   ├── movimentacoes.py  # upsert idempotente (conta movimentações novas)
│   │   ├── publicacoes.py    # upsert idempotente das publicações DJEN
│   │   └── oabs.py           # CRUD das OABs monitoradas + seed a partir das publicações
│   ├── services/
│   │   └── sincronizador.py  # orquestra o ciclo + grava sync_runs
│   ├── main.py               # CLI: add / importar / list / sync / seed
│   └── web.py                # app Flask: dashboard + endpoints (add/sync-em-background/movimentações)
├── scripts/
│   ├── seed_tribunais.py     # popula a tabela tribunais (91 registros)
│   └── run_periodico.py      # agendador local: roda sync em loop (intervalo configurável)
└── tests/
    ├── test_endpoints.py     # roteamento J+TR + contagem de 91 tribunais
    ├── test_parser.py        # normalização da capa + estabilidade do hash + consolidar
    └── test_idempotencia.py  # upsert não duplica (fake do cliente Supabase)
```

---

## Como rodar

> **Manter atualizada** se os comandos mudarem.

```bash
# 1. Ambiente
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2. Configuração — o .env já tem SUPABASE_URL/SUPABASE_KEY/DATAJUD_API_KEY.
#    (Para um novo ambiente: cp .env.example .env e preencher.)

# 3. Criar as tabelas (uma vez), colando no SQL Editor do Supabase, na ordem:
#    001_init.sql → 002_sync_status.sql → 003_djen.sql → 004_oabs.sql

# 4. Seed dos tribunais (uma vez, após criar as tabelas)
python -m scripts.seed_tribunais        # ou: python -m src.main seed

# 5. Cadastrar um processo (ou vários de uma vez a partir de um arquivo)
python -m src.main add 0001234-56.2023.8.26.0100   # aceita com ou sem máscara
python -m src.main importar processos.md            # 1 número CNJ por linha (upsert em lote)

# 6. Rodar uma sincronização de movimentos (DataJud, em lote)
python -m src.main sync

# (As publicações/intimações do DJEN são buscadas POR PROCESSO, junto do sync —
#  ver web "Atualizar TODOS" e o sync unitário. Não exige cadastro de OAB.)

# 7. Listar processos monitorados
python -m src.main list

# Testes / lint
python -m pytest
ruff check . && ruff format --check .
```

**Interface web (localhost):** app Flask em `src/web.py`. Roda no ambiente conda `promad`.
```bash
conda activate promad
python -m src.web        # http://127.0.0.1:5001  (host/porta via FLASK_HOST/FLASK_PORT no .env)
```
Rotas: `GET /` (dashboard paginado, 50/página, com coluna de Status), `POST /processos`
(cadastra **1** processo — campo de texto), `POST /sync` (sincroniza **TODOS**; **background**,
responde 202), `GET /sync/status` (estado do sync geral), `GET /processos/<id>/movimentacoes`
(página do processo: status + botão "Atualizar este processo"; `?format=json` para JSON das
movimentações), `POST /processos/<id>/sync` (sync **unitário**, síncrono), `GET /health`.
Status por processo é **derivado da presença real de dados** (`derivar_status()`), não da string
salva: `com_dados` (≥1 movimentação) | `sem_dados` (sincronizado, 0 mov.) | `sigilo`
(`nivel_sigilo>0`) | `nao_sync` (nunca sincronizado). Exibido na lista e na página do processo.
O dashboard tem **cards** clicáveis (Com dados / Sem dados / Sigilo / Não sincronizados / Total —
`com_dados+sem_dados+nao_sync = total`) e **filtros** por número, tribunal, classe e status
(server-side, preservados na paginação). Repo: `derivar_status()`, `resumo_status()`,
`listar_filtrado()`, `contar_filtrado()`, `_filtrar_status()`.

**Agendamento local (dev/teste):** loop simples na própria máquina, sem cron/Actions:
```bash
python -m scripts.run_periodico                  # padrão: a cada 12h
python -m scripts.run_periodico --intervalo 8 --ciclos 2   # demo: 2 ciclos, 8s
```

**Agendamento (produção):** Task Scheduler (Windows), cron, GitHub Actions (schedule) ou n8n
chamando `python -m src.main sync`. Exemplo cron (2x/dia):
```cron
0 8,18 * * * cd /caminho/projeto && .venv/bin/python -m src.main sync >> sync.log 2>&1
```

### Deploy com Docker (servidor)

`Dockerfile` (gunicorn) + `docker-compose.yml`. A app web **não tem autenticação**, então o
compose publica só em `127.0.0.1:${WEB_PORT}` por padrão — acesse via túnel SSH ou atrás de um
reverse proxy com auth. Ajuste `WEB_PORT` no `.env` para uma porta livre (não conflitar com n8n).

```bash
# No servidor, em ~/consulta_processos:
git pull                       # ou clonar o repo
cp .env.example .env           # e preencher SUPABASE_*/DATAJUD_* + WEB_PORT/WEB_BIND
docker compose up -d --build   # sobe o container 'consulta_processos_web'
docker compose logs -f         # acompanhar
# Acesso local/túnel:  http://127.0.0.1:${WEB_PORT}
# Túnel SSH a partir da sua máquina:  ssh -L 8090:127.0.0.1:8090 root@SERVIDOR
```

`migrations/` ficam disponíveis no container, mas as tabelas são criadas uma vez no Supabase
(SQL Editor). A rede do compose é isolada (bridge própria) — não interfere no n8n.

---

## Convenções de código

- **Python 3.11+**, type hints em tudo, funções pequenas e testáveis.
- **Lint/format:** Ruff (lint + format). Fixar a versão do Ruff no `requirements.txt`/`pyproject.toml` para evitar quebra de CI por bump de versão.
- **Logging estruturado** (módulo `logging`), nível via `LOG_LEVEL`. Nunca logar a `SUPABASE_SERVICE_KEY` nem a `DATAJUD_API_KEY`.
- **Sem segredos no código.** Tudo via `config.py`/`.env`.
- **Idempotência:** toda gravação de movimentação passa por `upsert` com `hash_unico`. Rodar `sync` N vezes não pode duplicar dados.
- **Resiliência:** retry com backoff exponencial em erros de rede/5xx/429; respeitar rate limit; timeouts explícitos.
- **Isolamento de falhas:** erro em um processo não derruba o lote — capturar, registrar em `detalhe_erros` e seguir.

---

## Tratamento de casos especiais

- **Processo sigiloso / segredo de justiça:** a API pode retornar vazio ou sem movimentações. Tratar como resultado válido (não como erro); marcar o processo adequadamente.
- **Número inválido / segmento não suportado (ex.: STF):** validar o número CNJ antes de consultar; se não houver endpoint, registrar e pular.
- **429 / rate limit:** backoff + reduzir `SYNC_BATCH_SIZE`. Considerar pausa entre requisições.
- **Mudança de chave do DataJud (401/403):** logar de forma clara orientando a atualizar `DATAJUD_API_KEY` a partir da wiki do CNJ.
- **Paginação:** usar `search_after` do Elasticsearch para processos com muitas movimentações.

## Limitações conhecidas

- **DataJud não é tempo real** — há defasagem na alimentação pelos tribunais.
- **Publicações/intimações (DJe)** — o DataJud **não** traz o conteúdo das intimações que geram prazo. Por isso foi adicionada a fonte complementar **DJEN/Comunica** (ver `src/djen/`), que traz essas publicações quase em tempo real. O DataJud segue como fonte dos movimentos processuais (TPU), mas é defasado para processos novos.
- **Cobertura variável** — alguns tribunais alimentam a base com menos frequência/completude.

---

## Decisões técnicas (ADR-lite)

> Registrar aqui cada decisão relevante: data, decisão, motivo.

- **2026-06-22** — Fonte única = API DataJud (sem scraping). *Motivo:* dados públicos padronizados, sem certificado, sem manutenção frágil de 27 scrapers; cobre o caso de uso (andamentos públicos).
- **2026-06-22** — Idempotência via `hash_unico` + `unique(processo_id, hash_unico)`. *Motivo:* permitir sincronizações repetidas sem duplicar movimentações.
- **2026-06-22** — Roteamento J+TR→alias materializado na tabela `tribunais`. *Motivo:* fonte de verdade versionada e auditável no banco.
- **2026-06-22** — `config.py` aceita `SUPABASE_KEY` **ou** `SUPABASE_SERVICE_KEY`. *Motivo:* o `.env` real do projeto já usava `SUPABASE_KEY` (service_role); evitar quebra mantendo compat com o nome do CLAUDE.md.
- **2026-06-22** — `DATAJUD_API_KEY` com fallback embutido para a chave pública conhecida do CNJ. *Motivo:* é uma chave pública compartilhada; fallback evita falha de config, mas o `.env` ainda manda. Fonte: `datajud-wiki.cnj.jus.br/api-publica/acesso`.
- **2026-06-22** — Consulta DataJud ordena só por `@timestamp` (sem `_id`). *Motivo:* o índice ES do DataJud bloqueia fielddata em `_id` (HTTP 400); para 1 processo cabe em uma página.
- **2026-06-23** — Sincronização **em lote por tribunal** via query `terms` (`client.buscar_lote`), chunks de 50. *Motivo:* a API é Elasticsearch e aceita `terms` com vários `numeroProcesso` numa requisição, mas cada tribunal tem endpoint próprio; agrupar por alias reduz ~13k requisições para ~266. Respostas em lote são pesadas → `_BULK_TIMEOUT=120s` e chunk pequeno para evitar timeout. Validado ao vivo (30 TJSP → 653 movimentações; 2ª passada = 0).
- **2026-06-23** — Status por processo (`ultimo_sync_status`/`ultimo_sync_detalhe`, migration 002) + sync **unitário** (`sincronizar_um`, rota `POST /processos/<id>/sync`). *Motivo:* o usuário pediu atualizar 1 processo isolado e ver sigilo/erro tanto no unitário quanto no geral. `repository.processos.marcar_status` é **resiliente**: se a migration 002 não foi aplicada, avisa e segue sem quebrar o sync (status persiste só após a migration; o feedback imediato no unitário independe dela).
- **2026-06-23** — `src/formato.py::data_br()` formata datas para exibição (ISO/UTC → `dd/mm/aaaa HH:MM:SS` no fuso de São Paulo), aplicado na web e na CLI `list`. *Motivo:* as datas vinham em ISO/UTC; usuário pediu pt-BR no horário de SP. Usa `zoneinfo` (dep `tzdata` p/ Windows) com fallback fixo UTC-3 (Brasil sem DST desde 2019).
- **2026-06-23** — Dashboard ganhou **cards de resumo** e **filtros** server-side (número, tribunal, classe, status), preservados na paginação. Contagens via `count='exact'`; filtros na query Supabase (`listar_filtrado`/`contar_filtrado`). Cards são links que aplicam o filtro.
- **2026-06-25** — **Docker/compose para deploy**: `Dockerfile` (python:3.12-slim + gunicorn, 1 worker/4 threads, serve `src.web:app`), `docker-compose.yml` (publica só em `127.0.0.1:${WEB_PORT}` por padrão pois a app não tem auth; rede bridge isolada p/ não afetar o n8n), `.dockerignore`. `gunicorn` no requirements. Deploy: `docker compose up -d --build` em `~/consulta_processos` no servidor.
- **2026-06-25** — **DJEN da carteira volta a ser POR PROCESSO** (sem exigir gestão de OAB). *Motivo:* a busca por OAB traz tudo do advogado (inclusive parte contrária / processos fora da carteira → ~28k "não cadastrados" no teste) e exige o usuário curar uma lista de OABs. Para uma **carteira fechada**, o DJEN por processo é direcionado e sem responsabilidade extra. Web "Atualizar TODOS" = `sincronizar(incluir_djen=True)` (DataJud em lote + DJEN por processo, em background). A infra de OAB (`sincronizar_djen_por_oab`, `repository/oabs.py`, `promad_oabs`/migration 004, CLI `oab`/`sync-djen`) **fica como opcional/avançada** — útil p/ descobrir processos novos da OAB, fora do escopo da carteira; não é mais surfada na UI.
- **2026-06-25** — (revertido no mesmo dia) Sync DJEN em lote por OAB (`sincronizar_djen_por_oab`) + tabela `promad_oabs`. Validado tecnicamente (OAB 516085/SP = 583 pub/87 processos em ~6 req), mas trazia ruído e responsabilidade — ver entrada acima.
- **2026-06-24** — **DJEN/Comunica como 2ª fonte** (complementar ao DataJud): `src/djen/` (client+parser), `repository/publicacoes.py`, tabela `promad_publicacoes_djen` + coluna `ultima_publicacao_data` (migration 003). Integrado no sync unitário e geral (`incluir_djen`). *Motivo:* o DataJud é defasado e não traz intimações/publicações; processos novos apareciam "sem dados" embora tivessem publicações no DJEN (confirmado ao vivo: `4000485-92.2026.8.26.0430` = 0 no DataJud, 2 no DJEN). API pública `comunicaapi.pje.jus.br`, sem auth, por número de processo. `derivar_status` passou a contar **com_dados = movimentação OU publicação**. Resiliente se a migration 003 não estiver aplicada.
- **2026-06-23** — Status passou a ser **derivado de colunas reais** (`derivar_status`/`_filtrar_status`), não da string `ultimo_sync_status`. *Motivo:* processos sincronizados antes do campo de status existir ficavam `null` e apareciam como "não sincronizado" mesmo tendo movimentações. Agora: `com_dados` = `ultima_movimentacao_data` not null; `sem_dados` = sincronizado sem movimentação; `sigilo` = `nivel_sigilo>0`; `nao_sync` = sem `ultima_sincronizacao`. Validado: 11.909 com dados / 1.260 sem / 104 não sincronizados / 13.273 total.
- **2026-06-22** — Capa de `processos` enriquecida (classe, assunto, órgão, grau, sistema, formato, nível de sigilo, data de ajuizamento). *Motivo:* a estrutura real do `_source` (verificada na wiki/exemplos) traz esses metadados úteis.
- **2026-06-23** — `parser.normalizar_data()` converte datas compactas para ISO 8601. *Motivo:* na API real, `dataAjuizamento` vem como `yyyyMMddHHmmss` (ex.: `20170821100532`), que o Postgres rejeita em `timestamptz` (erro 22008). ISO passa inalterado, preservando hashes existentes.
- **2026-06-23** — `configure_logging()` força UTF-8 em stdout/stderr. *Motivo:* console Windows (cp1252) levantava `UnicodeEncodeError` ao imprimir `→` no comando `add`.

---

## Roadmap

> Marcar `[x]` ao concluir e atualizar **Estado atual**.

- [x] Scaffolding inicial do projeto (estrutura de pastas, `config.py`, clients)
- [x] `datajud/client.py` com auth, POST, paginação e retry
- [x] `datajud/endpoints.py` com roteamento J+TR→alias (validado contra lista oficial de endpoints)
- [x] Migrations do Supabase (4 tabelas) + `seed_tribunais.py`
- [x] `parser.py` (normalização + hash) e `repository/` (upsert)
- [x] `sincronizador.py` (ciclo completo) e `main.py` (CLI)
- [x] Testes unitários (roteamento, parser, idempotência) — 24 testes passando
- [ ] Agendamento (cron/Actions/n8n)
- [ ] (Futuro) Notificação de novas movimentações (webhook/n8n)

---

## Estado atual

> **Atualizar a cada sessão de trabalho.**

- **Status:** projeto completo e **validado end-to-end contra o Supabase real**. Operacional.
- **Feito:** todo o código + migration + testes (26 passando) + lint limpo. Tabelas criadas no
  Supabase (prefixo `promad_`). Fluxo completo testado ao vivo: `seed` (91 tribunais) → `add`
  (TJDFT `0722391-40.2017.8.07.0001`) → `sync` (55 movimentações gravadas, capa preenchida) →
  `sync` novamente (0 novas = idempotência confirmada) → `list`. Verificado no banco: 55 linhas
  em `promad_movimentacoes`, capa completa, `promad_sync_runs` registrando execuções.
- **Em andamento:** nada.
- **Próximo passo:** definir agendamento de produção (cron/Actions/n8n) e cadastrar a carteira
  real de processos. (Opcional) notificação de novas movimentações.
- **Pendências/dúvidas em aberto:**
  - Confirmar a **ordenação TR→UF da Justiça Eleitoral (J=6)** contra a fonte oficial — foi
    assumida igual à estadual (alfabética); a estadual (J=8) está confirmada. Ver `endpoints.py`.
  - Definir agendamento de produção (cron/Actions/n8n).

---

## Changelog

- **2026-06-22** — Criação do `CLAUDE.md`: arquitetura, escopo, schema do Supabase, variáveis de ambiente, estrutura de arquivos, convenções e roadmap definidos.
- **2026-06-22** — Implementação completa do projeto: scaffolding, `config.py` (compat
  `SUPABASE_KEY`/`SUPABASE_SERVICE_KEY`), `supabase_client.py`, `datajud/` (client com
  retry/paginação, endpoints com roteamento J+TR validado contra a lista oficial, parser com
  consolidação multi-grau + hash), `repository/`, `sincronizador.py`, CLI `main.py`,
  `scripts/seed_tribunais.py`, `migrations/001_init.sql` (capa enriquecida), `README.md` e
  testes (24 passando). DataJud validado contra a API real; Supabase com conexão confirmada
  (faltam só as tabelas). Adicionados `DATAJUD_API_KEY`/`DATAJUD_BASE_URL` e vars de execução
  ao `.env`.
- **2026-06-23** — Tabelas renomeadas com prefixo **`promad_`** (`promad_tribunais`,
  `promad_processos`, `promad_movimentacoes`, `promad_sync_runs`) na migration e em todas as
  referências do código. *Motivo:* convivência com outras tabelas no mesmo schema Supabase.
- **2026-06-23** — Validação end-to-end contra o Supabase real: seed (91), add, sync (55
  movimentações + capa), idempotência confirmada (2º sync = 0 novas). Correções aplicadas:
  normalização de data compacta (`normalizar_data`) e UTF-8 forçado na saída da CLI. 26 testes.
- **2026-06-23** — `scripts/run_periodico.py` (agendador local em loop) e `src/web.py`
  (interface web Flask: dashboard + endpoints add/sync/movimentações). Flask adicionado ao
  `requirements.txt`. Web validada em `localhost:5001` no ambiente conda `promad`
  (`/health`, `/`, `POST /sync`, movimentações com 55 registros).
- **2026-06-23** — Importação em lote: `repository.processos.cadastrar_em_lote()` (upsert em
  chunks de 500, valida/roteia/deduplica) + comando CLI `importar <arquivo>`. Importados
  **13.272** processos de `processos.md` (103 inválidos de 12 dígitos e 1 segmento CNJ/J=2
  pulados; 1.554 duplicados no arquivo). Total no banco: 13.273.
- **2026-06-23** — Web: campo de texto passa a cadastrar **apenas 1** processo; botão
  "Atualizar TODOS" agora dispara o sync de **todos** os processos (forms separados; antes o
  botão exigia o campo `required`). Sync via web roda **em background** (thread + lock, 1 por
  vez) e o dashboard ficou **paginado** (50/página) para aguentar os 13k+ registros sem N+1.
