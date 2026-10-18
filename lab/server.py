"""Laboratório local sintético do Nekkora RPA Framework (só biblioteca padrão).

Dois sistemas fictícios na mesma origem:
- ``/clientes``: login + consulta de cliente por código (somente leitura);
- ``/pedidos``: login próprio + cadastro de pedido (efeito colateral: cria registro), confirmação por DUPLO clique,
  e lista por referência (usada na reconciliação).
Páginas adversariais em ``/adversarial`` (ambíguo, sósia, identidade errada, shadow, iframe, coberto, desabilitado,
nova aba, redirecionamentos). Um segundo servidor ("externo", outra porta = outra origem) conta acessos para provar
bloqueio de rede.

ORÁCULO: ``GET /api/lab/oracle`` devolve o estado de negócio registrado PELO SERVIDOR (consultas feitas, pedidos
criados, duplicados), independente de qualquer log do framework. ``POST /api/lab/reset`` zera; ``POST
/api/lab/fault`` injeta falhas (``{"target": ..., "mode": ..., "count": N, "ms": M}``).

Todos os dados são fictícios. Credenciais vêm de quem inicia o laboratório (por padrão, aleatórias por execução).
"""

from __future__ import annotations

import argparse
import http.cookies
import json
import secrets
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

STATIC = Path(__file__).resolve().parent / "static"

CLIENTES = {
    "C-1001": {"nome": "Aurora Ficticia Ltda", "situacao": "ATIVO"},
    "C-1002": {"nome": "Boreal Exemplo S.A.", "situacao": "SUSPENSO"},
    "C-1003": {"nome": "Cometa Teste ME", "situacao": "ATIVO"},
    "C-1004": {"nome": "Duna Sintetica Eireli", "situacao": "INATIVO"},
}
PRODUTOS = {"P-10": "Caneta azul", "P-20": "Caderno 96 folhas", "P-30": "Grampeador"}


@dataclass
class Fault:
    mode: str
    count: int
    ms: int = 0


@dataclass
class LabState:
    credentials: dict[str, tuple[str, str]]
    sessions: dict[str, str] = field(default_factory=dict)
    consultas: list[dict[str, object]] = field(default_factory=list)
    pedidos: list[dict[str, object]] = field(default_factory=list)
    tentativas_pedido: int = 0
    logins: dict[str, int] = field(default_factory=lambda: {"ok": 0, "recusado": 0})
    hits: dict[str, int] = field(default_factory=dict)
    faults: dict[str, Fault] = field(default_factory=dict)
    external_hits: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def take_fault(self, target: str) -> Fault | None:
        with self.lock:
            f = self.faults.get(target)
            if f is None or f.count <= 0:
                return None
            f.count -= 1
            return Fault(f.mode, 1, f.ms)

    def oracle(self) -> dict[str, object]:
        with self.lock:
            refs = [p["ref"] for p in self.pedidos]
            return {
                "consultas": list(self.consultas),
                "pedidos": list(self.pedidos),
                "pedidos_duplicados": len(refs) - len(set(refs)),
                "tentativas_pedido": self.tentativas_pedido,
                "logins": dict(self.logins),
                "hits": dict(self.hits),
                "external_hits": self.external_hits,
            }


