"""
Orquestrador do Pipeline Multiagente
======================================

RESPONSABILIDADE:
    Conecta e orquestra os agentes implementados do pipeline.
    Recebe o imóvel alvo e retorna os comparáveis ranqueados
    com validação de zona homogênea.

PIPELINE ATUAL (Agentes 1 e 2 implementados):
    Agente 1 — Coletor
        → Coleta imóveis via Apify (VivaReal, LugarCerto)
        → Enriquece com publishedAt e description via requests.get
        ↓  data/imoveis_completos.json
    Agente 2 — Comparáveis
        → Separa terrenos do clustering
        → Score numérico de similaridade
        → Clustering via LLM (Groq, llama-3.3-70b-versatile)
        → Zona homogênea (Google Maps + Groq Vision)
        ↓  data/imoveis_comparaveis.json
        ↓  data/zona_homogenea.json

PENDENTE:
    Agente 3 — Analisador Textual  → extrai padrão, conservação, diferenciais
    Agente 4 — Infraestrutura      → avalia entorno (OSM, Google Places)
    Agente 5 — Preço e Liquidez    → consolida e estima preço com liquidez

COMO USAR:
    from app.graph import executar_pipeline

    resultado = executar_pipeline({
        "rua":         "Rua Franklin Maximo Pereira",
        "numero":      "188",
        "bairro":      "Centro",
        "cidade":      "Itajai",
        "estado":      "SC",
        "localizacao": "Itajai, SC",
        "tipo":        "house",
        "area":        170,
        "bedrooms":    3,
        "bathrooms":   4,
        "parkingSpaces": 2,
        "pricePerSqm": 8205.88,
        "propertyType": "Casas",
    })
"""

import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


def executar_pipeline(imovel_alvo: dict) -> dict:
    """
    Executa o pipeline completo para o imóvel alvo.

    Parâmetros
    ----------
    imovel_alvo : dict
        Campos obrigatórios: localizacao, tipo, bairro, rua, cidade, estado
        Campos para Agente 2: area, bedrooms, bathrooms, parkingSpaces,
                              pricePerSqm, propertyType

    Retorna
    -------
    dict com:
        status            : "parcial" ou "completo"
        imovel_alvo       : identificação do imóvel
        comparaveis       : lista ranqueada (Cluster A + B + terrenos)
        terrenos          : terrenos separados (para zona homogênea)
        zona_homogenea    : resultado da validação geográfica (se disponível)
        resumo            : totais e método usado
        preco_estimado    : None (preenchido pelo Agente 5)
        liquidez          : None (preenchido pelo Agente 5)
    """
    logger.info("=" * 55)
    logger.info("PIPELINE MULTIAGENTE — PRECIFICAÇÃO IMOBILIÁRIA")
    logger.info("=" * 55)
    logger.info(
        f"Alvo: {imovel_alvo.get('rua')} — "
        f"{imovel_alvo.get('bairro')}, "
        f"{imovel_alvo.get('cidade')}/{imovel_alvo.get('estado')}"
    )

    # ------------------------------------------------------------------
    # AGENTE 1 — Coleta de imóveis comparáveis
    # Apify (ocrad) → VivaReal + LugarCerto
    # Enriquece com publishedAt e description via requests.get
    # ------------------------------------------------------------------
    from agents.collector import coletar_imoveis

    logger.info("Agente 1: coletando imóveis...")
    imoveis_coletados = coletar_imoveis(
        localizacao=imovel_alvo["localizacao"],
        tipo_imovel=imovel_alvo["tipo"],
        bairro=imovel_alvo.get("bairro", ""),
        rua=imovel_alvo.get("rua", ""),
    )
    logger.info(f"Agente 1 concluído: {len(imoveis_coletados)} imóveis coletados")

    if not imoveis_coletados:
        logger.warning("Agente 1 não retornou imóveis — verifique APIFY_TOKEN_2 no .env")
        return {
            "status":         "erro — Agente 1 sem resultados",
            "imovel_alvo":    f"{imovel_alvo.get('rua')} — {imovel_alvo.get('bairro')}",
            "comparaveis":    [],
            "terrenos":       [],
            "zona_homogenea": None,
            "resumo":         {},
            "preco_estimado": None,
            "liquidez":       None,
        }

    # ------------------------------------------------------------------
    # AGENTE 2 — Identificação de comparáveis
    # Score numérico + clustering LLM + zona homogênea
    # ------------------------------------------------------------------
    from agents.comparables import identificar_comparaveis, analisar_zona_homogenea
    import os

    logger.info("Agente 2: identificando comparáveis...")
    resultado_ag2 = identificar_comparaveis(
        imovel_alvo=imovel_alvo,
        imoveis_coletados=imoveis_coletados,
        usar_llm=True,
    )

    comparaveis = resultado_ag2.get("comparaveis", [])
    terrenos    = resultado_ag2.get("terrenos", [])
    resumo      = resultado_ag2.get("resumo", {})
    logger.info(
        f"Agente 2 concluído: "
        f"{resumo.get('cluster_a', 0)} similares | "
        f"{resumo.get('cluster_b', 0)} não similares | "
        f"{resumo.get('terrenos_excluidos', 0)} terrenos"
    )

    # Zona homogênea (opcional — requer GOOGLE_MAPS_KEY)
    zona_resultado = None
    if os.getenv("GOOGLE_MAPS_KEY"):
        logger.info("Agente 2 — Zona homogênea: validando geograficamente...")
        endereco = (
            f"{imovel_alvo.get('rua', '')}, "
            f"{imovel_alvo.get('numero', '')}, "
            f"{imovel_alvo.get('bairro', '')}, "
            f"{imovel_alvo.get('cidade', '')}, "
            f"{imovel_alvo.get('estado', '')}"
        )
        zona_resultado = analisar_zona_homogenea(
            endereco_alvo=endereco,
            imoveis=comparaveis + terrenos,
            cidade=imovel_alvo.get("cidade", ""),
            estado=imovel_alvo.get("estado", ""),
        )
        confirmados = zona_resultado.get("comparaveis_confirmados", [])
        fora        = zona_resultado.get("fora_zona", [])
        logger.info(f"Zona homogênea: {len(confirmados)} na zona | {len(fora)} fora")
    else:
        logger.info("GOOGLE_MAPS_KEY não configurada — zona homogênea pulada")

    # ------------------------------------------------------------------
    # AGENTE 3 — Análise textual (pendente)
    # ------------------------------------------------------------------
    # TODO: from agents.text_analyzer import analisar_descricao
    # analise_textual = analisar_descricao(imovel_alvo.get("description", ""))

    # ------------------------------------------------------------------
    # AGENTE 4 — Avaliação de infraestrutura (pendente)
    # ------------------------------------------------------------------
    # TODO: from agents.infra_evaluator import avaliar_infraestrutura
    # infra = avaliar_infraestrutura(imovel_alvo)

    # ------------------------------------------------------------------
    # AGENTE 5 — Estimativa de preço e liquidez (pendente)
    # ------------------------------------------------------------------
    # TODO: from agents.price_liquidity import estimar_preco
    # estimativa = estimar_preco(imovel_alvo, comparaveis, analise_textual, infra)

    return {
        "status":         "parcial — Agentes 1 e 2 implementados",
        "imovel_alvo":    f"{imovel_alvo.get('rua')} — {imovel_alvo.get('bairro')}",
        "comparaveis":    comparaveis,
        "terrenos":       terrenos,
        "zona_homogenea": zona_resultado,
        "resumo":         resumo,
        "preco_estimado": None,   # preenchido pelo Agente 5
        "liquidez":       None,   # preenchido pelo Agente 5
    }
