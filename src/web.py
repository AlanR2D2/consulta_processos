"""Interface web (Flask) do Monitor de Processos DataJud → Supabase.

Sobe um dashboard simples em localhost para:
  - listar os processos monitorados e suas capas;
  - cadastrar um processo novo (número CNJ);
  - disparar uma sincronização manual;
  - ver as movimentações de um processo.

Config via .env (FLASK_HOST, FLASK_PORT, FLASK_SECRET_KEY, FLASK_DEBUG).

Rodar:  python -m src.web
"""

from __future__ import annotations

import logging
import os
import threading

from flask import Flask, jsonify, redirect, render_template_string, request, url_for
from markupsafe import Markup

from src.config import _clean, _get, configure_logging
from src.datajud.endpoints import CNJInvalido, SegmentoNaoSuportado
from src.formato import data_br
from src.repository import movimentacoes as repo_mov
from src.repository import processos as repo_proc
from src.repository import publicacoes as repo_pub
from src.services.sincronizador import sincronizar, sincronizar_um

configure_logging()

app = Flask(__name__)
app.secret_key = _get("FLASK_SECRET_KEY") or "dev-secret"
logger = logging.getLogger("web")

# Sincronização roda em background (são muitos processos; uma request síncrona
# travaria o navegador). Um único sync por vez.
_sync_lock = threading.Lock()
_sync_estado: dict[str, object] = {"rodando": False, "ultimo": None}


def _rodar_sync_em_background() -> None:
    try:
        # DataJud (movimentos, em lote por tribunal) + DJEN (publicações, por processo).
        # Direcionado à carteira, sem precisar gerenciar OABs.
        _sync_estado["ultimo"] = sincronizar(incluir_djen=True)
    except Exception as exc:  # nunca derruba a thread sem registrar
        logger.exception("Falha na sincronização em background: %s", exc)
        _sync_estado["ultimo"] = {"status": "failed", "erro": str(exc)}
    finally:
        _sync_estado["rodando"] = False
        _sync_lock.release()


def _iniciar_sync() -> bool:
    """Dispara o sync numa thread. Retorna False se já houver um em andamento."""
    if not _sync_lock.acquire(blocking=False):
        return False
    _sync_estado["rodando"] = True
    threading.Thread(target=_rodar_sync_em_background, daemon=True).start()
    return True

