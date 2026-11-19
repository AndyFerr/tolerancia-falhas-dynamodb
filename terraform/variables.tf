variable "regiao_primaria" {
  description = "Região única do projeto. A conta não suporta recursos entre regiões."
  type        = string
  default     = "us-east-1"
}

variable "tabela" {
  description = "Nome da tabela global."
  type        = string
  default     = "Estoque"
}

variable "tabela_throttle" {
  description = "Nome da tabela de uma Região usada no Cenário B (throttling)."
  type        = string
  default     = "EstoqueThrottle"
}

variable "email_alerta_custo" {
  description = "E-mail que recebe o alerta de orçamento. Vazio = não cria o orçamento."
  type        = string
  default     = ""
}

variable "limite_custo_usd" {
  description = "Limite mensal do orçamento, em dólares."
  type        = number
  default     = 10
}
