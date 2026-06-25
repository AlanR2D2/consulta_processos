"""Idempotência do upsert de movimentações — testado com um fake do cliente Supabase,
sem rede. Garante que rodar a sincronização N vezes não duplica dados.
"""

from __future__ import annotations

from typing import Any

import src.repository.movimentacoes as repo_mov
from src.datajud.parser import Movimentacao


class _FakeTable:
    def __init__(self, store: list[dict[str, Any]]):
        self._store = store
        self._op: str | None = None
        self._select_payload: list[dict[str, Any]] = []

    def select(self, *_cols: str):
        self._op = "select"
        return self

    def eq(self, *_args: Any):
        return self

    def execute(self):
        if self._op == "select":
            return type("R", (), {"data": [{"hash_unico": r["hash_unico"]} for r in self._store]})
        return type("R", (), {"data": self._select_payload})

    def upsert(self, payload: list[dict[str, Any]], **_kw: Any):
        self._op = "upsert"
        existentes = {r["hash_unico"] for r in self._store}
        for row in payload:
            if row["hash_unico"] not in existentes:
                self._store.append(row)
                existentes.add(row["hash_unico"])
        self._select_payload = payload
        return self


class _FakeClient:
    def __init__(self):
        self.store: list[dict[str, Any]] = []

    def table(self, _name: str):
        return _FakeTable(self.store)


def _mov(codigo: int) -> Movimentacao:
    return Movimentacao(
        codigo_movimento=codigo,
        nome_movimento=f"Mov {codigo}",
        data_movimento="2020-01-01T00:00:00Z",
        complementos=[],
        hash_unico=f"hash-{codigo}",
    )


def test_upsert_idempotente(monkeypatch):
    fake = _FakeClient()
    monkeypatch.setattr(repo_mov, "get_client", lambda: fake)

    movimentos = [_mov(1), _mov(2), _mov(3)]

    # 1ª execução: 3 novas.
    assert repo_mov.upsert_movimentacoes("proc-1", movimentos) == 3
    # 2ª execução idêntica: 0 novas (idempotente).
    assert repo_mov.upsert_movimentacoes("proc-1", movimentos) == 0
    # Chega um movimento novo: só ele é gravado.
    assert repo_mov.upsert_movimentacoes("proc-1", [*movimentos, _mov(4)]) == 1

    assert len(fake.store) == 4
