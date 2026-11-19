# Matriz de riscos

> Entregável da linha **A8**. Revisar em cada marco.
>
> **Versão 2 — projeto de região única.** A restrição de região da conta se materializou (I4) e alterou a matriz: três riscos foram encerrados junto com o desenho multi-região, e dois novos entraram.
>
> A coluna **sinal de alerta** é o que torna esta matriz utilizável: é o evento observável que diz "este risco está virando problema, aja agora". Risco sem sinal de alerta é decoração.

## Situação atual — o que já aconteceu

Problemas **já materializados**. Mudam a prioridade de tudo abaixo.

| ID | Problema | Consequência | Ação |
|---|---|---|---|
| **I1** | Cronograma deslocado ~3 semanas | as semanas dos Cenários A e B já passaram no plano original | replanejar; decidir o que corta |
| **I2** | ~~Conta AWS não provisionada~~ | **resolvido em 18/11** | — |
| **I3** | Coluna "Responsável" vazia em ~30 das 46 linhas | trabalho sem dono não acontece numa equipe de 3 | preencher antes do Marco 1 |
| **I4** | **A conta não suporta recursos entre regiões** | Global Tables fora; Cenário A redesenhado; §6.1 deixa de ser medida | projeto remodelado para região única; limitação documentada no relatório |

### Sobre o I4

A conta foi criada pela nova experiência de cadastro da AWS, que atribui uma única região ao projeto (`us-east-2`). A documentação da AWS afirma que recursos multi-região e entre regiões não são suportados **nem no plano gratuito nem no plano pago** dessa modalidade de conta, o que contradiz o que o console sugere ao oferecer a atualização de plano.

Alternativas avaliadas e descartadas:

| Alternativa | Por que foi descartada |
|---|---|
| Atualizar para o plano pago | sem volta, anexa cobrança real, e pela documentação não garante o recurso entre regiões |
| Conta de outro integrante | ninguém da equipe tem conta anterior à mudança |
| Conta institucional | não funcionou |

Decisão: **remodelar para região única**, com a perda de cobertura registrada em `docs/CENARIOS.md`.

---

## Riscos ativos

| ID | Risco | Prob. | Impacto | Sinal de alerta | Mitigação | Dono |
|---|---|---|---|---|---|---|
| **R14** | O plano gratuito restringe também **PITR, transações ou streams** — e o projeto inteiro passou a depender de PITR (D) e transações (A) | média | **muito alto** | primeiro `terraform apply` falha, ou `RestoreTableToPointInTime` / `TransactWriteItems` devolve erro de recurso indisponível | **verificar antes de escrever qualquer cenário**: criar tabela com PITR e rodar uma transação de teste | |
| **R2** | Tabela criada em on-demand torna o Cenário B impossível | média | alto | `billing_mode` diferente de `PROVISIONED` na `EstoqueThrottle` | checagem no `01_setup_table.py`, que já falha se não for provisionada | |
| **R3** | Cenário C não produz sobrevenda observável — janela de concorrência curta demais | média | alto | primeira rodada com `sobrevendas` = 0 no modo sem condição | aumentar o intervalo entre leitura e escrita e o paralelismo; se persistir, **é achado** e vai para o relatório | |
| **R4** | Resultados inválidos por estoque não resetado entre execuções | alta | médio | estoque inicial ≠ 100 no começo do cenário | `POST /reset` obrigatório + erro `ESTOQUE_NAO_RESETADO` que aborta | |
| **R5** | Custo acima do previsto, ou infraestrutura esquecida ligada | média | alto | alarme de orçamento dispara | orçamento no Terraform; `terraform destroy` no runbook; teardown ao fim do dia | |
| **R15** | Os créditos ou os 6 meses do plano gratuito acabam e **a conta fecha**, levando as tabelas junto | baixa | alto | notificação da AWS de crédito restante | entrega é 13/12 e o consumo é de centavos; manter `results/` versionado no Git, que é a evidência que importa | |
| **R6** | Credencial de AWS commitada no repositório | baixa | muito alto | revisão de commit | `.env` e `terraform.tfvars` no `.gitignore`, perfil do AWS CLI, varredura antes do code freeze | |
| **R7** | Atraso do CloudWatch (~5 min) faz o painel parecer quebrado na demo | alta | baixo | métrica vazia logo após o cenário | contadores do próprio script como fonte primária; CloudWatch com o atraso sinalizado na tela | |
| **R9** | Restauração PITR demora e só cria tabela nova | alta | médio | — (comportamento conhecido) | rodar o Cenário D antes e apresentar em replay; incluir as tabelas restauradas no teardown | |
| **R10** | "Funciona na minha máquina" — ambiente divergente entre integrantes | média | médio | runbook falha quando outro integrante executa | B7 exige execução por quem **não** escreveu o runbook | |
| **R11** | Wi-fi ou AWS indisponível no momento da apresentação | baixa | muito alto | — | modo replay + vídeo de backup | |
| **R12** | Mudança no contrato depois de congelado quebra dashboard e scripts em paralelo | média | alto | commit alterando `docs/CONTRATOS.md` | JSON Schema validando `results/`; mudança exige acordo dos 3 | |
| **R16** | A condição do Cenário A não falha de forma determinística, e a transferência conclui | baixa | médio | `transferencias_concluidas > 0` em qualquer modo | o destino é preparado acima do limite no início de cada rodada; a preparação é uma etapa própria (`preparando_destino`) | |

## Riscos encerrados

Mantidos no registro para rastreabilidade — quem leu a versão 1 encontra aqui o destino de cada um.

| ID | Risco | Por que foi encerrado |
|---|---|---|
| **R1** | Cenário A ao vivo estoura o tempo da apresentação | o Cenário A deixou de envolver operação de réplica; agora roda em segundos |
| **R8** | Convergência da Global Table mais lenta que o esperado | não há mais replicação entre regiões |
| **R13** | Streams da Global Table contabiliza registros de replicação em dobro | sem replicação entre regiões, o stream carrega só as escritas da aplicação — o que torna a extensão opcional **mais segura** do que era |

## Leitura rápida

**O risco que domina agora é o R14.** O projeto foi remodelado para depender de PITR e de transações, e ninguém ainda confirmou que esta conta oferece os dois. É uma verificação de quinze minutos que precisa acontecer **antes** de qualquer linha de código de cenário — porque, se algum deles também estiver restrito, o remodelamento precisa de outra rodada e o tempo para isso está acabando.

**O desenho de região única reduziu o risco agregado.** Três riscos saíram, o Cenário A ficou determinístico e rápido, e o maior perigo da apresentação ao vivo desapareceu. A troca foi cobertura por previsibilidade — e, com três semanas e meia até a entrega, foi uma troca favorável.

**R3 continua sendo o único risco cuja materialização não é fracasso.** Se as sobrevendas não aparecerem, isso diz algo real sobre a janela de concorrência e rende discussão. O erro seria ajustar o experimento até ele dar o número esperado.
