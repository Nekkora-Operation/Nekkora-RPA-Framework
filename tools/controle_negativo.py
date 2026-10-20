"""Controle negativo: injeta, um de cada vez, defeitos plausíveis nas proteções do framework e confirma que a suíte
os detecta (pelo menos um teste falha). Restaura o arquivo original ao final de cada mutação.

Uso: ``python tools/controle_negativo.py [--saida reports/evidence/controle-negativo.md]``
Exige navegador (Playwright) para as mutações de resolver/ações/rede.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "nekkora_rpa"


@dataclass(frozen=True)
class Mutation:
    ident: str
    protection: str
    file: str
    old: str
    new: str
    tests: list[str]


MUTATIONS = [
    Mutation(
        "M01",
        "ambíguo nunca vira 'o primeiro'",
        "adapters/playwright/resolver.py",
        "                    if n > 1:\n",
        "                    if n > 99:\n",
        ["tests/integration/test_resolver.py"],
    ),
    Mutation(
        "M02",
        "identidade verificada antes de agir",
        "adapters/playwright/resolver.py",
        "            mismatch = identity_mismatch(page, first_h, target.expected)",
        "            mismatch = None",
        ["tests/integration/test_resolver.py"],
    ),
    Mutation(
        "M03",
        "camada de rede (proxy sumidouro) contra redirecionamento externo",
        "adapters/playwright/browser.py",
        '"headless": self.browser_config.headless, "proxy": self._proxy()}',
        '"headless": self.browser_config.headless}',
        ["tests/integration/test_actions.py", "-k", "redir"],
    ),
    Mutation(
        "M04",
        "transporte de tentativa única para POST",
        "adapters/playwright/browser.py",
        "        if request.method.upper() in SAFE_METHODS:",
        "        if True:",
        ["tests/integration/test_actions.py", "-k", "post_com_conexao"],
    ),
    Mutation(
        "M05",
        "OUTCOME_UNKNOWN nunca é repetido pela política",
        "resilience/retry.py",
        "    if error.category is ErrorCategory.UNKNOWN_OUTCOME:\n        return RetryDecision(False, denial=RetryDenial.OUTCOME_UNKNOWN)\n",
        "",
        ["tests/unit/test_retry.py"],
    ),
    Mutation(
        "M06",
        "falha depois de efeito vira OUTCOME_UNKNOWN (não reprocessa)",
        "core/engine.py",
        "if status in (TransactionStatus.FAILED_TECHNICAL, TransactionStatus.CANCELLED) and side_effects > 0:",
        "if False:",
        ["tests/unit/test_engine.py"],
    ),
    Mutation(
        "M07",
        "clique que fecha a aba no meio vira desfecho desconhecido (F3-A1)",
        "libs/actions.py",
        "                if page.is_closed():\n                    # achado F3-A1",
        "                if False:\n                    # achado F3-A1",
        ["tests/integration/test_actions.py", "-k", "despacho"],
    ),
    Mutation(
        "M08",
        "origem conferida antes de navegar",
        "libs/actions.py",
        "            if not self.ctx.config.origins.is_allowed(absolute):",
        "            if False:",
        ["tests/integration/test_actions.py", "-k", "origem or redir"],
    ),
    Mutation(
        "M09",
        "checkpoint grava EM ANDAMENTO antes de agir",
        "core/engine.py",
        "            ctx.transaction = scope\n            self._put(",
        "            ctx.transaction = scope\n            (lambda *a, **k: None)(",
        ["tests/unit/test_engine.py"],
    ),
    Mutation(
        "M10",
        "referência do item pseudonimizada no checkpoint",
        "core/checkpoints.py",
        '    return "tx-" + digest[:20]',
        '    return "tx-" + reference',
        ["tests/unit/test_engine.py", "-k", "checkpoint or retomada"],
    ),
    Mutation(
        "M11",
        "Secret não se revela em repr/str",
        "security/secrets.py",
        '        return f"Secret({self.name}, ***)"',
        '        return f"Secret({self.name}, {self.__value})"',
        ["tests/unit/test_config_security.py"],
    ),
    Mutation(
        "M12",
        "exceção externa não encadeada no traceback",
        "errors/exceptions.py",
        "        self.__suppress_context__ = True\n",
        "",
        ["tests/unit/test_retry.py", "-k", "traceback or contexto"],
    ),
    Mutation(
        "M13",
        "reconciliação decide desfecho desconhecido na execução",
        "core/engine.py",
        "            if status is TransactionStatus.OUTCOME_UNKNOWN and stop_after is None:",
        "            if False:",
        ["tests/unit/test_engine.py", "-k", "reconcil"],
    ),
    # ---- 0.2.0 (NEKKORA-E2E-001): uma mutação por fronteira nova — dados, download, origem, rótulo, resultado, avanço
    Mutation(
        "M14",
        "planilha com fórmula é recusada (dados)",
        "tabular.py",
        '                if formula or (isinstance(cell.value, str) and cell.value.startswith("=")):',
        "                if False:",
        ["tests/unit/test_tabular.py"],
    ),
    Mutation(
        "M15",
        "download só da origem autorizada",
        "libs/actions.py",
        "                if not self.ctx.config.origins.is_allowed(download.url):",
        "                if False:",
        ["tests/integration/test_framework002.py", "-k", "download"],
    ),
    Mutation(
        "M16",
        "assinatura do arquivo baixado conferida",
        "libs/actions.py",
        "                if magic is not None and not head.startswith(magic):",
        "                if False:",
        ["tests/integration/test_framework002.py", "-k", "download"],
    ),
    Mutation(
        "M17",
        "benchmark só com origem https exata fora do loopback",
        "security/origins.py",
        '                not url.lower().startswith("https://") or host in LOOPBACK_HOSTS or "*" in url or host is None',
        "                host is None",
        ["tests/unit/test_config_security.py", "-k", "benchmark"],
    ),
    Mutation(
        "M18",
        "rótulo irmão só identifica o ÚNICO campo do contêiner",
        "adapters/playwright/resolver.py",
        "  if (labels.length === 1 && controls.length === 1 && controls[0] === e) return norm(labels[0].textContent);",
        "  if (labels.length >= 1 && controls.indexOf(e) >= 0) return norm(labels[0].textContent);",
        ["tests/integration/test_framework002.py", "-k", "rotulo"],
    ),
    Mutation(
        "M19",
        "padrão de texto do resultado precisa ser ancorado",
        "libs/actions.py",
        '            or not (pattern.startswith("^") and pattern.endswith("$"))',
        "            or False",
        ["tests/integration/test_framework002.py", "-k", "padrao"],
    ),
    Mutation(
        "M20",
        "prova de avanço: nó marcado precisa sair do documento",
        "libs/actions.py",
        '            return not bool(mark.handle.evaluate("e => e.isConnected"))',
        "            return True",
        ["tests/integration/test_framework002.py"],
    ),
    Mutation(
        "M21",
        "linha vazia entre registros do CSV é recusada (não some em silêncio)",
        "tabular.py",
        '[tuple(v if v != "" else None for v in row) for row in rows]',
        '[tuple(v if v != "" else None for v in row) for row in rows if row != []]',
        ["tests/unit/test_tabular.py"],
    ),
    # 0.3.0 — leitura de texto e saída XLSX
    Mutation(
        "M22",
        "célula da planilha é sempre texto (texto lido que começa com '=' não vira fórmula)",
        "xlsx.py",
        '            c.data_type = "s"  # SEMPRE texto: "=..." não vira fórmula',
        "            pass",
        ["tests/unit/test_xlsx.py"],
    ),
    Mutation(
        "M23",
        "tudo ou nada: transação sem sucesso retém a planilha (nada parcial)",
        "xlsx.py",
        "            if self._blocked:",
        "            if False:",
        ["tests/unit/test_xlsx.py"],
    ),
    Mutation(
        "M24",
        "lote incompleto (parada/cancelamento) retém a planilha",
        "xlsx.py",
        "            if not run.complete:",
        "            if False:",
        ["tests/unit/test_xlsx.py"],
    ),
    Mutation(
        "M25",
        "chave repetida entre transações é recusada",
        "xlsx.py",
        '                raise SinkRejected("duplicate_key")',
        "                pass",
        ["tests/unit/test_xlsx.py"],
    ),
    Mutation(
        "M26",
        "planilha conferida REABRINDO o temporário antes da troca",
        "xlsx.py",
        "        if read_back(tmp, schema) != [tuple(r) for r in rows]:",
        "        if False:",
        ["tests/unit/test_xlsx.py"],
    ),
    Mutation(
        "M27",
        "data por extenso: duas datas distintas não viram uma (nunca escolhe)",
        "text.py",
        "    if len(found) != 1:",
        "    if not found:",
        ["tests/unit/test_text.py"],
    ),
    Mutation(
        "M28",
        "tecla só é despachada em alvo visível e habilitado",
        "libs/actions.py",
        "                    interactions.ensure_ready(handle, timeout_ms=_remaining(deadline, key, step_id))",
        "                    pass",
        ["tests/integration/test_leitura.py"],
    ),
    Mutation(
        "M29",
        "lista exibida é lida como itens (não como texto colado)",
        "adapters/playwright/interactions.py",
        "            return lis.length ? lis.map(li => li.innerText) : [e.innerText];",
        "            return [e.innerText];",
        ["tests/integration/test_leitura.py"],
    ),
    Mutation(
        "M30",
        "o engine consolida o destino depois do lote",
        "core/engine.py",
        "            self._consolidate(init_error is None and stop is None)",
        "            pass",
        ["tests/unit/test_xlsx.py"],
    ),
]


def run(m: Mutation) -> tuple[bool, str]:
    path = SRC / m.file
    raw = path.read_bytes()
    original = raw.decode("utf-8").replace("\r\n", "\n")
    if original.count(m.old) != 1:
        return False, "ÂNCORA NÃO ENCONTRADA"
    try:
        path.write_text(original.replace(m.old, m.new), encoding="utf-8", newline="\n")
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-x", *m.tests],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=900,
            check=False,
        )
    finally:
        path.write_bytes(raw)  # restauração byte a byte (inclusive finais de linha)
    tail = [line for line in r.stdout.splitlines() if re.search(r"\b(passed|failed|error)", line)]
    return r.returncode != 0, (tail[-1] if tail else r.stdout[-200:]).strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--saida", type=Path)
    ap.add_argument("--so", nargs="*", help="só estas mutações (ex.: M14 M15)")
    a = ap.parse_args()
    rows = ["| Mutação | Proteção | Testes | Detectada | Resultado da suíte com o defeito |", "|---|---|---|---|---|"]
    ok = True
    for m in MUTATIONS:
        if a.so and m.ident not in a.so:
            continue
        detected, summary = run(m)
        ok &= detected
        rows.append(
            f"| {m.ident} | {m.protection} | `{' '.join(m.tests)}` | {'sim' if detected else '**NÃO**'} | {summary} |"
        )
        print(rows[-1], flush=True)
    clean = subprocess.run(
        ["git", "status", "--porcelain", "src"], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout.strip()
    rows.append("")
    rows.append(f"Código-fonte restaurado depois das mutações: {'sim' if not clean else 'NÃO: ' + clean}")
    if a.saida:
        a.saida.parent.mkdir(parents=True, exist_ok=True)
        a.saida.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return 0 if ok and not clean else 1


if __name__ == "__main__":
    sys.exit(main())
