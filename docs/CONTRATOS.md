# Contratos técnicos

> Entregável da linha **A7**. Uma vez aprovado, este documento está **congelado**: mudar qualquer campo aqui exige acordo dos 3 integrantes, porque backend, scripts de cenário e dashboard são escritos em paralelo contra este texto.
>
> Modelo de domínio: **estoque de produtos**. Cada cenário provoca uma falha e mede a consequência em unidades de estoque — não em contagem de registros.

## Regras gerais

1. **Unidade no nome do campo.** Toda medida de tempo termina em `_ms` ou `_s`. Nunca existe um campo `duracao` sem sufixo.
2. **Timestamps em ISO 8601 UTC** com `Z` no fim: `2026-11-20T14:30:12.483Z`.
3. **Nomes em snake_case**, sem acento. Rótulos com acento só em campos de exibição (`rotulo`).
4. **Todo campo declarado aqui sempre existe.** Se não há valor, vai `null` — nunca omitido.
5. **Região sempre pelo código da AWS** (`sa-east-1`), nunca pelo nome da cidade.
6. **Estoque nunca é recalculado pelo dashboard.** O número exibido é o que o script mediu; a tela não faz aritmética sobre dados de cenário.

---

## 1. O item na tabela `Estoque`

Não aparece individualmente no dashboard. É a matéria-prima que os cenários decrementam.

```json
{
  "produto_id": "SKU-0042",
  "nome": "Fone bluetooth",
  "preco": 129.90,
  "estoque": 100,
  "versao": 7,
  "regiao_ultima_escrita": "sa-east-1",
  "atualizado_em": "2026-11-20T14:30:12.483Z"
}
```

| Campo | Tipo | Observação |
|---|---|---|
| `produto_id` | string | chave de partição — formato `SKU-NNNN` |
| `nome` | string | valor sintético do seed |
| `preco` | number | duas casas decimais |
| `estoque` | number | unidades disponíveis — **é o campo que os cenários movem** |
| `versao` | number | contador incrementado a cada escrita; alvo do `ConditionExpression` no Cenário C |
| `regiao_ultima_escrita` | string | qual região gravou por último — evidência de quem venceu o conflito |
| `atualizado_em` | string | carimbo **da aplicação**; não é o que o DynamoDB usa para desempatar |

**Seed (linha B4):** 50 produtos, `estoque` inicial 100 em cada, `versao` 0.

> **Consequência importante do modelo.** Como os cenários **decrementam** em vez de criar itens, a contagem de registros não muda nunca. O que converge entre regiões é o **valor** do campo `estoque`. Por isso os cards do dashboard mostram total de unidades, não número de itens.

---

## 2. O arquivo de resultado (`results/cenario_X_*.json`)

Todos os quatro cenários usam o **mesmo envelope**. Só `parametros` e `metricas` mudam.

