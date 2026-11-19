# Runbook da infraestrutura

> Status: **escrito, ainda não executado contra a AWS**. Quem rodar pela primeira vez corrige o que não bater (tarefa B7: validação por outro integrante).

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
  --region sa-east-1 \
  --create-bucket-configuration LocationConstraint=sa-east-1
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
| Tabela `Estoque` | `us-east-2` modo MREC; sob demanda; PITR ligado |
| Tabela `EstoqueThrottle` | em `us-east-2`; provisionada a 1 WCU / 1 RCU (Cenário B); o seed grava só o `prod-007` |
| Orçamento | alerta por e-mail em 50% e 100% do limite (só se `email_alerta_custo` for preenchido) |


## 3. Verificar e popular

```bash
python scripts/01_setup_table.py    # espera ACTIVE, confere o PITR e a EstoqueThrottle
python scripts/02_seed_data.py      # 50 produtos × 100 unidades
```

O esperado é 5.000 unidades.

## 4. Voltar ao estado inicial entre execuções

```bash
python scripts/03_reset.py
```

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
| `AccessDeniedException` em uma Região | a conta ou a política IAM não permite aquela Região |
| `terraform apply` falha ao criar réplica | Região não habilitada na conta, ou conta de laboratório com Regiões restritas |
| `01_setup_table.py` não sai de `CREATING` | réplicas ainda em criação; esperar e rodar de novo |
