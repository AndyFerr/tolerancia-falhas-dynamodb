# Contratos técnicos

> Entregável da linha **A7**. Uma vez aprovado, este documento está **congelado**: mudar qualquer campo aqui exige acordo dos 3 integrantes, porque backend, scripts de cenário e dashboard são escritos em paralelo contra este texto.
>
> **Versão 4 — projeto de região única (`us-east-2`).** A conta do grupo não suporta recursos entre regiões, então Global Tables está fora. Ver `docs/RISCOS.md` (I4) e `docs/CENARIOS.md`.

## Regras gerais

1. **Unidade no nome do campo.** Toda medida de tempo termina em `_ms` ou `_s`.
2. **Timestamps em ISO 8601 UTC** com milissegundos e `Z` — formato produzido por `lab/tempo.iso()`.
3. **Nomes em snake_case**, sem acento.
4. **Todo campo declarado aqui sempre existe.** Sem valor, vai `null` — nunca omitido.
5. **Região sempre pelo código da AWS** (`us-east-2`), nunca pelo nome da cidade.
6. **Números monetários e decimais usam `Decimal`**, nunca `float` — o boto3 recusa `float` ao gravar no DynamoDB.

---

## 1. As duas tabelas

Ambas em **`us-east-2`**, com papéis distintos.

| Tabela | Cobrança | Usada por |
|---|---|---|
| `Estoque` | sob demanda | Cenários A, C e D |
| `EstoqueThrottle` | provisionada, 1 WCU / 1 RCU | Cenário B |

A separação é deliberada: fixar 1 WCU na tabela principal estrangularia também os outros cenários. Com a tabela dedicada, o throttling é provocado sem efeito colateral e sem esperar mudança de capacidade.

**Consequência para o Cenário B:** a capacidade é configuração fixa da tabela, não algo que o cenário manipula.

### O item

Mesmo formato nas duas tabelas.

```json
{
  "produto_id": "prod-042",
  "nome": "Produto 042",
  "quantidade": 100,
  "preco": 115.00,
  "versao": 1,
  "atualizado_em": "2026-11-25T14:30:12.483Z",
  "regiao_escrita": "us-east-2",
  "escritor": "cenario_c"
}
```

| Campo | Tipo | Observação |
|---|---|---|
| `produto_id` | string | chave de partição — formato `prod-NNN`, de `config.id_produto(n)` |
| `nome` | string | `Produto NNN` |
| `quantidade` | number | unidades disponíveis — **é o campo que os cenários movem** |
| `preco` | Decimal | preço unitário; base das métricas de valor dos Cenários A e D |
| `versao` | number | incrementa a cada escrita; começa em **1**; alvo do `ConditionExpression` no Cenário C |
| `atualizado_em` | string | carimbo da aplicação |
| `regiao_escrita` | string | mantido no schema por estabilidade; com região única o valor é sempre `us-east-2` |
| `escritor` | string | processo que gravou: `seed`, `reset`, `cenario_a`…`cenario_d` |

**Seed (linha B4):** 50 produtos (`prod-001` a `prod-050`), `quantidade` 100, `versao` 1, na tabela `Estoque`. Na `EstoqueThrottle` entra **apenas o produto do Cenário B** — gravar 50 itens a 1 WCU levaria perto de um minuto só de throttling no próprio seed.

**`preco` é determinístico**, função de `n`, para que o valor total do estoque seja reproduzível e sirva de checksum.

> **Consequência do modelo.** Os cenários **movem** `quantidade` em vez de criar itens, então a contagem de registros é constante. O que varia é o valor do campo. Por isso o dashboard mostra unidades, não número de itens.

---

## 2. O arquivo de resultado (`results/cenario_X_*.json`)

Envelope único para os quatro cenários; só `parametros` e `metricas` mudam.

```json
{
  "schema_version": "4.0",
  "cenario": "A",
  "execucao_id": "a-2026-11-25T143000Z",
  "inicio": "2026-11-25T14:30:00.000Z",
  "fim": "2026-11-25T14:30:11.400Z",
  "duracao_s": 11.4,
  "status": "concluido",
  "parametros": {},
  "metricas": {},
  "erro": null
}
```

| Campo | Valores |
|---|---|
| `schema_version` | `"4.0"` |
| `cenario` | `A`, `B`, `C` ou `D` |
| `execucao_id` | `<cenario minúsculo>-<timestamp compacto>` — também é o nome do arquivo |
| `status` | `concluido`, `erro`, `em_andamento` |
| `erro` | objeto da seção 4, ou `null` |

