# Cenário B — throttling em produto quente

> Entregável das linhas **D1** (metodologia) e **D5** (execuções).
> Implementação: `scenarios/cenario_b.py` · Resultados: `results/cenario_b_*.json`

## Pergunta

O que acontece com uma carga acima da capacidade da tabela, e quanto do resultado final depende do comportamento do cliente e não do banco?

## Amarração com o paper

A §4 inteira trata de *admission control*: como o DynamoDB decide aceitar ou recusar uma requisição. Dois trechos importam aqui.

**§4.1.1 — bursting.** O serviço retém a capacidade não usada de uma partição por **até 300 segundos** e a libera quando o consumo passa do provisionado. Uma tabela ociosa chega ao experimento com capacidade acumulada.

**§4.4 — split por consumo.** O DynamoDB divide automaticamente uma partição quando o throughput consumido cruza um limiar, escolhendo o ponto de corte pela distribuição de chaves observada. Mas o paper nomeia **dois padrões que o split não resolve**: tráfego concentrado em **um único item** e faixa de chaves acessada sequencialmente. Nesses casos o serviço detecta o padrão e evita dividir.

Este cenário constrói deliberadamente o primeiro caso: toda a carga em `prod-007`.

## Por que uma tabela separada

A `EstoqueThrottle` existe só para isto, fixa em **1 WCU**. Estrangular a tabela principal afetaria os Cenários A, C e D, e mudar capacidade de tabela demora e tem limite diário de reduções. Com a tabela dedicada, o throttling é provocado sem efeito colateral e sem espera.

A capacidade é, portanto, **configuração fixa** — não algo que o cenário manipula. Ela aparece em `parametros` como contexto.

## Hipóteses

- **H1** — Sem tratamento de retry, uma parte significativa das escritas é rejeitada com `ProvisionedThroughputExceededException`, e a fase termina rápido: falhar é barato.
- **H2** — Com backoff exponencial e jitter, a taxa de sucesso se aproxima de 100%, **ao custo de uma duração total muito maior**.
- **H3** — Como a carga se concentra em um único item, o throttling **não diminui ao longo da execução**: não há split que resolva.

## Procedimento

| Etapa | Ação |
|---|---|
| — | `scripts/03_reset.py`; o cenário aborta se `prod-007` não estiver com 100 unidades |
| aquecimento | escreve até ocorrerem **10 throttles seguidos** (ou 90 s), consumindo a capacidade de burst |
| `fase_sem_retry` | 100 vendas, **uma tentativa cada**, com o retry do SDK desligado (`aws.cliente(regiao, tentativas=1)`) |
| `fase_com_backoff` | as mesmas 100 vendas, com backoff exponencial e **jitter completo** feito pelo cenário, até 15 tentativas por venda |

Entre as fases o produto volta a 100 unidades — e essa reposição também sofre throttling, então ela própria insiste com backoff.

**Desligar o retry do SDK é obrigatório.** Sem isso o boto3 aplica o backoff dele por baixo e as duas fases medem a mesma coisa.

A taxa de throttle é registrada **por janela de um segundo** (`throttle_por_janela`), que é o que permite testar H3: um número agregado não distingue "melhorou com o tempo" de "oscilou".

## Resultados medidos

Três execuções: as duas primeiras com dois minutos entre elas, a terceira no dia seguinte.

| Execução | `sem_retry` concluídas | `com_backoff` concluídas | tentativas no backoff | duração sem retry | duração com backoff |
|---|---|---|---|---|---|
| `b-2026-11-23T222419Z` | **58/100** | **100/100** | 125 | 12,7 s | 19,6 s |
| `b-2026-11-23T222821Z` | **56/100** | **100/100** | 127 | 12,7 s | 20,1 s |
| `b-2026-11-25T002408Z` | **56/100** | **100/100** | 127 | 12,6 s | 20,1 s |

Aquecimento: 38 escritas e 28 aceitas pelo burst nas duas primeiras, 40 e 30 na terceira. Em todas levou ~5 s e alcançou throttling contínuo.

Throttles por janela de 1 s, primeira execução:

```
janela:  1  2  3  4  5  6  7  8  9 10 11 12 13
throttle: 0  0  4  8  6  0  0  6  6  0  0  8  4
```

Segunda execução: `4, 0, 1, 8, 8, 1, 0, 3, 8, 0, 0, 6, 5`.

Terceira execução: `0, 0, 4, 8, 8, 0, 0, 6, 7, 0, 0, 7, 4`.

## Interpretação

**H2 confirmada sem ressalvas.** Nas três execuções o backoff levou a taxa de sucesso de ~57% para 100%, com cerca de 25 tentativas extras e um acréscimo de ~7 segundos. É a troca central do cenário: **o cliente compra sucesso com latência**. O banco não mudou entre as duas fases.

**H3 confirmada, e é o resultado mais forte.** A série por janela não decresce — ela **oscila**. Janelas inteiras sem nenhum throttle alternam com janelas em que 8 de 8 tentativas são recusadas. Esse padrão é compatível com o enchimento e esvaziamento de um token bucket, e é incompatível com a hipótese de que o serviço estaria dividindo a partição para absorver a carga. É exatamente o que a §4.4 prevê para item único: o DynamoDB detecta o padrão e **evita** dividir, porque dividir não resolveria.

**H1 confirmada apenas em parte — e a discrepância é o achado mais interessante.**

A tabela tem 1 WCU e a fase sem retry durou 12,7 segundos. A capacidade provisionada daria conta de cerca de **13 escritas**. Foram aceitas **58**.

A diferença é a **capacidade de burst da §4.1.1**. Mesmo com o aquecimento drenando o burst até 10 throttles seguidos, a reposição do produto entre o aquecimento e a fase 1 — que insiste com backoff por alguns segundos — devolve tempo ocioso à tabela, e parte dos tokens volta a acumular. A fase 1 mede, portanto, **1 WCU mais o resíduo de burst**, não 1 WCU puro.

Isso não invalida a comparação entre as fases, que é o objeto do cenário: as duas sofrem o mesmo viés. Mas significa que **o número 58 não deve ser lido como "o DynamoDB aceita 58 escritas por segundo com 1 WCU"**. Ele mede a capacidade efetiva de uma tabela que esteve ociosa por alguns segundos — que é, aliás, o comportamento real que uma aplicação encontraria.

Para isolar o limite puro, o aquecimento precisaria terminar imediatamente antes da fase, sem reposição no meio. Fica registrado como limitação, não como correção pendente: o burst **faz parte** do admission control que o cenário se propôs a observar.

## O que este cenário não mede

**Adaptive capacity e GAC (§4.1.2, §4.2).** Atuam antes de o cliente ver qualquer coisa, e o sucesso deles é a *ausência* de sintoma. Nada no lado do cliente os distingue.

**O limite de 1 WCU isolado**, pelo motivo acima.

**Métricas do CloudWatch.** A linha D4 prevê cruzar `ThrottledRequests` e `ConsumedWriteCapacityUnits` com os contadores do script, tratando o atraso de ~5 minutos da publicação. Ainda não foi feito; os contadores do script são a fonte primária, como define o contrato.

## Como reproduzir

```bash
source .venv/bin/activate
python scripts/03_reset.py && python scenarios/cenario_b.py
```

Cada execução leva cerca de 40 segundos. Entre execuções, deixe alguns minutos: a tabela precisa de tempo ocioso para que o aquecimento tenha burst a drenar, e o resultado fica mais comparável.
