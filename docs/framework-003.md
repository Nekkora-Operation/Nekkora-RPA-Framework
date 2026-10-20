# nekkora_rpa 0.3.0 — leitura de texto, tecla, planilha de saída (NEKKORA-E2E-002)

Versão **aditiva** sobre a 0.2.0: nenhuma API existente mudou de comportamento. Contratos versionados novos:
`nekkora-rpa/events` **1.2.0** (eventos `OUTPUT_*`, ações `press`, `read_items`, `current_address`) e
`nekkora-rpa/run-summary` **1.2.0** (campo `output`). Os esquemas 1.0.0 e 1.1.0 continuam publicados. O checkpoint e o
resultado JSON continuam em 1.1.0 (sem mudança). Nada aqui é específico de um site: são capacidades genéricas de leitura
de texto informativo, envio por teclado e saída tabular.

## 1. Ações novas — `nekkora_rpa.Actions`

| Ação | Contrato |
|---|---|
| `press(key, key_name="Enter", *, idempotent=False, postcondition=None, step_id=None)` | Tecla (`Enter`, `Tab`, `Escape`) sobre o alvo verificado. Antes da tecla o alvo precisa estar **visível e habilitado** (senão nada é despachado: `TARGET_NOT_READY`). Mesmo contrato do clique: não idempotente por padrão (falha depois do despacho → `OUTCOME_UNKNOWN`), `postcondition` confirma o efeito até o prazo. |
| `read_items(key, *, step_id=None) -> tuple[str, ...]` | Lê o alvo verificado como ITENS: se ele exibe uma lista (`<li>` visíveis sem sublista), um item por `<li>`; senão um item com o texto exibido. Cada item normalizado (`normalize_text`), vazios descartados. Mesma resolução com identidade de `read_text` (ambíguo → `TARGET_AMBIGUOUS`, nunca "o primeiro"). |
| `current_address(*, step_id=None) -> str` | Endereço da aba atual, conferido pela política de origens (fora dela → `SECURITY_POLICY_BLOCKED`). |

Nenhum valor lido, tecla ou endereço vai para os eventos.

## 2. Texto lido — `nekkora_rpa.text`

- `normalize_text(s)`: NFC, espaços (inclusive os não separáveis) colapsados, sem espaço nas pontas.
- `join_items(items, separator="; ")`: itens normalizados, vazios descartados.
- `parse_long_date(text, *, language="pt") -> str | None`: data **por extenso** (`21 de junho de 1839`, `1º de maio de
  1990`) → `AAAA-MM-DD`. Só devolve a data quando dia, mês e ano estão no texto e há **exatamente uma** data distinta;
  data inexistente (31 de fevereiro), incompleta (`junho de 1839`) ou ambígua (duas datas) → `None`. Nunca completa nem
  escolhe.
- `normalize_address` / `same_address(a, b)`: comparação de endereços (esquema/host sem caixa, porta padrão, caminho com
  codificação percentual normalizada, consulta igual, fragmento ignorado).

## 3. Planilha de saída — `nekkora_rpa.xlsx`

Requer o extra `excel` (openpyxl). Contrato `nekkora-rpa/xlsx-output` 1.0.0.

- **Esquema declarado** — `XlsxSchema(columns, key_field, sheet="Dados", max_rows=10_000)` com
  `OutputColumn(header, field, kind=ColumnKind.TEXT|ISO_DATE|URL, required=True, max_chars=2000)`. Cabeçalho não vazio,
  sem cara de fórmula, único (sem caixa); campo `snake_case` único; chave obrigatória; aba válida no Excel.
- **Células sempre texto** (`data_type="s"`, formato `@`): um valor lido que começa com `=`, `+`, `-` ou `@` NUNCA vira
  fórmula e ainda recebe o prefixo de citação do Excel. Datas `AAAA-MM-DD` gravadas como texto (o Excel não representa
  datas anteriores a 1900). Saneamento: NFC, espaços colapsados, caracteres proibidos no XML removidos.
