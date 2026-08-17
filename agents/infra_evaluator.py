"""
Agente 4 — Avaliador de Infraestrutura
========================================

RESPONSABILIDADE:
    Analisa o entorno do imovel alvo buscando pontos de interesse (POIs)
    via Google Places API (Nearby Search) em 3 faixas de distancia. Calcula score
    de infraestrutura 100% deterministico por categoria. LLM apenas
    interpreta os scores (nao modifica valores).

ENTRADA:
    - data/zona_homogenea_ag2.json (coordenadas do alvo — reutiliza lat/lon do Agente 2)
    - data/imoveis_analisados_ag3.json (imovel_alvo: rua, numero, bairro, cidade, estado)

SAIDA:
    - data/infra_avaliada_ag4.json

FLUXO COMPLETO:
===============

  ETAPA 1 — COORDENADAS DO ALVO
  ──────────────────────────────
    Reutiliza lat/lon do Agente 2 (zona_homogenea_ag2.json).
    Se nao disponivel: Nominatim → fallback Google Geocoding.

  ETAPA 2 — BUSCA DE POIs (Google Places API)
  ─────────────────────────────────────────────────
    Busca todos os POIs ate 1500m via Google Places API (Nearby Search New).
    Uma request por categoria (~7 requests total). Resposta em ~1s cada.
    Classifica cada POI pela distancia real (Haversine) em 3 faixas:

    0-400m   — microentorno imediato (~5 min a pe)
    401-800m — entorno caminhavel (~10 min a pe)
    801-1500m — infraestrutura regional (~15-20 min a pe)

    Tolerancia de 5% nos limites de faixa.
    Transporte: busca separada com deduplicacao espacial inteligente (40m).

  ETAPA 3 — SCORE POR CATEGORIA (100% deterministico)
  ────────────────────────────────────────────────────
    8 categorias, cada uma com pesos por faixa de distancia:

    Categoria               | 0-400m | 401-800m | 801-1500m | Normalizador
    ────────────────────────|────────|──────────|───────────|─────────────
    comercio                |  1.00  |   0.60   |   0.20    |     5
    educacao                |  1.00  |   0.70   |   0.30    |     3
    saude_basica            |  1.00  |   0.65   |   0.25    |     4
    transporte              |  1.00  |   0.70   |   0.30    |     6
    lazer                   |  1.00  |   0.70   |   0.35    |     3
    hospital                |  1.00  |   0.90   |   0.70    |     2
    equipamentos_regionais  |  1.00  |   0.90   |   0.70    |     2
    servicos_e_alimentacao  |  1.00  |   0.60   |   0.20    |     4

    Formula:
      poi_efetivo = (qtd_0_400 × peso_0_400) + (qtd_401_800 × peso_401_800) + (qtd_801_1500 × peso_801_1500)
      score_categoria = min(1.0, poi_efetivo / normalizador)
      score_final = media simples dos 8 scores de categoria

    servicos_e_alimentacao: limite por subtipo (restaurant 2, cafe 2, bank 1, atm 1)
      evita inflacao por concentracao de restaurantes.

    Transporte: deduplicacao espacial inteligente
      paradas < 40m com mesmo nome/ref = mesma parada fisica.
      Sem dados confiavel: score neutro 0.5.

  ETAPA 4 — CLASSIFICACAO (deterministico)
  ─────────────────────────────────────────
    < 0.30 → insuficiente
    0.30-0.49 → basica
    0.50-0.69 → moderada
    0.70-0.84 → boa
    >= 0.85 → excelente

    perfil_infraestrutura e impacto_infraestrutura: calculados em Python
    (nao pela LLM). Mapeamento fixo classificacao → perfil → impacto.

  ETAPA 5 — INTERPRETACAO VIA LLM (Groq, llama-3.1-8b-instant)
  ──────────────────────────────────────────────────────────────
    A LLM recebe os scores prontos (100% deterministicos) e produz
    APENAS interpretacao qualitativa:
      - Perfil da regiao (texto)
      - Pontos fortes (lista)
      - Pontos de atencao (lista)

    A LLM NAO modifica nenhum score numerico.
    A LLM NAO calcula impacto_infraestrutura (ja vem pronto do Python).

CATEGORIAS DE POIs (tags OSM):
──────────────────────────────
    comercio:               supermarket, marketplace, bakery, convenience, butcher, greengrocer
    educacao:               school, kindergarten
    saude_basica:           pharmacy, clinic, doctors, dentist
    transporte:             bus_stop, bus_station, platform, stop_position, station
    lazer:                  park, fitness_centre, sports_centre, playground
    hospital:               hospital
    equipamentos_regionais: university, college, mall
    servicos_e_alimentacao: restaurant, cafe, bank, atm

QUEM USA A SAIDA:
─────────────────
    Agente 5 → score_final (liquidez experimental, peso 40%)
    Interface → scores por categoria + perfil + pontos fortes/atencao

DEPENDENCIAS:
─────────────
    - Google Places API (busca POIs — Nearby Search New)
    - NVIDIA NIM (meta/llama-3.1-8b-instruct) — apenas interpretacao textual
    - Gemini (gemini-3.5-flash-lite) — fallback interpretacao
    - Nominatim / Google Geocoding (fallback geocodificacao)

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
    (0,   400,  "0_400"),
    (401, 800,  "401_800"),
    (801, 1500, "801_1500"),
]

# Tolerancia de 5% nos limites de faixa
TOLERANCIA = 0.05

# Raios maximos para busca (o maior raio da ultima faixa)
RAIO_MAX = 1500

# Pesos por distancia e categoria
# Todas as categorias tem peso em todas as faixas (quanto mais perto, mais vale)
PESOS_DISTANCIA = {
    "comercio": {
        "0_400": 1.00,
        "401_800": 0.60,
        "801_1500": 0.20
    },
    "educacao": {
        "0_400": 1.00,
        "401_800": 0.70,
        "801_1500": 0.30
    },
    "saude_basica": {
        "0_400": 1.00,
        "401_800": 0.65,
        "801_1500": 0.25
    },
    "transporte": {
        "0_400": 1.00,
        "401_800": 0.70,
        "801_1500": 0.30
    },
    "lazer": {
        "0_400": 1.00,
        "401_800": 0.70,
        "801_1500": 0.35
    },
    "hospital": {
        "0_400": 1.00,
        "401_800": 0.90,
        "801_1500": 0.70
    },
    "equipamentos_regionais": {
        "0_400": 1.00,
        "401_800": 0.90,
        "801_1500": 0.70
    },
    "servicos_e_alimentacao": {
        "0_400": 1.00,
        "401_800": 0.60,
        "801_1500": 0.20
    },
}

# Mapeamento de POIs por categoria usando (chave_osm, valor_osm)
# Cada POI pertence a UMA ÚNICA categoria (sem dupla contagem)
POIS_POR_CATEGORIA = {
    "comercio": [
        ("shop", "supermarket"),
        ("amenity", "marketplace"),
        ("shop", "bakery"),
        ("shop", "convenience"),
        ("shop", "butcher"),
        ("shop", "greengrocer"),
    ],
    "educacao": [
        ("amenity", "school"),
        ("amenity", "kindergarten"),
    ],
    "saude_basica": [
        ("amenity", "pharmacy"),
        ("amenity", "clinic"),
        ("amenity", "doctors"),
        ("amenity", "dentist"),
    ],
    "transporte": [
        ("highway", "bus_stop"),
        ("amenity", "bus_station"),
        ("public_transport", "platform"),
        ("public_transport", "stop_position"),
        ("public_transport", "station"),
    ],
    "lazer": [
        ("leisure", "park"),
        ("leisure", "fitness_centre"),
        ("leisure", "sports_centre"),
        ("leisure", "playground"),
    ],
    "hospital": [
        ("amenity", "hospital"),
    ],
    "equipamentos_regionais": [
        ("amenity", "university"),
        ("amenity", "college"),
        ("shop", "mall"),
    ],
    "servicos_e_alimentacao": [
        ("amenity", "restaurant"),
        ("amenity", "cafe"),
        ("amenity", "bank"),
        ("amenity", "atm"),
    ],
}

# Mapeamento reverso: (chave, valor) → categoria (para classificação rápida)
TAG_PARA_CATEGORIA = {}
for categoria, tags in POIS_POR_CATEGORIA.items():
    for chave, valor in tags:
        TAG_PARA_CATEGORIA[(chave, valor)] = categoria

# Tags OSM para consulta agrupadas por chave (para montar query ao osmnx)
TAGS_CONSULTA = {}
for categoria, tags in POIS_POR_CATEGORIA.items():
    for chave, valor in tags:
        if chave not in TAGS_CONSULTA:
            TAGS_CONSULTA[chave] = []
        if valor not in TAGS_CONSULTA[chave]:
            TAGS_CONSULTA[chave].append(valor)

# Distancia para deduplicacao de paradas de transporte (metros)
DEDUP_TRANSPORTE_METROS = 40

# Limites por subtipo para servicos_e_alimentacao (evita inflacao por concentracao)
LIMITES_SERVICOS_ALIMENTACAO = {
    "restaurant": 2,
    "cafe": 2,
    "bank": 1,
    "atm": 1,
}

# Normalizador por categoria (qtd ponderada esperada para score = 1.0)
# Calibrado para Google Places API (retorna ate 20 POIs por categoria)
NORMALIZADORES = {
    "comercio":           12,
    "educacao":           8,
    "saude_basica":       10,
    "transporte":         12,
    "lazer":              8,
    "hospital":           4,
    "equipamentos_regionais": 4,
    "servicos_e_alimentacao": 10,
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
    Busca dados de transporte publico via Google Places API (Nearby Search).
    Busca bus_station e transit_station no raio maximo.
    """
    try:
        resultado = {
            "paradas":  [],
            "estacoes": [],
            "rotas":    [],
            "status":   "dados_insuficientes",
        }

        api_key = os.getenv("GOOGLE_MAPS_KEY", "")
        if not api_key:
            logger.warning("  GOOGLE_MAPS_KEY nao configurada — transporte indisponivel")
            return resultado

        import requests

        # Busca paradas de onibus (bus_station + transit_station)
        tipos_transporte = ["bus_station", "transit_station"]
        for tipo_busca in tipos_transporte:
            url = "https://places.googleapis.com/v1/places:searchNearby"
            headers = {
                "Content-Type": "application/json",
                "X-Goog-Api-Key": api_key,
                "X-Goog-FieldMask": "places.displayName,places.location,places.primaryType",
            }
            body = {
                "includedTypes": [tipo_busca],
                "maxResultCount": 10,
                "locationRestriction": {
                    "circle": {
                        "center": {"latitude": lat, "longitude": lon},
                        "radius": float(RAIO_MAX),
                    }
                },
            }

            resp = requests.post(url, json=body, headers=headers, timeout=10)
            if resp.status_code != 200:
                continue

            data = resp.json()
            places = data.get("places", [])

            for place in places:
                loc = place.get("location", {})
                lat_p = loc.get("latitude", lat)
                lon_p = loc.get("longitude", lon)
                dist = _haversine(lat, lon, lat_p, lon_p)
                faixa = _faixa_de(dist)
                if faixa is None:
                    continue

                nome = place.get("displayName", {}).get("text", "parada")
                entrada = {
                    "nome": nome,
                    "tipo": tipo_busca,
                    "ref": None,
                    "distancia_metros": dist,
                    "faixa": faixa,
                }
                if tipo_busca == "bus_station":
                    resultado["estacoes"].append(entrada)
                else:
                    resultado["paradas"].append(entrada)

        resultado["paradas"].sort(key=lambda x: x["distancia_metros"])
        resultado["estacoes"].sort(key=lambda x: x["distancia_metros"])

        tem_paradas = len(resultado["paradas"]) > 0
        tem_estacoes = len(resultado["estacoes"]) > 0

        if tem_paradas or tem_estacoes:
            resultado["status"] = "servido"

        logger.info(f"  Transporte: {len(resultado['paradas'])} paradas | "
                    f"{len(resultado['estacoes'])} estacoes | status={resultado['status']}")

        return resultado

    except Exception as e:
        logger.warning(f"Busca de transporte falhou: {e}")
        return {"paradas": [], "estacoes": [], "rotas": [], "status": "dados_insuficientes"}



