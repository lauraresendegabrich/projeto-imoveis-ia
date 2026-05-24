"""
Agente 4 — Avaliador de Infraestrutura
========================================

RESPONSABILIDADE:
    Analisa o entorno do imovel alvo buscando pontos de interesse (POIs)
    em tres raios diferentes via osmnx (OpenStreetMap). Usa pesos por
    categoria e raio para calcular um score de infraestrutura. Usa LLM
    para classificar o perfil da regiao e inferir o impacto no valor.

ENTRADA:
    data/imoveis_analisados_ag3.json (gerado pelo Agente 3)
    Usa apenas o imovel_alvo (rua, numero, bairro, cidade, estado)

SAIDA: data/infra_avaliada_ag4.json

COMO FUNCIONA:
==============

  ETAPA 1 — GEOCODIFICACAO:
  ─────────────────────────
    Geocodifica o endereco do alvo via Nominatim (OpenStreetMap).
    Fallback: Google Geocoding API (GOOGLE_MAPS_KEY no .env).

  ETAPA 2 — BUSCA DE POIs (osmnx / OpenStreetMap):
  ──────────────────────────────────────────────────
    Busca POIs em 3 raios diferentes, cada um capturando um tipo
    de infraestrutura relevante para avaliacao imobiliaria:

    400m  — microentorno imediato (~5 min a pe)
            Comercio essencial, escolas, farmacias, transporte, lazer
    800m  — entorno caminhavel ampliado (~10 min a pe)
            Supermercados, praças, academias, hospitais, servicos
    1500m — infraestrutura de maior impacto regional (~15-20 min a pe)
            Hospitais, shoppings, universidades, grandes vias

  ETAPA 3 — SCORE MULTIRRAIO:
  ────────────────────────────
    Cada categoria tem raios relevantes e pesos diferentes:

    Categoria        | 400m | 800m | 1500m | Justificativa
    ─────────────────|──────|──────|───────|──────────────────────────────
    comercio         | 1.0  | 0.6  |  —    | Precisa estar perto
    educacao         | 1.0  | 0.6  |  —    | Escola proxima e diferencial
    saude_basica     | 1.0  | 0.6  |  —    | Farmacia/clinica: uso cotidiano
    transporte       | 1.0  | 0.6  |  —    | Onibus: quanto mais perto melhor
    lazer            | 1.0  | 0.6  |  —    | Parque/academia: uso frequente
    hospital         |  —   | 0.6  | 1.0   | Nao precisa estar a 400m
    grande_equipamento|  —  | 0.6  | 1.0   | Shopping/universidade: regional

    score_categoria = (qtd_raio × peso_raio) / normalizador
    score_final = media ponderada dos scores por categoria

  ETAPA 4 — ANALISE VIA LLM:
  ───────────────────────────
    Envia o resumo dos POIs por raio para o Groq (llama-3.1-8b-instant).
    LLM classifica o perfil da regiao e retorna impacto no valor.

FLUXO COMPLETO:
───────────────
  1. Carrega imovel_alvo de imoveis_analisados_ag3.json
  2. Geocodifica endereco (Nominatim → lat/lng)
  3. Busca POIs via osmnx nos 3 raios (400m, 800m, 1500m)
  4. Calcula score multirraio por categoria
  5. Envia resumo para LLM classificar perfil e impacto
  6. Salva em data/infra_avaliada_ag4.json

DEPENDENCIAS:
─────────────
  - osmnx (pip install osmnx)
  - Groq (gratis, 14.400 req/dia) — modelo llama-3.1-8b-instant
  - langchain-groq (pip install langchain-groq)

COMO RODAR:
───────────
  .venv/Scripts/python.exe -m tests.test_infra_evaluator
"""

import os
import json
import math
import logging
import requests
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

# =============================================================================
# CONFIGURACAO DE RAIOS E CATEGORIAS
# =============================================================================

# Faixas de distancia (cada POI fica so na faixa da sua distancia real)
FAIXAS = [
    (0,   400,  "microentorno_imediato"),
    (401, 800,  "entorno_caminhavel"),
    (801, 1500, "infraestrutura_ampliada"),
]

# Tolerancia de 5% nos limites de faixa
TOLERANCIA = 0.05

