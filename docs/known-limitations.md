# Limitações conhecidas (0.1.0)

| # | Limitação | Consequência | Caminho |
|---|---|---|---|
| L1 | Só ambiente LAB (loopback) | não roda contra sistemas reais | missão própria para ambientes, cofre de segredos e allowlist de produção |
| L2 | Sem iframe nem shadow DOM | alvo em iframe → `TARGET_NOT_FOUND`; em shadow root → `TARGET_IDENTITY_MISMATCH:scope` | contrato de escopo (`frame`, `shadow`) com testes próprios |
| L3 | Identidade limitada a tag, tipo, papel e nome acessível | dois elementos com a mesma identidade só são distinguidos pelo seletor; o framework bloqueia se o seletor também casar os dois | evidências adicionais (contexto/região) em versão futura do registro |
| L4 | Processo síncrono não preemptivo | o prazo da transação só é observado dentro das operações do framework; código do processo que trave não é interrompido | engine com supervisão (fora do MVP) |
| L5 | Transporte de tentativa única cobre só métodos não idempotentes de origens permitidas | GET com efeito colateral (má prática do sistema) segue a pilha do navegador e pode ser reenviado por ele | declarar navegações não idempotentes (`idempotent=False`) e reconciliar |
| L6 | Reenvio transparente do POST pelo Chromium observado no Windows; no Linux (contêiner) não se reproduziu | sem a guarda o comportamento é dependente de plataforma | a guarda torna o comportamento determinístico nas duas |
| L7 | Exactly-once não é garantido | o que existe é: não repetir às cegas + reconciliação baseada em leitura do sistema; reconciliação depende do processo implementar `reconcile` | deduplicação no sistema de destino (chave idempotente) |
| L8 | `kill` do processo não executa END | o navegador é encerrado pelo próprio driver do Playwright (verificado: nenhum processo órfão); não há resumo dessa execução | — |
| L9 | Checkpoint local em arquivo único | uma execução por pasta (`run_dir`); sem trava entre processos concorrentes | trava de arquivo ou armazenamento externo |
| L10 | `fill` só para campos de texto; sem `select_option`, upload, download, teclado, hover | processos que precisem disso esperam novas operações (com testes) | adicionar operações conforme demanda real |
| L11 | Sem conexão a navegador existente (CDP) | o framework sempre abre o próprio navegador/contexto | adapter de conexão com as mesmas guardas |
| L12 | Chrome de marca homologado com janela visível no Windows; no Linux só Chromium headless do contêiner | — | — |
| L13 | Sem publicação em índice de pacotes e sem release | instalação por wheel/sdist local | decisão da usuária |
