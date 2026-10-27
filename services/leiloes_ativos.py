"""
Leiloes ativos: lista dos imoveis de leilao (vw_leiloes, migracao 005) com a etapa
atual, o prazo e a ultima avaliacao, e a mudanca manual da situacao.

Quando a etapa mudou desde a avaliacao (ex.: avaliado no 1o leilao, que ja passou),
a resposta e recalculada com o valor minimo da etapa atual e a mesma liquidez da
avaliacao (mesma conta de services/leilao.py). A liquidez nao muda: so o preco de
entrada.
"""
from __future__ import annotations

import logging
from decimal import Decimal

from services.banco import TIMEOUT_COMANDO_MS, TIMEOUT_CONEXAO_S
from services.leilao import (
    DECISAO_SEM_ESTIMATIVA, ROI_MARGEM_APERTADA, ROI_OPORTUNIDADE, SITUACOES_LEILAO, classificar_roi,
    conta_investimento, estimativa_na_etapa, lance_para_roi,
)

logger = logging.getLogger(__name__)

# As views so tem o valor minimo da etapa atual; o do 2o leilao vem da tabela.
_ETAPAS = "i.valor_minimo_1, i.data_1_leilao, i.valor_minimo_2, i.data_2_leilao"
SQL_ATIVOS = (f"SELECT v.*, {_ETAPAS} FROM vw_leiloes_ativos v JOIN imoveis_leilao i ON i.id = v.id "
              f"ORDER BY v.encerramento NULLS LAST")
SQL_TODOS = (f"SELECT v.*, {_ETAPAS} FROM vw_leiloes v JOIN imoveis_leilao i ON i.id = v.id "
             f"ORDER BY v.ativo DESC, v.encerramento NULLS LAST")
SQL_SITUACAO = "UPDATE imoveis_leilao SET situacao = %s, atualizado_em = now() WHERE id = %s"


def _conectar(database_url: str):
    import psycopg
    # prepare_threshold=None: o endereco "-pooler" do Neon (ver services/banco.py).
    return psycopg.connect(database_url, connect_timeout=TIMEOUT_CONEXAO_S, prepare_threshold=None)


def _simples(valor):
    """Decimal do banco -> float (contas e formatacao)."""
    return float(valor) if isinstance(valor, Decimal) else valor


def listar_leiloes(database_url: str, incluir_inativos: bool = False) -> list[dict]:
    """Linhas de vw_leiloes_ativos (ou de vw_leiloes inteira). Erro de banco sobe."""
    with _conectar(database_url) as conexao, conexao.cursor() as cursor:
        cursor.execute(f"SET statement_timeout = {int(TIMEOUT_COMANDO_MS)}")
        cursor.execute(SQL_TODOS if incluir_inativos else SQL_ATIVOS)
        colunas = [c.name for c in cursor.description]
        return [{col: _simples(v) for col, v in zip(colunas, linha)} for linha in cursor.fetchall()]


def marcar_situacao(database_url: str, id_imovel: int, situacao: str) -> bool:
    """Muda a situacao manual (ativo, vendido, retirado, suspenso). True se mudou."""
    if situacao not in SITUACOES_LEILAO:
        raise ValueError(f"situacao invalida: {situacao}")
    with _conectar(database_url) as conexao, conexao.transaction(), conexao.cursor() as cursor:
        cursor.execute(SQL_SITUACAO, (situacao, int(id_imovel)))
        mudou = cursor.rowcount == 1
    logger.info(f"[Leiloes] imovel {id_imovel} -> {situacao} ({'ok' if mudou else 'nao encontrado'})")
    return mudou


def preparar_linha(linha: dict) -> dict:
    """
    Linha da view -> o que a pagina mostra: resposta, ROI e lances no valor minimo da
    etapa ATUAL. Sem estimativa confiavel na avaliacao (sem lance maximo gravado), a
    resposta e a gravada ("Sem estimativa"); sem avaliacao, nenhuma.
    `recalculado` = a etapa mudou desde a avaliacao e a conta foi refeita.
    """
    saida = dict(linha)
    liquidez, minimo = linha.get("liquidez"), linha.get("valor_minimo_atual")
    # So refaz a conta quando a avaliacao teve estimativa confiavel (lance maximo
    # gravado). Com "Sem estimativa" o Agente 5 ainda grava uma liquidez, mas ela nao
    # vale para decidir (ex.: so 3 comparaveis, minimo de 5).
    confiavel = linha.get("lance_maximo") is not None
    saida["recalculado"] = bool(linha.get("etapa_mudou")) and confiavel
    if confiavel and liquidez and minimo:
        conta = conta_investimento(minimo, liquidez)
        saida.update({
            "roi": conta["roi"],
            "decisao": classificar_roi(conta["roi"]),
            "lance_maximo": lance_para_roi(liquidez, ROI_OPORTUNIDADE),
            "lance_limite_descarte": lance_para_roi(liquidez, ROI_MARGEM_APERTADA),
        })
    elif linha.get("ultima_execucao"):
        saida.update({"decisao": linha.get("decisao") or DECISAO_SEM_ESTIMATIVA, "roi": None,
                      "lance_maximo": None, "lance_limite_descarte": None})
    # O cronometro e o rotulo usam as chaves de services/leilao.py.
    saida["etapa"] = linha.get("etapa_atual")
    # Leilao SFI ainda no 1o leilao: a estimativa do 2o, com a mesma liquidez.
    saida["estimativa_2o_leilao"] = (
        estimativa_na_etapa(liquidez, 2, linha["valor_minimo_2"], linha.get("data_2_leilao"))
        if confiavel and liquidez and linha.get("etapa_atual") == 1 and linha.get("valor_minimo_2")
        and not linha.get("encerrado") else None
    )
    return saida


def filtrar(linhas: list[dict], decisoes=None, modalidades=None, ufs=None) -> list[dict]:
    """Filtros da pagina (lista vazia ou None = sem filtro). "Sem avaliação" = sem decisao."""
    def ok(valor, aceitos):
        return not aceitos or valor in aceitos
    return [
        l for l in linhas
        if ok(l.get("decisao") or "Sem avaliação", decisoes) and ok(l.get("modalidade"), modalidades)
        and ok(l.get("uf"), ufs)
    ]