# Raios maximos para busca (o maior raio da ultima faixa)
RAIO_MAX = 1500

# Pesos por categoria e faixa
# None = nao e relevante nessa faixa para essa categoria
PESOS_CATEGORIA = {
    "comercio":           {"microentorno_imediato": 1.0, "entorno_caminhavel": 0.6, "infraestrutura_ampliada": None},
    "educacao":           {"microentorno_imediato": 1.0, "entorno_caminhavel": 0.6, "infraestrutura_ampliada": None},
    "saude_basica":       {"microentorno_imediato": 1.0, "entorno_caminhavel": 0.6, "infraestrutura_ampliada": None},
    "transporte":         {"microentorno_imediato": 1.0, "entorno_caminhavel": 0.6, "infraestrutura_ampliada": None},
    "lazer":              {"microentorno_imediato": 1.0, "entorno_caminhavel": 0.6, "infraestrutura_ampliada": None},
    "hospital":           {"microentorno_imediato": None, "entorno_caminhavel": 0.6, "infraestrutura_ampliada": 1.0},
    "grande_equipamento": {"microentorno_imediato": None, "entorno_caminhavel": 0.6, "infraestrutura_ampliada": 1.0},
}

# Mapeamento de tags OSM para categorias
TAG_PARA_CATEGORIA = {
    # Comercio
    "supermarket":   "comercio",
    "marketplace":   "comercio",
    "bakery":        "comercio",
    "bank":          "comercio",
    "atm":           "comercio",
    "convenience":   "comercio",
    "butcher":       "comercio",
    "greengrocer":   "comercio",
    # Educacao
    "school":        "educacao",
    "college":       "educacao",
    "kindergarten":  "educacao",
    # Saude basica
    "pharmacy":      "saude_basica",
    "clinic":        "saude_basica",
    "doctors":       "saude_basica",
    "dentist":       "saude_basica",
    # Transporte
    "bus_stop":      "transporte",
    "bus_station":   "transporte",
    "taxi":          "transporte",
    # Lazer
    "park":          "lazer",
    "fitness_centre":"lazer",
    "sports_centre": "lazer",
    "restaurant":    "lazer",
    "cafe":          "lazer",
    "playground":    "lazer",
    # Hospital (faixa maior)
    "hospital":      "hospital",
    # Grande equipamento (faixa maior)
    "university":    "grande_equipamento",
    "shopping_mall": "grande_equipamento",
    "mall":          "grande_equipamento",
}

# Normalizador por categoria (qtd esperada para score = 1.0)
NORMALIZADOR = {
    "comercio":           5,
    "educacao":           3,
    "saude_basica":       4,
    "transporte":         6,
    "lazer":              3,
    "hospital":           2,
    "grande_equipamento": 2,
}


# =============================================================================
# BLOCO 1 - GEOCODIFICACAO
# =============================================================================

def _geocodificar(endereco: str) -> tuple:
    """
    Geocodifica um endereco via Nominatim (principal) ou Google (fallback).
    Retorna (lat, lon) ou (None, None) se falhar.
    """
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


def _haversine(lat1, lon1, lat2, lon2) -> int:
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return round(R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a)))


# =============================================================================
# BLOCO 2 - BUSCA DE POIs VIA OSMNX (faixas sem duplicacao)
# =============================================================================

def _faixa_de(distancia: int) -> str:
    """
    Retorna a faixa correspondente a uma distancia, com tolerancia de 5%.
    Cada POI fica somente na faixa da sua distancia real.
    """
    for limite_min, limite_max, nome_faixa in FAIXAS:
        limite_max_tolerado = limite_max * (1 + TOLERANCIA)
        if limite_min <= distancia <= limite_max_tolerado:
            return nome_faixa
    return None  # fora de todas as faixas


