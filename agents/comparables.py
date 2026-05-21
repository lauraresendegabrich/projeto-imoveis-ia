"""
Agente 2 - Identificador de Imoveis Comparaveis
=================================================

COMO FUNCIONA:
==============

Recebe os imoveis coletados pelo Agente 1 (imoveis_completos.json) e as
caracteristicas do imovel alvo. Identifica quais sao realmente comparaveis
usando 2 tecnicas combinadas:

  ETAPA 1 — SIMILARIDADE NUMERICA (sem LLM, instantaneo):
  ─────────────────────────────────────────────────────────
    Calcula um score de 0.0 a 1.0 para cada imovel baseado em:
      - area (m²)    — peso 30% (fator mais importante na avaliacao)
      - quartos      — peso 25%
      - preco/m²     — peso 20% (indica padrao construtivo similar)
      - banheiros    — peso 15%
      - vagas        — peso 10%

    Formula: para cada campo, calcula a distancia relativa entre alvo e
    candidato (|alvo - cand| / max), converte pra similaridade (1 - dist),
    e pondera pelo peso. Score final = media ponderada.

    Exemplo: alvo 170m² vs candidato 160m²
      distancia = |170-160| / 170 = 0.059
      similaridade = 1 - 0.059 = 0.941 (muito similar)

  ETAPA 2 — CLUSTERING VIA LLM (Groq, llama-3.3-70b-versatile):
  ──────────────────────────────────────────────────────────────
    Envia apenas casas/apartamentos para a LLM (terrenos sao excluidos
    antes — tipo incomparavel com imovel construido). Envia com:
      - Caracteristicas do imovel alvo
      - Caracteristicas completas de cada candidato (sem score, pra nao enviesar)
      - Criterios de avaliacao imobiliaria

    A LLM retorna:
      - Cluster A ou B para cada imovel (similar vs nao similar)
      - Ranking global de 1 a N (todos ranqueados)
      - Justificativa em 1 frase para cada classificacao

    A LLM entende nuances que o score numerico nao pega:
      - Terreno vazio vs casa construida (tipo diferente)
      - Casa com kitnets alugadas (uso diferente)
      - Preco absurdo (R$ 8M vs R$ 1.4M = padrao incompativel)

    NOTA: O score numerico NAO e enviado pra LLM pra evitar viés.
    A LLM faz sua propria analise baseada nas caracteristicas.

FLUXO COMPLETO:
───────────────
  1. Carrega imoveis_completos.json (saida do Agente 1, todos os tipos)
  2. Separa terrenos (propertyType == "Terrenos") do restante:
       → Terrenos NAO entram no ranking nem no clustering via LLM
         (score numerico seria distorcido — sem quartos, banheiros, vagas)
       → Terrenos SIM sao enviados para a Etapa 3 (zona homogenea),
         pois a validacao geografica por distancia e relevante
         independente do tipo de imovel
  3. Calcula score numerico de similaridade so para casas/apartamentos
  4. LLM (Groq) clusteriza e ranqueia apenas casas/apartamentos:
       → Cluster A: similares ao alvo
       → Cluster B: nao similares
  5. Ordena: Cluster A primeiro (por ranking_llm), depois Cluster B
  6. Terrenos sao adicionados ao final com cluster="terreno", ranking_llm=null
  7. Salva em data/imoveis_comparaveis.json

FALLBACK (se LLM falhar):
─────────────────────────
  Usa apenas o score numerico:
    - Score >= 0.60 → Cluster A (similar)
    - Score < 0.60  → Cluster B (nao similar)
    - Ranking = posicao no score (1 = maior score)

DEPENDENCIAS:
─────────────
  - Groq (gratis, 14.400 req/dia) — modelo llama-3.3-70b-versatile
  - langchain-groq (pip install langchain-groq)
  - Dados do Agente 1: data/imoveis_completos.json

ENTRADA:
────────
  - imovel_alvo: dict com area, bedrooms, bathrooms, parkingSpaces,
    pricePerSqm, propertyType, neighborhood, street, description
  - data/imoveis_completos.json (gerado pelo Agente 1)

SAIDA: data/imoveis_comparaveis.json
──────
  {
    "imovel_alvo": {...},
    "comparaveis": [
      {
        ...campos do imovel...,
        "score_similaridade": 0.85,
        "ranking_llm": 1,
        "cluster": "A",              ← "A" (similar) ou "B" (nao similar)
        "justificativa": "Area e quartos proximos, mesmo bairro..."
      },
      {
        ...campos do terreno...,
        "score_similaridade": null,  ← terrenos nao tem score
        "ranking_llm": null,         ← terrenos nao foram ranqueados
        "cluster": "terreno",        ← identificados separadamente
        "justificativa": "Terreno excluido do ranking — tipo incomparavel..."
      }
    ],
    "terrenos": [...],               ← lista separada so com os terrenos
    "resumo": {
      "total_analisados": 28,        ← so casas/apartamentos
      "cluster_a": 14,
      "cluster_b": 14,
      "terrenos_excluidos": 17,      ← contagem dos terrenos separados
      "metodo": "similaridade_numerica + clustering_llm"
    }
  }

ETAPA 3 — ZONA HOMOGENEA (Google Maps + Groq Vision):
──────────────────────────────────────────────────────
  Valida geograficamente os imoveis usando imagem de satelite + IA de visao.
  1. Geocodifica endereco do alvo (Nominatim → lat/lng; fallback: Google Geocoding API),
  2. Google Maps Static API gera imagem hybrid  1280x1280 scale=2 com marcador
  3. Groq Vision (Llama 4 Scout 17B) analisa a imagem e retorna:
     tipo_regiao, uso_predominante, padrao_construtivo, densidade_urbana,
     homogeneidade_visual, infraestrutura, elementos de valor,
     raio_sugerido_metros, justificativa, confianca, limitacoes
  4. Geocodifica cada imovel e calcula distancia (Haversine)
  5. Classifica: na_zona (ate raio da LLM) ou fora_zona (acima)

  SAIDA: data/zona_homogenea.json + data/satelite_zona_homogenea.png

COMO RODAR:
───────────
  .venv/Scripts/python.exe -m tests.test_comparaveis
"""