### Cenário A — escrita parcial vs. transação

Transferência de unidades entre dois produtos, com a segunda escrita falhando por regra de negócio no destino.

```json
"parametros": {
  "tabela": "Estoque",
  "produto_origem": "prod-001",
  "produto_destino": "prod-050",
  "unidades_transferidas": 10,
  "limite_prateleira": 100,
  "rodadas": 5
},
"metricas": {
  "modos": {
    "sem_transacao": {
      "transferencias_tentadas": 5,
      "transferencias_concluidas": 0,
      "unidades_totais_antes": 5000,
      "unidades_totais_depois": 4950,
      "unidades_perdidas": 50,
      "estado_parcial": true
    },
    "com_transacao": {
      "transferencias_tentadas": 5,
      "transferencias_concluidas": 0,
      "unidades_totais_antes": 5000,
      "unidades_totais_depois": 5000,
      "unidades_perdidas": 0,
      "estado_parcial": false
    }
  }
}
```

| Campo | Significado |
|---|---|
| `transferencias_concluidas` | transferências que terminaram com origem e destino atualizados — por desenho, **zero nos dois modos** |
| `unidades_perdidas` | `unidades_totais_antes − unidades_totais_depois` — unidades que saíram da origem e não chegaram ao destino |
| `estado_parcial` | se alguma escrita foi aplicada sem a sua contraparte |

O invariante medido é a **conservação de unidades**: uma transferência não pode mudar o total do estoque.

### Cenário B — throttling em produto quente

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

`write_capacity_units` é registrado como **contexto**, não como algo alterado pelo cenário.

O cliente precisa desligar o retry do SDK para medir o próprio backoff — `aws.cliente(regiao, tentativas=1)`.

Para a hipótese H3 (item quente não se beneficia de split), gravar também a série por janela:

```json
"throttle_por_janela": [
  { "janela_s": 1, "tentativas": 34, "throttled": 31 },
  { "janela_s": 2, "tentativas": 33, "throttled": 30 },
  { "janela_s": 3, "tentativas": 33, "throttled": 27 }
]
```

### Cenário C — atualização perdida e sobrevenda

Dois processos concorrentes sobre o mesmo item, na mesma região.

```json
"parametros": {
  "tabela": "Estoque",
  "produto_id": "prod-042",
  "quantidade_inicial": 100,
  "processos": 2,
  "vendas_por_processo": 50,
  "rodadas": 5
},
"metricas": {
  "modos": {
    "sem_condicao": {
      "vendas_confirmadas": 100,
      "quantidade_esperada": 0,
      "quantidade_final": 63,
      "sobrevendas": 63,
      "conflitos_detectados": 0
    },
    "com_condicao": {
      "vendas_confirmadas": 61,
      "quantidade_esperada": 39,
      "quantidade_final": 39,
      "sobrevendas": 0,
      "conflitos_detectados": 39
    }
  }
}
```

| Campo | Significado |
|---|---|
| `vendas_confirmadas` | quantas vendas a aplicação **disse ao cliente** que deram certo |
| `quantidade_esperada` | `quantidade_inicial − vendas_confirmadas` |
| `quantidade_final` | o que a tabela mostra ao fim |
| `sobrevendas` | `quantidade_final − quantidade_esperada` — unidades vendidas que nunca saíram da prateleira |
| `conflitos_detectados` | `ConditionalCheckFailedException` capturadas |

No modo com condição, `vendas_confirmadas` cai porque parte das tentativas vira erro explícito em vez de sobrescrita silenciosa. Essa queda **é o resultado desejado**, não uma perda.

### Cenário D — recuperação via PITR

```json
"parametros": {
  "tabela": "Estoque",
  "tipo_corrupcao": "quantidade_zerada_em_massa",
  "produtos_afetados": 40,
  "instante_restauracao": "2026-11-25T14:20:00.000Z",
  "tabela_restaurada": "Estoque_restore_20261125T1430"
},
"metricas": {
  "produtos_antes": 50,
  "unidades_antes": 5000,
  "unidades_apos_corrupcao": 1000,
  "valor_antes": 317000.00,
  "valor_apos_corrupcao": 63400.00,
  "produtos_restaurados": 50,
  "unidades_restauradas": 5000,
  "valor_restaurado": 317000.00,
  "divergencias": 0,
  "checksum_antes": "a3f1c0d9",
  "checksum_depois": "a3f1c0d9",
  "duracao_restauracao_s": 612
}
```