_INDEX = """
<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Monitor de Processos — DataJud</title>
  <style>
    :root { color-scheme: light dark; }
    body { font-family: system-ui, sans-serif; margin: 0; background: #0f172a; color: #e2e8f0; }
    header { background: #1e293b; padding: 1rem 1.5rem; border-bottom: 1px solid #334155; }
    h1 { font-size: 1.15rem; margin: 0; }
    main { padding: 1.5rem; max-width: 1100px; margin: 0 auto; }
    .bar { display: flex; gap: .75rem; flex-wrap: wrap; align-items: center; margin-bottom: 1.25rem; }
    input[type=text] { flex: 1; min-width: 240px; padding: .55rem .7rem; border-radius: 8px;
      border: 1px solid #475569; background: #0b1220; color: #e2e8f0; }
    button { padding: .55rem .9rem; border: 0; border-radius: 8px; cursor: pointer;
      background: #2563eb; color: #fff; font-weight: 600; }
    button.alt { background: #059669; }
    table { width: 100%; border-collapse: collapse; font-size: .9rem; }
    th, td { text-align: left; padding: .55rem .6rem; border-bottom: 1px solid #1e293b; }
    th { color: #94a3b8; font-weight: 600; }
    a { color: #60a5fa; text-decoration: none; }
    .muted { color: #94a3b8; }
    .flash { background: #166534; padding: .6rem .9rem; border-radius: 8px; margin-bottom: 1rem; }
    .pill { background: #334155; border-radius: 999px; padding: .1rem .55rem; font-size: .75rem; }
    .cards { display: flex; gap: .75rem; flex-wrap: wrap; margin: 1rem 0 1.25rem; }
    .card { background: #1e293b; border: 1px solid #334155; border-radius: 12px;
      padding: .8rem 1rem; min-width: 150px; flex: 1; }
    .card .n { font-size: 1.6rem; font-weight: 700; }
    .card .l { color: #94a3b8; font-size: .8rem; }
    .card.ok { border-left: 4px solid #22c55e; }
    .card.no { border-left: 4px solid #f59e0b; }
    .card.si { border-left: 4px solid #d97706; }
    .card.na { border-left: 4px solid #64748b; }
    .filtros { display: grid; grid-template-columns: 2fr 1fr 2fr 1.3fr auto auto;
      gap: .5rem; margin-bottom: 1rem; align-items: center; }
    .filtros input, .filtros select { padding: .45rem .55rem; border-radius: 8px;
      border: 1px solid #475569; background: #0b1220; color: #e2e8f0; min-width: 0; }
    .filtros button { padding: .45rem .7rem; }
    .filtros a.limpar { color: #94a3b8; font-size: .85rem; }
    @media (max-width: 760px) { .filtros { grid-template-columns: 1fr 1fr; } }
  </style>
</head>
<body>
  <header><h1>⚖️ Monitor de Processos Judiciais — DataJud → Supabase</h1></header>
  <main>
    {% if msg %}<div class="flash">{{ msg }}</div>{% endif %}
    {% if sync_rodando %}<div class="flash" style="background:#1d4ed8">↻ Sincronização em andamento em background…</div>{% endif %}
    <div class="bar">
      <form class="bar" style="flex:1; margin:0" method="post" action="{{ url_for('add') }}">
        <input type="text" name="numero" placeholder="Número CNJ para cadastrar (com ou sem máscara)" required>
        <button type="submit">+ Cadastrar processo</button>
      </form>
      <form method="post" action="{{ url_for('sync') }}" style="margin:0">
        <button class="alt" type="submit">↻ Atualizar TODOS os processos</button>
      </form>
    </div>
    <p class="muted">
      O campo de texto cadastra <strong>um</strong> processo. O botão verde atualiza
      <strong>todos</strong>: movimentos (DataJud) + publicações/intimações (DJEN) — direcionado
      à sua carteira, sem precisar cadastrar nada além dos processos.
    </p>

    <div class="cards">
      <a class="card ok" href="{{ url_for('index', status='com_dados') }}">
        <div class="n">{{ resumo.com_dados }}</div><div class="l">Com dados (≥1 movimentação)</div></a>
      <a class="card no" href="{{ url_for('index', status='sem_dados') }}">
        <div class="n">{{ resumo.sem_dados }}</div><div class="l">Sem dados</div></a>
      <a class="card si" href="{{ url_for('index', status='sigilo') }}">
        <div class="n">{{ resumo.sigilo }}</div><div class="l">Sigilo</div></a>
      <a class="card na" href="{{ url_for('index', status='nao_sync') }}">
        <div class="n">{{ resumo.nao_sync }}</div><div class="l">Não sincronizados</div></a>
      <a class="card" href="{{ url_for('index') }}">
        <div class="n">{{ resumo.total }}</div><div class="l">Total</div></a>
    </div>

    <form class="filtros" method="get" action="{{ url_for('index') }}">
      <input type="text" name="numero" value="{{ f.numero }}" placeholder="Filtrar nº CNJ…">
      <input type="text" name="tribunal" value="{{ f.tribunal }}" placeholder="Tribunal (ex: tjsp)">
      <input type="text" name="classe" value="{{ f.classe }}" placeholder="Classe contém…">
      <select name="status">
        <option value="" {{ 'selected' if not f.status }}>Status: todos</option>
        <option value="com_dados" {{ 'selected' if f.status=='com_dados' }}>Com dados</option>
        <option value="sem_dados" {{ 'selected' if f.status=='sem_dados' }}>Sem dados</option>
        <option value="sigilo" {{ 'selected' if f.status=='sigilo' }}>Sigilo</option>
        <option value="nao_sync" {{ 'selected' if f.status=='nao_sync' }}>Não sincronizados</option>
      </select>
      <button type="submit">Filtrar</button>
      <a class="limpar" href="{{ url_for('index') }}">Limpar</a>
    </form>

    <p class="muted">
      <strong>{{ total }}</strong> processo(s){{ ' filtrado(s)' if filtrando else ' cadastrado(s)' }} ·
      página {{ page }} de {{ paginas }} (mostrando {{ processos|length }}).
    </p>
    <table>
      <thead><tr>
        <th>Número</th><th>Tribunal</th><th>Classe</th><th>Status</th>
        <th>Últ. movimentação</th><th>Últ. sync</th>
      </tr></thead>
      <tbody>
      {% for p in processos %}
        <tr>
          <td><a href="{{ url_for('movimentacoes', processo_id=p.id) }}">{{ p.numero_formatado or p.numero_cnj }}</a></td>
          <td><span class="pill">{{ p.tribunal_alias or '-' }}</span></td>
          <td>{{ p.classe_nome or '-' }}</td>
          <td>{{ status_label(derivar_status(p)) }}</td>
          <td class="muted">{{ data_br(p.ultima_movimentacao_data) }}</td>
          <td class="muted">{{ data_br(p.ultima_sincronizacao) }}</td>
        </tr>
      {% else %}
        <tr><td colspan="6" class="muted">Nenhum processo encontrado para o filtro.</td></tr>
      {% endfor %}
      </tbody>
    </table>
    <div class="bar" style="margin-top:1rem; justify-content:center">
      {% if page > 1 %}<a href="{{ pagina_url(page-1) }}">← anterior</a>{% endif %}
      {% if page < paginas %}<a href="{{ pagina_url(page+1) }}">próxima →</a>{% endif %}
    </div>
  </main>
</body>
</html>
"""


