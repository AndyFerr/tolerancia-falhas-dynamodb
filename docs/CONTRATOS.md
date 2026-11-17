# Contratos técnicos

> Entregável da linha **A7**. Uma vez aprovado, este documento está **congelado**: mudar qualquer campo aqui exige acordo dos 3 integrantes, porque backend, scripts de cenário e dashboard são escritos em paralelo contra este texto.
>
> Versão 3 — alinhada ao código já existente em `lab/` e `terraform/` (branch `feat/infra-base`). Os nomes de campo seguem o código; o que mudou foi o documento.

## Regras gerais

1. **Unidade no nome do campo.** Toda medida de tempo termina em `_ms` ou `_s`.
2. **Timestamps em ISO 8601 UTC** com milissegundos e `Z`: `2026-11-20T14:30:12.483Z` (formato produzido por `lab/tempo.iso()`).
3. **Nomes em snake_case**, sem acento.
4. **Todo campo declarado aqui sempre existe.** Sem valor, vai `null` — nunca omitido.
5. **Região sempre pelo código da AWS** (`sa-east-1`), nunca pelo nome da cidade.
6. **Números monetários e decimais usam `Decimal`**, nunca `float` — o boto3 recusa `float` ao gravar no DynamoDB.

---

## 1. As duas tabelas

O projeto usa **duas** tabelas, com papéis distintos.

| Tabela | Regiões | Cobrança | Usada por |
|---|---|---|---|
| `Estoque` | `sa-east-1` (primária), réplicas em `us-east-1` e `eu-west-1` | sob demanda | Cenários A, C e D |
| `EstoqueThrottle` | só `sa-east-1` | provisionada, 1 WCU / 1 RCU | Cenário B |

A separação é deliberada: fixar 1 WCU na tabela global estrangularia também a replicação e inviabilizaria os Cenários A, C e D. Com a tabela dedicada, o throttling é provocado sem efeito colateral e sem esperar mudança de capacidade.

**Consequência para o Cenário B:** a capacidade é configuração fixa da tabela, não algo que o cenário manipula. Não existem etapas de reduzir e restaurar capacidade.

### O item

Mesmo formato nas duas tabelas.

```json
{
  "produto_id": "prod-042",
  "nome": "Produto 042",
  "quantidade": 100,
  "preco": 115.00,
  "versao": 1,
  "atualizado_em": "2026-11-20T14:30:12.483Z",
  "regiao_escrita": "sa-east-1",
  "escritor": "cenario_c"
}
```

| Campo | Tipo | Observação |
|---|---|---|
| `produto_id` | string | chave de partição — formato `prod-NNN`, gerado por `config.id_produto(n)` |
| `nome` | string | `Produto NNN` |
| `quantidade` | number | unidades disponíveis — **é o campo que os cenários movem** |
| `preco` | Decimal | preço unitário; base das métricas de valor do Cenário D |
| `versao` | number | incrementa a cada escrita; começa em **1** no seed; alvo do `ConditionExpression` no Cenário C |
| `atualizado_em` | string | carimbo **da aplicação**; não é o que o DynamoDB usa para desempatar conflito |
| `regiao_escrita` | string | região que gravou — evidência de quem venceu o conflito |
| `escritor` | string | processo que gravou: `seed`, `reset`, `cenario_a`…`cenario_d` |

**Seed (linha B4):** 50 produtos (`prod-001` a `prod-050`), `quantidade` 100, `versao` 1, na tabela `Estoque`. Na `EstoqueThrottle` entra **apenas o produto usado pelo Cenário B** — gravar 50 itens a 1 WCU levaria perto de um minuto só de throttling no próprio seed.

**`preco` é determinístico**, função de `n`, para que o valor total do estoque seja reproduzível entre execuções e sirva de checksum.

> **Consequência do modelo.** Os cenários **decrementam** em vez de criar itens, então a contagem de registros nunca muda. O que converge entre regiões é o valor de `quantidade`. Por isso os cards do dashboard mostram unidades, não número de itens.

---

## 2. O arquivo de resultado (`results/cenario_X_*.json`)

Todos os cenários usam o **mesmo envelope**. Só `parametros` e `metricas` mudam.

```json
{
  "schema_version": "3.0",
  "cenario": "A",
  "execucao_id": "a-2026-11-20T143000Z",
  "inicio": "2026-11-20T14:30:00.000Z",
  "fim": "2026-11-20T14:33:34.700Z",
  "duracao_s": 214.7,
  "status": "concluido",
  "parametros": {},
  "metricas": {},
  "erro": null
}
```

| Campo | Valores |
|---|---|
| `schema_version` | `"3.0"` |
| `cenario` | `A`, `B`, `C` ou `D` |
| `execucao_id` | `<cenario minúsculo>-<timestamp compacto>` — também é o nome do arquivo |
| `status` | `concluido`, `erro`, `em_andamento` |
| `erro` | objeto da seção 4, ou `null` |

### Cenário A — falha de região

