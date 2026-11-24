"""Cenário D — recuperação via PITR (docs/CENARIOS.md; contrato, seção 2).

A própria aplicação corrompe o estoque (zera a quantidade de 40 produtos) e a
recuperação é feita por point-in-time restore para uma tabela NOVA, com
comparação item a item contra o estado registrado antes da corrupção.

Etapas: corrompendo_quantidade → restaurando_pitr → comparando_itens

Demora: o PITR só aceita instantes até ~5 minutos atrás, e a restauração em si
leva de minutos a dezenas de minutos. Rode com antecedência e apresente em replay.

Depois de rodar:
  * a tabela Estoque fica corrompida: rode scripts/03_reset.py;
  * a tabela restaurada NÃO está no Terraform: apague à mão (o comando é impresso).

Uso: python scenarios/cenario_d.py      (rode scripts/03_reset.py antes)
"""
import hashlib
import sys
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

try:
    from . import _caminho  # noqa: F401
except ImportError:
    import _caminho  # noqa: F401

from lab import aws, config
from lab.execucao import ErroCenario, rodar_cli
from lab.tempo import iso

PRODUTOS_AFETADOS = 40           # prod-001 … prod-040 têm a quantidade zerada
ESPERA_ANTES_DO_CORTE_S = 3      # folga entre o retrato e o instante de restauração
ESPERA_DEPOIS_DO_CORTE_S = 2     # folga entre o instante de restauração e a corrupção
ESPERA_PITR_MAX_S = 15 * 60      # até o instante escolhido virar restaurável
ESPERA_RESTAURACAO_MAX_S = 90 * 60
INTERVALO_CONSULTA_S = 15


def _retrato(regiao: str, tabela: str) -> dict:
    """Todos os itens da tabela, com leitura fortemente consistente."""
    t = aws.tabela(regiao, tabela)
    itens, kwargs = {}, {"ConsistentRead": True}
    while True:
        pagina = t.scan(**kwargs)
        for it in pagina.get("Items", []):
            itens[it["produto_id"]] = it
        if "LastEvaluatedKey" not in pagina:
            return itens
        kwargs["ExclusiveStartKey"] = pagina["LastEvaluatedKey"]


def _resumo(itens: dict) -> dict:
    unidades = sum(int(it.get("quantidade", 0)) for it in itens.values())
    valor = sum((Decimal(it.get("preco", 0)) * int(it.get("quantidade", 0)) for it in itens.values()), Decimal(0))
    return {"produtos": len(itens), "unidades": unidades, "valor": valor}


def _checksum(itens: dict) -> str:
    """Impressão digital do estoque: produto, quantidade e preço de cada item."""
    linhas = sorted(f"{pid}:{int(it.get('quantidade', 0))}:{Decimal(it.get('preco', 0))}" for pid, it in itens.items())
    return hashlib.sha256("\n".join(linhas).encode()).hexdigest()[:8]


def _divergencias(antes: dict, depois: dict) -> int:
    """Produtos ausentes, sobrando ou com quantidade/preço diferentes."""
    n = len(set(antes) ^ set(depois))
    for pid in set(antes) & set(depois):
        a, d = antes[pid], depois[pid]
        if int(a["quantidade"]) != int(d["quantidade"]) or Decimal(a["preco"]) != Decimal(d["preco"]):
            n += 1
    return n


def _esperar_restauravel(cliente, tabela: str, instante: datetime) -> None:
    """O PITR só restaura até LatestRestorableDateTime, que fica ~5 min atrás do relógio."""
    limite = time.monotonic() + ESPERA_PITR_MAX_S
    while True:
        pitr = cliente.describe_continuous_backups(TableName=tabela)[
            "ContinuousBackupsDescription"]["PointInTimeRecoveryDescription"]
        if pitr.get("PointInTimeRecoveryStatus") != "ENABLED":
            raise ErroCenario("TABELA_INDISPONIVEL", f"PITR não está ligado em {tabela}.")
        mais_antigo = pitr.get("EarliestRestorableDateTime")
        mais_recente = pitr.get("LatestRestorableDateTime")
        if mais_antigo and mais_antigo > instante:
            raise ErroCenario("TABELA_INDISPONIVEL",
                              f"O PITR só cobre a partir de {mais_antigo.isoformat()}; "
                              f"o instante pedido ({instante.isoformat()}) é anterior.")
        if mais_recente and mais_recente >= instante:
            return
        if time.monotonic() > limite:
            raise ErroCenario("FALHA_AWS", "O instante de restauração não ficou disponível no tempo esperado.")
        falta = (instante - mais_recente).total_seconds() if mais_recente else None
        print(f"  aguardando o PITR alcançar o instante de corte"
              + (f" (faltam ~{falta:.0f} s)" if falta else ""), flush=True)
        time.sleep(INTERVALO_CONSULTA_S)


def _esperar_ativa(cliente, tabela: str) -> None:
    limite = time.monotonic() + ESPERA_RESTAURACAO_MAX_S
    while True:
        estado = cliente.describe_table(TableName=tabela)["Table"]["TableStatus"]
        if estado == "ACTIVE":
            return
        if time.monotonic() > limite:
            raise ErroCenario("FALHA_AWS", f"{tabela} não ficou ACTIVE em {ESPERA_RESTAURACAO_MAX_S // 60} min.")
        print(f"  {tabela}: {estado}", flush=True)
        time.sleep(INTERVALO_CONSULTA_S)