import os
import re
import json
import logging
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


# =============================================================================
# BLOCO 1 - SIMILARIDADE NUMERICA
# =============================================================================

def _calcular_score_similaridade(alvo: dict, candidato: dict) -> float:
    """
    Calcula score de similaridade entre o imovel alvo e um candidato.
    Score de 0.0 (totalmente diferente) a 1.0 (identico).

    Pesos:
      - area: 30% (m² e o fator mais importante na avaliacao)
      - quartos: 25%
      - preco_m2: 20% (indica padrao construtivo similar)
      - banheiros: 15%
      - vagas: 10%

    Usa distancia relativa: |alvo - candidato| / max(alvo, candidato)
    Se um campo esta ausente, usa penalidade de 50% naquele peso.
    """
    pesos = {
        "area": 0.30,
        "bedrooms": 0.25,
        "pricePerSqm": 0.20,
        "bathrooms": 0.15,
        "parkingSpaces": 0.10,
    }

    score_total = 0.0
    peso_total = 0.0

    for campo, peso in pesos.items():
        val_alvo = alvo.get(campo)
        val_cand = candidato.get(campo)

        if val_alvo and val_cand and val_alvo > 0 and val_cand > 0:
            # Distancia relativa: 0 = identico, 1 = totalmente diferente
            maximo = max(val_alvo, val_cand)
            distancia = abs(val_alvo - val_cand) / maximo
            # Converte pra similaridade: 1 = identico, 0 = diferente
            similaridade = max(0, 1 - distancia)
            score_total += similaridade * peso
            peso_total += peso
        elif val_alvo or val_cand:
            # Um tem o campo e outro nao — penalidade parcial
            score_total += 0.5 * peso
            peso_total += peso
        # Se ambos nao tem, ignora o campo

    if peso_total == 0:
        return 0.0

    return round(score_total / peso_total, 4)


# =============================================================================
# BLOCO 2 - CLUSTERING VIA LLM
# =============================================================================

