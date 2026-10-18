# Contratos e interfaces públicas (versão 0.1.0)

Esquemas JSON versionados em [`src/nekkora_rpa/contracts`](../src/nekkora_rpa/contracts) (distribuídos no wheel,
gerados dos enums do código por `tools/gerar_contratos.py`; um teste falha se divergirem).

| Contrato | Arquivo | Onde aparece |
|---|---|---|
| `nekkora-rpa/selectors` 1.0.0 | `selectors-1.0.0.schema.json` | registro de alvos do projeto |
| `nekkora-rpa/events` 1.0.0 | `events-1.0.0.schema.json` | `events.jsonl` (uma linha por evento) |
| `nekkora-rpa/checkpoint` 1.0.0 | `checkpoint-1.0.0.schema.json` | `checkpoint.json` |
| `nekkora-rpa/result` 1.0.0 | `result-1.0.0.schema.json` | `JsonDirectoryResultSink` (`<transaction_id>.json`) |
| `nekkora-rpa/run-summary` 1.0.0 | `run-summary-1.0.0.schema.json` | `summary.json` e saída do CLI |

Mudança incompatível = nova versão do contrato; nunca ajuste silencioso.

## 1. Registro de alvos — `nekkora-rpa/selectors` 1.0.0

```json
{
  "schema": "nekkora-rpa/selectors", "version": "1.0.0", "system": "clientes",
  "targets": {
    "clientes.login.entrar": {
      "page": "login",
      "preferred": {"strategy": "css", "expression": "#entrar"},
      "alternatives": [{"strategy": "role", "role": "button", "name": "Entrar"}],
      "expected": {"tag": "button", "role": "button", "name": "Entrar"},
      "variants": {"homolog": {"preferred": {"strategy": "id", "value": "entrar-h"}}},
      "provenance": {"studioStepId": "a44a73a5-7733-4745-8140-7442cde06414"}
    }
  }
}
```

- Chave: `^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$`, começando por `<system>.`. Duplicada (inclusive chave JSON) → recusa.
- Estratégias: `css`, `xpath` (`expression`), `id`, `name`, `test_id` (`value`, atributo `data-testid`), `role`
  (`role` + `name` exato). Não equivalentes entre si: cada uma é um candidato.
- `expected`: `tag` obrigatória; `type` (tipo de `input`/`button`); `role`; `name` (nome acessível exato; exige `role`).
- `alternatives` (até 5) só com `expected.name` (identidade forte). Candidatos repetidos → recusa.
- `variants`: substituição explícita por ambiente (todas são validadas, mesmo as não usadas).
- Leitura estrita: campo desconhecido, versão diferente, tipo errado → `INVALID_CONFIGURATION` com detalhe enumerado.
- `revision` = `sha256:` do JSON canônico (vai em todo evento como `selector_registry_revision`).
- Não suportado (documentado): `frame`/`iframe`, shadow DOM, índice (`nth`). Alvo em shadow root → recusado
  (`TARGET_IDENTITY_MISMATCH:scope`); em iframe → não encontrado.

## 2. Ações — `nekkora_rpa.Actions`

Todas recebem a CHAVE (nunca seletor) e `step_id` opcional (`^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$`).

| Método | Parâmetros | Semântica |
|---|---|---|
| `click(key, *, timeout_ms=None, mode="pointer", click_count=1, step_id=None, postcondition=None, idempotent=False)` | `mode` só `"pointer"`; `click_count` 1 ou 2 | clique do Playwright (não é mouse do SO). Não idempotente por padrão |
| `double_click(key, *, timeout_ms, step_id, postcondition, idempotent=False)` | — | um `dblclick` efetivo (o navegador entrega 2 `click` + 1 `dblclick`) |
| `fill(key, value, *, timeout_ms, step_id, verify=True)` | `value`: `str` ou `Secret` | idempotente; confere o valor aplicado sem registrá-lo |
| `wait_visible(key, *, timeout_ms, step_id)` | — | alvo com identidade verificada fica visível |
| `wait_hidden(key, *, timeout_ms, step_id)` | — | nenhum candidato com elemento visível (ausência não exige identidade) |
| `exists(key, *, step_id)` | — | sem espera; `True` só com 1 elemento verificado; ambíguo/identidade → erro |
| `is_visible(key, *, step_id)` | — | como `exists`, e visível agora |
| `read_text(key, *, timeout_ms, step_id)` | — | texto (ou valor de campo); o retorno nunca é registrado |
| `navigate(url, *, timeout_ms, step_id, wait_until="load", idempotent=True)` | absoluta ou relativa à `base_url` | origem conferida antes; redirecionamento externo barrado na rede |
| `expect_new_page(...)` + `use_page(page)` | — | aba aberta pela ação; `use_page` confere a origem |

