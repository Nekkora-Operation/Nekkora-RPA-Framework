# Guia: novas Libs, Pages, Modules e processos

## Novo processo (projeto consumidor)

```
meu_projeto/
├── config/lab.toml        # sem credenciais
├── selectors.json         # nekkora-rpa/selectors 1.0.0, system "meusistema"
├── pages/                 # uma classe por tela (BasePage)
├── processes/             # RpaProcess
└── main.py                # run_cli(MeuProcesso(), reference_field="...")
```

1. Registre cada alvo por chave (`meusistema.tela.alvo`) com `expected` (tag + papel + nome sempre que possível).
2. Escreva Pages com intenções da tela; use `self.k("alvo")` para as chaves; nunca seletores.
3. No processo: valide a entrada ANTES de agir (`BusinessRuleRejected("CODIGO")`); declare `idempotent=True` só para
   cliques sem efeito colateral (consultar, abrir aba); deixe a gravação não idempotente; dê `postcondition` objetiva.
4. Implemente `reconcile` se o processo grava algo: leia o sistema e devolva `DONE` (com o resultado), `NOT_DONE` ou
   `UNKNOWN`. Sem `reconcile`, desfecho desconhecido vai para revisão.
5. Rode com `python main.py --config config/lab.toml --entrada itens.jsonl --saida resultados --run-dir execucao`.

## Nova Page

```python
from nekkora_rpa.pages import BasePage

class FaturaPage(BasePage):
    prefix = "financeiro.fatura"
    identity = "titulo"            # alvo que prova que esta é a tela atual

    def emitir(self, numero: str) -> str:
        self.act.fill(self.k("numero"), numero, step_id="FAT-01")
        self.act.click(self.k("emitir"), step_id="FAT-02",
                       postcondition=lambda: self.act.is_visible(self.k("protocolo")))
        return self.act.read_text(self.k("protocolo"), step_id="FAT-03")
```

## Novo Module

Parametrize por chaves (não por sistema), use só `Actions`, não dependa de Pages:

```python
class PaginacaoModule:
    def __init__(self, actions, *, proxima: str, ultima_pagina: str):
        ...
    def percorrer(self, ao_visitar): ...
```

## Nova operação (Lib)

Uma operação nova entra em `libs/actions.py` somente com:
1. classificação clara de despachado × não despachado (e idempotência padrão justificada);
2. prazo total via `ctx.action_deadline`, origem via `_require_origin`, resolução com identidade via `_resolve`;
3. eventos pelo `_run` (sem valores);
4. testes de integração positivos e negativos no laboratório e uma mutação no `tools/controle_negativo.py`;
5. atualização do contrato `events` (lista de ações) via `tools/gerar_contratos.py`.

Fora do MVP e proibidos como fallback automático: `force`, clique por JavaScript/`dispatchEvent`, mouse do sistema
operacional, `nth()`/`first()` arbitrários.
