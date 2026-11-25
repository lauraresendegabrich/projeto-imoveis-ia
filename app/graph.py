"""
Orquestrador do Pipeline Multiagente
======================================

RESPONSABILIDADE:
    Avaliacao pelo terminal. Chama o MESMO fluxo da tela (services/pipeline.py):
    nao tem fluxo proprio desde 24/11/2026. A descricao abaixo e dos agentes; os
    modelos de IA estao em docs/MODELOS_LLM.md.

PIPELINE:
    Agente 1 — Coletor (sequencial)
        → Fonte principal: Amazon Athena (tabela anuncios em S3/Parquet: VivaReal,
          Lugar Certo, ImovelWeb e Chaves na Mão, coleta mais recente de cada)
        → Fallback: Apify/ocrad (VivaReal, LugarCerto) quando o Athena
          util/local fica abaixo de 10 resultados
        → Normaliza campos, filtra leilões/duplicatas, enriquece fotos
        ↓  data/imoveis_coletados_ag1.json
        ↓  data/imoveis_completos_ag1.json

    Agente 2 — Comparáveis (sequencial, depende do Ag. 1)
        → Separa terrenos do clustering
        → Pré-classificação determinística + score numérico de similaridade
        → Clustering via LLM (cadeia Qwen3-VL-8B Colab → Groq openai/gpt-oss-120b
          → Groq_2 → Gemini → NVIDIA nemotron; nomes no .env)
        → Zona homogênea (Google Maps + LLM de visão sobre imagem de satélite)
        ↓  data/imoveis_comparaveis_ag2.json
        ↓  data/zona_homogenea_ag2.json

    Agente 3 — Analisador Qualitativo (PARALELO, depende do Ag. 2)
        → Analisa texto + fotos (multimodal). Cadeia: Qwen3-VL-8B Colab → Groq
          → NVIDIA nemotron-vl → Gemini
        → Fotos por provider: Qwen 4, Gemini 4, Groq 2, NVIDIA 1 (interface aceita até 8)
        → Score qualitativo determinístico por imóvel (+ score_llm comparativo)
        ↓  data/imoveis_analisados_ag3.json

    Agente 4 — Infraestrutura (PARALELO, depende do Ag. 2)
        → Busca POIs via Geoapify Places (fallback Google Places) em 3 faixas
        → Score de infraestrutura determinístico multifaixa
        → Nível 2: LLM classifica perfil da região e ajusta o score em ±0.10
          (cadeia Qwen → Gemini → Groq → NVIDIA)
        ↓  data/infra_avaliada_ag4.json

    Agente 5 — Estimador de Preço (sequencial, depende dos Ag. 3 e 4)
        → Calcula valor m² da zona (terreno + construção por padrão)
        → Estima valor mínimo, médio e de liquidez (TRIMMEAN 0.5, desconto 10%)
        → Estima tempo de venda (liquidez experimental)
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


def executar_pipeline(imovel_alvo: dict, dados_leilao: dict | None = None, gravar: bool = False) -> dict:
    """
    Avaliacao completa pelo terminal: o MESMO fluxo da tela (services/pipeline.py).

    Ate 24/11/2026 este arquivo tinha o proprio fluxo, que ficou para tras da tela
    (nao localizava o alvo antes da coleta, mandava os terrenos para a zona por outro
    caminho, nao passava o imovel ao Agente 3 nem avaliava o leilao). Agora so chama
    o fluxo unico; nao mexa nos agentes por aqui.

    imovel_alvo: no formato dos agentes (tipo "house"/"apartment"); para montar a
        partir dos campos do formulario, use services.pipeline.montar_imovel_alvo.
    dados_leilao: o de services.leilao.ler_formulario_leilao (opcional).
    gravar: False (padrao) = nao grava no banco; True = grava como a tela.

    Retorna as chaves de sempre (status, comparaveis, terrenos, zona_homogenea,
    analise_qualitativa, infraestrutura, preco_estimado, resumo) e mais as da tela
    (leilao, verificacoes, falhas...), em "resultado_completo".
    """
    from services.pipeline import ObservadorLog, executar_avaliacao

    imovel_alvo = dict(imovel_alvo)
    imovel_alvo.setdefault("localizacao", f"{imovel_alvo.get('cidade')}, {imovel_alvo.get('estado')}")
    imovel_alvo.setdefault("neighborhood", imovel_alvo.get("bairro"))
    imovel_alvo.setdefault("street", imovel_alvo.get("rua"))
    imovel_alvo.setdefault("images", [])
    rotulo = f"{imovel_alvo.get('rua')} — {imovel_alvo.get('bairro')}"
    logger.info("=" * 55)
    logger.info("PIPELINE MULTIAGENTE — PRECIFICAÇÃO IMOBILIÁRIA (fluxo da tela)")
    logger.info("=" * 55)
    logger.info(f"Alvo: {rotulo}, {imovel_alvo.get('cidade')}/{imovel_alvo.get('estado')}")

    saida = executar_avaliacao(imovel_alvo, dados_leilao=dados_leilao, obs=ObservadorLog(), gravar=gravar)
    resultado = saida["resultado"] or {}
    if saida["parada"] == "sem_comparaveis":
        status = "erro — Agente 2 sem comparáveis (LLM não classificou nenhum como similar)"
    elif saida["parada"] == "sem_anuncios":
        status = "erro — Agente 1 sem resultados"
    elif resultado.get("falhas"):
        status = f"parcial — {len(resultado['falhas'])} falha(s): {'; '.join(resultado['falhas'])}"
    else:
        status = "completo — Agentes 1 a 5 executados"
    return {
        "status": status,
        "id_execucao": resultado.get("id_execucao"),
        "imovel_alvo": rotulo,
        "comparaveis": resultado.get("comparaveis", []),
        "terrenos": resultado.get("terrenos", []),
        "zona_homogenea": resultado.get("zona_homogenea"),
        "analise_qualitativa": resultado.get("analise_qualitativa", {}),
        "infraestrutura": resultado.get("infraestrutura", {}),
        "preco_estimado": resultado.get("preco_estimado"),
        "resumo": resultado.get("resumo", {}),
        "leilao": resultado.get("leilao"),
        "resultado_completo": resultado,
    }