`valor_*` é a soma de `preco × quantidade` — um checksum de negócio, legível para quem não é técnico.

Como em todos os exemplos deste documento, os números são **formato, não previsão**.

---

## 3. A API REST

Base: `http://localhost:8080`

### `GET /status`

Consultado pelo dashboard a cada poucos segundos. Com região única, os cards passam a ser **por tabela**.

```json
{
  "regiao": "us-east-2",
  "consultado_em": "2026-11-25T14:28:03.221Z",
  "tabelas": [
    { "tabela": "Estoque",         "estado": "ACTIVE", "produtos": 50, "unidades": 5000, "valor": 317000.00 },
    { "tabela": "EstoqueThrottle", "estado": "ACTIVE", "produtos": 1,  "unidades": 100,  "valor": 11500.00 }
  ],
  "execucao_em_andamento": null
}
```

`estado` repassa o valor da AWS: `ACTIVE`, `CREATING`, `UPDATING`, `DELETING`, ou `AUSENTE`.

`produtos`, `unidades` e `valor` vêm de `lab.aws.resumo_regiao()` — um `Scan` paginado projetando `quantidade` e `preco`. **Não** usar o `ItemCount` do `DescribeTable`: é aproximado, atualiza a cada ~6 horas e, neste modelo, nem mudaria.

### `POST /cenario/{a|b|c|d}`

Dispara em segundo plano e responde **imediatamente** com `202`. Sem corpo — os parâmetros são fixos no script.

```json
{ "execucao_id": "a-2026-11-25T143000Z", "status": "em_andamento" }
```

Com execução em andamento, responde `409`.

> Os Cenários A e C passaram a rodar em segundos. O ciclo assíncrono é mantido assim mesmo: o Cenário D continua levando minutos, e um contrato único para os quatro vale mais que a economia de um polling.

### `GET /execucao/{execucao_id}`

```json
{
  "execucao_id": "a-2026-11-25T143000Z",
  "status": "em_andamento",
  "etapa": "modo_sem_transacao",
  "progresso": { "atual": 3, "total": 5 }
}
```

Ao terminar, devolve o envelope completo da seção 2.

| Cenário | Etapas |
|---|---|
| A | `preparando_destino`, `modo_sem_transacao`, `modo_com_transacao` |
| B | `fase_sem_retry`, `fase_com_backoff` |
| C | `modo_sem_condicao`, `modo_com_condicao` |
| D | `corrompendo_quantidade`, `restaurando_pitr`, `comparando_itens` |

### `GET /resultados`

Lista as execuções gravadas em `results/`. Alimenta o modo replay.

```json
{
  "execucoes": [
    { "execucao_id": "a-2026-11-25T143000Z", "cenario": "A", "fim": "2026-11-25T14:30:11.400Z", "status": "concluido" }
  ]
}
```

### `POST /reset`

Regrava os 50 produtos com 100 unidades e `versao` 1, e remove itens fora do conjunto.

```json
{ "produtos_resetados": 50, "unidades": 5000, "sobras_removidas": 0 }
```

Necessário entre execuções: sem isso, a rodada seguinte começa com estoque consumido e os números perdem sentido.

---

## 4. Erros

```json
{
  "erro": {
    "codigo": "EXECUCAO_EM_ANDAMENTO",
    "mensagem": "Já existe uma execução em andamento (a-2026-11-25T143000Z).",
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
| `TABELA_INDISPONIVEL` | 503 | tabela não está `ACTIVE` |

Cenário que falha no meio **grava o arquivo mesmo assim**, com `status: "erro"` e a `etapa` em que parou.

> Atenção no Cenário A: a `ConditionalCheckFailedException` do destino **não é erro de execução** — é o evento que o cenário provoca de propósito. Ela é capturada e contabilizada, nunca propagada como `FALHA_AWS`.

---

## Onde cada coisa mora

| O quê | Caminho | Versionado? |
|---|---|---|
| Este contrato | `docs/CONTRATOS.md` | sim |
| Exemplos executáveis (mocks de B5/B6) | `scenarios/fixtures/*.json` | sim |
| Resultados reais | `results/*.json` | sim — é a evidência do trabalho |
| Schema de validação (opcional) | `docs/schemas/resultado.schema.json` | sim |