def _montar_prompt_clustering(alvo: dict, candidatos: list[dict]) -> str:
    """
    Monta o prompt para a LLM clusterizar os imoveis.
    Envia caracteristicas resumidas (sem URLs/imagens) pra economizar tokens.
    """
    # Resumo do imovel alvo
    alvo_resumo = (
        f"IMOVEL ALVO:\n"
        f"  Tipo: {alvo.get('propertyType', '?')}\n"
        f"  Area: {alvo.get('area', '?')} m²\n"
        f"  Quartos: {alvo.get('bedrooms', '?')}\n"
        f"  Banheiros: {alvo.get('bathrooms', '?')}\n"
        f"  Vagas: {alvo.get('parkingSpaces', '?')}\n"
        f"  Preco: {alvo.get('priceFormatted', '?')}\n"
        f"  Preco/m²: R$ {alvo.get('pricePerSqm', '?')}\n"
        f"  Bairro: {alvo.get('neighborhood', '?')}\n"
        f"  Rua: {alvo.get('street', '?')}\n"
        f"  Descricao: {(alvo.get('description') or '')[:200]}\n"
    )

    # Lista de candidatos (caracteristicas completas, sem score pra nao enviesar)
    candidatos_texto = ""
    for idx, c in enumerate(candidatos, 1):
        desc = (c.get("description") or "")[:300]
        candidatos_texto += (
            f"\n[{idx}]\n"
            f"  Tipo: {c.get('propertyType', '?')} | Area: {c.get('area', '?')}m² | "
            f"Quartos: {c.get('bedrooms', '?')} | Banheiros: {c.get('bathrooms', '?')} | "
            f"Vagas: {c.get('parkingSpaces', '?')}\n"
            f"  Preco: {c.get('priceFormatted', '?')} | Preco/m²: R$ {c.get('pricePerSqm', '?')}\n"
            f"  Bairro: {c.get('neighborhood', '?')} | Rua: {c.get('street', '?')}\n"
        )
        if desc:
            candidatos_texto += f"  Descricao: {desc}\n"

    prompt = f"""Voce e um avaliador imobiliario. Analise os imoveis abaixo e classifique cada um.

{alvo_resumo}

IMOVEIS CANDIDATOS ({len(candidatos)} imoveis):
{candidatos_texto}

TAREFA:
1. Classifique cada imovel em CLUSTER A (similar ao alvo) ou CLUSTER B (nao similar).
2. Ordene TODOS por similaridade (1 = mais similar, independente do cluster).
3. Justifique brevemente cada classificacao (1 frase).

CRITERIOS para Cluster A (similar):
- Mesmo tipo de imovel (casa com casa, terreno com terreno)
- Area na mesma faixa (diferenca ate 50% e aceitavel)
- Numero de quartos proximo (diferenca de 1 quarto e aceitavel)
- Mesmo bairro ou regiao equivalente
- Preco/m² na mesma faixa (diferenca ate 50% e aceitavel)
- NAO precisa ser identico — basta ser comparavel para avaliacao

CRITERIOS para Cluster B (nao similar):
- Tipo diferente (terreno vazio vs casa construida)
- Area MUITO diferente (terreno de 500m² vs casa de 100m²)
- Padrao MUITO diferente (kitnet vs mansao)
- Uso diferente (comercial vs residencial)

IMPORTANTE: Na avaliacao imobiliaria, imoveis "comparaveis" sao aqueles
que um comprador consideraria como alternativa. Casas de 3 quartos com
135-226m² no mesmo bairro SAO comparaveis entre si, mesmo com diferencas
de preco. Diferenca de 1 banheiro ou 1 vaga NAO desqualifica um imovel.
Seja GENEROSO no Cluster A — so coloque no B se for realmente
incompativel (tipo diferente, area >2x maior/menor, ou uso diferente).

RESPONDA EXATAMENTE neste formato JSON (sem texto antes ou depois):
{{
  "classificacao": [
    {{"id": 1, "cluster": "A", "ranking": 1, "justificativa": "..."}},
    {{"id": 2, "cluster": "B", "ranking": 15, "justificativa": "..."}},
    ...
  ]
}}"""

    return prompt


def _chamar_llm(prompt: str) -> str:
    """
    Chama a LLM (Groq) e retorna a resposta como texto.
    Usa llama-3.3-70b-versatile — melhor modelo gratuito pra
    tarefas de classificacao/clustering imobiliario.
    Groq: ~6s por chamada, 100 req/min no free tier.
    """
    try:
        from langchain_groq import ChatGroq
        api_key = os.getenv("GROQ_API_KEY", "")
        if not api_key:
            logger.warning("GROQ_API_KEY nao configurada")
            return ""
        llm = ChatGroq(
            model="llama-3.3-70b-versatile",
            api_key=api_key,
            temperature=0,
        )
        resposta = llm.invoke(prompt)
        if hasattr(resposta, "content"):
            return resposta.content
        return str(resposta)
    except Exception as e:
        logger.error(f"Erro ao chamar LLM: {e}")
        return ""


def _parsear_resposta_llm(resposta: str, candidatos: list[dict]) -> list[dict]:
    """
    Parseia a resposta JSON da LLM e aplica nos candidatos.
    Se a LLM falhar, usa fallback baseado no score numerico.
    """
    # Tenta extrair JSON da resposta
    m = re.search(r'\{[\s\S]*"classificacao"[\s\S]*\}', resposta)
    if not m:
        logger.warning("LLM nao retornou JSON valido — usando fallback numerico")
        return _fallback_numerico(candidatos)

    try:
        data = json.loads(m.group(0))
        classificacoes = data.get("classificacao", [])
    except json.JSONDecodeError:
        logger.warning("JSON invalido da LLM — usando fallback numerico")
        return _fallback_numerico(candidatos)

    # Aplica classificacoes nos candidatos
    for item in classificacoes:
        idx = item.get("id", 0) - 1  # 1-indexed -> 0-indexed
        if 0 <= idx < len(candidatos):
            candidatos[idx]["cluster"] = item.get("cluster", "B")
            candidatos[idx]["ranking_llm"] = item.get("ranking")
            candidatos[idx]["justificativa"] = item.get("justificativa", "")

    # Garante que todos tem os campos
    for c in candidatos:
        if "cluster" not in c:
            c["cluster"] = "B"
        if "ranking_llm" not in c:
            c["ranking_llm"] = None
        if "justificativa" not in c:
            c["justificativa"] = ""

    return candidatos