_PER_PAGE = 50


@app.get("/")
def index():
    filtros = {
        "numero": (request.args.get("numero") or "").strip(),
        "tribunal": (request.args.get("tribunal") or "").strip(),
        "classe": (request.args.get("classe") or "").strip(),
        "status": (request.args.get("status") or "").strip(),
    }
    filtrando = any(filtros.values())

    total = repo_proc.contar_filtrado(filtros)
    paginas = max(1, (total + _PER_PAGE - 1) // _PER_PAGE)
    try:
        page = max(1, min(int(request.args.get("page", 1)), paginas))
    except ValueError:
        page = 1
    processos = repo_proc.listar_filtrado(_PER_PAGE, (page - 1) * _PER_PAGE, filtros)

    def pagina_url(p: int) -> str:
        return url_for("index", page=p, **{k: v for k, v in filtros.items() if v})

    return render_template_string(
        _INDEX,
        processos=processos,
        total=total,
        page=page,
        paginas=paginas,
        msg=request.args.get("msg"),
        sync_rodando=_sync_estado["rodando"],
        status_label=_status_label,
        data_br=data_br,
        derivar_status=repo_proc.derivar_status,
        resumo=repo_proc.resumo_status(),
        f=filtros,
        filtrando=filtrando,
        pagina_url=pagina_url,
    )


@app.post("/processos")
def add():
    numero = request.json.get("numero") if request.is_json else request.form.get("numero")
    try:
        row = repo_proc.adicionar(numero)
    except (CNJInvalido, SegmentoNaoSuportado) as exc:
        if request.is_json:
            return jsonify(erro=str(exc)), 400
        return redirect(url_for("index", msg=f"Erro: {exc}"))
    if request.is_json:
        return jsonify(row), 201
    return redirect(url_for("index", msg=f"Cadastrado: {row['numero_formatado']} → {row['tribunal_alias']}"))


@app.post("/sync")
def sync():
    iniciou = _iniciar_sync()
    if request.is_json:
        estado = "iniciado" if iniciou else "ja_em_andamento"
        return jsonify(status=estado, ultimo=_sync_estado["ultimo"]), 202
    msg = (
        "Sincronização de TODOS os processos iniciada em background. "
        "Acompanhe pelos logs / recarregue a página."
        if iniciou
        else "Já existe uma sincronização em andamento."
    )
    return redirect(url_for("index", msg=msg))


@app.get("/sync/status")
def sync_status():
    return jsonify(rodando=_sync_estado["rodando"], ultimo=_sync_estado["ultimo"])


_STATUS_INFO = {
    "com_dados": ("#166534", "✓ Sincronizado"),
    "sigilo": ("#b45309", "🔒 Sigilo"),
    "sem_dados": ("#92400e", "⚠ Sem dados"),
    "nao_sync": ("#475569", "○ Não sincronizado"),
    "erro": ("#991b1b", "✗ Erro"),
}


def _status_label(status: str | None) -> Markup:
    if not status:
        return Markup('<span class="muted">—</span>')
    cor, rotulo = _STATUS_INFO.get(status, ("#334155", status))
    return Markup(f'<span class="pill" style="background:{cor}">{rotulo}</span>')


def _banner_status(processo: dict, extra_msg: str | None) -> str:
    partes = []
    if extra_msg:
        partes.append(f"<div class='flash'>{extra_msg}</div>")
    if processo:
        status = repo_proc.derivar_status(processo)
        cor, rotulo = _STATUS_INFO.get(status, ("#334155", status))
        detalhe = processo.get("ultimo_sync_detalhe")
        txt = rotulo + (f" — {detalhe}" if detalhe else "")
        partes.append(f"<div class='flash' style='background:{cor}'>{txt}</div>")
    return "".join(partes)


@app.post("/processos/<processo_id>/sync")
def sync_um(processo_id: str):
    resumo = sincronizar_um(processo_id)
    if request.is_json:
        return jsonify(resumo)
    detalhe = resumo.get("detalhe")
    msg = (
        f"Sincronização deste processo: {resumo['status']}"
        + (f" — {detalhe}" if detalhe else "")
        + f" ({resumo.get('movimentacoes_novas', 0)} movimentação(ões), "
        + f"{resumo.get('publicacoes_novas', 0)} publicação(ões) nova(s))."
    )
    return redirect(url_for("movimentacoes", processo_id=processo_id, msg=msg))


@app.get("/processos/<processo_id>/movimentacoes")
def movimentacoes(processo_id: str):
    movs = repo_mov.listar_por_processo(processo_id)
    if request.args.get("format") == "json" or request.is_json:
        return jsonify(movs)
    processo = repo_proc.obter(processo_id) or {}
    pubs = repo_pub.listar_por_processo(processo_id)
    titulo = processo.get("numero_formatado") or processo.get("numero_cnj") or processo_id
    banner = _banner_status(processo, request.args.get("msg"))
    linhas = "".join(
        f"<tr><td class='muted'>{data_br(m.get('data_movimento'))}</td>"
        f"<td>{m.get('codigo_movimento') or '-'}</td>"
        f"<td>{m.get('nome_movimento') or '-'}</td></tr>"
        for m in movs
    )

    def _pub_row(p: dict) -> str:
        link = p.get("link")
        tipo = p.get("tipo_comunicacao") or p.get("tipo_documento") or "-"
        link_html = f"<a href='{link}' target=_blank>abrir</a>" if link else "-"
        return (
            f"<tr><td class='muted'>{data_br(p.get('data_disponibilizacao'), com_hora=False)}</td>"
            f"<td>{tipo}</td>"
            f"<td>{p.get('nome_orgao') or '-'}</td>"
            f"<td>{link_html}</td></tr>"
        )

    linhas_pub = "".join(_pub_row(p) for p in pubs)
    html = f"""
    <!doctype html><html lang=pt-br><head><meta charset=utf-8>
    <meta name=viewport content="width=device-width, initial-scale=1">
    <title>Processo {titulo}</title>
    <style>body{{font-family:system-ui,sans-serif;background:#0f172a;color:#e2e8f0;padding:1.5rem;max-width:1000px;margin:0 auto}}
    table{{width:100%;border-collapse:collapse;font-size:.9rem}}
    th,td{{text-align:left;padding:.5rem .6rem;border-bottom:1px solid #1e293b}}
    a{{color:#60a5fa}} .muted{{color:#94a3b8}}
    .flash{{background:#166534;padding:.6rem .9rem;border-radius:8px;margin:.4rem 0}}
    .bar{{display:flex;gap:.75rem;align-items:center;margin:1rem 0}}
    button{{padding:.5rem .9rem;border:0;border-radius:8px;cursor:pointer;background:#2563eb;color:#fff;font-weight:600}}
    </style></head><body>
    <p><a href="/">← voltar</a></p>
    <h2>{titulo} <span class=muted style=font-size:.8rem>{processo.get('tribunal_alias') or ''}</span></h2>
    {banner}
    <div class=bar>
      <form method=post action="{url_for('sync_um', processo_id=processo_id)}">
        <button type=submit>↻ Atualizar este processo</button>
      </form>
      <span class=muted>Última sync: {data_br(processo.get('ultima_sincronizacao'))}</span>
    </div>
    <h3>📋 {len(pubs)} publicação(ões) / intimação(ões) — DJEN</h3>
    <table><thead><tr><th>Disponibilização</th><th>Tipo</th><th>Órgão</th><th>Inteiro teor</th></tr></thead>
    <tbody>{linhas_pub or '<tr><td colspan=4 class=muted>Sem publicações no DJEN.</td></tr>'}</tbody></table>

    <h3 style="margin-top:1.5rem">⚖️ {len(movs)} movimentação(ões) — DataJud</h3>
    <table><thead><tr><th>Data</th><th>Código</th><th>Movimento</th></tr></thead>
    <tbody>{linhas or '<tr><td colspan=3 class=muted>Sem movimentações no DataJud.</td></tr>'}</tbody></table>
    </body></html>"""
    return html


@app.get("/health")
def health():
    return jsonify(status="ok")


def main() -> None:
    host = _get("FLASK_HOST") or "127.0.0.1"
    port = int(_get("FLASK_PORT") or "5001")
    debug = (_clean(os.getenv("FLASK_DEBUG")) or "false").lower() in ("1", "true", "yes")
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    main()
