"""F9 — homologação integrada: o WHEEL instalado numa venv limpa, fora do repositório, executando os dois exemplos
como processos separados contra o laboratório local. O resultado de negócio é conferido pelo ORÁCULO do servidor
(estado registrado pelo próprio laboratório), nunca só pelo código de saída ou pelos logs do runtime.

Ambiente: ``NK_BROWSER_CHANNEL`` (``chromium`` | ``chrome``) e ``NK_HEADLESS`` (``0`` = janela visível).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from lab.server import CLIENTES, Lab

pytestmark = pytest.mark.e2e

ROOT = Path(__file__).resolve().parents[2]
SENT = {
    "clientes": ("usr.SENTINELA-U1", "pwd-SENTINELA-P1#x"),
    "pedidos": ("op.SENTINELA-U2", "pwd-SENTINELA-P2#y"),
}
OBS = "observacao SENTINELA-OBS 123.456.789-09"


@dataclass
class Venv:
    root: Path
    python: Path
    work: Path


def _run(cmd: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=False, **kw)  # type: ignore[call-overload]


@pytest.fixture(scope="session")
def venv() -> Iterator[Venv]:
    base = Path(tempfile.mkdtemp(prefix="nk-rpa-e2e-"))
    dist = base / "dist"
    r = _run([sys.executable, "-m", "build", "--wheel", "--outdir", str(dist), str(ROOT)])
    assert r.returncode == 0, r.stderr[-3000:]
    wheel = next(dist.glob("nekkora_rpa-*.whl"))
    root = base / "venv"
    assert _run([sys.executable, "-m", "venv", str(root)]).returncode == 0
    py = root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    r = _run([str(py), "-m", "pip", "install", "-q", str(wheel), "-c", str(ROOT / "constraints" / "lab.txt")])
    assert r.returncode == 0, r.stderr[-3000:]
    work = base / "projetos"
    for ex in ("consulta_clientes", "cadastro_pedidos"):
        shutil.copytree(ROOT / "examples" / ex, work / ex, ignore=shutil.ignore_patterns("runs", "__pycache__"))
    yield Venv(root, py, work)
    if os.environ.get("NK_E2E_KEEP") != "1":
        shutil.rmtree(base, ignore_errors=True)


@pytest.fixture(scope="module")
def lab() -> Iterator[Lab]:
    instance = Lab(SENT).start()
    yield instance
    instance.stop()


@pytest.fixture
def fresh(lab: Lab) -> Lab:
    lab.reset()
    return lab


ARTIFACTS: list[Path] = []
OUTPUTS: list[str] = []


def run_example(v: Venv, lab: Lab, example: str, items: list[dict[str, object]], name: str,
                *, creds: dict[str, tuple[str, str]] | None = None, extra: list[str] | None = None,
                background: bool = False) -> tuple[int, dict[str, object], Path] | subprocess.Popen[str]:
    d = v.work / example
    out = d / "execucoes" / name
    out.mkdir(parents=True, exist_ok=True)
    entrada = out / "itens.jsonl"
    if not entrada.exists():
        entrada.write_text("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items), encoding="utf-8")
    env = {k: v2 for k, v2 in os.environ.items() if not k.startswith(("NK_SECRET_", "PYTHONPATH"))}
    for system, (u, p) in (creds or SENT).items():
        env[f"NK_SECRET_{system.upper()}_USUARIO"] = u
        env[f"NK_SECRET_{system.upper()}_SENHA"] = p
    cmd = [str(v.python), str(d / "main.py"), "--config", str(d / "config" / "lab.toml"), "--entrada", str(entrada),
           "--saida", str(out / "resultados"), "--run-dir", str(out / "run"), "--base-url", lab.url, "--console",
           "--channel", os.environ.get("NK_BROWSER_CHANNEL", "chromium")]
    if os.environ.get("NK_HEADLESS", "1") == "0":
        cmd.append("--visivel")
    cmd += extra or []
    ARTIFACTS.append(out)
    if background:
        # saída em arquivos: um PIPE não lido enche e trava o processo
        return subprocess.Popen(cmd, cwd=str(v.work), env=env, stdout=(out / "stdout-1.txt").open("w"),
                                stderr=(out / "stderr-1.txt").open("w"), text=True)
    r = subprocess.run(cmd, cwd=str(v.work), env=env, capture_output=True, text=True, timeout=600, check=False)
    OUTPUTS.extend([r.stdout, r.stderr])
    (out / "stdout.txt").write_text(r.stdout, encoding="utf-8")
    (out / "stderr.txt").write_text(r.stderr, encoding="utf-8")
    summary = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}
    return r.returncode, summary, out


def results(out: Path) -> dict[str, dict[str, object]]:
    """Resultados por referência de negócio (lidos do destino de resultados, que é o registro de negócio)."""
    res: dict[str, dict[str, object]] = {}
    for f in (out / "resultados").glob("*.json"):
        doc = json.loads(f.read_text(encoding="utf-8"))
        res[doc["transaction_id"]] = doc
    return res


def by_status(out: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for doc in results(out).values():
        counts[str(doc["status"])] = counts.get(str(doc["status"]), 0) + 1
    return counts


# ------------------------------------------------------------------------------------------------ distribuição
def test_pacote_instalado_e_o_usado_e_exemplos_nao_copiam_o_nucleo(venv: Venv):
    r = _run([str(venv.python), "-c", "import nekkora_rpa, sys; print(nekkora_rpa.__file__); print(sys.prefix)"],
             cwd=str(venv.work))
    file, prefix = r.stdout.split()
    assert Path(file).is_relative_to(Path(prefix)) and not Path(file).is_relative_to(ROOT)
    for ex in ("consulta_clientes", "cadastro_pedidos"):
        for py in (venv.work / ex).rglob("*.py"):
            text = py.read_text(encoding="utf-8")
            assert not re.search(r"^\s*(class (Actions|Engine|Resolver|RetryPolicy)\b|def run_with_retry)", text, re.M)
            for m in re.finditer(r"^\s*(?:from|import)\s+([\w.]+)", text, re.M):
                assert m.group(1).split(".")[0] in {"nekkora_rpa", "pages", "processes", "__future__", "re",
                                                    "dataclasses"}, (py, m.group(1))


# ------------------------------------------------------------------------------------------------ processo 1
def test_consulta_lote_misto_com_falha_transitoria_recuperada(venv: Venv, fresh: Lab):
    fresh.fault("clientes.consulta", "error500", count=1)  # 1ª consulta: serviço indisponível
    items = [{"codigo": "C-1001"}, {"codigo": "C-9999"}, {"codigo": "invalido"}, {"codigo": "C-1004"},
             {"codigo": "C-1002"}]
    code, summary, out = run_example(venv, fresh, "consulta_clientes", items, "e1-lote")
    assert code == 0 and summary["status"] == "COMPLETED", summary
    assert by_status(out) == {"SUCCEEDED": 3, "BUSINESS_REJECTED": 2}
    # oráculo: o servidor registrou exatamente as consultas válidas (a que falhou com 503 não conta)
    assert [c["codigo"] for c in fresh.oracle()["consultas"]] == ["C-1001", "C-9999", "C-1004", "C-1002"]
    # o que o processo entregou bate com o cadastro do servidor (fonte independente)
    for doc in results(out).values():
        if doc["status"] == "SUCCEEDED":
            o = doc["output"]
            assert {"nome": o["nome"], "situacao": o["situacao"]} == CLIENTES[o["codigo"]]
    events = (out / "run" / "events.jsonl").read_text(encoding="utf-8")
    assert "TRANSACTION_RETRY_SCHEDULED" in events


def test_consulta_credencial_recusada_para_no_init_sem_insistir(venv: Venv, fresh: Lab):
    code, summary, _ = run_example(venv, fresh, "consulta_clientes", [{"codigo": "C-1001"}], "e7-credencial",
                                   creds={"clientes": ("usr.SENTINELA-U1", "errada-SENTINELA-P9")})
    assert code == 3 and summary["status"] == "INIT_FAILED" and summary["stop_detail"] == "login_rejected"
    assert fresh.oracle()["logins"] == {"ok": 0, "recusado": 1}
    assert fresh.oracle()["consultas"] == []


def test_configuracao_fora_do_laboratorio_e_recusada(venv: Venv, fresh: Lab):
    code, summary, _ = run_example(venv, fresh, "consulta_clientes", [{"codigo": "C-1001"}], "e6-origem",
                                   extra=["--base-url", "https://erp.exemplo.com.br"])
    assert code == 5 and summary["detail"] == "allowed_origins_not_lab"
    assert fresh.oracle()["hits"] == {}


# ------------------------------------------------------------------------------------------------ processo 2
def pedidos(*specs: tuple[str, str, int]) -> list[dict[str, object]]:
    return [{"ref": r, "produto": p, "quantidade": q, "observacao": OBS} for r, p, q in specs]


def oracle_orders(lab: Lab) -> dict[str, int]:
    counts: dict[str, int] = {}
    for p in lab.oracle()["pedidos"]:  # type: ignore[union-attr]
        counts[p["ref"]] = counts.get(p["ref"], 0) + 1
    return counts


def test_pedidos_lote_misto(venv: Venv, fresh: Lab):
    items = pedidos(("REF-1", "P-10", 3), ("REF-2", "P-99", 1), ("REF-3", "P-20", 0), ("REF-4", "P-30", 2))
    code, summary, out = run_example(venv, fresh, "cadastro_pedidos", items, "e2-lote")
    assert code == 0 and summary["status"] == "COMPLETED", summary
    assert by_status(out) == {"SUCCEEDED": 2, "BUSINESS_REJECTED": 2}
    assert oracle_orders(fresh) == {"REF-1": 1, "REF-4": 1}
    o = fresh.oracle()
    assert o["tentativas_pedido"] == 3  # REF-3 foi recusado ANTES de qualquer ação; REF-2 pelo servidor (422)
    protocolos = {p["ref"]: p["protocolo"] for p in o["pedidos"]}  # type: ignore[union-attr]
    for doc in results(out).values():
        if doc["status"] == "SUCCEEDED":
            assert protocolos[doc["output"]["referencia"]] == doc["output"]["protocolo"]
        else:
            assert doc["detail"] in ("PRODUTO_INEXISTENTE", "QUANTIDADE_INVALIDA")


def test_pedido_criado_e_conexao_perdida_reconcilia_sem_duplicar(venv: Venv, fresh: Lab):
    fresh.fault("pedidos.criar:REF-A", "drop_after")
    code, summary, out = run_example(venv, fresh, "cadastro_pedidos",
                                     pedidos(("REF-A", "P-10", 1), ("REF-B", "P-20", 2)), "e3-queda")
    assert code == 0, summary
    assert oracle_orders(fresh) == {"REF-A": 1, "REF-B": 1}
    assert fresh.oracle()["tentativas_pedido"] == 2  # o duplo clique da REF-A NÃO foi repetido
    docs = list(results(out).values())
    assert sorted(d["status"] for d in docs) == ["SUCCEEDED", "SUCCEEDED"]
    assert any(d["output"].get("reconciliado") for d in docs)
    events = (out / "run" / "events.jsonl").read_text(encoding="utf-8")
    assert '"RECONCILIATION_COMPLETED"' in events and '"outcome":"DONE"' in events


def test_servico_indisponivel_reconcilia_nao_feito_e_tenta_de_novo_uma_vez(venv: Venv, fresh: Lab):
    fresh.fault("pedidos.criar:REF-C", "error500")
    code, summary, out = run_example(venv, fresh, "cadastro_pedidos", pedidos(("REF-C", "P-30", 4)), "e4-503")
    assert code == 0, summary
    assert oracle_orders(fresh) == {"REF-C": 1} and fresh.oracle()["tentativas_pedido"] == 2
    events = (out / "run" / "events.jsonl").read_text(encoding="utf-8")
    assert '"outcome":"NOT_DONE"' in events and "TRANSACTION_RETRY_SCHEDULED" in events


def test_interrupcao_real_no_meio_do_lote_e_retomada_sem_duplicar(venv: Venv, fresh: Lab):
    items = pedidos(*[(f"REF-R{i}", "P-10", i) for i in range(1, 6)])
    # o servidor demora 3 s para gravar a REF-R3; o processo é morto (kill) enquanto espera — e o servidor GRAVA
    fresh.fault("pedidos.criar:REF-R3", "delay", ms=3_000)
    proc = run_example(venv, fresh, "cadastro_pedidos", items, "e5-retomada", background=True)
    assert isinstance(proc, subprocess.Popen)
    t0 = time.monotonic()
    while fresh.oracle()["tentativas_pedido"] < 3 and time.monotonic() - t0 < 120:
        time.sleep(0.05)
    proc.kill()
    proc.wait(timeout=60)
    for f in ("stdout-1.txt", "stderr-1.txt"):
        OUTPUTS.append((ARTIFACTS[-1] / f).read_text(encoding="utf-8"))
    time.sleep(3.5)
    assert oracle_orders(fresh) == {"REF-R1": 1, "REF-R2": 1, "REF-R3": 1}
    cp = json.loads((ARTIFACTS[-1] / "run" / "checkpoint.json").read_text(encoding="utf-8"))["body"]
    assert sorted(r["status"] for r in cp["transactions"].values()) == ["IN_PROGRESS", "SUCCEEDED", "SUCCEEDED"]
    # retomada: mesma pasta de execução e mesma entrada
    code, summary, out = run_example(venv, fresh, "cadastro_pedidos", items, "e5-retomada")
    assert code == 0, summary
    assert summary["counts"] == {"SUCCEEDED": 3, "SKIPPED": 2}
    assert oracle_orders(fresh) == {f"REF-R{i}": 1 for i in range(1, 6)}
    assert fresh.oracle()["pedidos_duplicados"] == 0 and fresh.oracle()["tentativas_pedido"] == 5
    # terceira execução: nada a fazer, nada duplicado
    code, summary, _ = run_example(venv, fresh, "cadastro_pedidos", items, "e5-retomada")
    assert summary["counts"] == {"SKIPPED": 5} and fresh.oracle()["tentativas_pedido"] == 5


# ------------------------------------------------------------------------------------------------ privacidade
def test_zz_nenhum_valor_sensivel_em_artefatos_saida_ou_logs():
    """Varre TUDO o que as execuções acima persistiram (eventos, checkpoint, resumo, stdout/stderr) e também os
    resultados (registro de negócio), procurando credenciais, a observação sentinela e as referências/códigos."""
    assert ARTIFACTS, "rode a suíte inteira"
    forbidden = [u for u, _ in SENT.values()] + [p for _, p in SENT.values()] + [
        "errada-SENTINELA-P9", "SENTINELA-OBS", "123.456.789-09", "SENTINELA"]
    item_values = ["REF-", "C-1001", "C-9999", "C-1004", "C-1002", "invalido", "P-10", "P-30", "Aurora Ficticia"]
    files = 0
    for out in set(ARTIFACTS):
        for f in out.rglob("*"):
            if not f.is_file() or f.name == "itens.jsonl":
                continue
            text = f.read_text(encoding="utf-8")
            files += 1
            for s in forbidden:
                assert s not in text, (f, s)
            if "resultados" not in f.parts:
                for s in item_values:
                    assert s not in text, (f, s)
    for text in OUTPUTS:
        for s in forbidden + item_values:
            assert s not in text, s
    assert files >= 20