```json
{
  "schema_version": "2.0",
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

| Campo | Tipo | Valores |
|---|---|---|
| `schema_version` | string | `"2.0"` — versão do modelo de estoque |
| `cenario` | string | `A`, `B`, `C` ou `D` |
| `execucao_id` | string | `<cenario minúsculo>-<timestamp compacto>` — também é o nome do arquivo |
| `status` | string | `concluido`, `erro`, `em_andamento` |
| `erro` | object \| null | preenchido só quando `status` = `erro` (ver seção 4) |

### Cenário A — falha de região

Vende durante a queda de uma réplica e mede quando o estoque converge.

```json
"parametros": {
  "regiao_removida": "us-east-1",
  "regiao_venda": "sa-east-1",
  "n_vendas": 100,
  "produtos_envolvidos": 50
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

`tempo_convergencia_ms` é medido do momento em que a réplica volta a `ACTIVE` até `unidades_por_regiao` ficar igual nas três.

### Cenário B — throttling em produto quente

Promoção relâmpago em **um único produto** — que é exatamente o caso que a §4.4 diz não se resolver com split de partição.

```json
"parametros": {
  "produto_id": "SKU-0007",
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

`vendas_perdidas` é a leitura de negócio do throttling: não é um erro abstrato, é venda que não aconteceu.

### Cenário C — conflito last-writer-wins e sobrevenda

O cenário central do modelo de estoque. Duas regiões vendem o mesmo produto ao mesmo tempo. Três modos, mesma estrutura de métricas, para isolar o que a escrita condicional resolve e o que ela não resolve.

```json
"parametros": {
  "produto_id": "SKU-0042",
  "estoque_inicial": 100,
  "vendas_por_regiao": 50,
  "regioes": ["sa-east-1", "eu-west-1"],
  "rodadas": 5
},
"metricas": {
  "modos": {
    "sem_condicao": {
      "vendas_confirmadas": 100,
      "estoque_esperado": 0,
      "estoque_final": 63,
      "sobrevendas": 63,
      "conflitos_detectados": 0,
      "convergencia_p50_ms": 1240,
      "convergencia_p95_ms": 1884
    },
    "com_condicao_multi_regiao": {
      "vendas_confirmadas": 98,
      "estoque_esperado": 2,
      "estoque_final": 41,
      "sobrevendas": 39,
      "conflitos_detectados": 2,
      "convergencia_p50_ms": 1310,
      "convergencia_p95_ms": 1960
    },
    "com_condicao_regiao_unica": {
      "vendas_confirmadas": 100,
      "estoque_esperado": 0,
      "estoque_final": 0,
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
| `estoque_esperado` | `estoque_inicial − vendas_confirmadas` |
| `estoque_final` | o que a tabela realmente mostra depois da convergência |
| `sobrevendas` | `estoque_final − estoque_esperado` — unidades vendidas que nunca saíram da prateleira |
| `conflitos_detectados` | `ConditionalCheckFailedException` capturadas |

O modo `com_condicao_regiao_unica` é o controle: ele deve zerar as sobrevendas. Os dois primeiros modos não devem zerar — e é essa diferença que é o achado do cenário.

### Cenário D — recuperação via PITR

Atualização em massa que zera o estoque por engano, restaurada por point-in-time.

```json
"parametros": {
  "tipo_corrupcao": "estoque_zerado_em_massa",
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
  "divergencias": 0,
  "checksum_antes": "a3f1c0d9",
  "checksum_depois": "a3f1c0d9",
  "duracao_restauracao_s": 612
}
```

`valor_*` é a soma de `preco × estoque` — um checksum de negócio, legível para quem não é técnico.

---

## 3. A API REST

Base: `http://localhost:8080`

### `GET /status`

Consultado pelo dashboard a cada poucos segundos. É o que pinta os cards.

```json
{
  "tabela": "Estoque",
  "consultado_em": "2026-11-20T14:28:03.221Z",
  "regioes": [
    { "regiao": "sa-east-1", "rotulo": "São Paulo", "estado": "ACTIVE", "produtos": 50, "unidades": 5000 },
    { "regiao": "us-east-1", "rotulo": "Virgínia",  "estado": "ACTIVE", "produtos": 50, "unidades": 5000 },
    { "regiao": "eu-west-1", "rotulo": "Irlanda",   "estado": "ACTIVE", "produtos": 50, "unidades": 5000 }
  ],
  "execucao_em_andamento": null
}
```

`estado` repassa o valor da AWS: `ACTIVE`, `CREATING`, `UPDATING`, `DELETING`, ou `AUSENTE` quando a réplica não existe.

`produtos` e `unidades` vêm de um `Scan` por região somando o campo `estoque` — **não** do `ItemCount` do `DescribeTable`, que é aproximado, só atualiza a cada ~6 horas e, neste modelo, nem mudaria (o número de itens é constante). Com 50 produtos o `Scan` é instantâneo.

### `POST /cenario/{a|b|c|d}`

Dispara o cenário em segundo plano e responde **imediatamente** com `202`. Cenários levam minutos; segurar a conexão estouraria o timeout do navegador. Sem corpo na requisição — os parâmetros são fixos no script.

```json
{
  "execucao_id": "a-2026-11-20T143000Z",
  "status": "em_andamento"
}
```

Se já houver execução em andamento, responde `409` com o corpo de erro da seção 4.

### `GET /execucao/{execucao_id}`

O dashboard consulta em intervalo regular até `status` sair de `em_andamento`.

```json
{
  "execucao_id": "a-2026-11-20T143000Z",
  "status": "em_andamento",
  "etapa": "vendendo_durante_queda",
  "progresso": { "atual": 57, "total": 100 }
}
```

Ao terminar, devolve **o envelope completo da seção 2** — o mesmo conteúdo gravado em `results/`.

| Cenário | Etapas |
|---|---|
| A | `removendo_replica`, `vendendo_durante_queda`, `recriando_replica`, `medindo_convergencia` |
| B | `reduzindo_capacidade`, `fase_sem_retry`, `fase_com_backoff`, `restaurando_capacidade` |
| C | `modo_sem_condicao`, `modo_com_condicao_multi_regiao`, `modo_com_condicao_regiao_unica`, `aguardando_convergencia` |
| D | `corrompendo_estoque`, `restaurando_pitr`, `comparando_itens` |

### `GET /resultados`

Lista as execuções já gravadas em `results/`. Alimenta o **modo replay**.

```json
{
  "execucoes": [
    { "execucao_id": "a-2026-11-20T143000Z", "cenario": "A", "fim": "2026-11-20T14:33:34.700Z", "status": "concluido" }
  ]
}
```

### `POST /reset`

Repõe o estoque de todos os produtos para 100 e zera `versao`. Necessário entre execuções — sem isso, a segunda rodada do Cenário C começa com estoque já consumido.

```json
{ "produtos_resetados": 50, "unidades": 5000 }
```

---

## 4. Erros

Mesmo formato em qualquer endpoint. O dashboard nunca mostra stack trace.

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

Quando um cenário falha no meio, o arquivo em `results/` **é gravado mesmo assim**, com `status: "erro"` e a `etapa` em que parou. Execução que falhou também é evidência.

---

## Onde cada coisa mora

| O quê | Caminho | Versionado? |
|---|---|---|
| Este contrato | `docs/CONTRATOS.md` | sim |
| Exemplos executáveis (mocks de B5/B6) | `scenarios/fixtures/*.json` | sim |
| Resultados reais das execuções | `results/*.json` | sim — é a evidência do trabalho |
| Schema de validação (opcional) | `docs/schemas/resultado.schema.json` | sim |