class Handler(BaseHTTPRequestHandler):
    server: LabServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        pass

    # ------------------------------------------------------------------ utilidades
    @property
    def state(self) -> LabState:
        return self.server.state

    def _send(self, status: int, body: bytes, ctype: str, headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, obj: object, headers: dict[str, str] | None = None) -> None:
        self._send(
            status, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", headers
        )

    def _body(self) -> dict[str, object]:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        data = json.loads(self.rfile.read(n).decode("utf-8"))
        return data if isinstance(data, dict) else {}

    def _session(self) -> str | None:
        cookie = http.cookies.SimpleCookie(self.headers.get("Cookie") or "")
        sid = cookie.get("lab_sid")
        return self.state.sessions.get(sid.value) if sid else None

    def _drop(self) -> None:
        """Fecha a conexão sem resposta (simula queda depois do processamento)."""
        self.close_connection = True
        try:
            self.connection.shutdown(2)
        except OSError:
            pass

    def _apply_fault(self, target: str) -> bool:
        f = self.state.take_fault(target)
        if f is None:
            return False
        if f.mode == "delay":
            time.sleep(f.ms / 1000)
            return False
        if f.mode == "error500":
            self._json(503, {"erro": "SERVICO_INDISPONIVEL"})
            return True
        if f.mode == "drop":
            self._drop()
            return True
        return False

    # ------------------------------------------------------------------ GET
    def do_GET(self) -> None:
        url = urlsplit(self.path)
        q = parse_qs(url.query)
        path = url.path
        with self.state.lock:
            self.state.hits[path] = self.state.hits.get(path, 0) + 1
        if path == "/api/lab/oracle":
            return self._json(200, self.state.oracle())
        if path == "/redir/mesma-origem":
            return self._send(302, b"", "text/plain", {"Location": "/adversarial/destino.html"})
        if path == "/redir/externo":
            return self._send(302, b"", "text/plain", {"Location": self.server.external_url + "/alvo"})
        if path == "/api/clientes/consulta":
            if self._session() != "clientes":
                return self._json(401, {"erro": "SEM_SESSAO"})
            if self._apply_fault("clientes.consulta"):
                return None
            codigo = (q.get("codigo") or [""])[0]
            with self.state.lock:
                self.state.consultas.append({"codigo": codigo})
            c = CLIENTES.get(codigo)
            return self._json(200, {"encontrado": c is not None, **(c or {})})
        if path == "/api/pedidos/por-referencia":
            if self._session() != "pedidos":
                return self._json(401, {"erro": "SEM_SESSAO"})
            ref = (q.get("ref") or [""])[0]
            with self.state.lock:
                achados = [p for p in self.state.pedidos if p["ref"] == ref]
            return self._json(200, {"pedidos": [{"protocolo": p["protocolo"]} for p in achados]})
        if path in ("/", ""):
            return self._send(302, b"", "text/plain", {"Location": "/index.html"})
        # páginas protegidas exigem a sessão do próprio sistema
        if path.startswith("/clientes/") and path != "/clientes/login.html" and self._session() != "clientes":
            return self._send(302, b"", "text/plain", {"Location": "/clientes/login.html"})
        if path.startswith("/pedidos/") and path != "/pedidos/login.html" and self._session() != "pedidos":
            return self._send(302, b"", "text/plain", {"Location": "/pedidos/login.html"})
        file = (STATIC / path.lstrip("/")).resolve()
        if STATIC not in file.parents or not file.is_file():
            return self._send(404, b"nao encontrado", "text/plain; charset=utf-8")
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
        }.get(file.suffix, "application/octet-stream")
        return self._send(200, file.read_bytes(), ctype)

    # ------------------------------------------------------------------ POST
    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        body = self._body()
        st = self.state
        if path == "/api/lab/reset":
            with st.lock:
                st.consultas.clear()
                st.pedidos.clear()
                st.tentativas_pedido = 0
                st.logins = {"ok": 0, "recusado": 0}
                st.hits.clear()
                st.faults.clear()
                st.external_hits = 0
            return self._json(200, {"ok": True})
        if path == "/api/lab/fault":
            with st.lock:
                st.faults[str(body["target"])] = Fault(
                    str(body["mode"]),
                    int(body.get("count", 1)),  # type: ignore[call-overload]
                    int(body.get("ms", 0)),
                )  # type: ignore[call-overload]
            return self._json(200, {"ok": True})
        if path in ("/api/clientes/login", "/api/pedidos/login"):
            system = path.split("/")[2]
            user, pwd = st.credentials[system]
            if self._apply_fault(system + ".login"):
                return None
            ok = body.get("usuario") == user and body.get("senha") == pwd
            with st.lock:
                st.logins["ok" if ok else "recusado"] += 1
            if not ok:
                return self._json(401, {"erro": "CREDENCIAL_RECUSADA"})
            sid = secrets.token_hex(16)
            st.sessions[sid] = system
            return self._json(200, {"ok": True}, {"Set-Cookie": f"lab_sid={sid}; Path=/; HttpOnly; SameSite=Lax"})
        if path == "/api/pedidos":
            if self._session() != "pedidos":
                return self._json(401, {"erro": "SEM_SESSAO"})
            with st.lock:
                st.tentativas_pedido += 1
            fault = st.take_fault("pedidos.criar:" + str(body.get("ref", ""))) or st.take_fault("pedidos.criar")
            if fault is not None and fault.mode == "delay":
                time.sleep(fault.ms / 1000)  # o servidor continua e GRAVA mesmo que o cliente desista/caia
                fault = None
            if fault is not None and fault.mode in ("error500", "drop_before"):
                # NÃO registrou: falha antes de gravar
                if fault.mode == "drop_before":
                    return self._drop()
                return self._json(503, {"erro": "SERVICO_INDISPONIVEL"})
            produto, qtd, ref = str(body.get("produto", "")), body.get("quantidade"), str(body.get("ref", ""))
            if produto not in PRODUTOS:
                return self._json(422, {"erro": "PRODUTO_INEXISTENTE"})
            if not isinstance(qtd, int) or not 1 <= qtd <= 99:
                return self._json(422, {"erro": "QUANTIDADE_INVALIDA"})
            with st.lock:
                protocolo = f"PED-{len(st.pedidos) + 1:06d}"
                st.pedidos.append({"ref": ref, "produto": produto, "quantidade": qtd, "protocolo": protocolo})
            if fault is not None and fault.mode == "drop_after":
                return self._drop()  # gravou e caiu antes de responder: desfecho desconhecido para o cliente
            return self._json(201, {"protocolo": protocolo})
        return self._json(404, {"erro": "NAO_ENCONTRADO"})


