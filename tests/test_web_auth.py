from dataclasses import dataclass

import src.web as web


@dataclass
class _FakeSettings:
    auth_email: str = "user@test.com"
    auth_password: str = "segredo123"


def _client(monkeypatch):
    monkeypatch.setattr(web, "settings", _FakeSettings())
    web.app.config["TESTING"] = True
    web.app.secret_key = "test-secret"
    return web.app.test_client()


def test_health_publico(monkeypatch):
    c = _client(monkeypatch)
    assert c.get("/health").status_code == 200


def test_sem_login_redireciona(monkeypatch):
    c = _client(monkeypatch)
    r = c.get("/")
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


def test_login_senha_errada(monkeypatch):
    c = _client(monkeypatch)
    r = c.post("/login", data={"email": "user@test.com", "senha": "errada"})
    assert r.status_code == 200  # re-renderiza com erro
    assert "inválidos" in r.get_data(as_text=True)


def test_login_ok_da_acesso(monkeypatch):
    c = _client(monkeypatch)
    r = c.post(
        "/login",
        data={"email": "user@test.com", "senha": "segredo123"},
        follow_redirects=False,
    )
    assert r.status_code == 302  # autenticou e redirecionou
    # agora a sessão está logada; /health continua ok e a guarda não bloqueia
    assert c.get("/health").status_code == 200


def test_api_json_sem_login_401(monkeypatch):
    c = _client(monkeypatch)
    r = c.post("/sync", json={})
    assert r.status_code == 401
