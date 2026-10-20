"""Verificação da DISTRIBUIÇÃO do nekkora-rpa (wheel + sdist), sem publicar nada.

1. Constrói wheel e sdist (``python -m build``) com ``SOURCE_DATE_EPOCH`` = data do commit — com ``--sem-isolamento``,
   usando o backend travado de ``constraints/build.lock`` (wheel reprodutível byte a byte) — ou usa os artefatos de ``--dist``.
2. Confere o CONTEÚDO: módulos do pacote, ``py.typed``, os esquemas ``contracts/*.json``, ``LICENSE``; recusa o que não
   pode ir para fora (``.env``, chaves, planilhas, ``.nekkora``, relatórios, laboratório, testes, caches, ``.pyc``).
3. Confere os METADADOS: nome, versão = ``_version.py``, ``Requires-Python``, dependências e extra ``excel``.
4. Instala CADA artefato numa venv NOVA, numa pasta temporária fora do checkout, sem ``PYTHONPATH``: dependências de
   ``constraints/lab.lock`` com ``--require-hashes``; o artefato com ``--no-deps``; ``pip check``;
   ``importlib.metadata.version``; import real (rodando FORA do checkout); esquemas pelo ``importlib.resources``;
   gravação e releitura de uma planilha SINTÉTICA pelo ``nekkora_rpa.xlsx``.
5. Escreve um relatório JSON com os SHA-256 e o resultado de cada passo; código de saída ≠ 0 em qualquer falha.

Uso: ``python tools/verificar_distribuicao.py --saida <pasta> [--dist <pasta-com-wheel-e-sdist>] [--sem-instalar]``
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "nekkora-rpa"
PKG = "nekkora_rpa"
FORBIDDEN = re.compile(
    r"(^|/)(\.env[^/]*|.*\.(pem|key|p12|pfx|nekkora|xlsx|xls|csv|pyc|log|sqlite|db)|__pycache__|\.git|\.venv|reports|runs|lab|tests|"
    r"examples|tools|constraints|docs|node_modules|.*(token|secret|credential).*\.(txt|json))(/|$)",
    re.IGNORECASE,
)
SAFE_SECRET_MODULES = {f"{PKG}/security/secrets.py"}  # o módulo de segredos do framework (só código; nenhum valor)
SYNTHETIC = r"""
import importlib.metadata as md, importlib.resources as res, json, pathlib, sys, tempfile
import nekkora_rpa
from nekkora_rpa.xlsx import ColumnKind, OutputColumn, XlsxSchema, read_back, write_xlsx
out = {"version": md.version("nekkora-rpa"), "module_version": nekkora_rpa.__version__, "file": nekkora_rpa.__file__}
schemas = sorted(p.name for p in res.files("nekkora_rpa.contracts").iterdir() if p.name.endswith(".json"))
for s in schemas:
    json.loads(res.files("nekkora_rpa.contracts").joinpath(s).read_text(encoding="utf-8"))
out["schemas"] = schemas
schema = XlsxSchema((OutputColumn("URL", "url", ColumnKind.URL), OutputColumn("Nome", "nome"),
                     OutputColumn("Data", "data", ColumnKind.ISO_DATE)), key_field="url", sheet="Dados")
rows = [{"url": "https://exemplo.test/a", "nome": "Pessoa Ficticia Á", "data": "2001-03-04"},
        {"url": "https://exemplo.test/b", "nome": "=1+1", "data": "1999-12-31"}]
with tempfile.TemporaryDirectory() as d:
    p = pathlib.Path(d) / "sintetica.xlsx"
    write_xlsx(p, schema, rows)
    back = read_back(p, schema)
