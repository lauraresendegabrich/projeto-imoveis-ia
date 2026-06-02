"""
Orquestrador do Pipeline Multiagente
======================================

RESPONSABILIDADE:
    Conecta e orquestra os agentes implementados do pipeline.
    Recebe o imóvel alvo e retorna os comparáveis ranqueados
    com análise qualitativa e de infraestrutura.

PIPELINE:
    Agente 1 — Coletor (sequencial)
        → Coleta imóveis via Apify (VivaReal, LugarCerto)
        → Enriquece com publishedAt, description e URLs de imagens
        ↓  data/imoveis_completos_ag1.json

    Agente 2 — Comparáveis (sequencial, depende do Ag. 1)
        → Separa terrenos do clustering
        → Score numérico de similaridade
        → Clustering via LLM (Groq, llama-3.3-70b-versatile)
        → Zona homogênea (Google Maps + Groq Vision)
        ↓  data/imoveis_comparaveis_ag2.json
        ↓  data/zona_homogenea_ag2.json

    Agente 3 — Analisador Qualitativo (PARALELO, depende do Ag. 2)
        → Analisa texto + 8 fotos via NVIDIA NIM (ministral-14b)
        → Score qualitativo por imóvel
        ↓  data/imoveis_analisados_ag3.json

    Agente 4 — Infraestrutura (PARALELO, depende do Ag. 2)
        → Busca POIs via osmnx (OpenStreetMap) em 3 faixas
        → Score de infraestrutura multifaixa
        ↓  data/infra_avaliada_ag4.json

    Agente 5 — Estimador de Preço (sequencial, depende dos Ag. 3 e 4)
        → Calcula valor m² da zona (terreno + construção por padrão)
        → Estima valor mínimo, médio e de liquidez
        → Estima tempo de venda
        ↓  data/preco_liquidez_ag5.json

PENDENTE:
    Nenhum — pipeline completo (5 agentes implementados)

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

    comparaveis = []
    terrenos = []
    resumo = {}
    zona_resultado = None

    try:
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
    except Exception as e:
        logger.error(f"Agente 2 falhou: {e}")
        return {
            "status":         f"erro — Agente 2 falhou: {str(e)}",
            "imovel_alvo":    f"{imovel_alvo.get('rua')} — {imovel_alvo.get('bairro')}",
            "comparaveis":    [],
            "terrenos":       [],
            "zona_homogenea": None,
            "resumo":         {},
            "preco_estimado": None,
        }

    if not comparaveis:
        logger.warning("Agente 2 não encontrou comparáveis — pipeline não pode continuar")
        return {
            "status":         "erro — Agente 2 sem comparáveis (LLM não classificou nenhum como similar)",
            "imovel_alvo":    f"{imovel_alvo.get('rua')} — {imovel_alvo.get('bairro')}",
            "comparaveis":    [],
            "terrenos":       terrenos,
            "zona_homogenea": None,
            "resumo":         resumo,
            "preco_estimado": None,
        }
    # Zona homogênea (opcional — requer GOOGLE_MAPS_KEY)
    zona_resultado = None
    if os.getenv("GOOGLE_MAPS_KEY"):
        try:
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
        except Exception as e:
            logger.error(f"Zona homogênea falhou: {e} — continuando sem ela")
            zona_resultado = None
    else:
        logger.info("GOOGLE_MAPS_KEY não configurada — zona homogênea pulada")

    # ------------------------------------------------------------------
    # AGENTES 3 e 4 — PARALELO (ambos dependem do Ag. 2, não entre si)
    # ------------------------------------------------------------------
    from agents.text_analyzer import analisar_comparaveis
    from agents.infra_evaluator import avaliar_infraestrutura
    from concurrent.futures import ThreadPoolExecutor

    logger.info("Agentes 3 e 4: rodando em paralelo...")

    resultado_ag3 = {}
    resultado_ag4 = {}
    falhas = []

    with ThreadPoolExecutor(max_workers=2) as executor:
        # Agente 3 — Análise qualitativa (texto + fotos)
        future_ag3 = executor.submit(analisar_comparaveis)

        # Agente 4 — Infraestrutura (POIs do entorno)
        future_ag4 = executor.submit(avaliar_infraestrutura)

        # Coleta resultado do Agente 3 com tratamento de erro
        try:
            resultado_ag3 = future_ag3.result()
            if not resultado_ag3:
                falhas.append("Agente 3 retornou vazio — analise qualitativa indisponivel")
                logger.warning("Agente 3 retornou resultado vazio")
            else:
                logger.info(f"Agente 3 concluído: score médio = {resultado_ag3.get('resumo', {}).get('score_qualitativo_medio', '?')}")
        except Exception as e:
            falhas.append(f"Agente 3 falhou: {str(e)}")
            logger.error(f"Agente 3 falhou com erro: {e}")

        # Coleta resultado do Agente 4 com tratamento de erro
        try:
            resultado_ag4 = future_ag4.result()
            if not resultado_ag4:
                falhas.append("Agente 4 retornou vazio — analise de infraestrutura indisponivel")
                logger.warning("Agente 4 retornou resultado vazio")
            else:
                logger.info(f"Agente 4 concluído: score infra = {resultado_ag4.get('scores', {}).get('score_final', '?')}")
        except Exception as e:
            falhas.append(f"Agente 4 falhou: {str(e)}")
            logger.error(f"Agente 4 falhou com erro: {e}")

    # ------------------------------------------------------------------
    # AGENTE 5 — Estimativa de preço e liquidez
    # Depende dos Ag. 3 e 4, mas funciona com dados parciais
    # ------------------------------------------------------------------
    from agents.price_liquidity import estimar_preco

    resultado_ag5 = {}
    try:
        logger.info("Agente 5: estimando preço e liquidez...")
        resultado_ag5 = estimar_preco(imovel_alvo_extra=imovel_alvo)
        logger.info(
            f"Agente 5 concluído: valor médio = R$ {resultado_ag5.get('avaliacao', {}).get('valor_medio_imovel', '?'):,.2f}"
        )
    except Exception as e:
        falhas.append(f"Agente 5 falhou: {str(e)}")
        logger.error(f"Agente 5 falhou com erro: {e}")

    # ------------------------------------------------------------------
    # RESULTADO FINAL
    # ------------------------------------------------------------------
    if falhas:
        logger.warning(f"Pipeline concluído com {len(falhas)} falha(s):")
        for f in falhas:
            logger.warning(f"  - {f}")

    status = "completo — Agentes 1 a 5 executados"
    if falhas:
        status = f"parcial — {len(falhas)} falha(s): {'; '.join(falhas)}"

    return {
        "status":              status,
        "imovel_alvo":         f"{imovel_alvo.get('rua')} — {imovel_alvo.get('bairro')}",
        "comparaveis":         comparaveis,
        "terrenos":            terrenos,
        "zona_homogenea":      zona_resultado,
        "analise_qualitativa": resultado_ag3,
        "infraestrutura":      resultado_ag4,
        "preco_estimado":      resultado_ag5,
        "resumo":              resumo,
    }