class ExternalHandler(BaseHTTPRequestHandler):
    server: LabServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        with self.server.state.lock:
            self.server.state.external_hits += 1
        body = b"<!doctype html><title>Externo</title><button id='externo'>Externo</button>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_POST = do_GET


class LabServer(ThreadingHTTPServer):
    daemon_threads = True
    state: LabState
    external_url: str


class Lab:
    """Laboratório em threads (para testes e homologação)."""

    def __init__(self, credentials: dict[str, tuple[str, str]] | None = None, port: int = 0) -> None:
        self.credentials = credentials or {
            "clientes": ("lab." + secrets.token_hex(3), "Lab#" + secrets.token_urlsafe(9)),
            "pedidos": ("op." + secrets.token_hex(3), "Ped#" + secrets.token_urlsafe(9)),
        }
        self.state = LabState(self.credentials)
        self.main = LabServer(("127.0.0.1", port), Handler)
        self.external = LabServer(("127.0.0.1", 0), ExternalHandler)
        for s in (self.main, self.external):
            s.state = self.state
        self.main.external_url = self.external_url
        self._threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in (self.main, self.external)]

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.main.server_address[1]}"

    @property
    def external_url(self) -> str:
        return f"http://127.0.0.1:{self.external.server_address[1]}"

    def start(self) -> Lab:
        for t in self._threads:
            t.start()
        return self

    def stop(self) -> None:
        for s in (self.main, self.external):
            s.shutdown()
            s.server_close()

    def reset(self) -> None:
        self.state.consultas.clear()
        self.state.pedidos.clear()
        self.state.tentativas_pedido = 0
        self.state.logins = {"ok": 0, "recusado": 0}
        self.state.hits.clear()
        self.state.faults.clear()
        self.state.external_hits = 0

    def fault(self, target: str, mode: str, count: int = 1, ms: int = 0) -> None:
        with self.state.lock:
            self.state.faults[target] = Fault(mode, count, ms)

    def oracle(self) -> dict[str, object]:
        return self.state.oracle()


def main() -> None:
    ap = argparse.ArgumentParser(description="Laboratório local sintético (somente 127.0.0.1)")
    ap.add_argument("--port", type=int, default=18080)
    ap.add_argument("--credenciais", help="arquivo JSON {sistema: [usuario, senha]} (padrão: aleatórias)")
    a = ap.parse_args()
    creds = None
    if a.credenciais:
        raw = json.loads(Path(a.credenciais).read_text(encoding="utf-8"))
        creds = {k: (v[0], v[1]) for k, v in raw.items()}
    lab = Lab(creds, a.port).start()
    print(json.dumps({"url": lab.url, "externo": lab.external_url}), flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        lab.stop()


if __name__ == "__main__":
    main()