def _buscar_transporte(lat: float, lon: float) -> dict:
    """
    Busca dados de transporte publico com tags expandidas via osmnx/Overpass.

    Busca as seguintes tags:
      - highway=bus_stop
      - public_transport=platform
      - public_transport=stop_position
      - amenity=bus_station
      - bus=yes
      - route=bus
      - route_master=bus

    Classifica o resultado em:
      - paradas:  lista de paradas encontradas (nodes)
      - estacoes: terminais/estacoes de onibus
      - rotas:    rotas de onibus proximas (relations)
      - status:   "servido" | "possui_indicios_de_atendimento" | "dados_insuficientes"
    """
    try:
        import osmnx as ox

        resultado = {
            "paradas":  [],
            "estacoes": [],
            "rotas":    [],
            "status":   "dados_insuficientes",
        }

        # 1. Busca paradas e plataformas (nodes/ways)
        tags_paradas = {
            "highway": "bus_stop",
            "public_transport": ["platform", "stop_position"],
            "amenity": "bus_station",
        }
        try:
            gdf_paradas = ox.features_from_point((lat, lon), tags=tags_paradas, dist=RAIO_MAX)
            if not gdf_paradas.empty:
                for _, row in gdf_paradas.iterrows():
                    nome = row.get("name") or row.get("name:pt") or "parada"
                    if not isinstance(nome, str):
                        nome = "parada"
                    tipo = (row.get("highway") or row.get("public_transport") or
                            row.get("amenity") or "bus_stop")
                    if not isinstance(tipo, str):
                        tipo = "bus_stop"

                    geom = row.get("geometry")
                    if geom is not None:
                        try:
                            c = geom.centroid
                            lat_p, lon_p = c.y, c.x
                        except Exception:
                            lat_p, lon_p = lat, lon
                    else:
                        lat_p, lon_p = lat, lon

                    dist = _haversine(lat, lon, lat_p, lon_p)
                    faixa = _faixa_de(dist)
                    if faixa is None:
                        continue

                    entrada = {"nome": nome, "tipo": tipo, "distancia_metros": dist, "faixa": faixa}
                    if tipo == "bus_station":
                        resultado["estacoes"].append(entrada)
                    else:
                        resultado["paradas"].append(entrada)

                resultado["paradas"].sort(key=lambda x: x["distancia_metros"])
                resultado["estacoes"].sort(key=lambda x: x["distancia_metros"])
        except Exception as e:
            logger.warning(f"  Busca de paradas falhou: {e}")

        # 2. Busca rotas de onibus (relations)
        tags_rotas = {
            "route": "bus",
            "route_master": "bus",
        }
        try:
            gdf_rotas = ox.features_from_point((lat, lon), tags=tags_rotas, dist=RAIO_MAX)
            if not gdf_rotas.empty:
                for _, row in gdf_rotas.iterrows():
                    nome = row.get("name") or row.get("ref") or "rota"
                    if not isinstance(nome, str):
                        nome = "rota"
                    resultado["rotas"].append({"nome": nome, "tipo": row.get("route", "bus")})
        except Exception as e:
            logger.warning(f"  Busca de rotas falhou: {e}")

        # 3. Determina status
        tem_paradas  = len(resultado["paradas"]) > 0
        tem_estacoes = len(resultado["estacoes"]) > 0
        tem_rotas    = len(resultado["rotas"]) > 0

        if tem_paradas or tem_estacoes:
            resultado["status"] = "servido"
        elif tem_rotas:
            resultado["status"] = "possui_indicios_de_atendimento"
        else:
            resultado["status"] = "dados_insuficientes"

        logger.info(f"  Transporte: {len(resultado['paradas'])} paradas | "
                    f"{len(resultado['estacoes'])} estacoes | "
                    f"{len(resultado['rotas'])} rotas | status={resultado['status']}")

        return resultado

    except Exception as e:
        logger.warning(f"Busca de transporte falhou: {e}")
        return {"paradas": [], "estacoes": [], "rotas": [], "status": "dados_insuficientes"}


