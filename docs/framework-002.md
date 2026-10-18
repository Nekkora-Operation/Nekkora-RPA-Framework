# nekkora_rpa 0.2.0 (FRAMEWORK-002) — o que é novo

Versão ADITIVA sobre 0.1.0 (os contratos 1.0.0 continuam congelados e aceitos). Motivo: NEKKORA-E2E-001 (código gerado
pelo Nekkora Studio para o RPA Challenge). Nada aqui é específico do desafio.

## 1. Dados tabulares — `nekkora_rpa.tabular`

- `TabularSchema((Column("Nome"), Column("Telefone", integer_as_text=True), ...), sheet=None)` declara as colunas;
  `Limits` define as cotas.
- `read_xlsx` (extra opcional `excel` = `openpyxl`), `read_csv`, `read_tabular` → `TabularData` (`headers`, `rows`,
  `source_sha256`). Recusas com `TabularInvalid` (`TABULAR_INVALID`, detalhe só em código + linha/coluna): cabeçalho
  duplicado ou ausente, fórmula, macro, vínculo externo, zip-bomb, cota, linha vazia no meio, CSV malformado.
  Cabeçalhos comparados após `strip` ("Last Name " ≡ "Last Name"). Número em coluna de texto só com
  `integer_as_text=True` e se for inteiro exato.
- `TabularInputProvider.from_file(path, schema)` — um item de transação por linha; linha com problema vai com
  `PROBLEMS_KEY` para o processo recusar como regra de negócio.
- `DeferredTabularInputProvider(lambda: caminho, schema)` — a planilha é lida depois do INIT (ex.: baixada pelo próprio
  processo).

## 2. Download — `Actions.download`

`download(key, *, dest_dir, file_name, allowed_extensions=(".xlsx", ".csv"), max_bytes=10 MiB, magic=None,
timeout_ms=None, step_id=None) -> DownloadedFile(path, size_bytes, sha256)`. Exige `browser.accept_downloads = true`.
Nome de DESTINO escolhido por quem chama (nunca o sugerido pelo site); origem do arquivo conferida (2ª barreira além da
rede); tamanho; assinatura (`magic`); gravação atômica (`.part` → `os.replace`); arquivo existente não é sobrescrito.
Erros: `DOWNLOAD_INVALID` (`size`, `signature`, `failed`, `exists`…), `SECURITY_POLICY_BLOCKED` (`DOWNLOAD_ORIGIN`),
`ACTION_TIMEOUT` (`no_download`).

## 3. Ambiente `benchmark`

`runtime.environment = "benchmark"`: lista FECHADA de origens `https` exatas (sem curinga, caminho ou loopback), para
sites públicos de treinamento autorizados explicitamente. Não é LAB: `lab` continua só loopback. Mesmas guardas de
rede (rota, proxy sumidouro, redirecionamento externo, POST de tentativa única).

## 4. Identidade por rótulo visível — `nekkora-rpa/selectors` 1.1.0

- Estratégia `{"strategy": "label", "text": "Email"}`: `get_by_label` (rótulo associado, envolvente,
  `aria-labelledby`) OU o ÚNICO `<label>` irmão de um ÚNICO campo no mesmo contêiner. Não é posicional.
- Evidência `expected.label`: o rótulo visível do elemento precisa ser exatamente esse (útil quando o nome acessível é
  vazio). Um campo que divide o contêiner com outro não "herda" o rótulo.
- Esquema publicado `selectors-1.1.0.schema.json` (corrigido para descrever `label` e `expected.label`).

## 5. Ações novas

- `mark(key) -> ElementMark` e `replaced(mark) -> bool`: prova de avanço para formulários recriados (o nó marcado
  saiu do documento); própria para `postcondition`.
- `is_visible(key)`; `wait_visible` re-resolve nós destacados.
- `read_text_matching(pattern)`: lê o ÚNICO elemento cujo texto casa um padrão ANCORADO (`^…$`, até 300 caracteres) —
  para observar uma mensagem sem identidade exportável. Nenhum → `TARGET_NOT_FOUND`; mais de um → `TARGET_AMBIGUOUS`.
  O texto lido nunca vai para eventos.

## 6. Contratos 1.1.0

`events`, `checkpoint`, `result`, `run-summary` e `selectors` em 1.1.0 (aditivos; códigos `TABULAR_INVALID` e
`DOWNLOAD_INVALID`). O leitor de checkpoint aceita 1.0.0 e 1.1.0.

## 7. Prova

`tests/unit/test_tabular.py`, `tests/integration/test_framework002.py` (réplica do desafio com 10 rodadas a 100%,
sósias, rótulo trocado, downloads recusados, guarda de rede falhando), `tests/contract/` e
`tools/controle_negativo.py` (M14–M20: uma mutação por fronteira nova; 20/20 detectadas).