def _buscar_pois_classificados(lat: float, lon: float) -> dict:
    """
    Busca todos os POIs relevantes (exceto transporte) via Google Places API (Nearby Search).
    Classifica cada POI na categoria correspondente.
    Um POI pertence a apenas UMA categoria.
    Retorna dict: { nome_faixa: { categoria: [pois] } }
    """
    try:
        import requests

        api_key = os.getenv("GOOGLE_MAPS_KEY", "")
        if not api_key:
            logger.warning("GOOGLE_MAPS_KEY nao configurada — usando scores neutros")
            return {nome: {cat: [] for cat in POIS_POR_CATEGORIA} for _, _, nome in FAIXAS}

        logger.info(f"  Buscando POIs ate {RAIO_MAX}m via Google Places API...")

        resultado = {
            nome: {cat: [] for cat in POIS_POR_CATEGORIA}
            for _, _, nome in FAIXAS
        }

        # Mapeamento de tipos Google Places → categoria do sistema
        TIPOS_GOOGLE = {
            "comercio": ["supermarket", "grocery_store", "bakery", "convenience_store"],
            "educacao": ["school", "primary_school", "secondary_school"],
            "saude_basica": ["pharmacy", "doctor", "dentist"],
            "lazer": ["park", "gym", "playground"],
            "hospital": ["hospital"],
            "equipamentos_regionais": ["university", "shopping_mall"],
            "servicos_e_alimentacao": ["restaurant", "cafe", "bank", "atm"],
        }

        vistos = set()
        total_encontrados = 0

        for categoria, tipos in TIPOS_GOOGLE.items():
            url = "https://places.googleapis.com/v1/places:searchNearby"
            headers = {
                "Content-Type": "application/json",
                "X-Goog-Api-Key": api_key,
                "X-Goog-FieldMask": "places.displayName,places.location,places.primaryType",
            }
            body = {
                "includedTypes": tipos,
                "maxResultCount": 20,
                "locationRestriction": {
                    "circle": {
                        "center": {"latitude": lat, "longitude": lon},
                        "radius": float(RAIO_MAX),
                    }
                },
            }

            try:
                resp = requests.post(url, json=body, headers=headers, timeout=10)
                if resp.status_code != 200:
                    logger.warning(f"  Google Places ({categoria}): HTTP {resp.status_code}")
                    continue

                data = resp.json()
                places = data.get("places", [])

                for place in places:
                    loc = place.get("location", {})
                    lat_p = loc.get("latitude", lat)
                    lon_p = loc.get("longitude", lon)
                    dist = _haversine(lat, lon, lat_p, lon_p)
                    faixa = _faixa_de(dist)
                    if faixa is None:
                        continue

                    nome = place.get("displayName", {}).get("text", "?")
                    tipo_encontrado = place.get("primaryType", categoria)

                    # Deduplicacao
                    chave_dedup = f"{tipo_encontrado}_{round(lat_p, 5)}_{round(lon_p, 5)}"
                    if chave_dedup in vistos:
                        continue
                    vistos.add(chave_dedup)

                    resultado[faixa][categoria].append({
                        "nome":             nome,
                        "tipo":             tipo_encontrado,
                        "categoria":        categoria,
                        "distancia_metros": dist,
                    })
                    total_encontrados += 1

            except Exception as e:
                logger.warning(f"  Google Places ({categoria}) falhou: {e}")
                continue

        # Ordena cada categoria por distancia
        for faixa_data in resultado.values():
            for cat in faixa_data:
                faixa_data[cat].sort(key=lambda x: x["distancia_metros"])

        # Log por faixa
        for _, _, nome_faixa in FAIXAS:
            total = sum(len(v) for v in resultado[nome_faixa].values())
            logger.info(f"  {nome_faixa}: {total} POIs")

        logger.info(f"  Total: {total_encontrados} POIs encontrados via Google Places")

        return resultado

    except Exception as e:
        logger.warning(f"Google Places falhou: {e}")
        return {nome: {cat: [] for cat in POIS_POR_CATEGORIA} for _, _, nome in FAIXAS}


