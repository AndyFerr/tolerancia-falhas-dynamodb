"""Servidor do laboratório: estado das tabelas, execução dos cenários e replay.

Implementa docs/CONTRATOS.md, seção 3. Roda os cenários de verdade — a
`Execucao` é criada aqui para o 202 devolver o id na hora, e passada a
`lab.execucao.rodar`, que grava o envelope em results/ ao final.

O dashboard é servido na raiz, de propósito: assim não há CORS entre a página
e a API.

Uso: python scripts/server.py        (http://localhost:8080)
"""
import importlib
import json
import sys
import threading
from pathlib import Path

from flask import Flask, jsonify, send_from_directory

import _caminho  # noqa: F401
from lab import aws, config, tempo
from lab.execucao import Execucao, rodar

RAIZ = Path(__file__).resolve().parent.parent
RESULTADOS = RAIZ / "results"
DASHBOARD = RAIZ / "dashboard"
PORTA = 8080

sys.path.insert(0, str(RAIZ / "scripts"))

from scenarios import cenario_a, cenario_b, cenario_c, cenario_d  # noqa: E402

CENARIOS = {"a": cenario_a, "b": cenario_b, "c": cenario_c, "d": cenario_d}
ROTULOS = {"Estoque": "principal", "EstoqueThrottle": "throttling"}

app = Flask(__name__, static_folder=None)

_trava = threading.Lock()
_execucoes: dict[str, Execucao] = {}
_em_andamento: str | None = None


def erro(codigo: str, mensagem: str, http: int, etapa=None):
    return jsonify({"erro": {"codigo": codigo, "mensagem": mensagem, "etapa": etapa}}), http


# ------------------------------------------------------------------- /status

@app.get("/status")
def rota_status():
    cfg = config.carregar()
    tabelas = []
    for nome in (cfg.tabela, cfg.tabela_throttle):
        try:
            estado = aws.cliente(cfg.primaria).describe_table(
                TableName=nome)["Table"]["TableStatus"]
            r = aws.resumo_regiao(cfg.primaria, nome)
            tabelas.append({"tabela": nome, "rotulo": ROTULOS.get(nome, ""), "estado": estado,
                            "produtos": r["itens"], "unidades": r["unidades"],
                            "valor": float(r["valor"])})
        except Exception:  # noqa: BLE001 - card indisponível não derruba a tela
            tabelas.append({"tabela": nome, "rotulo": ROTULOS.get(nome, ""), "estado": "AUSENTE",
                            "produtos": 0, "unidades": 0, "valor": 0.0})
    return jsonify({"regiao": cfg.primaria, "consultado_em": tempo.iso(),
                    "tabelas": tabelas, "execucao_em_andamento": _em_andamento})


# ------------------------------------------------------------------ cenários

def _rodar_em_segundo_plano(ex: Execucao, modulo, cfg) -> None:
    global _em_andamento
    try:
        rodar(ex.cenario, ex.parametros, modulo.executar, cfg=cfg, ex=ex)
    finally:
        with _trava:
            _em_andamento = None


@app.post("/cenario/<cenario>")
def rota_cenario(cenario: str):
    global _em_andamento
    cenario = cenario.lower()
    modulo = CENARIOS.get(cenario)
    if modulo is None:
        return erro("EXECUCAO_NAO_ENCONTRADA", f"Cenário desconhecido: {cenario}.", 404)

    cfg = config.carregar()
    with _trava:
        if _em_andamento:
            return erro("EXECUCAO_EM_ANDAMENTO",
                        f"Já existe uma execução em andamento ({_em_andamento}).", 409)
        ex = Execucao(cenario.upper(), modulo.parametros(cfg))
        _execucoes[ex.execucao_id] = ex
        _em_andamento = ex.execucao_id

    threading.Thread(target=_rodar_em_segundo_plano, args=(ex, modulo, cfg), daemon=True).start()
    return jsonify({"execucao_id": ex.execucao_id, "status": "em_andamento"}), 202


@app.get("/execucao/<execucao_id>")
def rota_execucao(execucao_id: str):
    ex = _execucoes.get(execucao_id)
    if ex is not None:
        return jsonify(ex.estado())
    for arquivo in _arquivos():
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
        if dados.get("execucao_id") == execucao_id:
            return jsonify(dados)
    return erro("EXECUCAO_NAO_ENCONTRADA", f"Execução {execucao_id} não encontrada.", 404)


# ----------------------------------------------------------------- resultados

def _arquivos() -> list[Path]:
    if not RESULTADOS.exists():
        return []
    return sorted(RESULTADOS.glob("cenario_*.json"), reverse=True)


@app.get("/resultados")
def rota_resultados():
    execucoes = []
    for arquivo in _arquivos():
        d = json.loads(arquivo.read_text(encoding="utf-8"))
        execucoes.append({"execucao_id": d["execucao_id"], "cenario": d["cenario"],
                          "fim": d.get("fim"), "status": d.get("status")})
    return jsonify({"execucoes": execucoes})


# ---------------------------------------------------------------------- reset

@app.post("/reset")
def rota_reset():
    with _trava:
        if _em_andamento:
            return erro("EXECUCAO_EM_ANDAMENTO",
                        f"Há uma execução em andamento ({_em_andamento}).", 409)
    try:
        reset_mod = importlib.import_module("03_reset")
        seed_mod = importlib.import_module("02_seed_data")
        cfg = config.carregar()
        sobras = reset_mod.apagar_sobras(cfg)
        seed_mod.semear(cfg, escritor="reset")
        return jsonify({
            "produtos_resetados": config.TOTAL_PRODUTOS,
            "unidades": config.TOTAL_PRODUTOS * config.UNIDADES_POR_PRODUTO,
            "sobras_removidas": sobras,
        })
    except Exception as e:  # noqa: BLE001
        return erro("FALHA_AWS", str(e) or type(e).__name__, 502)


# ------------------------------------------------------------------ dashboard

@app.get("/")
def rota_dashboard():
    return send_from_directory(DASHBOARD, "dashboard.html")


if __name__ == "__main__":
    print(f"http://localhost:{PORTA}  (cenários rodam de verdade na AWS)")
    app.run(host="127.0.0.1", port=PORTA, threaded=True)
