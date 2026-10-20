# Nekkora RPA Framework (`nekkora_rpa`)

Runtime Python reutilizável para automações RPA com Playwright. É a fundação comum para processos diferentes, sem
duplicar o núcleo: registro de alvos por chave com verificação de identidade, ações seguras, ciclo de vida
transacional `INIT → TRANSFER_DATA_IN → PROCESS → TRANSFER_DATA_OUT → END`, erros tipados, retentativa que nunca
repete um desfecho desconhecido, checkpoint com retomada e reconciliação, e logs estruturados sem valores sensíveis.

Inspirado conceitualmente no UiPath REFramework, com contratos e comportamento próprios. Versão atual **0.3.0**
(novidades: [docs/framework-003.md](docs/framework-003.md)); a base veio da missão NEKKORA-RPA-FRAMEWORK-001. **Escopo desta versão: somente laboratório local (loopback) e dados sintéticos.**

O que ele **não** é: um gerador de código, um SDD, uma plataforma de execução distribuída, nem um adaptador
Windows/SAP/API/Excel.

## Instalação

O pacote **ainda não está publicado em índice** (a decisão de distribuição/licença é da titular — ver
[docs/distribuicao.md](docs/distribuicao.md)). Até lá, instala-se o wheel construído e verificado deste repositório,
numa venv própria, com as dependências travadas POR HASH:

```sh
python -m venv .venv
.venv/Scripts/python -m pip install --require-hashes --only-binary=:all: -r constraints/lab.lock   # Linux: .venv/bin/python
.venv/Scripts/python -m pip install --no-deps nekkora_rpa-0.3.0-py3-none-any.whl
.venv/Scripts/python -m pip check
python -m playwright install chromium        # só para Chromium (o Google Chrome instalado usa browser.channel = "chrome")
```

Depois de uma publicação aprovada pela titular: `python -m pip install "nekkora-rpa[excel]==0.3.0"` (o extra `excel` traz
o `openpyxl` da escrita de planilhas). O Nekkora Studio prepara esse ambiente sozinho, com confirmação (Dependency
Manager). Para construir e verificar os artefatos: `python tools/verificar_distribuicao.py --saida <pasta>`.

Requisitos: Python ≥ 3.12; dependência direta única `playwright>=1.63,<2` (homologado com 1.63.0). Para usar o Google
Chrome instalado, configure `browser.channel = "chrome"`.

## Tutorial: um processo do zero

**1. Registre os alvos por chave** (`selectors.json`, contrato `nekkora-rpa/selectors` 1.0.0):

```json
{
  "schema": "nekkora-rpa/selectors", "version": "1.0.0", "system": "clientes",
  "targets": {
    "clientes.consulta.titulo":    {"preferred": {"strategy": "id", "value": "titulo-consulta"},
                                    "expected": {"tag": "h1", "role": "heading", "name": "Consulta de clientes"}},
    "clientes.consulta.codigo":    {"preferred": {"strategy": "id", "value": "codigo"},
                                    "expected": {"tag": "input", "role": "textbox", "name": "Código do cliente"}},
    "clientes.consulta.consultar": {"preferred": {"strategy": "test_id", "value": "consultar"},
                                    "alternatives": [{"strategy": "role", "role": "button", "name": "Consultar"}],
                                    "expected": {"tag": "button", "role": "button", "name": "Consultar"}},
    "clientes.consulta.nome":      {"preferred": {"strategy": "css", "expression": "#resultado #res-nome"},
                                    "expected": {"tag": "dd"}}
  }
}
```

Um seletor que encontra um elemento não prova que é o alvo certo: `expected` é conferido no próprio nó antes de
qualquer ação. Dois elementos → `TARGET_AMBIGUOUS` (nunca "o primeiro").

**2. Escreva a Page** (intenções da tela, só com chaves):

```python
from nekkora_rpa.pages import BasePage

class ConsultaPage(BasePage):
    prefix = "clientes.consulta"
    identity = "titulo"

    def consultar(self, codigo: str) -> str:
        self.act.fill(self.k("codigo"), codigo, step_id="CON-01")
        self.act.click(self.k("consultar"), step_id="CON-02", idempotent=True,   # consulta: sem efeito colateral
                       postcondition=lambda: self.act.is_visible(self.k("nome")))
        return self.act.read_text(self.k("nome"), step_id="CON-03")
```