def _fallback_numerico(candidatos: list[dict]) -> list[dict]:
    """
    Fallback quando a LLM falha: usa score numerico pra clusterizar.
    Cluster A: score >= 0.60 (similar)
    Cluster B: score < 0.60 (nao similar)
    Ranking: todos recebem (1 = mais similar).
    """
    THRESHOLD = 0.60

    # Ordena por score
    ordenados = sorted(candidatos, key=lambda x: x.get("score_similaridade", 0), reverse=True)

    for ranking, c in enumerate(ordenados, 1):
        score = c.get("score_similaridade", 0)
        c["ranking_llm"] = ranking
        if score >= THRESHOLD:
            c["cluster"] = "A"
            c["justificativa"] = f"Score numerico {score:.2f} >= {THRESHOLD} (threshold)"
        else:
            c["cluster"] = "B"
            c["justificativa"] = f"Score numerico {score:.2f} < {THRESHOLD} (threshold)"

    return ordenados


# =============================================================================
# BLOCO 3 - FUNCAO PUBLICA
# =============================================================================

def identificar_comparaveis(
    imovel_alvo: dict,
    imoveis_coletados: Optional[list[dict]] = None,
    arquivo_entrada: str = "imoveis_completos_ag1.json",
    arquivo_saida: str = "imoveis_comparaveis_ag2.json",
    usar_llm: bool = True,
) -> dict:
    """
    Identifica imoveis comparaveis ao alvo usando similaridade numerica + LLM.

    Fluxo:
        1. Carrega todos os imoveis do Agente 1 (imoveis_completos.json)
        2. Calcula score numerico de similaridade pra cada um
        3. Envia TODOS pra LLM (Groq, llama-3.3-70b) clusterizar e ranquear
        4. LLM classifica em Cluster A (similar) ou B (nao similar)
        5. LLM ranqueia todos de 1 a N (1 = mais similar)
        6. Salva resultado em data/imoveis_comparaveis.json

    Parametros
    ----------
    imovel_alvo : dict
        Caracteristicas do imovel alvo. Campos usados:
        area, bedrooms, bathrooms, parkingSpaces, pricePerSqm,
        propertyType, neighborhood, street, description
    imoveis_coletados : list[dict], optional
        Lista de imoveis. Se None, carrega do arquivo.
    arquivo_entrada : str
        Arquivo JSON com imoveis do Agente 1 (default: imoveis_completos.json).
    arquivo_saida : str
        Arquivo JSON de saida com ranking e clusters.
    usar_llm : bool
        Se True, usa LLM para clustering. Se False, usa so score numerico.

    Retorna
    -------
    dict com:
      - imovel_alvo: caracteristicas do alvo
      - comparaveis: lista ranqueada com score, cluster, ranking, justificativa
      - resumo: totais e metodo usado
    """
    logger.info("=" * 55)
    logger.info("AGENTE 2: IDENTIFICADOR DE COMPARAVEIS")
    logger.info("=" * 55)

    # ── CARREGA DADOS ─────────────────────────────────────────────
    if imoveis_coletados is None:
        caminho = os.path.join(DATA_DIR, arquivo_entrada)
        if not os.path.exists(caminho):
            # Fallback: tenta agent1_imoveis_coletados.json
            caminho = os.path.join(DATA_DIR, "imoveis_coletados_ag1.json")
        if not os.path.exists(caminho):
            logger.error("Nenhum arquivo de imoveis encontrado")
            return {"imovel_alvo": imovel_alvo, "comparaveis": [], "resumo": {}}

        with open(caminho, "r", encoding="utf-8") as f:
            imoveis_coletados = json.load(f)
        logger.info(f"Carregados: {len(imoveis_coletados)} imoveis de {caminho}")

    # ── FILTRA POR TIPO ───────────────────────────────────────────
    # Terrenos sao separados antes do ranking/clustering:
    #   - Nao faz sentido comparar terreno vazio com casa construida
    #   - Score numerico seria distorcido (sem quartos, banheiros, vagas)
    #   - LLM nao precisa gastar tokens avaliando algo que nao e comparavel
    # Terrenos ficam no resultado final com cluster="terreno" (sem ranking)
    terrenos = [i for i in imoveis_coletados if (i.get("propertyType") or "").lower() == "terrenos"]
    filtrados = [i for i in imoveis_coletados if (i.get("propertyType") or "").lower() != "terrenos"]
    logger.info(f"Total para analise: {len(filtrados)} imoveis (terrenos excluidos do ranking: {len(terrenos)})")

    # ── CALCULA SCORE NUMERICO ────────────────────────────────────
    for im in filtrados:
        im["score_similaridade"] = _calcular_score_similaridade(imovel_alvo, im)

    # Ordena por score (mais similar primeiro)
    filtrados.sort(key=lambda x: x.get("score_similaridade", 0), reverse=True)
    logger.info(f"Scores calculados. Top 5:")
    for i, im in enumerate(filtrados[:5]):
        logger.info(f"  [{i+1}] score={im['score_similaridade']:.3f} | "
                    f"{im.get('area','?')}m² | {im.get('bedrooms','?')}q | "
                    f"{im.get('priceFormatted','?')} | {im.get('street') or im.get('neighborhood','?')}")

    # ── CLUSTERING VIA LLM ────────────────────────────────────────
    # Envia todos os candidatos para a LLM em lotes de 40
    # (llama-3.3-70b-versatile: limite de ~12.000 tokens/min no free tier)
    # Cada lote e processado separadamente e os resultados sao combinados
    TAMANHO_LOTE = 40

    if usar_llm:
        todos_classificados = []
        lotes = [filtrados[i:i+TAMANHO_LOTE] for i in range(0, len(filtrados), TAMANHO_LOTE)]
        logger.info(f"Enviando {len(filtrados)} candidatos para LLM em {len(lotes)} lote(s) de ate {TAMANHO_LOTE}...")

        for num_lote, lote in enumerate(lotes, 1):
            logger.info(f"  Lote {num_lote}/{len(lotes)}: {len(lote)} candidatos...")
            prompt = _montar_prompt_clustering(imovel_alvo, lote)
            resposta = _chamar_llm(prompt)

            if resposta:
                logger.info(f"  Lote {num_lote}: LLM respondeu ({len(resposta)} chars)")
                lote = _parsear_resposta_llm(resposta, lote)
            else:
                logger.warning(f"  Lote {num_lote}: LLM sem resposta — fallback numerico")
                lote = _fallback_numerico(lote)

            todos_classificados.extend(lote)

            # Pausa entre lotes para nao estourar o rate limit de tokens/min
            if num_lote < len(lotes):
                import time
                time.sleep(3)

        candidatos_llm = todos_classificados
    else:
        logger.info("LLM desativada — usando apenas score numerico")
        candidatos_llm = _fallback_numerico(filtrados)

    excluidos_llm = []  # todos foram processados (por lote ou fallback)

    # ── ORDENA RESULTADO FINAL ────────────────────────────────────
    # Cluster A primeiro (ordenado por ranking_llm), depois Cluster B, terrenos por ultimo
    todos = candidatos_llm + excluidos_llm
    cluster_a = sorted(
        [c for c in todos if c.get("cluster") == "A"],
        key=lambda x: x.get("ranking_llm") or 999
    )
    cluster_b = [c for c in todos if c.get("cluster") != "A"]

    # Terrenos nao passaram pelo ranking/clustering — marcados separadamente
    for t in terrenos:
        t["cluster"] = "terreno"
        t["ranking_llm"] = None
        t["justificativa"] = "Terreno excluido do ranking — tipo incomparavel com imovel construido"

    resultado_final = cluster_a + cluster_b + terrenos

    # ── RESUMO ────────────────────────────────────────────────────
    resumo = {
        "total_analisados": len(candidatos_llm),
        "cluster_a": len(cluster_a),
        "cluster_b": len(cluster_b),
        "terrenos_excluidos": len(terrenos),
        "metodo": "similaridade_numerica + clustering_llm" if usar_llm else "similaridade_numerica",
    }

    logger.info("=" * 55)
    logger.info(f"RESULTADO: {resumo['cluster_a']} similares | {resumo['cluster_b']} nao similares | {resumo['terrenos_excluidos']} terrenos excluidos")
    logger.info(f"  Total analisados: {resumo['total_analisados']}")
    logger.info(f"  Metodo: {resumo['metodo']}")
    logger.info("=" * 55)

    # ── SALVA ─────────────────────────────────────────────────────
    saida = {
        "imovel_alvo": imovel_alvo,
        "comparaveis": resultado_final,
        "terrenos": terrenos,   # separados — nao passaram pelo ranking, mas vao para zona homogenea
        "resumo": resumo,
    }

    caminho_saida = os.path.join(DATA_DIR, arquivo_saida)
    with open(caminho_saida, "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=2)
    logger.info(f"Salvo em: {caminho_saida}")

    return saida


# =============================================================================
# BLOCO 4 - ZONA HOMOGENEA (Google Maps + Groq Vision)
# =============================================================================

def _obter_imagem_satelite(endereco: str, lat: float = None, lon: float = None, zoom: int = 16) -> bytes:
    """
    Gera imagem de satelite via Google Maps Static API.
    Usa maptype=hybrid (satelite + nomes de ruas) com scale=2 (alta resolucao)
    e marcador vermelho no imovel alvo.
    Retorna bytes da imagem PNG (1280x1280 pixels efetivos).
    Gasta 1 chamada das 10.000/mes gratis.
    """
    maps_key = os.getenv("GOOGLE_MAPS_KEY", "")
    if not maps_key:
        logger.warning("GOOGLE_MAPS_KEY nao configurada")
        return b""

    import requests

    # Usa coordenadas se disponiveis, senao endereco textual
    center = f"{lat},{lon}" if lat and lon else endereco

    params = {
        "center": center,
        "zoom": zoom,
        "size": "640x640",
        "scale": 2,  # Alta resolucao (1280x1280 efetivo)
        "maptype": "hybrid",  # Satelite + nomes de ruas
        "markers": f"color:red|{center}",  # Marcador no alvo
        "key": maps_key,
    }
    try:
        r = requests.get(
            "https://maps.googleapis.com/maps/api/staticmap",
            params=params,
            timeout=15,
        )
        if r.status_code == 200 and "image" in r.headers.get("content-type", ""):
            return r.content
        else:
            logger.warning(f"Maps Static API erro: {r.status_code}")
            return b""
    except Exception as e:
        logger.warning(f"Maps Static API falhou: {e}")
        return b""


def _analisar_zona_homogenea(imagem_bytes: bytes, endereco_alvo: str) -> dict:
    """
    Envia imagem de satelite pro Groq Vision (Llama 4 Scout 17B)
    e pede pra analisar a regiao e identificar a zona homogenea.

    Foca nos tres fatores prioritarios para definir a zona:
      - Padrao construtivo aparente (casas, sobrados, predios, misto)
      - Homogeneidade visual (alta, media, baixa)
      - Densidade urbana (baixa, media, alta)

    Retorna dict com:
      - padrao_construtivo: str
      - homogeneidade_visual: str
      - densidade_urbana: str
      - raio_sugerido_metros: int
      - justificativa_raio: str
      - descricao_zona_homogenea: str
      - confianca: str
    """
    import base64
    from openai import OpenAI

    groq_key = os.getenv("GROQ_API_KEY", "")
    if not groq_key:
        return {}

    img_b64 = base64.b64encode(imagem_bytes).decode("utf-8")

    client = OpenAI(
        base_url="https://api.groq.com/openai/v1",
        api_key=groq_key,
    )

    prompt = f"""Voce e um assistente especializado em analise urbana para avaliacao imobiliaria.
Analise a imagem de satelite/mapa hibrido da regiao de um imovel marcado no mapa.

Endereco do imovel alvo (marcador vermelho): {endereco_alvo}

Analise apenas o que pode ser observado na imagem. Nao invente informacoes.

Foque nos tres aspectos mais importantes para definir a zona homogenea:
1. PADRAO CONSTRUTIVO APARENTE — que tipo de edificacoes predominam visualmente
2. HOMOGENEIDADE VISUAL — o quanto a regiao e uniforme em padrao e uso
3. DENSIDADE URBANA — quao ocupada e a regiao

Com base nesses tres fatores, sugira o raio adequado para a zona homogenea.

Retorne somente um JSON valido, sem texto fora do JSON, no seguinte formato:
{{
  "padrao_construtivo": "casas | sobrados | predios_baixos | predios_medios | torres_altas | misto | indefinido",
  "homogeneidade_visual": "alta | media | baixa | indefinida",
  "densidade_urbana": "baixa | media | alta | indefinida",
  "raio_sugerido_metros": 700,
  "justificativa_raio": "Explique em uma frase por que esse raio e adequado, baseando-se nos tres fatores acima.",
  "descricao_zona_homogenea": "Descreva em ate 2 frases o perfil da zona com base no padrao construtivo, homogeneidade e densidade.",
  "confianca": "alta | media | baixa"
}}"""

    try:
        response = client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{img_b64}"}
                        }
                    ]
                }
            ],
            temperature=0,
            max_tokens=512,
        )
        texto = response.choices[0].message.content or ""
        logger.info(f"Groq Vision respondeu ({len(texto)} chars)")

        # Parseia JSON
        m = re.search(r'\{[\s\S]+\}', texto)
        if m:
            try:
                resultado = json.loads(m.group(0))
                # Normaliza campo de raio
                if "raio_sugerido_metros" in resultado:
                    resultado["raio_metros"] = resultado["raio_sugerido_metros"]
                return resultado
            except json.JSONDecodeError:
                logger.warning("JSON invalido da Groq Vision")
                return {"descricao_zona_homogenea": texto, "raio_metros": 700}
        else:
            logger.warning("Groq Vision nao retornou JSON valido")
            return {"descricao_zona_homogenea": texto, "raio_metros": 700}

    except Exception as e:
        logger.error(f"Groq Vision falhou: {e}")
        return {}