`timeout_ms`: prazo TOTAL da operação (localização + esperas + tentativas + backoff), limitado pelo que resta da
transação; 1 ms a 30 min (nunca infinito). Padrões: `timeouts.action_ms` / `timeouts.navigation_ms`.

`postcondition`: função sem argumentos que devolve `bool`, consultada até o prazo; erros transitórios dentro dela
contam como "ainda não"; segurança, configuração e cancelamento propagam.

## 3. Erros — `nekkora_rpa.errors`

`str(erro)` = `CÓDIGO` ou `CÓDIGO:detalhe` (detalhe sempre enumerado). A exceção externa não é encadeada; só o nome
do tipo fica em `cause_type`.

| Código | Categoria | Retentativa automática |
|---|---|---|
| `TARGET_NOT_FOUND`, `TARGET_NOT_READY`, `TARGET_DETACHED`, `ACTION_TIMEOUT`, `NAVIGATION_FAILED`, `TRANSIENT_TECHNICAL_FAILURE` | `TRANSIENT_TECHNICAL` | sim, pela política, dentro do prazo |
| `TARGET_AMBIGUOUS`, `TARGET_IDENTITY_MISMATCH`, `PAGE_CLOSED`, `UNEXPECTED_ERROR`, `CHECKPOINT_WRITE_FAILED`, `INPUT_PROVIDER_FAILED`, `TRANSACTION_DEADLINE_EXCEEDED` | `PERMANENT_TECHNICAL` | não |
| `BUSINESS_RULE_REJECTED` | `BUSINESS` | nunca |
| `OUTCOME_UNKNOWN` (motivos: `ACTION_INTERRUPTED`, `POSTCONDITION_NOT_MET`, `SINK_UNCERTAIN`, `INTERRUPTED_RUN`, `DECLARED_BY_PROCESS`) | `UNKNOWN_OUTCOME` | nunca |
| `SECURITY_POLICY_BLOCKED` | `SECURITY` | nunca; para o lote |
| `INVALID_CONFIGURATION`, `INVALID_ARGUMENT`, `SECRET_UNAVAILABLE`, `CHECKPOINT_CORRUPTED` | `CONFIGURATION` | nunca; para o lote |
| `CANCELLED` | `CANCELLED` | nunca; para o lote |

## 4. Retentativa — `RetryPolicy`

`max_attempts` (1–10, conta a 1ª), `initial_backoff_ms` ≤ `max_backoff_ms` ≤ 60 000, `multiplier` 1–10,
`jitter_ratio` 0–0,5, `retry_on` ⊆ códigos transitórios. A espera nunca ultrapassa o prazo; sem tempo útil depois do
backoff → `RETRY_DENIED:DEADLINE`. Retentativa da TRANSAÇÃO: `batch.max_transaction_attempts`, só sem efeito
colateral despachado (ou depois de reconciliação "não feito"), precedida de `process.recover`.

## 5. Ciclo de vida — `Engine`, `RpaProcess`, `Runtime`

```python
class MeuProcesso(RpaProcess):
    name = "meu_processo"                 # identificador (vai para eventos e checkpoint)
    requires_browser = True               # o engine abre/fecha a sessão
    required_secrets = ("sistema.senha",) # conferidos no INIT, sem ler valores
    def init(self, rt): ...               # login, tela inicial
    def process(self, rt, item) -> ProcessResult: ...
    def recover(self, rt): ...            # antes de nova tentativa da transação
    def reconcile(self, rt, item) -> Reconciliation: ...  # DONE (com resultado) | NOT_DONE | UNKNOWN (padrão)
    def end(self, rt): ...
```