**3. Escreva o processo:**

```python
from nekkora_rpa import ProcessResult, RpaProcess
from nekkora_rpa.errors import BusinessRuleRejected

class ConsultaClientes(RpaProcess):
    name = "consulta_clientes"
    required_secrets = ("clientes.usuario", "clientes.senha")

    def init(self, rt):
        rt.act.navigate("/clientes/login.html", step_id="INIT-01")
        ...  # login (LoginModule) e tela inicial

    def process(self, rt, item):
        codigo = item.data.get("codigo")
        if not isinstance(codigo, str):
            raise BusinessRuleRejected("CODIGO_INVALIDO")       # código do processo, nunca o valor
        return ProcessResult({"codigo": codigo, "nome": ConsultaPage(rt.act).consultar(codigo)})
```

**4. Configure** (`config/lab.toml`, sem credenciais) e **rode**:

```python
# main.py
from nekkora_rpa.cli import run_cli
from processes.consulta import ConsultaClientes
raise SystemExit(run_cli(ConsultaClientes(), reference_field="codigo"))
```

```sh
set NK_SECRET_CLIENTES_USUARIO=...   &  set NK_SECRET_CLIENTES_SENHA=...      # nunca em arquivo
python main.py --config config/lab.toml --entrada itens.jsonl --saida resultados --run-dir execucao --console
```

A pasta `execucao/` recebe `events.jsonl` (eventos `nekkora-rpa/events`), `checkpoint.json` e `summary.json`; rodar
de novo com a mesma pasta RETOMA sem repetir o que já terminou. `resultados/` recebe um arquivo por transação.

Também é possível usar o engine direto: `Engine(processo, provider, sink, load_config(...), secrets=...).run()`.

## Exemplos e laboratório

| Exemplo | O que demonstra |
|---|---|
| [`examples/consulta_clientes`](examples/consulta_clientes) | somente leitura; lote misto; falha transitória recuperada pela nova tentativa da transação |
| [`examples/cadastro_pedidos`](examples/cadastro_pedidos) | gravação com efeito colateral confirmada por **duplo clique**; reconciliação pela lista de pedidos; retomada sem duplicar |

Os dois usam o mesmo pacote instalado (Pages próprias; `LoginModule`/`FormModule` do framework). O laboratório
sintético fica em [`lab/`](lab) (`python -m lab.server --port 18080`, credenciais aleatórias por padrão).

## Garantias e limites

- Nunca age sobre elemento ambíguo, de identidade divergente, em origem fora do laboratório ou depois de prazo vencido.
- Nunca repete automaticamente uma operação cujo desfecho é desconhecido; `FAILED_TECHNICAL` significa "nada foi
  despachado, reprocessar é seguro"; `OUTCOME_UNKNOWN` significa "reconciliar ou revisar".
- Não promete exactly-once: oferece não repetição às cegas + reconciliação baseada em leitura do sistema.
- Logs: estruturas fechadas, sem valores, URLs, seletores, DOM ou mensagens externas.
- Limitações: [docs/known-limitations.md](docs/known-limitations.md).

## Documentação

[Arquitetura](docs/architecture.md) · [Contratos e APIs](docs/contracts.md) · [Decisões e achados](docs/decisions.md) ·
[Segurança](docs/security.md) · [Guia de extensão](docs/extending.md) · [Plano de testes](docs/test-plan.md) ·
[Homologação](docs/homologation.md) · [Auditoria F0](docs/f0-auditoria.md) · [Novidades 0.2.0](docs/framework-002.md) ·
[Relatório final](reports/framework-001-final-report.md)

## Desenvolvimento

```sh
python -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev]" -c constraints/dev.txt
.venv/Scripts/ruff check src tests lab tools examples && .venv/Scripts/mypy
.venv/Scripts/python -m pytest -q                                          # 196 testes (Chromium headless)
NK_BROWSER_CHANNEL=chrome NK_HEADLESS=0 .venv/Scripts/python -m pytest -q  # Google Chrome real
sh tools/linux.sh                                                          # Linux (Docker)
```

Licença: todos os direitos reservados (ver [LICENSE](LICENSE)).