**Provoca a falha removendo a réplica** via `UpdateTable`. É a única forma usada: apontar o cliente para um endpoint inválido não remove a cópia dos dados, a replicação continua normal e não existe convergência para medir.

```json
"parametros": {
  "tabela": "Estoque",
  "regiao_removida": "us-east-1",
  "regiao_venda": "sa-east-1",
  "n_vendas": 100
},
"metricas": {
  "vendas_aceitas": 100,
  "vendas_rejeitadas": 0,
  "unidades_antes": 5000,
  "unidades_apos_vendas": 4900,
  "tempo_convergencia_ms": 1842,
  "unidades_por_regiao": {
    "sa-east-1": 4900,
    "us-east-1": 4900,
    "eu-west-1": 4900
  }
}
```

`tempo_convergencia_ms` é medido de quando a réplica volta a `ACTIVE` até `unidades_por_regiao` ficar igual nas três.

### Cenário B — throttling em produto quente

Roda contra `EstoqueThrottle`, que já está em 1 WCU. Duas fases sobre o mesmo produto.

```json
"parametros": {
  "tabela": "EstoqueThrottle",
  "produto_id": "prod-007",
  "write_capacity_units": 1,
  "n_vendas": 100
},
"metricas": {
  "fase_sem_retry": {
    "vendas_concluidas": 12,
    "vendas_perdidas": 88,
    "throttled": 88,
    "tentativas_totais": 100,
    "duracao_ms": 3180
  },
  "fase_com_backoff": {
    "vendas_concluidas": 100,
    "vendas_perdidas": 0,
    "throttled": 0,
    "tentativas_totais": 243,
    "duracao_ms": 47090
  }
}
```

`write_capacity_units` é registrado como **contexto**, não como algo que o cenário alterou.

O cliente precisa desligar o retry do SDK para medir o próprio backoff — `aws.cliente(regiao, tentativas=1)`.

`vendas_perdidas` é a leitura de negócio do throttling: não é erro abstrato, é venda que não aconteceu.

### Cenário C — conflito last-writer-wins e sobrevenda

Duas regiões vendem o mesmo produto ao mesmo tempo. Três modos, mesma estrutura de métricas.

```json
"parametros": {
  "tabela": "Estoque",
  "produto_id": "prod-042",
  "quantidade_inicial": 100,
  "vendas_por_regiao": 50,
  "regioes": ["sa-east-1", "eu-west-1"],
  "rodadas": 5
},
"metricas": {
  "modos": {
    "sem_condicao": {
      "vendas_confirmadas": 100,
      "quantidade_esperada": 0,
      "quantidade_final": 63,
      "sobrevendas": 63,
      "conflitos_detectados": 0,
      "convergencia_p50_ms": 1240,
      "convergencia_p95_ms": 1884
    },
    "com_condicao_multi_regiao": {
      "vendas_confirmadas": 98,
      "quantidade_esperada": 2,
      "quantidade_final": 41,
      "sobrevendas": 39,
      "conflitos_detectados": 2,
      "convergencia_p50_ms": 1310,
      "convergencia_p95_ms": 1960
    },
    "com_condicao_regiao_unica": {
      "vendas_confirmadas": 100,
      "quantidade_esperada": 0,
      "quantidade_final": 0,
      "sobrevendas": 0,
      "conflitos_detectados": 37,
      "convergencia_p50_ms": null,
      "convergencia_p95_ms": null
    }
  }
}
```

| Campo | Significado |
|---|---|
| `vendas_confirmadas` | quantas vendas a aplicação **disse ao cliente** que deram certo |
| `quantidade_esperada` | `quantidade_inicial − vendas_confirmadas` |
| `quantidade_final` | o que a tabela mostra depois da convergência |
| `sobrevendas` | `quantidade_final − quantidade_esperada` — unidades vendidas que nunca saíram da prateleira |
| `conflitos_detectados` | `ConditionalCheckFailedException` capturadas |

O modo `com_condicao_regiao_unica` é o **controle**: ele deve zerar as sobrevendas. Os outros dois não devem — e é essa diferença que é o achado.

Os números acima são **formato, não previsão**. A hipótese fica em `docs/cenarios/C.md`.

### Cenário D — recuperação via PITR

```json
"parametros": {
  "tabela": "Estoque",
  "tipo_corrupcao": "quantidade_zerada_em_massa",
  "produtos_afetados": 40,
  "instante_restauracao": "2026-11-20T14:20:00.000Z",
  "tabela_restaurada": "Estoque_restore_20261120T1430"
},
"metricas": {
  "produtos_antes": 50,
  "unidades_antes": 5000,
  "unidades_apos_corrupcao": 1000,
  "valor_antes": 64950.00,
  "valor_apos_corrupcao": 12990.00,
  "produtos_restaurados": 50,
  "unidades_restauradas": 5000,
  "valor_restaurado": 64950.00,
  "divergencias": 0,
  "checksum_antes": "a3f1c0d9",
  "checksum_depois": "a3f1c0d9",
  "duracao_restauracao_s": 612
}
```

