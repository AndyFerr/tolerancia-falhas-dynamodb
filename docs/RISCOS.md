# Matriz de riscos

> Entregável da linha **A8**. Revisar em cada marco (G1*, G2*, E5, G5).
>
> A coluna **sinal de alerta** é o que torna esta matriz utilizável: é o evento observável que diz "este risco está virando problema, aja agora". Risco sem sinal de alerta é decoração.

## Situação atual — o que já aconteceu

Estes não são riscos, são **problemas já materializados**. Entram aqui porque mudam a prioridade de tudo abaixo.

| ID | Problema | Consequência | Ação |
|---|---|---|---|
| **I1** | Cronograma deslocado ~3 semanas: estamos na S5 e a Fase 2 não começou | as semanas dos Cenários A e B já passaram no plano original | replanejar no checkpoint E5; decidir o que corta |
| **I2** | Conta AWS não provisionada (linha A3) | bloqueia B1, B2 e toda a Fase 2 | puxar A3 para frente — é o caminho crítico |
| **I3** | Coluna "Responsável" vazia em ~30 das 46 linhas | trabalho sem dono não acontece numa equipe de 3 | preencher antes do Marco 1 |

## Riscos

| ID | Risco | Prob. | Impacto | Sinal de alerta | Mitigação | Dono |
|---|---|---|---|---|---|---|
| **R1** | Cenário A ao vivo estoura o tempo da apresentação — remover e recriar réplica leva minutos | alta | alto | primeira execução cronometrada passa de 4 min | apresentar o Cenário A em **modo replay** (F3); ao vivo só os cenários rápidos | |
| **R2** | Tabela criada em on-demand torna o Cenário B impossível | média | alto | `billing_mode` diferente de `PROVISIONED` no `main.tf` | checar no review da B2; teste que falha se a tabela não estiver provisionada | |
| **R3** | Cenário C não produz sobrevenda observável — janela de concorrência curta demais | média | alto | primeira rodada com `sobrevendas` = 0 | aumentar paralelismo e reduzir o intervalo entre escritas; se ainda assim zerar, **isso é achado** e vai para o relatório, não é falha | |
| **R4** | Resultados inválidos por estoque não resetado entre execuções | alta | médio | estoque inicial ≠ 100 no começo do cenário | `POST /reset` obrigatório + erro `ESTOQUE_NAO_RESETADO` que aborta a execução | |
| **R5** | Custo de AWS acima do previsto, ou infraestrutura esquecida ligada | média | alto | alarme de billing dispara | alarme na A3; `terraform destroy` no runbook (B7); teardown parcial na G4 e total na H5 | |
| **R6** | Credencial de AWS commitada no repositório | baixa | muito alto | revisão de commit | `.env` no `.gitignore`, perfil do AWS CLI em vez de chave em arquivo, varredura antes do code freeze (G5) | |
| **R7** | Atraso do CloudWatch (~5 min) faz o painel parecer quebrado na demo | alta | baixo | métrica vazia logo após o cenário terminar | contadores do próprio script como fonte primária (D3); CloudWatch exibido com o atraso sinalizado na tela (D4) | |
| **R8** | Convergência da Global Table mais lenta que o esperado, não observável no tempo da demo | média | médio | p95 de convergência acima de 10 s nos testes da S3 | medir cedo (C4) e ajustar o roteiro da apresentação ao número real | |
| **R9** | Restauração PITR demora e só cria tabela nova | alta | médio | — (é comportamento conhecido, não surpresa) | rodar o Cenário D antes e apresentar em replay; incluir as tabelas restauradas no teardown | |
| **R10** | "Funciona na minha máquina" — ambiente divergente entre integrantes | média | médio | runbook falha quando outro integrante executa | B7 exige execução por quem **não** escreveu o runbook | |
| **R11** | Wi-fi ou AWS indisponível no momento da apresentação | baixa | muito alto | — | modo replay (F3) + vídeo de backup (G2) | |
| **R12** | Mudança no contrato depois de congelado quebra dashboard e scripts que evoluem em paralelo | média | alto | commit alterando `docs/CONTRATOS.md` | JSON Schema validando todo arquivo de `results/`; mudança exige acordo dos 3 integrantes | |
| **R13** | Streams da Global Table contabiliza registros de replicação em dobro (só se o cenário extra de reconstrução for implementado) | média | médio | estoque reconstruído diferente do real por múltiplo inteiro | filtrar por `regiao_ultima_escrita`; cenário é opcional e só entra com folga na S6 | |

## Leitura rápida

**Os três que mais merecem atenção agora:** I2 (conta AWS bloqueando tudo), R1 (risco de demo) e R2 (erro que só aparece tarde e custa recriar a tabela).

**R3 é especial.** É o único risco cuja materialização não é fracasso: se as sobrevendas não aparecerem, isso diz algo real sobre o comportamento do DynamoDB e rende discussão. O erro seria esconder o resultado ou forçar o experimento até dar o número esperado.

**R9 está marcado como probabilidade alta porque não é risco, é certeza** — restauração PITR sempre cria tabela nova e sempre demora. Está na matriz para ninguém ser pego de surpresa no dia.
