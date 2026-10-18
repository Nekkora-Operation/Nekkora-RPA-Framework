# Segurança e privacidade

## Escopo de execução (LAB)

- Ambiente único: `lab`. Origens permitidas só em loopback (`127.0.0.1`, `localhost`, `[::1]`), validadas na carga da
  configuração; caminho, query, fragmento ou credencial na origem → recusa.
- O bloqueio acontece ANTES da interação, em três pontos:
  1. `navigate`: destino conferido antes de qualquer requisição (`SECURITY_POLICY_BLOCKED:ORIGIN_NOT_ALLOWED`);
  2. rede: proxy sumidouro + roteamento — nenhuma requisição sai para fora da lista, inclusive redirecionamento
     (`REDIRECT_BLOCKED`), recurso e aba nova; a aba que tentou sair é lembrada (`NAVIGATION_BLOCKED`);
  3. antes de cada ação sobre elemento: a página atual precisa estar numa origem permitida.
- `page.goto()` não é autorização: o framework confere o destino final da navegação.
- Prova: `external_hits == 0` (contador do servidor "externo" do laboratório) em todos os testes de origem.

## Credenciais

- `Secret`: `str`/`repr`/`format`/`==`/`pickle` não revelam o valor; só o adapter chama `reveal()` no preenchimento.
- `SecretProvider` injetável; `EnvSecretProvider` (variáveis `NK_SECRET_<NOME>`) só para o laboratório. Os nomes
  exigidos (`required_secrets`) são conferidos no INIT sem guardar valores.
- `LoginModule` exige `Secret` para a senha; credencial recusada para o lote (não insiste).

## Logs seguros por construção

- Eventos são estruturas fechadas (sem campo livre); todo texto é código enumerado ou identificador validado por
  `^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$` (não passa URL, seletor CSS, e-mail, frase, `?`, `=`, `/`, espaço).
- Nunca registrados: valores de entrada e saída, `repr(value)`, mensagem/stack de exceção externa (só `cause_type`),
  query string, corpo de resposta, DOM, senha, token, seletor cru, captura de tela, referência do item.
- Exceções do framework: `str` = código; a exceção externa não é encadeada (traceback impresso pelo processo não a
  mostra).
- Checkpoint e resumo: só ids pseudônimos (HMAC com sal), estados e códigos.
- O destino de resultados é o registro de negócio do processo (contém a saída de negócio, nunca credenciais ou
  entradas que o processo não devolva).
- Nenhuma captura de tela é produzida.

## Provas (testes com sentinelas)

| Ataque | Onde é provado |
|---|---|
| credencial em `Secret` e em `fill` | `test_fill_com_segredo`, `test_privacidade.py`, e2e (`SENTINELA-P1/P2`, senha errada) |
| CPF fictício em entrada, referência do item, DOM e exceção do processo | `test_privacidade.py`, `test_engine.py` (`SENTINELA-CPF-123.456.789-09`) |
| seletor contendo dado | `test_privacidade.py` (`SENTINELA-SELETOR` nas expressões, inclusive com erro de ambiguidade/ausência) |
| texto de DOM lido pelo processo | `test_privacidade.py` (lido e devolvido ao processo; ausente dos artefatos) |
| URL com query | `test_privacidade.py` (`?cpf=…&q=SENTINELA-QUERY`) |
| mensagem e traceback de exceção externa | `test_excecao_externa_nao_e_encadeada…`, `test_contexto_suprimido…`, `test_privacidade.py` (tracebacks formatados) |
| configuração com valor | `test_erro_de_configuracao_nao_ecoa_valor`, `test_json_invalido_e_erro_sem_conteudo` |
| capturas de tela | `test_privacidade.py` (nenhum arquivo de imagem) |
| todos os artefatos de duas execuções reais | e2e `test_zz_nenhum_valor_sensivel_em_artefatos_saida_ou_logs` (stdout, stderr, eventos, checkpoint, resumo) |

## Integridade da execução

- Checkpoint com integridade sha-256 e escrita atômica; corrompido/de outro processo → não executa.
- Transporte de tentativa única para POST/PUT/PATCH/DELETE (o navegador não reenvia uma gravação em silêncio).
- Sem fallback perigoso: nada de `force`, clique por JavaScript, `dispatchEvent` ou mouse do sistema operacional.