# =============================================================================
# BLOCO 3 - SCORE POR CATEGORIA COM PESOS POR DISTANCIA
# =============================================================================

def _calcular_score(pois_por_faixa: dict, transporte: dict) -> dict:
    """
    Calcula score de infraestrutura por categoria usando pesos por distancia.

    Formula por categoria:
        poi_efetivo = (qtd_0_400 × peso_0_400) + (qtd_401_800 × peso_401_800) + (qtd_801_1500 × peso_801_1500)
        score_categoria = poi_efetivo / normalizador
        score_categoria = max(0.0, min(1.0, score_categoria))

    Tratamento especial para transporte:
      - "servido": calcula score pela quantidade de paradas por faixa
      - "possui_indicios_de_atendimento": score 0.4
      - "dados_insuficientes": score 0.5 neutro

    Score final = media simples dos 7 scores de categoria.
    """
    scores_categoria = {}
    detalhes_score = {}
    transporte_insuficiente = False

    for categoria, pesos_faixa in PESOS_DISTANCIA.items():
        if categoria == "transporte":
            # Tratamento especial com dados expandidos
            status = transporte.get("status", "dados_insuficientes")
            if status == "servido":
                # Calcula score pela quantidade de paradas por faixa
                qtd_por_faixa = {}
                total_ponderado = 0.0
                for _, _, nome_faixa in FAIXAS:
                    peso = pesos_faixa.get(nome_faixa, 0)
                    paradas_faixa = [
                        p for p in transporte.get("paradas", []) + transporte.get("estacoes", [])
                        if p.get("faixa") == nome_faixa
                    ]
                    qtd = len(paradas_faixa)
                    qtd_por_faixa[nome_faixa] = qtd
                    total_ponderado += qtd * peso

                normalizador = NORMALIZADORES.get("transporte", 6)
                score = max(0.0, min(1.0, round(total_ponderado / normalizador, 3)))
                scores_categoria["transporte"] = score
                detalhes_score["transporte"] = {
                    "qtd_0_400": qtd_por_faixa.get("0_400", 0),
                    "qtd_401_800": qtd_por_faixa.get("401_800", 0),
                    "qtd_801_1500": qtd_por_faixa.get("801_1500", 0),
                    "poi_efetivo": round(total_ponderado, 3),
                    "normalizador": normalizador,
                    "score": score,
                    "status": status,
                }
            elif status == "possui_indicios_de_atendimento":
                scores_categoria["transporte"] = 0.4
                transporte_insuficiente = True
                detalhes_score["transporte"] = {
                    "qtd_0_400": 0, "qtd_401_800": 0, "qtd_801_1500": 0,
                    "poi_efetivo": 0, "normalizador": NORMALIZADORES.get("transporte", 6),
                    "score": 0.4, "status": status,
                }
            else:  # dados_insuficientes
                scores_categoria["transporte"] = 0.5
                transporte_insuficiente = True
                detalhes_score["transporte"] = {
                    "qtd_0_400": 0, "qtd_401_800": 0, "qtd_801_1500": 0,
                    "poi_efetivo": 0, "normalizador": NORMALIZADORES.get("transporte", 6),
                    "score": 0.5, "status": status,
                }
            continue

        # Tratamento especial para servicos_e_alimentacao (limite por subtipo)
        if categoria == "servicos_e_alimentacao":
            # Coleta todos os POIs dessa categoria de todas as faixas
            todos_pois = []
            for _, _, nome_faixa in FAIXAS:
                pois_faixa = pois_por_faixa.get(nome_faixa, {}).get(categoria, [])
                for poi in pois_faixa:
                    todos_pois.append({**poi, "faixa_original": nome_faixa})

            # Agrupa por subtipo, ordena por distancia, aplica limite
            from collections import defaultdict
            por_subtipo = defaultdict(list)
            for poi in todos_pois:
                por_subtipo[poi.get("tipo", "?")].append(poi)

            # Ordena cada subtipo por distancia e aplica limite
            pois_selecionados = []
            qtd_bruta_por_tipo = {}
            qtd_considerada_por_tipo = {}
            for subtipo, pois_sub in por_subtipo.items():
                pois_sub.sort(key=lambda x: x.get("distancia_metros", 9999))
                qtd_bruta_por_tipo[subtipo] = len(pois_sub)
                limite = LIMITES_SERVICOS_ALIMENTACAO.get(subtipo, 2)
                selecionados = pois_sub[:limite]
                qtd_considerada_por_tipo[subtipo] = len(selecionados)
                pois_selecionados.extend(selecionados)

            # Distribui nas faixas e calcula poi_efetivo
            qtd_por_faixa = {"0_400": 0, "401_800": 0, "801_1500": 0}
            total_ponderado = 0.0
            tipos_encontrados = set()
            for poi in pois_selecionados:
                faixa_poi = poi.get("faixa_original")
                if faixa_poi:
                    qtd_por_faixa[faixa_poi] = qtd_por_faixa.get(faixa_poi, 0) + 1
                    peso = pesos_faixa.get(faixa_poi, 0)
                    total_ponderado += peso
                    tipos_encontrados.add(poi.get("tipo", "?"))

            normalizador = NORMALIZADORES.get(categoria, 4)
            score = max(0.0, min(1.0, round(total_ponderado / normalizador, 3)))
            scores_categoria[categoria] = score
            detalhes_score[categoria] = {
                "qtd_0_400": qtd_por_faixa.get("0_400", 0),
                "qtd_401_800": qtd_por_faixa.get("401_800", 0),
                "qtd_801_1500": qtd_por_faixa.get("801_1500", 0),
                "tipos_encontrados": sorted(tipos_encontrados),
                "quantidade_bruta_por_tipo": qtd_bruta_por_tipo,
                "quantidade_considerada_por_tipo": qtd_considerada_por_tipo,
                "poi_efetivo": round(total_ponderado, 3),
                "normalizador": normalizador,
                "score": score,
            }
            continue

        # Calcula para categorias normais (cap de 5 POIs por faixa pra evitar inflacao)
        CAP_POR_FAIXA = 5
        qtd_por_faixa = {}
        total_ponderado = 0.0
        tipos_encontrados = set()
        for _, _, nome_faixa in FAIXAS:
            peso = pesos_faixa.get(nome_faixa, 0)
            pois_faixa = pois_por_faixa.get(nome_faixa, {}).get(categoria, [])
            qtd = min(len(pois_faixa), CAP_POR_FAIXA)  # Cap pra nao inflar score
            qtd_por_faixa[nome_faixa] = len(pois_faixa)  # Log mostra real
            total_ponderado += qtd * peso
            for poi in pois_faixa:
                tipos_encontrados.add(poi.get("tipo", "?"))

        normalizador = NORMALIZADORES.get(categoria, 3)
        score = max(0.0, min(1.0, round(total_ponderado / normalizador, 3)))
        scores_categoria[categoria] = score
        detalhes_score[categoria] = {
            "qtd_0_400": qtd_por_faixa.get("0_400", 0),
            "qtd_401_800": qtd_por_faixa.get("401_800", 0),
            "qtd_801_1500": qtd_por_faixa.get("801_1500", 0),
            "tipos_encontrados": sorted(tipos_encontrados),
            "poi_efetivo": round(total_ponderado, 3),
            "normalizador": normalizador,
            "score": score,
        }

    # Score final = media simples dos 7 scores
    score_final = round(
        max(0.0, min(1.0, sum(scores_categoria.values()) / len(scores_categoria))),
        3
    )

    # Validacao de consistencia (nao interrompe execucao)
    try:
        for cat in scores_categoria:
            if cat in detalhes_score:
                if scores_categoria[cat] != detalhes_score[cat]["score"]:
                    logger.warning(f"Inconsistencia: scores_categoria[{cat}]={scores_categoria[cat]} != detalhes_score score={detalhes_score[cat]['score']}")
    except Exception:
        pass

    return {
        "score_final": score_final,
        "scores_categoria": scores_categoria,
        "detalhes_score": detalhes_score,
        "transporte_status": transporte.get("status", "dados_insuficientes"),
        "transporte_dados_insuficientes": transporte_insuficiente,
    }


