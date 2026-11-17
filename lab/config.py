"""Configuração lida de variáveis de ambiente.

LAB_TABELA           nome da tabela global (padrão: Estoque)
LAB_TABELA_THROTTLE  tabela de uma Região usada no cenário de throttling
LAB_REGIOES          Regiões separadas por vírgula; a primeira é a primária
"""
import os
from dataclasses import dataclass

TOTAL_PRODUTOS = 50
UNIDADES_POR_PRODUTO = 100


@dataclass(frozen=True)
class Config:
    tabela: str = "Estoque"
    tabela_throttle: str = "EstoqueThrottle"
    regioes: tuple = ("sa-east-1", "us-east-1", "eu-west-1")

    @property
    def primaria(self) -> str:
        return self.regioes[0]


def carregar() -> Config:
    regioes = tuple(
        r.strip() for r in os.environ.get("LAB_REGIOES", "sa-east-1,us-east-1,eu-west-1").split(",") if r.strip()
    )
    if not regioes:
        raise ValueError("LAB_REGIOES está vazio")
    return Config(
        tabela=os.environ.get("LAB_TABELA", "Estoque"),
        tabela_throttle=os.environ.get("LAB_TABELA_THROTTLE", "EstoqueThrottle"),
        regioes=regioes,
    )


def id_produto(n: int) -> str:
    return f"prod-{n:03d}"