def _buscar_pois_classificados(lat: float, lon: float) -> dict:
    """
    Busca todos os POIs relevantes (exceto transporte) ate RAIO_MAX via osmnx.
    Classifica cada POI na faixa correta pela sua distancia real — sem duplicacao.
    Retorna dict: { nome_faixa: { categoria: [pois] } }
    """
    try:
        import osmnx as ox

        tags = {
            "amenity": True,
            "shop": True,
            "leisure": True,
        }

        logger.info(f"  Buscando todos os POIs ate {RAIO_MAX}m via osmnx...")
        gdf = ox.features_from_point((lat, lon), tags=tags, dist=RAIO_MAX)

        resultado = {
            nome: {cat: [] for cat in PESOS_CATEGORIA}
            for _, _, nome in FAIXAS
        }

        if gdf.empty:
            logger.info("  Nenhum POI encontrado")
            return resultado

        logger.info(f"  {len(gdf)} elementos brutos encontrados")

        vistos = set()
        for _, row in gdf.iterrows():
            tipo = (
                row.get("amenity") or
                row.get("shop") or
                row.get("leisure") or
                "?"
            )
            if not isinstance(tipo, str):
                continue

            categoria = TAG_PARA_CATEGORIA.get(tipo)
            if not categoria or categoria == "transporte":
                continue  # transporte tratado separadamente

            nome = row.get("name") or row.get("name:pt") or tipo
            if not isinstance(nome, str):
                nome = tipo

            geom = row.get("geometry")
            if geom is not None:
                try:
                    c = geom.centroid
                    lat_poi, lon_poi = c.y, c.x
                except Exception:
                    lat_poi, lon_poi = lat, lon
            else:
                lat_poi, lon_poi = lat, lon

            dist = _haversine(lat, lon, lat_poi, lon_poi)
            faixa = _faixa_de(dist)
            if faixa is None:
                continue

            peso = PESOS_CATEGORIA.get(categoria, {}).get(faixa)
            if peso is None:
                continue

            chave = f"{nome}_{tipo}_{dist}"
            if chave not in vistos:
                vistos.add(chave)
                resultado[faixa][categoria].append({
                    "nome":             nome,
                    "tipo":             tipo,
                    "categoria":        categoria,
                    "distancia_metros": dist,
                })

        for faixa_data in resultado.values():
            for cat in faixa_data:
                faixa_data[cat].sort(key=lambda x: x["distancia_metros"])

        for _, _, nome_faixa in FAIXAS:
            total = sum(len(v) for v in resultado[nome_faixa].values())
            logger.info(f"  {nome_faixa}: {total} POIs")

        return resultado

    except Exception as e:
        logger.warning(f"osmnx falhou: {e}")
        return {nome: {cat: [] for cat in PESOS_CATEGORIA} for _, _, nome in FAIXAS}



    """
    Busca todos os POIs ate RAIO_MAX via osmnx e classifica por faixa.
    Cada POI fica somente na faixa da sua distancia real — sem duplicacao.

    Retorna dict: { nome_faixa: { categoria: [pois] } }
    """
    try:
        import osmnx as ox

        tags = {
            "amenity": True,
            "shop": True,
            "leisure": True,
            "highway": "bus_stop",
        }

        logger.info(f"  Buscando todos os POIs ate {RAIO_MAX}m via osmnx...")
        gdf = ox.features_from_point((lat, lon), tags=tags, dist=RAIO_MAX)

        # Inicializa estrutura de resultado
        resultado = {
            nome: {cat: [] for cat in PESOS_CATEGORIA}
            for _, _, nome in FAIXAS
        }

        if gdf.empty:
            logger.info("  Nenhum POI encontrado")
            return resultado

        logger.info(f"  {len(gdf)} elementos brutos encontrados")

        vistos = set()
        for _, row in gdf.iterrows():
            tipo = (
                row.get("amenity") or
                row.get("shop") or
                row.get("leisure") or
                row.get("highway") or
                "?"
            )
            if not isinstance(tipo, str):
                continue

            categoria = TAG_PARA_CATEGORIA.get(tipo)
            if not categoria:
                continue

            nome = row.get("name") or row.get("name:pt") or tipo
            if not isinstance(nome, str):
                nome = tipo

            geom = row.get("geometry")
            if geom is not None:
                try:
                    c = geom.centroid
                    lat_poi, lon_poi = c.y, c.x
                except Exception:
                    lat_poi, lon_poi = lat, lon
            else:
                lat_poi, lon_poi = lat, lon

            dist = _haversine(lat, lon, lat_poi, lon_poi)

            # Classifica na faixa correta (sem duplicacao)
            faixa = _faixa_de(dist)
            if faixa is None:
                continue

            # Verifica se a categoria e relevante nessa faixa
            peso = PESOS_CATEGORIA.get(categoria, {}).get(faixa)
            if peso is None:
                continue

            chave = f"{nome}_{tipo}_{dist}"
            if chave not in vistos:
                vistos.add(chave)
                resultado[faixa][categoria].append({
                    "nome":             nome,
                    "tipo":             tipo,
                    "categoria":        categoria,
                    "distancia_metros": dist,
                })

        # Ordena cada categoria por distancia
        for faixa_data in resultado.values():
            for cat in faixa_data:
                faixa_data[cat].sort(key=lambda x: x["distancia_metros"])

        # Log por faixa
        for _, _, nome_faixa in FAIXAS:
            total = sum(len(v) for v in resultado[nome_faixa].values())
            logger.info(f"  {nome_faixa}: {total} POIs")

        return resultado

    except Exception as e:
        logger.warning(f"osmnx falhou: {e}")
        return {nome: {cat: [] for cat in PESOS_CATEGORIA} for _, _, nome in FAIXAS}


