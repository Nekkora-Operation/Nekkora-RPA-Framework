# Arquitetura

```
 processo do projeto (fora do pacote)            nekkora_rpa (pacote instalado)
 ┌──────────────────────────────┐   ┌───────────────────────────────────────────────────────────────────┐
 │ processes/  RpaProcess       │──►│ core/engine     INIT → TRANSFER_DATA_IN → PROCESS → TRANSFER_DATA_OUT │
 │   init / process / recover / │   │                 → (próximo | END); estados, lote, reconciliação        │
 │   reconcile / end            │   │ core/checkpoints  checkpoint atômico (ids pseudônimos, estados)        │
 │ pages/      BasePage         │──►│ core/contracts    item, resultado, provider, sink, Runtime             │
 │ (intenção de UMA tela)       │   │ core/config       TOML estrito + sobreposição por CLI                  │
 │ selectors.json  (chaves)     │──►│ selectors/        registro por chave, leitura estrita, revisão sha-256 │
 │ config/lab.toml (sem segredo)│   │ libs/actions      click, double_click, fill, wait_*, exists,           │
 └──────────────────────────────┘   │                   is_visible, read_text, navigate, expect_new_page     │
          ▲ modules (composição)    │ modules/          LoginModule, FormModule (parametrizados por chave)   │
          └─────────────────────────│ pages/            BasePage                                            │
                                    │ adapters/playwright  browser (sessão, guardas de rede), resolver       │
                                    │                      (identidade), interactions (classificação)       │
                                    │ resilience/       RetryPolicy, decide, run_with_retry, prazos, cancel  │
                                    │ errors/           códigos estáveis + categorias + exceções            │
                                    │ observability/    eventos fechados, logger, sinks                     │
                                    │ security/         origens (LAB = loopback), Secret, SecretProvider    │
                                    │ data, cli         JSON Lines → itens; diretório de resultados; runner │
                                    └───────────────────────────────────────────────────────────────────┘
```

## Fronteiras de responsabilidade

| Camada | Faz | Não faz |
|---|---|---|
| `libs` (Actions) | operação genérica por CHAVE, prazo total, origem, resolução com identidade, classificação, retentativa, eventos | regra de negócio, seletor literal |
| `adapters/playwright` | tudo o que é específico do Playwright: sessão, rede, resolução, interação | decidir retentativa ou estado de transação |
| `selectors` | carregar e validar o registro; revisão | tocar no navegador |
| `pages` (do projeto) | intenção de uma tela ("consultar", "registrar") | retry, timeout, seletor |
| `modules` | comportamento reutilizável parametrizado por chaves (login, formulário) | conhecer um sistema específico; depender de Pages |
| `processes` (do projeto) | orquestração de negócio, validação de entrada, reconciliação | reimplementar operações |
| `core/engine` | ciclo de vida, estados, checkpoint, lote, parada | interagir com a página |

Sem dependências circulares: `modules` → `libs`; `pages` → `libs`/`modules`; `engine` → `libs` (só para montar as
ações no INIT). O proposto `libs/navigation.py` e `libs/waits.py` ficou em `libs/actions.py` (uma única classe com
infraestrutura comum; D-F001-07).

## Fluxo de uma ação (ex.: `click`)

1. valida argumentos (`mode`, `click_count`, `timeout_ms`, `step_id`, `postcondition`) → `INVALID_ARGUMENT`, nada feito;
2. prazo total = min(`timeout_ms`, prazo restante da transação);
3. origem da página atual (`SECURITY_POLICY_BLOCKED` se fora; também se a aba foi barrada ao tentar sair);
4. resolução (`Resolver`): conta todos os candidatos, exige concordância, verifica identidade no nó → `ElementHandle`;
5. `click(trial=True)`: actionability sem clicar. Falha aqui = **não despachado** (transitória);
6. nova conferência de origem; marca efeito colateral (se não idempotente); clique real no MESMO nó;
7. falha depois do despacho → `OUTCOME_UNKNOWN` (ou transitória, se declarado idempotente); aba fechada no meio do
   clique também (achado F3-A1);
8. pós-condição opcional, consultada até o prazo; não confirmada → `OUTCOME_UNKNOWN` (`POSTCONDITION_NOT_MET`);
9. `run_with_retry` repete só o que a política e a categoria permitem; eventos em cada passo.

## Fluxo de uma transação

```
TRANSFER_DATA_IN: provider.next_item() → transaction_id = "tx-" + HMAC(sal do checkpoint, referência)[:20]
  checkpoint já tem a transação?  final (SUCCEEDED/BUSINESS_REJECTED) → SKIPPED (ALREADY_FINAL)
                                   OUTCOME_UNKNOWN → SKIPPED (NEEDS_REVIEW)
                                   IN_PROGRESS (execução interrompida) → reconcile
                                   FAILED_TECHNICAL/CANCELLED sem efeito → reprocessa
PROCESS: checkpoint IN_PROGRESS (antes de agir; falhou gravar → para) → process.process()
  BusinessRuleRejected → BUSINESS_REJECTED
  falha técnica sem efeito → FAILED_TECHNICAL → recover + nova tentativa (até max_transaction_attempts)
  falha técnica COM efeito / OutcomeUnknown → reconcile: DONE → SUCCEEDED | NOT_DONE → como FAILED_TECHNICAL | UNKNOWN
  segurança, configuração, cancelamento → registra e PARA o lote
TRANSFER_DATA_OUT: sink.deliver() → COMMITTED | REJECTED | UNCERTAIN → estado final → checkpoint
END (sempre): process.end(), fechar navegador; falha de limpeza não substitui a causa original
```

## Rede (sessão de navegador)

- **Origem na rede:** proxy "sumidouro" (porta reservada sem `listen`, conexões recusadas) com exceção só para as
  origens permitidas: nada sai para fora, nem por redirecionamento (F0-A10).
- **Roteamento:** aborta navegação, recurso e aba nova fora da lista, com contagem; páginas barradas são lembradas.
- **Transporte de tentativa única** para POST/PUT/PATCH/DELETE (F9-A2): a requisição é feita uma vez por um cliente
  HTTP do Playwright sem proxy (só origens permitidas, sem seguir redirecionamento, cookies do contexto) e a resposta,
  inclusive `Set-Cookie`, é entregue à página. Uma queda vira erro de rede na página → desfecho desconhecido →
  reconciliação. Sem isso o Chromium (Windows) reenviava o POST e o servidor gravava duas vezes.
