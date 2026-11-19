output "tabela" {
  value = aws_dynamodb_table.estoque.name
}

output "regioes" {
  description = "Use em LAB_REGIOES."
  value       = var.regiao_primaria
}

output "tabela_throttle" {
  value = aws_dynamodb_table.throttle.name
}