# =============================================================================
# BLOCO 3 - SCORE MULTIFAIXA COM TRATAMENTO DE TRANSPORTE
# =============================================================================

def _calcular_score(pois_por_faixa: dict, transporte: dict) -> dict:
    """
    Calcula score de infraestrutura por categoria usando pesos por faixa.

    Tratamento especial para transporte (tags expandidas):
      - "servido": score baseado na quantidade de paradas por faixa
      - "possui_indicios_de_atendimento": score 0.4 (indicios sem paradas mapeadas)
      - "dados_insuficientes": score 0.5 neutro, sem penalizacao

    Formula por categoria:
        score_cat = sum(qtd_faixa * peso_faixa) / normalizador
        score_cat = min(score_cat, 1.0)

    Score final = media dos scores por categoria.
    """
    scores = {}
    transporte_insuficiente = False

    for categoria, pesos_faixa in PESOS_CATEGORIA.items():
        if categoria == "transporte":
            # Tratamento especial com dados expandidos
            status = transporte.get("status", "dados_insuficientes")
            if status == "servido":
                # Calcula score pela quantidade de paradas por faixa
                total_ponderado = 0.0
                for _, _, nome_faixa in FAIXAS:
                    peso = pesos_faixa.get(nome_faixa)
                    if peso is None:
                        continue
                    paradas_faixa = [
                        p for p in transporte.get("paradas", []) + transporte.get("estacoes", [])
                        if p.get("faixa") == nome_faixa
                    ]
                    total_ponderado += len(paradas_faixa) * peso
                normalizador = NORMALIZADOR.get("transporte", 6)
                scores["transporte"] = min(round(total_ponderado / normalizador, 3), 1.0)
            elif status == "possui_indicios_de_atendimento":
                scores["transporte"] = 0.4  # indicios sem paradas mapeadas
                transporte_insuficiente = True
            else:  # dados_insuficientes
                scores["transporte"] = 0.5  # neutro, sem penalizacao
                transporte_insuficiente = True
            continue

        total_ponderado = 0.0
        for _, _, nome_faixa in FAIXAS:
            peso = pesos_faixa.get(nome_faixa)
            if peso is None:
                continue
            qtd = len(pois_por_faixa.get(nome_faixa, {}).get(categoria, []))
            total_ponderado += qtd * peso

        normalizador = NORMALIZADOR.get(categoria, 3)
        scores[categoria] = min(round(total_ponderado / normalizador, 3), 1.0)

    score_final = round(sum(scores.values()) / len(scores), 3)
    scores["score_final"] = score_final
    scores["transporte_status"] = transporte.get("status", "dados_insuficientes")
    scores["transporte_dados_insuficientes"] = transporte_insuficiente

    return scores


# =============================================================================
# BLOCO 4 - ANALISE VIA LLM COM CLASSIFICACOES EXPANDIDAS
# =============================================================================

def _classificar_infraestrutura(score: float) -> str:
    """
    Classifica o nivel de infraestrutura com base no score final.
    """
    if score >= 0.80:
        return "excelente"
    elif score >= 0.65:
        return "boa"
    elif score >= 0.45:
        return "regular"
    else:
        return "insuficiente"


