"""
Orquestrador do Pipeline Multiagente (LangGraph)
=================================================

RESPONSABILIDADE:
    Conecta e orquestra os 5 agentes do pipeline usando LangGraph.
    Recebe o imóvel alvo e retorna a estimativa de preço com liquidez.

PIPELINE COMPLETO:
    Agente 1 — Coletor          → coleta imóveis comparáveis
         ↓
    Agente 2 — Comparáveis      → seleciona os mais similares ao alvo
         ↓
    Agente 3 — Analisador Textual → extrai fatores qualitativos
         ↓
    Agente 4 — Infraestrutura   → avalia entorno (OSM, Google Places)
         ↓
    Agente 5 — Preço e Liquidez → consolida e estima preço com liquidez

ESTADO ATUAL:
    Apenas o Agente 1 está implementado.
    Os demais agentes estão marcados como TODO.

COMO USAR (quando completo):
    from app.graph import executar_pipeline

    resultado = executar_pipeline({
        "rua":         "Rua Walter Ianni, 290",
        "bairro":      "Sao Gabriel",
        "cidade":      "Belo Horizonte",
        "estado":      "MG",
        "localizacao": "Belo Horizonte, MG",
        "tipo":        "house",
    })

DEPENDÊNCIAS:
    - langgraph (pip install langgraph)
    - Todos os agentes implementados
"""

import logging
from agents.collector_brightdata import coletar_imoveis_bd

logger = logging.getLogger(__name__)


def executar_pipeline(imovel_alvo: dict) -> dict:
    """
    Executa o pipeline completo para o imóvel alvo.

    Parâmetros
    ----------
    imovel_alvo : dict
        Deve conter: localizacao, tipo, bairro, rua, cidade, estado

    Retorna
    -------
    dict
        Resultado consolidado: preco_estimado, liquidez, comparaveis, etc.
        Enquanto os agentes não estão todos implementados, retorna parcial.
    """
    logger.info(
        f"Iniciando pipeline | "
        f"{imovel_alvo.get('rua')} — "
        f"{imovel_alvo.get('bairro')}, "
        f"{imovel_alvo.get('cidade')}/{imovel_alvo.get('estado')}"
    )

    # ------------------------------------------------------------------
    # AGENTE 1 — Coleta de comparáveis (implementado)
    # Usa Bright Data MCP para raspar ZAP/VivaReal com rua e data
    # ------------------------------------------------------------------
    comparaveis = coletar_imoveis_bd(
        localizacao=imovel_alvo["localizacao"],
        tipo_imovel=imovel_alvo["tipo"],
        bairro=imovel_alvo.get("bairro", ""),
        rua=imovel_alvo.get("rua", ""),
    )
    logger.info(f"Agente 1 concluído: {len(comparaveis)} comparáveis")

    # ------------------------------------------------------------------
    # AGENTE 2 — Identificação de comparáveis (pendente)
    # Seleciona os mais similares por área, quartos, padrão e localização
    # ------------------------------------------------------------------
    # TODO: from agents.comparables import identificar_comparaveis
    # comparaveis = identificar_comparaveis(imovel_alvo, comparaveis)

    # ------------------------------------------------------------------
    # AGENTE 3 — Análise textual (pendente)
    # Extrai padrão, conservação e diferenciais da descrição
    # ------------------------------------------------------------------
    # TODO: from agents.text_analyzer import analisar_descricao
    # analise_textual = analisar_descricao(imovel_alvo.get("descricao", ""))

    # ------------------------------------------------------------------
    # AGENTE 4 — Avaliação de infraestrutura (pendente)
    # Analisa entorno: escolas, hospitais, comércio via OSM/Google Places
    # ------------------------------------------------------------------
    # TODO: from agents.infra_evaluator import avaliar_infraestrutura
    # infra = avaliar_infraestrutura(imovel_alvo)

    # ------------------------------------------------------------------
    # AGENTE 5 — Estimativa de preço e liquidez (pendente)
    # Consolida tudo e sugere preço que maximize a liquidez
    # ------------------------------------------------------------------
    # TODO: from agents.price_liquidity import estimar_preco
    # estimativa = estimar_preco(imovel_alvo, comparaveis, analise_textual, infra)

    # Retorno parcial — apenas Agente 1 implementado
    return {
        "status":            "parcial — Agente 1 implementado",
        "imovel_alvo":       f"{imovel_alvo.get('rua')} — {imovel_alvo.get('bairro')}",
        "total_comparaveis": len(comparaveis),
        "comparaveis":       comparaveis,
        "preco_estimado":    None,   # preenchido pelo Agente 5
        "liquidez":          None,   # preenchido pelo Agente 5
    }