`valor_*` é a soma de `preco × quantidade` — um checksum de negócio, legível para quem não é técnico. É o motivo de `preco` existir no item.

Como em todos os exemplos deste documento, os números acima são **formato, não previsão**: o valor real decorre da função `config.preco(n)` e da quantidade corrente.

---

## 3. A API REST

Base: `http://localhost:8080`

### `GET /status`

Consultado pelo dashboard a cada poucos segundos. Reporta a tabela `Estoque`; a `EstoqueThrottle` não aparece nos cards.

```json
{
  "tabela": "Estoque",
  "consultado_em": "2026-11-20T14:28:03.221Z",
  "regioes": [
    { "regiao": "sa-east-1", "rotulo": "São Paulo", "estado": "ACTIVE", "itens": 50, "unidades": 5000 },
    { "regiao": "us-east-1", "rotulo": "Virgínia",  "estado": "ACTIVE", "itens": 50, "unidades": 5000 },
    { "regiao": "eu-west-1", "rotulo": "Irlanda",   "estado": "ACTIVE", "itens": 50, "unidades": 5000 }
  ],
  "execucao_em_andamento": null
}
```

`estado` repassa o valor da AWS: `ACTIVE`, `CREATING`, `UPDATING`, `DELETING`, ou `AUSENTE` quando a réplica não existe.

`itens` e `unidades` vêm de `lab.aws.resumo_regiao()` — um `Scan` paginado projetando só `quantidade`. **Não** usar o `ItemCount` do `DescribeTable`: é aproximado, atualiza a cada ~6 horas e, neste modelo, nem mudaria.

### `POST /cenario/{a|b|c|d}`

Dispara em segundo plano e responde **imediatamente** com `202`. Sem corpo na requisição — os parâmetros são fixos no script.

```json
{ "execucao_id": "a-2026-11-20T143000Z", "status": "em_andamento" }
```

Com execução em andamento, responde `409`.

### `GET /execucao/{execucao_id}`

```json
{
  "execucao_id": "a-2026-11-20T143000Z",
  "status": "em_andamento",
  "etapa": "vendendo_durante_queda",
  "progresso": { "atual": 57, "total": 100 }
}
```

Ao terminar, devolve o envelope completo da seção 2.

| Cenário | Etapas |
|---|---|
| A | `removendo_replica`, `vendendo_durante_queda`, `recriando_replica`, `medindo_convergencia` |
| B | `fase_sem_retry`, `fase_com_backoff` |
| C | `modo_sem_condicao`, `modo_com_condicao_multi_regiao`, `modo_com_condicao_regiao_unica`, `aguardando_convergencia` |
| D | `corrompendo_quantidade`, `restaurando_pitr`, `comparando_itens` |

### `GET /resultados`

Lista as execuções gravadas em `results/`. Alimenta o modo replay.

```json
{
  "execucoes": [
    { "execucao_id": "a-2026-11-20T143000Z", "cenario": "A", "fim": "2026-11-20T14:33:34.700Z", "status": "concluido" }
  ]
}
```

### `POST /reset`

Chama o equivalente de `scripts/03_reset.py`: regrava os 50 produtos com 100 unidades e `versao` 1 nas duas tabelas, e remove itens que não pertençam ao conjunto.

```json
{ "produtos_resetados": 50, "unidades": 5000, "sobras_removidas": 0 }
```

Necessário entre execuções: sem isso, a rodada seguinte começa com estoque já consumido e os números perdem sentido.

---

## 4. Erros

```json
{
  "erro": {
    "codigo": "EXECUCAO_EM_ANDAMENTO",
    "mensagem": "Já existe uma execução em andamento (a-2026-11-20T143000Z).",
    "etapa": null
  }
}
```

| Código | HTTP | Quando |
|---|---|---|
| `EXECUCAO_EM_ANDAMENTO` | 409 | tentou disparar cenário com outro rodando |
| `EXECUCAO_NAO_ENCONTRADA` | 404 | `execucao_id` inexistente |
| `ESTOQUE_NAO_RESETADO` | 409 | cenário exige estoque cheio e encontrou estoque parcial |
| `CREDENCIAIS_INVALIDAS` | 500 | boto3 sem credencial válida |
| `FALHA_AWS` | 502 | erro devolvido pela AWS no meio do cenário |
| `TABELA_INDISPONIVEL` | 503 | tabela não está `ACTIVE` nas regiões necessárias |

Cenário que falha no meio **grava o arquivo mesmo assim**, com `status: "erro"` e a `etapa` em que parou. Execução que falhou também é evidência.

---

## Onde cada coisa mora

| O quê | Caminho | Versionado? |
|---|---|---|
| Este contrato | `docs/CONTRATOS.md` | sim |
| Exemplos executáveis (mocks de B5/B6) | `scenarios/fixtures/*.json` | sim |
| Resultados reais | `results/*.json` | sim — é a evidência do trabalho |
| Schema de validação (opcional) | `docs/schemas/resultado.schema.json` | sim |