def _analisar_infra_llm(pois_por_faixa: dict, scores: dict, endereco: str, transporte: dict) -> dict:
    """
    Envia resumo dos POIs por faixa para o Groq e retorna analise estruturada.
    Usa classificacoes expandidas de perfil e impacto.
    """
    try:
        from langchain_groq import ChatGroq
        import re

        api_key = os.getenv("GROQ_API_KEY", "")
        if not api_key:
            logger.warning("GROQ_API_KEY nao configurada")
            return {}

        # Monta resumo por faixa
        resumo = ""
        for _, _, nome_faixa in FAIXAS:
            cats = pois_por_faixa.get(nome_faixa, {})
            total = sum(len(v) for v in cats.values())
            resumo += f"\n\n{nome_faixa} ({total} POIs):"
            for cat, pois in cats.items():
                if cat == "transporte":
                    continue  # transporte tratado separadamente
                if pois:
                    nomes = [p["nome"] for p in pois[:4]]
                    resumo += f"\n  {cat} ({len(pois)}): {', '.join(nomes)}"

        # Resumo de transporte expandido
        status_transp = transporte.get("status", "dados_insuficientes")
        paradas = transporte.get("paradas", [])
        estacoes = transporte.get("estacoes", [])
        rotas = transporte.get("rotas", [])
        resumo_transp = f"\n\nTRANSPORTE PUBLICO (status: {status_transp}):"
        if paradas:
            nomes_p = [f"{p['nome']} ({p['distancia_metros']}m)" for p in paradas[:4]]
            resumo_transp += f"\n  paradas ({len(paradas)}): {', '.join(nomes_p)}"
        if estacoes:
            nomes_e = [f"{e['nome']} ({e['distancia_metros']}m)" for e in estacoes[:3]]
            resumo_transp += f"\n  estacoes ({len(estacoes)}): {', '.join(nomes_e)}"
        if rotas:
            nomes_r = [r["nome"] for r in rotas[:4]]
            resumo_transp += f"\n  rotas ({len(rotas)}): {', '.join(nomes_r)}"
        if not paradas and not estacoes and not rotas:
            resumo_transp += "\n  Nenhum dado encontrado — possivel sub-representacao no OSM"

        scores_sem_meta = {k: v for k, v in scores.items()
                          if k not in ("score_final", "transporte_dados_insuficientes", "transporte_status")}

        classificacao = _classificar_infraestrutura(scores.get("score_final", 0.5))

        prompt = f"""Voce e um avaliador imobiliario especializado em analise urbana. Analise a infraestrutura do entorno do imovel e responda APENAS com um JSON valido.

Endereco: {endereco}

Pontos de interesse por faixa de distancia:{resumo}
{resumo_transp}

Scores calculados por categoria:
{json.dumps(scores_sem_meta, ensure_ascii=False, indent=2)}

Score final: {scores.get('score_final', 0.5)}
Classificacao da infraestrutura: {classificacao}

REGRAS OBRIGATORIAS:

1. perfil_regiao:
   - Se score >= 0.70 com alta pontuacao em educacao, saude, hospital e grandes equipamentos: "regiao_mista_com_alta_infraestrutura"
   - Se score >= 0.70 predominantemente residencial: "residencial_com_alta_infraestrutura"
   - Se score 0.50-0.69 com servicos essenciais: "residencial_servida"
   - Se score < 0.50: "regiao_pouco_servida"

2. impacto_estimado_no_valor:
   - Mesmo com score alto, se comercio ou lazer forem baixos: "positivo_moderado" (nao "positivo_forte")
   - "positivo_forte" so se TODAS as categorias tiverem score >= 0.70
   - Opcoes: negativo_forte | negativo_moderado | neutro | positivo_moderado | positivo_forte

3. limitacoes:
   - SEMPRE incluir: "Nenhuma limitacao critica foi identificada no teste, mas os resultados dependem da completude dos dados disponiveis no OpenStreetMap."
   - Adicionar outras limitacoes especificas se identificadas

Responda exatamente neste formato JSON:
{{
  "perfil_regiao": "...",
  "pontos_fortes": ["lista dos principais diferenciais de infraestrutura"],
  "pontos_de_atencao": ["categorias com pontuacao mais baixa"],
  "limitacoes": ["Nenhuma limitacao critica foi identificada no teste, mas os resultados dependem da completude dos dados disponiveis no OpenStreetMap."],
  "impacto_estimado_no_valor": "...",
  "tempo_liquidez_regional": "estimativa do tempo medio de venda de um imovel nesta regiao (ex: 30 a 60 dias, 60 a 90 dias, 90 a 150 dias, acima de 150 dias). Considere a infraestrutura, acessibilidade e atratividade da regiao.",
  "justificativa": "paragrafo explicando o impacto considerando as tres faixas, os pontos fortes, os pontos de atencao e as limitacoes do OSM",
  "conclusao": "O Agente 4 utiliza OpenStreetMap, Nominatim e osmnx para identificar pontos de interesse no entorno do imovel. A analise multirraio considera educacao, saude, hospitais, transporte, comercio, lazer e grandes equipamentos urbanos. [complete com o resultado especifico deste imovel]"
}}"""

        llm = ChatGroq(model="llama-3.1-8b-instant", api_key=api_key, temperature=0)
        resposta = llm.invoke(prompt)
        conteudo = resposta.content if hasattr(resposta, "content") else str(resposta)

        m = re.search(r'\{[\s\S]+\}', conteudo)
        if not m:
            logger.warning("LLM nao retornou JSON valido")
            return {}

        data = json.loads(m.group(0))

        # Força regra: positivo_forte só se TODAS as categorias >= 0.70
        scores_cat = {k: v for k, v in scores.items()
                      if k not in ("score_final", "transporte_dados_insuficientes", "transporte_status")}
        todas_altas = all(v >= 0.70 for v in scores_cat.values())
        if not todas_altas and data.get("impacto_estimado_no_valor") == "positivo_forte":
            data["impacto_estimado_no_valor"] = "positivo_moderado"

        # Garante que limitacoes sempre tem o texto padrao
        limitacoes = data.get("limitacoes", [])
        texto_padrao = "Nenhuma limitacao critica foi identificada no teste, mas os resultados dependem da completude dos dados disponiveis no OpenStreetMap."
        if not any("completude" in str(l) for l in limitacoes):
            limitacoes = [texto_padrao] + [l for l in limitacoes if l != texto_padrao]
            data["limitacoes"] = limitacoes
        return data

    except Exception as e:
        logger.error(f"Erro ao chamar LLM: {e}")
        return {}