# =============================================================================
# BLOCO 4 - CLASSIFICACAO E ANALISE VIA LLM
# =============================================================================

def _classificar_infraestrutura(score: float) -> str:
    """
    Classifica o nivel de infraestrutura com base no score final.
    Intervalos:
      < 0.30 → insuficiente
      0.30 até < 0.50 → basica
      0.50 até < 0.70 → moderada
      0.70 até < 0.85 → boa
      >= 0.85 → excelente
    """
    if score < 0.30:
        return "insuficiente"
    elif score < 0.50:
        return "basica"
    elif score < 0.70:
        return "moderada"
    elif score < 0.85:
        return "boa"
    else:
        return "excelente"


# Mapeamento classificacao → perfil (determinístico)
MAPA_PERFIL_INFRAESTRUTURA = {
    "excelente": "infraestrutura_muito_alta",
    "boa": "infraestrutura_alta",
    "moderada": "infraestrutura_moderada",
    "basica": "infraestrutura_basica",
    "insuficiente": "infraestrutura_insuficiente",
}


def _calcular_impacto(score_final: float) -> str:
    """Calcula impacto da infraestrutura de forma deterministica."""
    if score_final >= 0.85:
        return "muito_positivo"
    elif score_final >= 0.70:
        return "positivo"
    elif score_final >= 0.50:
        return "neutro"
    elif score_final >= 0.30:
        return "negativo"
    else:
        return "muito_negativo"