def _geocodificar(endereco: str) -> tuple:
    """
    Geocodifica um endereco. Tenta 2 fontes:
      1. Nominatim (OpenStreetMap) — gratis, sem key, 1 req/s
      2. Google Geocoding API (fallback) — mais completo, gasta da cota de 10.000/mes

    Retorna (latitude, longitude) ou (None, None) se ambos falharem.
    """
    import requests

    # 1. Nominatim (gratis, sem key)
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": endereco, "format": "json", "limit": 1},
            headers={"User-Agent": "ProjetoImoveisIA/1.0"},
            timeout=10,
        )
        if r.status_code == 200 and r.json():
            data = r.json()[0]
            return float(data["lat"]), float(data["lon"])
    except Exception:
        pass

    # 2. Google Geocoding API (fallback — mais completo)
    maps_key = os.getenv("GOOGLE_MAPS_KEY", "")
    if maps_key:
        try:
            r = requests.get(
                "https://maps.googleapis.com/maps/api/geocode/json",
                params={"address": endereco, "key": maps_key},
                timeout=10,
            )
            if r.status_code == 200:
                results = r.json().get("results", [])
                if results:
                    loc = results[0]["geometry"]["location"]
                    return float(loc["lat"]), float(loc["lng"])
        except Exception:
            pass

    return None, None