# =============================================================================
# BLOCO 5 - FUNCAO PUBLICA
# =============================================================================

def avaliar_infraestrutura(
    imovel_alvo: Optional[dict] = None,
    arquivo_entrada: str = "imoveis_comparaveis_ag2.json",
    arquivo_saida: str = "infra_avaliada_ag4.json",
) -> dict:
    """
    Avalia a infraestrutura do entorno do imovel alvo com analise multirraio.

    Fluxo:
        1. Carrega imovel_alvo de imoveis_analisados_ag3.json
        2. Geocodifica o endereco (Nominatim → lat/lng)
        3. Busca POIs via osmnx nos 3 raios (400m, 800m, 1500m)
        4. Calcula score multirraio por categoria com pesos diferenciados
        5. Envia resumo para LLM classificar perfil e impacto
        6. Salva em data/infra_avaliada_ag4.json

    Retorna dict com: imovel_alvo, coordenadas, pois_por_raio,
                      scores, analise_llm
    """
    logger.info("=" * 55)
    logger.info("AGENTE 4: AVALIADOR DE INFRAESTRUTURA")
    logger.info("=" * 55)

    # ── CARREGA DADOS ─────────────────────────────────────────────
    if imovel_alvo is None:
        caminho = os.path.join(DATA_DIR, arquivo_entrada)
        if not os.path.exists(caminho):
            logger.error(f"Arquivo nao encontrado: {caminho}")
            return {}
        with open(caminho, "r", encoding="utf-8") as f:
            dados = json.load(f)
        imovel_alvo = dados.get("imovel_alvo", {})
        logger.info(f"Imovel alvo: {imovel_alvo.get('rua','?')}, {imovel_alvo.get('numero','')}")

    # ── GEOCODIFICACAO ────────────────────────────────────────────
    rua    = imovel_alvo.get("rua", "") or imovel_alvo.get("street", "")
    numero = imovel_alvo.get("numero", "")
    bairro = imovel_alvo.get("bairro", "") or imovel_alvo.get("neighborhood", "")
    cidade = imovel_alvo.get("cidade", "") or imovel_alvo.get("city", "")
    estado = imovel_alvo.get("estado", "") or imovel_alvo.get("state", "")
    endereco = f"{rua}, {numero}, {bairro}, {cidade}, {estado}, Brasil".strip(", ")

    logger.info(f"Geocodificando: {endereco}")
    lat, lon = _geocodificar(endereco)
    if not lat:
        logger.error("Nao foi possivel geocodificar o endereco")
        return {}
    logger.info(f"Coordenadas: {lat:.6f}, {lon:.6f}")

    # ── BUSCA POR FAIXAS ──────────────────────────────────────────
    logger.info(f"Buscando POIs nas faixas 0-400m / 401-800m / 801-1500m via osmnx...")
    pois_por_faixa = _buscar_pois_classificados(lat, lon)

    # ── BUSCA DE TRANSPORTE (tags expandidas) ─────────────────────
    logger.info("Buscando transporte publico (tags expandidas)...")
    transporte = _buscar_transporte(lat, lon)

    # ── SCORE MULTIFAIXA ──────────────────────────────────────────
    scores = _calcular_score(pois_por_faixa, transporte)
    logger.info(f"Scores por categoria:")
    for cat, score in scores.items():
        if cat not in ("score_final", "transporte_dados_insuficientes", "transporte_status"):
            sufixo = f" [{scores.get('transporte_status','?')}]" if cat == "transporte" and scores.get("transporte_dados_insuficientes") else ""
            logger.info(f"  {cat:20}: {score:.3f}{sufixo}")
    logger.info(f"  {'score_final':20}: {scores['score_final']:.3f}")
    if scores.get("transporte_dados_insuficientes"):
        logger.info(f"  AVISO: transporte status={scores.get('transporte_status')}")

    # ── ANALISE VIA LLM ───────────────────────────────────────────
    logger.info("Analisando via LLM...")
    analise = _analisar_infra_llm(pois_por_faixa, scores, endereco, transporte)
    if analise:
        logger.info(f"Perfil: {analise.get('perfil_regiao','?')} | "
                    f"Impacto: {analise.get('impacto_valor','?')}")
    else:
        analise = {
            "perfil_regiao":   "indefinido",
            "pontos_fortes":   [],
            "pontos_fracos":   [],
            "limitacoes_osm":  [],
            "impacto_valor":   "neutro",
            "justificativa":   "Analise nao disponivel",
        }

    # ── SALVA ─────────────────────────────────────────────────────
    classificacao = _classificar_infraestrutura(scores.get("score_final", 0.5))

    saida = {
        "imovel_alvo":   imovel_alvo,
        "coordenadas":   {"lat": lat, "lon": lon},
        "faixas_metros": {"microentorno_imediato": "0-400m",
                          "entorno_caminhavel":    "401-800m",
                          "infraestrutura_ampliada": "801-1500m"},
        "tolerancia_pct": TOLERANCIA * 100,
        "pois_por_faixa": pois_por_faixa,
        "transporte":     transporte,
        "scores":         scores,
        "resumo_scores": {
            "score_final":                  scores.get("score_final"),
            "classificacao_infraestrutura": classificacao,
            "perfil_regiao":                analise.get("perfil_regiao"),
            "impacto_estimado_no_valor":    analise.get("impacto_estimado_no_valor"),
            "tempo_liquidez_regional":      analise.get("tempo_liquidez_regional"),
            "pontos_fortes":                analise.get("pontos_fortes", []),
            "pontos_de_atencao":            analise.get("pontos_de_atencao", []),
            "limitacoes":                   analise.get("limitacoes", []),
        },
        "analise_llm":    analise,
    }

    caminho_saida = os.path.join(DATA_DIR, arquivo_saida)
    with open(caminho_saida, "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=2)
    logger.info(f"Salvo em: {caminho_saida}")
    logger.info("=" * 55)

    return saida
