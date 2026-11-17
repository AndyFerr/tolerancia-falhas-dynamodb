output "tabela" {
  value = aws_dynamodb_table.estoque.name
}

output "regioes" {
  description = "Use em LAB_REGIOES (a primeira é a primária)."
  value       = join(",", concat([var.regiao_primaria], var.regioes_replica))
}

output "tabela_throttle" {
  value = aws_dynamodb_table.throttle.name
}