- **Gravação atômica conferida** — `write_xlsx(path, schema, rows, *, overwrite=OverwritePolicy.FAIL_IF_EXISTS)`: valida
  TODAS as linhas antes do disco; grava um temporário na mesma pasta, **reabre e confere** (`read_back`: uma aba, cabeçalho
  idêntico, nenhuma fórmula, nenhuma célula extra) e só então troca (`os.replace`). Arquivo travado (aberto no Excel) →
  `XlsxOutputError("locked")` e o arquivo anterior fica intacto; nenhum temporário sobra.
- **Destino transacional** — `XlsxResultSink(path, schema, *, state_dir, overwrite=REPLACE, commit=ALL_OR_NOTHING,
  expected_rows=None)` implementa `ResultSink` + `finalize` (`FinalizingResultSink`):
  - `deliver`: transação bem-sucedida → linha validada e PREPARADA num estado persistido (`<state_dir>/<nome>.xlsx-output.json`,
    atômico). Linha inválida/incompleta ou chave repetida de outra transação → `SinkRejected(<token>)`, nada preparado.
    Mesma transação entregue de novo → idempotente.
  - `finalize`: com `ALL_OR_NOTHING`, grava só se o lote chegou ao fim e TODAS as transações tiveram sucesso (e, com
    `expected_rows`, se a quantidade bate); senão **retém** (`WITHHELD`, sem arquivo parcial). Estados observáveis:
    `OPEN → COMMITTING → COMMITTED | WITHHELD | FAILED`. O hash pretendido é gravado ANTES da troca: uma queda entre a
    conferência e o fim é reconciliada na retomada (arquivo com o hash → `COMMITTED`; senão regrava).
  - Retomada: linhas já preparadas são reaproveitadas; reprocessar não duplica (chave por `transaction_id` e por campo).
  - Depois do `COMMITTED` (estado 1.1.0) os valores ficam **só na planilha**: o estado guarda o hash, a contagem e as
    transações gravadas. Repetir uma transação gravada não muda nada; transação NOVA nesse estado → `SinkRejected
    ("output_committed")` (não reabre a saída, que seria regravada sem as linhas anteriores); planilha alterada por fora
    → `FAILED/committed_output_changed`, sem regravar. Estado 1.0.0 com valores é lido e os valores são esquecidos.
- **Privacidade**: nenhum valor de célula em eventos ou erros (códigos-token). Antes do commit o estado guarda as linhas
  preparadas (necessárias para retomar); a planilha É dado de negócio e fica só no caminho de quem configura o processo.

## 4. Consolidação no engine

`Engine` chama `finalize(OutputRun(complete, statuses))` do destino que o implementa UMA vez, depois do lote, na fase
`TRANSFER_DATA_OUT` e antes do `END` (o ciclo fica INIT → TRANSFER_DATA_IN → PROCESS → TRANSFER_DATA_OUT → … →
TRANSFER_DATA_OUT (consolidação) → END). Eventos `OUTPUT_COMMITTED | OUTPUT_WITHHELD | OUTPUT_FAILED` com contagem e
motivo-token; `summary.json` ganha `output: {status, rows, detail}`. Todas as transações bem-sucedidas mas saída não
gravada → `COMPLETED_WITH_FAILURES`. A consolidação nunca derruba o engine.

## 5. Laboratório e testes

`lab/static/leitura/` (pessoas FICTÍCIAS): busca cujo campo é RECRIADO ao receber foco (o nó novo não tem id) e cópia
oculta no cabeçalho fixo; fichas com quadro por cabeçalho de linha (`th` → `td`), listas, campo ausente, cabeçalho
repetido, Unicode e um valor com cara de fórmula. `tests/integration/test_leitura.py` (navegador real),
`tests/unit/test_xlsx.py`, `tests/unit/test_text.py`; mutações M22–M30 em `tools/controle_negativo.py`.

## 6. Correções da homologação real (E2E-002)

- **Nó desanexado durante a verificação de identidade** (componente recriado ao receber texto, ex.: busca com sugestões)
  agora é `TARGET_DETACHED` — transitório, repetido pela política de repetição do processo — e não
  `TARGET_IDENTITY_MISMATCH`. Nada é feito no nó desanexado; a ação resolve de novo e age uma vez só.
- **Estado do `XlsxResultSink` sem valores depois do commit** (ver §3).