`Engine(process, provider, sink, config, *, secrets, registry, run_dir, checkpoint, event_sinks, console, cancel,
clock, session_factory, execution_id).run() -> RunSummary`.

- `InputProvider.next_item() -> TransactionItem | None`; prontos: `SingleInputProvider`, `InMemoryInputProvider`,
  `data.JsonLinesInputProvider(path, reference_field=...)`.
- `ResultSink.deliver(item, outcome)` + atributo `idempotent`; `SinkRejected` = não gravou; outra exceção = incerto.
  Prontos: `InMemoryResultSink`, `data.JsonDirectoryResultSink(dir)`.
- `TransactionItem(reference, data)`: `reference` e `data` nunca são registrados; `transaction_id` é pseudônimo.

Estados: `PENDING → IN_PROGRESS → {SUCCEEDED, BUSINESS_REJECTED, FAILED_TECHNICAL, OUTCOME_UNKNOWN, CANCELLED}`;
`PENDING → SKIPPED`. Terminais e monotônicos. `FAILED_TECHNICAL` significa "nenhum efeito despachado: reprocessar é
seguro"; `OUTCOME_UNKNOWN` significa "pode ter produzido efeito: revisão/reconciliação".

`RunStatus`: `COMPLETED`, `COMPLETED_WITH_FAILURES`, `STOPPED`, `INIT_FAILED`, `CANCELLED`. Códigos de saída do CLI:
0, 1, 2, 3, 4 (e 5 = argumentos/configuração inválidos).

## 6. Eventos — `nekkora-rpa/events` 1.0.0

Campos: `schema`, `version`, `timestamp_utc`, `execution_id`, `event_code`, `framework_version`, `phase`,
`transaction_id`, `step_id`, `key`, `action`, `attempt`, `elapsed_ms`, `outcome`, `error_code`, `detail`, `cause_type`,
`strategy_index`, `delay_ms`, `count`, `selector_registry_revision`. Estrutura fechada: todo texto é código ou
identificador validado; não existe campo livre. Códigos: `ENGINE_*`, `PHASE_*`, `TRANSACTION_*`, `RECONCILIATION_*`,
`TARGET_RESOLVED/REJECTED`, `ACTION_STARTED/COMPLETED/FAILED`, `RETRY_SCHEDULED/DENIED`, `OUTCOME_UNKNOWN`,
`SINK_COMMITTED/UNCERTAIN/FAILED`, `CHECKPOINT_SAVED/LOADED`, `SECURITY_BLOCKED`, `CLEANUP_COMPLETED/FAILED`,
`CANCELLED`. O console é projeção do mesmo evento.

## 7. Configuração — TOML

```toml
[runtime]   environment = "lab"; allowed_origins = ["http://127.0.0.1:18080"]; base_url = "..."; process_name = "..."
[timeouts]  action_ms = 8000; navigation_ms = 15000; transaction_ms = 120000
[retry]     max_attempts = 1; initial_backoff_ms = 200; max_backoff_ms = 2000; multiplier = 2.0; jitter_ratio = 0.0
[batch]     max_transaction_attempts = 1; max_consecutive_technical_failures = 3
[browser]   channel = "chromium" | "chrome"; headless = true
[paths]     selectors = "selectors.json"; run_dir = "runs"     # relativos à pasta do arquivo
```

Estrito (seção/campo desconhecido → recusa). `environment` só `lab`; origens só loopback. Sobreposição:
`load_config(path, {"retry.max_attempts": 3})` ou CLI (`--base-url`, `--channel`, `--visivel`). Credenciais nunca na
configuração: `EnvSecretProvider` lê `NK_SECRET_<NOME>` (laboratório).

## 8. Checkpoint — `nekkora-rpa/checkpoint` 1.0.0

`{"body": {schema, version, process_name, salt, transactions: {tx-…: {status, delivery, side_effects, attempts,
error_code, detail, execution_id, updated_utc}}}, "integrity": "sha256:…"}`. Escrita atômica; outro processo, outra
versão, integridade quebrada ou arquivo ilegível → `CHECKPOINT_CORRUPTED` (não sobrescreve, não recomeça do zero).
