terraform {
  required_version = ">= 1.10" # use_lockfile no backend S3 exige 1.10

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # State local por padrão. Para state remoto compartilhado, copie
  # backend.tf.example para backend.tf e rode `terraform init -migrate-state`.
}

provider "aws" {
  region = var.regiao_primaria

  default_tags {
    tags = {
      Projeto    = "tolerancia-falhas-dynamodb"
      Disciplina = "sistemas-distribuidos"
    }
  }
}