def _numero(v: Decimal):
    """Decimal → int ou float com 2 casas, para as métricas de valor."""
    return int(v) if v == v.to_integral_value() else float(round(v, 2))


def executar(ex, cfg, parciais: dict) -> dict:
    regiao, origem = cfg.primaria, cfg.tabela
    cliente = aws.cliente(regiao)

    # --- estado inicial
    antes = _retrato(regiao, origem)
    r_antes = _resumo(antes)
    esperado = config.TOTAL_PRODUTOS * config.UNIDADES_POR_PRODUTO
    if r_antes["produtos"] != config.TOTAL_PRODUTOS or r_antes["unidades"] != esperado:
        raise ErroCenario("ESTOQUE_NAO_RESETADO",
                          f"{origem} tem {r_antes['produtos']} produtos e {r_antes['unidades']} unidades; "
                          f"esperado {config.TOTAL_PRODUTOS} e {esperado}. Rode scripts/03_reset.py.")
    parciais.update({
        "produtos_antes": r_antes["produtos"],
        "unidades_antes": r_antes["unidades"],
        "valor_antes": _numero(r_antes["valor"]),
        "checksum_antes": _checksum(antes),
    })

    time.sleep(ESPERA_ANTES_DO_CORTE_S)
    instante = datetime.now(timezone.utc).replace(microsecond=0)
    ex.parametros["instante_restauracao"] = iso(int(instante.timestamp() * 1000))
    destino = f"{origem}_restore_{instante.strftime('%Y%m%dT%H%M%S')}"
    ex.parametros["tabela_restaurada"] = destino
    time.sleep(ESPERA_DEPOIS_DO_CORTE_S)

    # --- corrupção lógica: escritas válidas, confirmadas, e erradas
    ex.etapa("corrompendo_quantidade", total=PRODUTOS_AFETADOS)
    t = aws.tabela(regiao, origem)
    with t.batch_writer() as lote:
        for n in range(1, PRODUTOS_AFETADOS + 1):
            versao = int(antes[config.id_produto(n)]["versao"]) + 1
            lote.put_item(Item=aws.item_estoque(n, regiao, "cenario_d", quantidade=0, versao=versao))
            ex.avancar()
    r_corrompido = _resumo(_retrato(regiao, origem))
    parciais.update({
        "unidades_apos_corrupcao": r_corrompido["unidades"],
        "valor_apos_corrupcao": _numero(r_corrompido["valor"]),
    })
    print(f"  corrompido: {r_corrompido['unidades']} unidades (antes {r_antes['unidades']})", flush=True)

    # --- restauração
    ex.etapa("restaurando_pitr")
    _esperar_restauravel(cliente, origem, instante)
    t_restauracao = time.monotonic()
    cliente.restore_table_to_point_in_time(
        SourceTableName=origem,
        TargetTableName=destino,
        RestoreDateTime=instante,
        BillingModeOverride="PAY_PER_REQUEST",
    )
    print(f"  restauração pedida: {destino} (instante {ex.parametros['instante_restauracao']})", flush=True)
    _esperar_ativa(cliente, destino)
    parciais["duracao_restauracao_s"] = round(time.monotonic() - t_restauracao)

    # --- comparação
    ex.etapa("comparando_itens", total=config.TOTAL_PRODUTOS)
    depois = _retrato(regiao, destino)
    ex.avancar(config.TOTAL_PRODUTOS)
    r_depois = _resumo(depois)

    print(f"\n  Lembretes:\n"
          f"    python scripts/03_reset.py                      # a tabela {origem} ficou corrompida\n"
          f"    aws dynamodb delete-table --table-name {destino} --region {regiao}\n", flush=True)

    return {
        "produtos_antes": parciais["produtos_antes"],
        "unidades_antes": parciais["unidades_antes"],
        "unidades_apos_corrupcao": parciais["unidades_apos_corrupcao"],
        "valor_antes": parciais["valor_antes"],
        "valor_apos_corrupcao": parciais["valor_apos_corrupcao"],
        "produtos_restaurados": r_depois["produtos"],
        "unidades_restauradas": r_depois["unidades"],
        "valor_restaurado": _numero(r_depois["valor"]),
        "divergencias": _divergencias(antes, depois),
        "checksum_antes": parciais["checksum_antes"],
        "checksum_depois": _checksum(depois),
        "duracao_restauracao_s": parciais["duracao_restauracao_s"],
    }


def parametros(cfg) -> dict:
    return {
        "tabela": cfg.tabela,
        "tipo_corrupcao": "quantidade_zerada_em_massa",
        "produtos_afetados": PRODUTOS_AFETADOS,
        "instante_restauracao": None,     # definido durante a execução
        "tabela_restaurada": None,        # definido durante a execução
    }


if __name__ == "__main__":
    _cfg = config.carregar()
    sys.exit(rodar_cli("D", parametros(_cfg), executar))