def _distancia_haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calcula distancia em metros entre 2 coordenadas usando formula de Haversine.
    Precisao: ~0.5% pra distancias curtas (< 10km).
    """
    import math
    R = 6371000  # raio da Terra em metros
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _classificar_por_distancia(distancia_metros: float, raio_zona: int = 700) -> str:
    """
    Classifica se o imovel esta na zona homogenea ou fora.
    Usa o raio sugerido pela LLM (baseado na analise visual da regiao).
    Raio minimo: 400m (evita zonas muito pequenas em centros urbanos).
    """
    raio = max(raio_zona, 400)
    if distancia_metros <= raio:
        return "na_zona"
    else:
        return "fora_zona"


def analisar_zona_homogenea(
    endereco_alvo: str,
    imoveis: list[dict],
    cidade: str = "",
    estado: str = "",
) -> dict:
    """
    Analisa a zona homogenea do imovel alvo e valida os comparaveis.

    FLUXO:
      1. Geocodificacao do endereco alvo (Nominatim → lat/lng)
      2. Geracao da imagem da regiao (Google Maps Static API, hybrid, scale=2, marcador)
      3. Analise visual da regiao (Groq Vision, Llama 4 Scout)
      4. Definicao da zona de analise (raio sugerido pela LLM, minimo 400m)
      5. Geocoding de cada imovel (Nominatim) + calculo de distancia (Haversine)
      6. Classificacao: na_zona ou fora_zona

    CLASSIFICACAO:
      - na_zona: ate o raio sugerido pela LLM (ou mesmo bairro sem coordenada)
      - fora_zona: acima do raio

    Parametros
    ----------
    endereco_alvo : str
        Endereco completo do imovel alvo
    imoveis : list[dict]
        Lista de imoveis pra validar geograficamente
    cidade : str
        Cidade (complementa enderecos incompletos)
    estado : str
        Estado (sigla)

    Retorna
    -------
    dict com:
      - zona_homogenea: analise visual da LLM (tipo, uso, padrao, densidade, raio, etc.)
      - comparaveis_confirmados: imoveis na zona
      - fora_zona: imoveis fora da zona
      - imagem_satelite: caminho do PNG salvo
    """
    logger.info("=" * 55)
    logger.info("ZONA HOMOGENEA: Google Maps + Groq Vision")
    logger.info("=" * 55)

    # ── 1. GEOCODIFICACAO DO ALVO ─────────────────────────────────
    logger.info(f"Geocodificando: {endereco_alvo}")
    lat_alvo, lon_alvo = _geocodificar(endereco_alvo)
    if not lat_alvo:
        logger.warning("Nao geocodificou o alvo — usando todos os imoveis como confirmados")
        return {
            "zona_homogenea": {},
            "comparaveis_confirmados": imoveis,
            "fora_zona": [],
            "imagem_satelite": None,
        }
    logger.info(f"Alvo: {lat_alvo:.6f}, {lon_alvo:.6f}")

    # ── 2. IMAGEM DE SATELITE ─────────────────────────────────────
    logger.info("Gerando imagem de satelite (hybrid, scale=2, marcador)...")
    imagem = _obter_imagem_satelite(endereco_alvo, lat=lat_alvo, lon=lon_alvo)
    img_path = None
    if imagem:
        img_path = os.path.join(DATA_DIR, "satelite_zona_homogenea_ag2.png")
        with open(img_path, "wb") as f:
            f.write(imagem)
        logger.info(f"Imagem salva: {img_path} ({len(imagem)//1024}KB)")
    else:
        logger.warning("Nao gerou imagem de satelite — continuando sem analise visual")

    # ── 3. ANALISE VISUAL VIA GROQ VISION ─────────────────────────
    zona = {}
    if imagem:
        logger.info("Enviando imagem para Groq Vision (Llama 4 Scout)...")
        zona = _analisar_zona_homogenea(imagem, endereco_alvo)
        logger.info(f"Zona: padrao={zona.get('padrao_construtivo','?')} | "
                    f"homogeneidade={zona.get('homogeneidade_visual','?')} | "
                    f"densidade={zona.get('densidade_urbana','?')} | "
                    f"raio={zona.get('raio_sugerido_metros', zona.get('raio_metros','?'))}m")
        if zona.get("descricao_zona_homogenea"):
            logger.info(f"Descricao: {zona['descricao_zona_homogenea']}")

    # ── 4. GEOCODING DOS IMOVEIS + CLASSIFICACAO POR DISTANCIA ────
    import time
    raio_zona = zona.get("raio_sugerido_metros", zona.get("raio_metros", 700))
    logger.info(f"Geocodificando {len(imoveis)} imoveis (raio da LLM: {raio_zona}m, minimo: {max(raio_zona, 400)}m)...")

    confirmados = []      # na_zona (por distancia ou por bairro)
    fora = []             # fora_zona

    for idx, im in enumerate(imoveis):
        rua = im.get("street", "")
        bairro = im.get("neighborhood", "")

        # Se nao tem rua especifica, nao geocodifica
        # Mesmo bairro = assume na zona (precisao geografica baixa)
        if not rua:
            im["distancia_metros"] = None
            im["classificacao_zona"] = "na_zona"
            im["coordenadas"] = None
            confirmados.append(im)
            logger.info(f"  [{idx+1}/{len(imoveis)}] na_zona (mesmo bairro) | {bairro}")
            continue

        # Geocodifica com endereco completo (rua + bairro + cidade + estado)
        end_imovel = f"{rua}, {bairro}, {cidade}, {estado}, Brasil"
        lat, lon = _geocodificar(end_imovel)
        time.sleep(1)  # Nominatim: 1 req/s

        if lat and lon:
            dist = _distancia_haversine(lat_alvo, lon_alvo, lat, lon)
            classificacao = _classificar_por_distancia(dist, raio_zona)

            im["distancia_metros"] = round(dist)
            im["classificacao_zona"] = classificacao
            im["coordenadas"] = {"lat": lat, "lon": lon}

            if classificacao == "na_zona":
                confirmados.append(im)
            else:
                fora.append(im)

            logger.info(f"  [{idx+1}/{len(imoveis)}] {dist:.0f}m | {classificacao} | {rua}")
        else:
            # Geocoding falhou — assume na zona (mesmo bairro)
            im["distancia_metros"] = None
            im["classificacao_zona"] = "na_zona"
            im["coordenadas"] = None
            confirmados.append(im)
            logger.info(f"  [{idx+1}/{len(imoveis)}] na_zona (sem coords) | {rua}")

    # ── 5. RESUMO ─────────────────────────────────────────────────
    raio_usado = max(raio_zona, 400)
    logger.info("=" * 55)
    logger.info(f"RESULTADO ZONA HOMOGENEA (raio: {raio_usado}m):")
    logger.info(f"  Na zona: {len(confirmados)}")
    logger.info(f"  Fora da zona: {len(fora)}")
    logger.info("=" * 55)

    resultado = {
        "zona_homogenea": zona,
        "comparaveis_confirmados": confirmados,
        "fora_zona": fora,
        "imagem_satelite": img_path,
    }

    # Salva resultado em JSON
    caminho_saida = os.path.join(DATA_DIR, "zona_homogenea_ag2.json")
    with open(caminho_saida, "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2, default=str)
    logger.info(f"Salvo em: {caminho_saida}")

    return resultado
