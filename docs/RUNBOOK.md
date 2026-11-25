# Runbook da infraestrutura


## 0. Pré-requisitos

- Python 3.11 ou mais novo
- Terraform 1.10 ou mais novo
- AWS CLI v2 configurada (`aws configure`) com um usuário IAM do grupo, não o usuário raiz
- Permissões: DynamoDB (tabelas, réplicas, backups), CloudWatch (leitura) e Budgets, em us-east-2

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
aws sts get-caller-identity      # confirma a conta e o usuário
```

## 1. Validar o Terraform sem conta AWS

Confere a sintaxe e a configuração. Não toca na AWS nem gera custo.

```bash
cd terraform
terraform init -backend=false
terraform validate
cd ..
```

## 2. Criar a infraestrutura

Se a equipe optar por state remoto, crie o bucket **antes** do primeiro `init` (o Terraform não consegue criar o bucket onde ele mesmo guarda o state):

```bash
aws s3api create-bucket --bucket NOME-DO-BUCKET \
  --region us-east-2 \
  --create-bucket-configuration LocationConstraint=us-east-2
```


```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars    # ajuste o e-mail do alerta de custo
terraform init
terraform plan
terraform apply
cd ..
```

O que é criado:

| Recurso | Configuração |
|---|---|
| Tabela `Estoque` | `us-east-2`; sob demanda; PITR e streams ligados |
| Tabela `EstoqueThrottle` | em `us-east-2`; provisionada a 1 WCU / 1 RCU (Cenário B); o seed grava só o `prod-007` |
| Orçamento | alerta por e-mail em 50% e 100% do limite (só se `email_alerta_custo` for preenchido) |


## 3. Verificar e popular

```bash
python scripts/01_setup_table.py    # espera ACTIVE, confere o PITR e a EstoqueThrottle
python scripts/02_seed_data.py      # 50 produtos × 100 unidades
```

O esperado é 5.000 unidades.

Antes de rodar qualquer cenário, confira se a conta permite os recursos que eles usam (risco R14):

```bash
python scripts/04_verificar_recursos.py   # PITR, TransactWriteItems e escrita condicional
```

## 4. Voltar ao estado inicial entre execuções

```bash
python scripts/03_reset.py
```

## 4.1 Rodar os cenários

No Git Bash, defina a região uma vez por terminal: `export LAB_REGIOES=us-east-2`.

Sempre com reset antes. Cada execução grava `results/cenario_<x>_<timestamp>.json`, inclusive quando falha.

```bash
python scripts/03_reset.py
python scenarios/cenario_a.py     # segundos: transferência sem e com transação

python scripts/03_reset.py
python scenarios/cenario_c.py     # ~1 min: 2 processos concorrentes, 5 rodadas por modo

python scripts/03_reset.py
python scenarios/cenario_b.py     # ~3 min: aquecimento + 2 fases de 100 vendas

python scripts/03_reset.py
python scenarios/cenario_d.py     # 10 a 40 min: espera o PITR alcançar o instante de corte e restaura
```

Depois do Cenário D:

- rode `scripts/03_reset.py`, porque a tabela `Estoque` fica corrompida de propósito;
- apague a tabela restaurada (o comando aparece no fim da execução). Ela **não** está no Terraform.

## 4.2 Dashboard

```bash
python scripts/server.py          # http://localhost:8080
```

- Os botões de cenário rodam na AWS, como os scripts acima. Um cenário por vez: o servidor recusa outro enquanto um está rodando.
- O botão de reset faz o mesmo que `scripts/03_reset.py`.
- A lista de execuções lê `results/` e funciona sem a infraestrutura. Para gravar o vídeo depois do `terraform destroy`, use essa lista (replay).

## 5. Destruir tudo

```bash
cd terraform
terraform destroy
```

Depois, conferir no console de us-east-2 se não sobrou tabela. Tabelas criadas por restauração (PITR) não estão no Terraform e precisam ser apagadas à mão.

## 6. Custo

- `Estoque` é sob demanda: paga por requisição.
- `EstoqueThrottle` tem 1 WCU e 1 RCU provisionados.
- O PITR é cobrado pelo tamanho da tabela, que aqui é de poucos kilobytes.
- O maior risco de custo é **esquecer a infraestrutura ligada**. Rodar `terraform destroy` ao fim do dia, se não for usar no dia seguinte.

Conferir os valores na página de preços do DynamoDB antes de colocar números no relatório.

## Problemas comuns

| Sintoma | Causa provável |
|---|---|
| `ModuleNotFoundError: boto3` | faltou `pip install -r requirements.txt` |
| `NoCredentialsError` | AWS CLI não configurada neste terminal |
| `AccessDeniedException` com "service control policy" | a conta só permite `us-east-2`; confira `LAB_REGIOES` e o `regiao_primaria` do `terraform.tfvars` |
| `01_setup_table.py` não sai de `CREATING` | tabela ainda em criação; esperar e rodar de novo |
| cenário termina com `ESTOQUE_NAO_RESETADO` | faltou `scripts/03_reset.py` antes de rodar |
| Cenário B com `throttling_continuo: false` no aquecimento | o burst não esgotou em 90 s; rodar de novo e registrar no relatório |