def _analisar_infra_llm(pois_por_faixa: dict, scores: dict, endereco: str, transporte: dict) -> dict:
    """
    Envia resumo dos POIs e scores para LLM e retorna APENAS interpretacao textual.
    A LLM NAO decide perfil, impacto ou classificacao — apenas interpreta.
    Cadeia: NVIDIA NIM (principal) → Gemini (fallback)
    """
    import re

    # Monta resumo de POIs por faixa
    resumo_pois = ""
    for _, _, nome_faixa in FAIXAS:
        cats = pois_por_faixa.get(nome_faixa, {})
        total = sum(len(v) for v in cats.values())
        resumo_pois += f"\n  {nome_faixa} ({total} POIs):"
        for cat, pois in cats.items():
            if cat == "transporte":
                continue
            if pois:
                nomes = [p["nome"] for p in pois[:3]]
                resumo_pois += f"\n    {cat} ({len(pois)}): {', '.join(nomes)}"

    # Monta resumo de transporte
    status_transp = transporte.get("status", "dados_insuficientes")
    paradas = transporte.get("paradas", [])
    resumo_transporte = f"Status: {status_transp}, {len(paradas)} paradas encontradas"

    # Campos calculados pelo Python
    scores_categoria = scores.get("scores_categoria", {})
    score_final = scores.get("score_final", 0.5)
    classificacao = _classificar_infraestrutura(score_final)
    perfil = MAPA_PERFIL_INFRAESTRUTURA.get(classificacao, "infraestrutura_moderada")
    impacto = _calcular_impacto(score_final)

    scores_json = json.dumps(scores_categoria, ensure_ascii=False, indent=2)

    prompt = f"""Avaliador imobiliario. Interprete os resultados de infraestrutura abaixo.
NAO recalcule valores. Apenas interprete.

Endereco: {endereco}
POIs:{resumo_pois}
Transporte: {resumo_transporte}
Scores: {scores_json}
Score final: {score_final} | Classificacao: {classificacao}

Retorne JSON:
- pontos_fortes: categorias com score >= 0.70 (max 4)
- pontos_de_atencao: categorias com score < 0.50 (max 4)
- descricao_infraestrutura: 1-2 frases
- conclusao: 1 frase

JSON:
{{"pontos_fortes": [], "pontos_de_atencao": [], "descricao_infraestrutura": "", "conclusao": ""}}"""

    # Tentativa 1: NVIDIA NIM (sem limite diario)
    try:
        from openai import OpenAI
        nvidia_key = os.getenv("NVIDIA_API_KEY", "")
        if nvidia_key:
            client = OpenAI(base_url="https://integrate.api.nvidia.com/v1", api_key=nvidia_key)
            response = client.chat.completions.create(
                model="meta/llama-3.1-8b-instruct",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=600,
                temperature=0,
            )
            conteudo = response.choices[0].message.content or ""
            m = re.search(r'\{[\s\S]+\}', conteudo)
            if m:
                logger.info("LLM interpretou (NVIDIA NIM)")
                return json.loads(m.group(0))
    except Exception as e:
        logger.warning(f"NVIDIA NIM falhou: {e}")

    # Tentativa 2: Gemini (fallback)
    try:
        from google import genai
        from google.genai import types
        google_key = os.getenv("GOOGLE_API_KEY_2", "") or os.getenv("GOOGLE_API_KEY", "")
        if google_key:
            client = genai.Client(api_key=google_key)
            response = client.models.generate_content(
                model="gemini-3.5-flash-lite",
                contents=[types.Content(role="user", parts=[types.Part.from_text(text=prompt)])],
                config=types.GenerateContentConfig(temperature=0),
            )
            conteudo = response.text or ""
            m = re.search(r'\{[\s\S]+\}', conteudo)
            if m:
                logger.info("LLM interpretou (Gemini fallback)")
                return json.loads(m.group(0))
    except Exception as e:
        logger.warning(f"Gemini falhou: {e}")

    logger.warning("Nenhuma LLM disponivel para interpretacao")
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

    # Tenta reutilizar coordenadas já calculadas pelo Agente 2 (zona homogênea)
    lat, lon = None, None
    caminho_zona = os.path.join(DATA_DIR, "zona_homogenea_ag2.json")
    if os.path.exists(caminho_zona):
        try:
            with open(caminho_zona, "r", encoding="utf-8") as f:
                zona_data = json.load(f)
            coords = zona_data.get("coordenadas_alvo", {})
            if coords.get("lat") and coords.get("lon"):
                lat, lon = coords["lat"], coords["lon"]
                logger.info(f"Coordenadas reutilizadas do Agente 2: {lat:.6f}, {lon:.6f}")
        except Exception:
            pass

    # Fallback: geocodifica se não encontrou coordenadas anteriores
    if not lat:
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
    resultado_score = _calcular_score(pois_por_faixa, transporte)
    scores = resultado_score
    logger.info(f"Scores por categoria:")
    for cat, score in scores.get("scores_categoria", {}).items():
        sufixo = f" [{scores.get('transporte_status','?')}]" if cat == "transporte" and scores.get("transporte_dados_insuficientes") else ""
        logger.info(f"  {cat:20}: {score:.3f}{sufixo}")
    logger.info(f"  {'score_final':20}: {scores['score_final']:.3f}")
    if scores.get("transporte_dados_insuficientes"):
        logger.info(f"  AVISO: transporte status={scores.get('transporte_status')}")

    # ── ANALISE VIA LLM ───────────────────────────────────────────
    logger.info("Analisando via LLM...")
    analise = _analisar_infra_llm(pois_por_faixa, scores, endereco, transporte)
    if analise:
        logger.info(f"LLM interpretou: {len(analise.get('pontos_fortes',[]))} pontos fortes, {len(analise.get('pontos_de_atencao',[]))} atencao")
    else:
        logger.warning("LLM nao retornou interpretacao — usando defaults")

    # ── SALVA ─────────────────────────────────────────────────────
    classificacao = _classificar_infraestrutura(scores.get("score_final", 0.5))
    perfil_infraestrutura = MAPA_PERFIL_INFRAESTRUTURA.get(classificacao, "infraestrutura_moderada")
    impacto_infraestrutura = _calcular_impacto(scores.get("score_final", 0.5))

    saida = {
        "imovel_alvo":   imovel_alvo,
        "coordenadas":   {"lat": lat, "lon": lon},
        "fonte_infraestrutura": "OpenStreetMap",
        "raio_maximo_metros": RAIO_MAX,
        "total_pois_validos": sum(
            len(pois)
            for faixa_data in pois_por_faixa.values()
            for pois in faixa_data.values()
        ),
        "faixas_metros": {"0_400": "0-400m",
                          "401_800": "401-800m",
                          "801_1500": "801-1500m"},
        "tolerancia_pct": TOLERANCIA * 100,
        "pois_por_faixa": pois_por_faixa,
        "transporte":     transporte,
        "scores":         {
            "score_final": scores["score_final"],
            "classificacao_infraestrutura": classificacao,
            "perfil_infraestrutura": perfil_infraestrutura,
            "impacto_infraestrutura": impacto_infraestrutura,
            "scores_categoria": scores.get("scores_categoria", {}),
            "detalhes_score": scores.get("detalhes_score", {}),
        },
        "interpretacao_llm": analise if analise else {
            "pontos_fortes": [],
            "pontos_de_atencao": [],
            "descricao_infraestrutura": "Interpretacao nao disponivel",
            "justificativa": "LLM nao retornou resultado",
            "conclusao": "",
        },
    }

    caminho_saida = os.path.join(DATA_DIR, arquivo_saida)
    with open(caminho_saida, "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=2)
    logger.info(f"Salvo em: {caminho_saida}")
    logger.info("=" * 55)

    return saida
