# Matriz de riscos

> Entregável da linha **A8**. Revisar em cada marco.
>
> **Versão 2 — projeto de região única.** A restrição de região da conta se materializou (I4) e alterou a matriz: três riscos foram encerrados junto com o desenho multi-região, e dois novos entraram.
>
> **Revisão de 27/11 — depois das execuções.** Com os quatro cenários rodados na AWS (A ×6, B ×3, C ×2, D ×2), R14, R2, R3 e R16 foram encerrados com evidência em `results/`. O que resta ativo é a apresentação e o teardown.
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
| **R4** | Resultados inválidos por estoque não resetado entre execuções | alta | médio | estoque inicial ≠ 100 no começo do cenário | `POST /reset` obrigatório + erro `ESTOQUE_NAO_RESETADO` que aborta | |
| **R5** | Custo acima do previsto, ou infraestrutura esquecida ligada | média | alto | alarme de orçamento dispara | orçamento no Terraform; `terraform destroy` no runbook; teardown ao fim do dia | |
| **R15** | Os créditos ou os 6 meses do plano gratuito acabam e **a conta fecha**, levando as tabelas junto | baixa | alto | notificação da AWS de crédito restante | entrega é 13/12 e o consumo é de centavos; manter `results/` versionado no Git, que é a evidência que importa | |
| **R6** | Credencial de AWS commitada no repositório | baixa | muito alto | revisão de commit | `.env` e `terraform.tfvars` no `.gitignore`, perfil do AWS CLI, varredura antes do code freeze | |
| **R7** | Atraso do CloudWatch (~5 min) faz o painel parecer quebrado na demo | alta | baixo | métrica vazia logo após o cenário | contadores do próprio script como fonte primária; CloudWatch com o atraso sinalizado na tela | |
| **R9** | Restauração PITR demora e só cria tabela nova | alta | médio | — (comportamento conhecido) | rodar o Cenário D antes e apresentar em replay; incluir as tabelas restauradas no teardown. Em 27/11, `list-tables` em `us-east-2` mostrava só `Estoque` e `EstoqueThrottle`: as duas tabelas restauradas já tinham sido apagadas | |
| **R10** | "Funciona na minha máquina" — ambiente divergente entre integrantes | média | médio | runbook falha quando outro integrante executa | B7 exige execução por quem **não** escreveu o runbook | |
| **R11** | Wi-fi ou AWS indisponível no momento da apresentação | baixa | muito alto | — | modo replay + vídeo de backup | |
| **R12** | Mudança no contrato depois de congelado quebra dashboard e scripts em paralelo | média | alto | commit alterando `docs/CONTRATOS.md` | JSON Schema validando `results/`; mudança exige acordo dos 3 | |

## Riscos encerrados

Mantidos no registro para rastreabilidade — quem leu a versão 1 encontra aqui o destino de cada um.

| ID | Risco | Por que foi encerrado |
|---|---|---|
| **R14** | O plano gratuito restringe também PITR, transações ou streams | a conta oferece os três: o `terraform apply` criou a `Estoque` com PITR e streams ligados, o Cenário A rodou `TransactWriteItems` seis vezes e o Cenário D restaurou por PITR duas vezes. A checagem de PITR e transações também está em `scripts/04_verificar_recursos.py` |
| **R2** | Tabela criada em on-demand torna o Cenário B impossível | a `EstoqueThrottle` está provisionada em 1 WCU e o Cenário B produziu throttling nas três execuções (42 a 44 rejeições de 100) |
| **R3** | Cenário C não produz sobrevenda observável | não se materializou: 248 e 249 sobrevendas sem condição, com `JANELA_S` de 20 ms |
| **R16** | A condição do Cenário A não falha de forma determinística | `transferencias_concluidas = 0` nos dois modos, em todas as seis execuções |
| **R1** | Cenário A ao vivo estoura o tempo da apresentação | o Cenário A deixou de envolver operação de réplica; agora roda em segundos |
| **R8** | Convergência da Global Table mais lenta que o esperado | não há mais replicação entre regiões |
| **R13** | Streams da Global Table contabiliza registros de replicação em dobro | sem replicação entre regiões, o stream carrega só as escritas da aplicação — o que torna a extensão opcional **mais segura** do que era |

## Leitura rápida

**Os riscos técnicos estão encerrados.** O R14, que dominava a versão anterior, não se materializou: a conta oferece PITR e transações, e os quatro cenários rodaram até o fim, com as hipóteses principais confirmadas (a H1 do B só em parte, por causa do burst; ver `docs/cenarios/B.md`). A evidência está versionada em `results/`.

**Os riscos que restam são de entrega e de custo.** R11 (apresentação sem rede) se resolve com o replay do dashboard e o vídeo de backup. R5 e R15 se resolvem com o `terraform destroy` depois da gravação: até lá, as duas tabelas continuam ligadas em `us-east-2`.

**O desenho de região única foi uma troca favorável.** Ele trocou cobertura por previsibilidade, e o resultado foi um Cenário A determinístico e rápido. O preço é a §6.1 sem medição, que precisa aparecer no relatório como limitação de ambiente.