out["xlsx_rows"] = len(back)
out["xlsx_formula_as_text"] = back[1][1] == "=1+1"
print(json.dumps(out))
"""


def sha256(p: Path) -> str:
    return "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()


def run(cmd: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
    )


def clean_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTHON", "PIP_", "VIRTUAL_ENV"))}
    env["PYTHONIOENCODING"] = "utf-8"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    return env


def version_of_source() -> str:
    m = re.search(r'__version__\s*=\s*"([^"]+)"', (ROOT / "src" / PKG / "_version.py").read_text(encoding="utf-8"))
    assert m
    return m.group(1)


def build(dist: Path, isolated: bool) -> None:
    env = clean_env()
    epoch = run(["git", "log", "-1", "--format=%ct"], cwd=ROOT).stdout.strip()
    if epoch.isdigit():
        env["SOURCE_DATE_EPOCH"] = epoch
    cmd = [sys.executable, "-m", "build", "--outdir", str(dist), str(ROOT)]
    if not isolated:
        cmd.insert(3, "--no-isolation")  # backend travado de constraints/build.lock (reprodutível)
    r = run(cmd, env=env)
    if r.returncode != 0:
        raise SystemExit("build falhou:\n" + r.stdout[-3000:] + r.stderr[-3000:])


def check_names(kind: str, names: list[str], version: str) -> list[str]:
    problems = []
    rel = [n.split("/", 1)[1] if kind == "sdist" and "/" in n else n for n in names]
    for n in rel:
        inner = n[4:] if n.startswith("src/") else n
        if FORBIDDEN.search(inner) and inner not in SAFE_SECRET_MODULES:
            problems.append(f"{kind}: arquivo proibido {n}")
    pkg = [n[4:] if n.startswith("src/") else n for n in rel]
    need = [f"{PKG}/__init__.py", f"{PKG}/py.typed", f"{PKG}/_version.py", f"{PKG}/xlsx.py"]
    need += [f"{PKG}/contracts/{p.name}" for p in sorted((ROOT / "src" / PKG / "contracts").glob("*.json"))]
    need += [
        f"{PKG}/{p.relative_to(ROOT / 'src' / PKG).as_posix()}" for p in sorted((ROOT / "src" / PKG).rglob("*.py"))
    ]
    for n in sorted(set(need)):
        if n not in pkg:
            problems.append(f"{kind}: falta {n}")
    if not any(n.endswith("LICENSE") for n in rel):
        problems.append(f"{kind}: falta LICENSE")
    return problems


def check_metadata(meta: str, version: str) -> list[str]:
    problems = []
    fields: dict[str, list[str]] = {}
    for line in meta.split("\n\n", 1)[0].splitlines():
        if ": " in line and not line.startswith(" "):
            k, v = line.split(": ", 1)
            fields.setdefault(k, []).append(v)
    if fields.get("Name") != [NAME]:
        problems.append(f"metadados: Name {fields.get('Name')}")
    if fields.get("Version") != [version]:
        problems.append(f"metadados: Version {fields.get('Version')} ≠ {version}")
    if fields.get("Requires-Python") != [">=3.12"]:
        problems.append(f"metadados: Requires-Python {fields.get('Requires-Python')}")
    req = fields.get("Requires-Dist", [])
    if not any(r.startswith("playwright") for r in req) or not any(
        r.startswith("openpyxl") and 'extra == "excel"' in r for r in req
    ):
        problems.append("metadados: dependências ou extra excel ausentes")
    if "excel" not in fields.get("Provides-Extra", []):
        problems.append("metadados: Provides-Extra excel ausente")
    return problems


def install_and_probe(artifact: Path, kind: str, tmp: Path) -> dict[str, object]:
    venv = tmp / f"venv {kind} á"  # espaço e acento no caminho, de propósito
    env = clean_env()
    steps: dict[str, object] = {}
    r = run([sys.executable, "-m", "venv", str(venv)], env=env)
    py = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    steps["venv"] = r.returncode == 0
    r = run(
        [
            str(py),
            "-m",
            "pip",
            "install",
            "--require-hashes",
            "--only-binary=:all:",
            "-r",
            str(ROOT / "constraints" / "lab.lock"),
        ],
        env=env,
    )
    steps["deps_travadas_por_hash"] = r.returncode == 0
    if r.returncode != 0:
        steps["deps_erro"] = r.stdout[-1500:] + r.stderr[-1500:]
    r = run([str(py), "-m", "pip", "install", "--no-deps", str(artifact)], env=env)
    steps["instalar_artefato"] = r.returncode == 0
    if r.returncode != 0:
        steps["instalar_erro"] = r.stdout[-1500:] + r.stderr[-1500:]
    r = run([str(py), "-m", "pip", "check"], env=env)
    steps["pip_check"] = r.returncode == 0
    steps["pip_check_saida"] = r.stdout.strip()[-500:]
    work = tmp / "fora-do-checkout"
    work.mkdir(exist_ok=True)
    r = run([str(py), "-I", "-c", SYNTHETIC], cwd=work, env=env)  # -I: sem diretório atual nem PYTHON* no sys.path
    try:
        probe = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        probe = {"erro": (r.stdout + r.stderr)[-1500:]}
    steps["sonda"] = probe
    file = str(probe.get("file", ""))
    steps["importado_da_venv"] = bool(file) and str(venv) in file and str(ROOT) not in file
    return steps


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--saida", required=True)
    ap.add_argument("--dist")
    ap.add_argument("--sem-instalar", action="store_true")
    ap.add_argument(
        "--sem-isolamento", action="store_true", help="constrói com o backend já instalado (constraints/build.lock)"
    )
    a = ap.parse_args()
    out = Path(a.saida)
    out.mkdir(parents=True, exist_ok=True)
    version = version_of_source()
    dist = Path(a.dist) if a.dist else out / "dist"
    if not a.dist:
        dist.mkdir(exist_ok=True)
        build(dist, isolated=not a.sem_isolamento)
    wheel = next(dist.glob(f"{PKG}-{version}-py3-none-any.whl"))
    sdist = next(dist.glob(f"{PKG}-{version}.tar.gz"))
    report: dict[str, object] = {
        "versao": version,
        "python": sys.version.split()[0],
        "plataforma": sys.platform,
        "artefatos": {wheel.name: sha256(wheel), sdist.name: sha256(sdist)},
    }
    problems: list[str] = []
    with zipfile.ZipFile(wheel) as z:
        problems += check_names("wheel", z.namelist(), version)
        problems += check_metadata(z.read(f"{PKG}-{version}.dist-info/METADATA").decode("utf-8"), version)
    with tarfile.open(sdist) as t:
        names = [m.name for m in t.getmembers() if m.isfile()]
        problems += check_names("sdist", names, version)
        member = t.extractfile(f"{PKG}-{version}/PKG-INFO")
        assert member is not None
        problems += check_metadata(member.read().decode("utf-8"), version)
    report["conteudo_e_metadados"] = problems or "OK"
    if not a.sem_instalar:
        with tempfile.TemporaryDirectory(prefix="nk-dist-") as d:
            tmp = Path(d)
            for kind, art in (("wheel", wheel), ("sdist", sdist)):
                res = install_and_probe(art, kind, tmp)
                report[f"instalacao_{kind}"] = res
                probe = res.get("sonda", {})
                ok = (
                    all(
                        res.get(k)
                        for k in (
                            "venv",
                            "deps_travadas_por_hash",
                            "instalar_artefato",
                            "pip_check",
                            "importado_da_venv",
                        )
                    )
                    and isinstance(probe, dict)
                    and probe.get("version") == version
                    and probe.get("module_version") == version
                    and len(probe.get("schemas", [])) == len(list((ROOT / "src" / PKG / "contracts").glob("*.json")))
                    and probe.get("xlsx_rows") == 2
                    and probe.get("xlsx_formula_as_text") is True
                )
                if not ok:
                    problems.append(f"instalação do {kind} não comprovada")
    report["resultado"] = "OK" if not problems else "FALHOU"
    report["problemas"] = problems
    (out / "verificacao-distribuicao.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {"resultado": report["resultado"], "artefatos": report["artefatos"], "problemas": problems},
            ensure_ascii=False,
            indent=1,
        )
    )
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
