# Tabela global Estoque (global tables versão 2019.11.21, modo MREC).
# Sob demanda: a capacidade não interfere nos cenários de replicação.

resource "aws_dynamodb_table" "estoque" {
  name         = var.tabela
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "produto_id"

  attribute {
    name = "produto_id"
    type = "S"
  }

  # Global tables exigem streams com imagem nova e antiga.
  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"

  # PITR na Região primária (pré-requisito do Cenário D).
  point_in_time_recovery {
    enabled = true
  }
}

# Tabela separada para o Cenário B: 1 WCU provoca throttling de propósito,
# sem afetar a replicação da tabela global.
resource "aws_dynamodb_table" "throttle" {
  name           = var.tabela_throttle
  billing_mode   = "PROVISIONED"
  read_capacity  = 1
  write_capacity = 1
  hash_key       = "produto_id"

  attribute {
    name = "produto_id"
    type = "S"
  }
}

# Alerta de custo: avisa por e-mail ao atingir 50% e 100% do limite.
resource "aws_budgets_budget" "lab" {
  count = var.email_alerta_custo == "" ? 0 : 1

  name         = "lab-tolerancia-falhas-dynamodb"
  budget_type  = "COST"
  limit_amount = tostring(var.limite_custo_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  dynamic "notification" {
    for_each = [50, 100]
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = [var.email_alerta_custo]
    }
  }
}
