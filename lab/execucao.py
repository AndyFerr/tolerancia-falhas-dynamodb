"""Envelope de execução dos cenários (docs/CONTRATOS.md, seções 2 e 4).

Todo cenário roda dentro de uma `Execucao`. Ela guarda a etapa e o progresso
(o que `GET /execucao/{id}` devolve enquanto o cenário roda) e, ao final,
grava `results/cenario_<x>_<timestamp>.json` com o envelope do contrato —
inclusive quando o cenário falha no meio.

Uso por um cenário:

    def executar(ex: Execucao, cfg, parciais: dict) -> dict:
        ex.etapa("fase_sem_retry", total=100)
        ...
        ex.avancar()
        parciais["fase_sem_retry"] = {...}   # sobrevive se o cenário falhar depois
        ...
        return metricas

    if __name__ == "__main__":
        sys.exit(rodar_cli("B", PARAMETROS, executar))
"""
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .tempo import agora_ms, iso

SCHEMA_VERSION = "4.0"
RAIZ = Path(__file__).resolve().parent.parent
PASTA_RESULTADOS = RAIZ / "results"


class ErroCenario(Exception):
    """Falha prevista pelo contrato (seção 4), com o código já definido."""

    def __init__(self, codigo: str, mensagem: str):
        super().__init__(mensagem)
        self.codigo = codigo
        self.mensagem = mensagem


def classificar_erro(e: Exception) -> str:
    """Traduz uma exceção para um código da seção 4 do contrato."""
    if isinstance(e, ErroCenario):
        return e.codigo
    nome = type(e).__name__
    if nome in ("NoCredentialsError", "PartialCredentialsError", "NoRegionError"):
        return "CREDENCIAIS_INVALIDAS"
    codigo_aws = (getattr(e, "response", None) or {}).get("Error", {}).get("Code", "")
    if codigo_aws == "ResourceNotFoundException":
        return "TABELA_INDISPONIVEL"
    if codigo_aws in ("UnrecognizedClientException", "InvalidSignatureException", "ExpiredTokenException"):
        return "CREDENCIAIS_INVALIDAS"
    if codigo_aws or nome in ("EndpointConnectionError", "ConnectTimeoutError", "ReadTimeoutError"):
        return "FALHA_AWS"
    # Não previsto no contrato: bug no próprio script. Fica registrado assim
    # para não ser confundido com uma falha da AWS.
    return "ERRO_INTERNO"


class Execucao:
    def __init__(self, cenario: str, parametros: dict):
        self.cenario = cenario.upper()
        self.parametros = parametros
        agora = datetime.now(timezone.utc)
        self._carimbo = agora.strftime("%Y-%m-%dT%H%M%SZ")
        self.execucao_id = f"{self.cenario.lower()}-{self._carimbo}"
        self._inicio_ms = agora_ms()
        self._t0 = time.monotonic()
        self._trava = threading.Lock()
        self._etapa = None
        self._atual = 0
        self._total = None
        self.envelope = None

    # ----------------------------------------------------------- progresso

    def etapa(self, nome: str, total: int | None = None) -> None:
        with self._trava:
            self._etapa, self._atual, self._total = nome, 0, total
        print(f"[{self.execucao_id}] etapa: {nome}" + (f" (0/{total})" if total else ""), flush=True)

    def avancar(self, n: int = 1) -> None:
        with self._trava:
            self._atual += n

    def estado(self) -> dict:
        """Resposta de `GET /execucao/{id}` enquanto o cenário roda."""
        if self.envelope is not None:
            return self.envelope
        with self._trava:
            progresso = {"atual": self._atual, "total": self._total} if self._total else None
            return {"execucao_id": self.execucao_id, "status": "em_andamento",
                    "etapa": self._etapa, "progresso": progresso}

    # ----------------------------------------------------------- resultado

    def _fechar(self, status: str, metricas: dict, erro: dict | None) -> dict:
        self.envelope = {
            "schema_version": SCHEMA_VERSION,
            "cenario": self.cenario,
            "execucao_id": self.execucao_id,
            "inicio": iso(self._inicio_ms),
            "fim": iso(),
            "duracao_s": round(time.monotonic() - self._t0, 1),
            "status": status,
            "parametros": self.parametros,
            "metricas": metricas,
            "erro": erro,
        }
        return self.envelope

    def concluir(self, metricas: dict) -> dict:
        return self._fechar("concluido", metricas, None)

    def falhar(self, e: Exception, metricas_parciais: dict | None = None) -> dict:
        erro = {"codigo": classificar_erro(e), "mensagem": str(e) or type(e).__name__, "etapa": self._etapa}
        return self._fechar("erro", metricas_parciais or {}, erro)

    def gravar(self) -> Path:
        PASTA_RESULTADOS.mkdir(parents=True, exist_ok=True)
        caminho = PASTA_RESULTADOS / f"cenario_{self.cenario.lower()}_{self._carimbo}.json"
        caminho.write_text(json.dumps(self.envelope, ensure_ascii=False, indent=2, default=_json_padrao) + "\n",
                           encoding="utf-8")
        return caminho


def _json_padrao(v):
    """Decimal vira número no JSON (o contrato mostra valores como números)."""
    from decimal import Decimal

    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    raise TypeError(f"{type(v).__name__} não é serializável")


def rodar(cenario: str, parametros: dict, executar, cfg=None, ex: Execucao | None = None) -> dict:
    """Roda `executar(ex, cfg, parciais)`, monta o envelope e grava o arquivo — sempre.

    `parciais` é um dicionário que o cenário vai preenchendo; se ele falhar no
    meio, o que já foi medido vai para `metricas` do arquivo de erro.

    O backend pode criar a `Execucao` antes (para devolver o id no 202) e
    passá-la em `ex`.
    """
    cfg = cfg or config.carregar()
    ex = ex or Execucao(cenario, parametros)
    metricas_parciais: dict = {}
    try:
        ex.concluir(executar(ex, cfg, metricas_parciais))
    except Exception as e:  # noqa: BLE001 - toda falha vira evidência gravada
        ex.falhar(e, metricas_parciais)
    caminho = ex.gravar()
    print(f"[{ex.execucao_id}] {ex.envelope['status']} -> {caminho.relative_to(RAIZ)}", flush=True)
    if ex.envelope["erro"]:
        print(f"  erro: {ex.envelope['erro']['codigo']}: {ex.envelope['erro']['mensagem']}", flush=True)
    return ex.envelope


def rodar_cli(cenario: str, parametros: dict, executar) -> int:
    """Ponto de entrada para `python scenarios/cenario_x.py`. Código 1 se falhou."""
    envelope = rodar(cenario, parametros, executar)
    return 0 if envelope["status"] == "concluido" else 1
