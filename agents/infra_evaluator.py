"""
Agente 4 — Avaliador de Infraestrutura
========================================

RESPONSABILIDADE:
    Analisa o entorno do imovel alvo buscando pontos de interesse (POIs).
    Fonte principal: Geoapify Places API.
    Fallback: Google Places API somente quando a consulta Geoapify falha ou
    retorna zero resultados para um grupo. Se as duas fontes falharem
    tecnicamente, a categoria recebe score neutro 0.5.

ENTRADA:
    - data/zona_homogenea_ag2.json
    - data/imoveis_analisados_ag3.json

SAIDA:
    - data/infra_avaliada_ag4.json

FLUXO:
    1. Reutiliza coordenadas do Agente 2; Nominatim -> Google Geocoding se necessario.
    2. Faz consultas Geoapify com limit=20.
    3. Google Places fica como fallback por grupo.
    4. Busca imobiliaria separadamente.
    5. Haversine, faixas, pesos, normalizadores e score continuam determinísticos.
    6. Se Geoapify + Google falharem tecnicamente, usa score neutro 0.5.
    7. LLM apenas interpreta o resultado.

GEOAPIFY:
    - 20 resultados por consulta.
    - ate 1 credito por consulta.
    - maximo planejado: 8 creditos por avaliacao.
"""

import os
import json
import math
import logging
import requests
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


# =============================================================================
# CONFIGURACAO
# =============================================================================

FAIXAS = [
    (0,   400,  "0_400"),
    (401, 800,  "401_800"),
    (801, 1500, "801_1500"),
]

TOLERANCIA = 0.05
RAIO_MAX = 1500

GEOAPIFY_LIMIT = 20
RAIO_IMOBILIARIA = 8000
SCORE_NEUTRO = 0.5


GEOAPIFY_GRUPOS = {

    "comercio": [
        "commercial.supermarket",
        "commercial.marketplace",
        "commercial.food_and_drink.bakery",
        "commercial.convenience",
        "commercial.food_and_drink.butcher",
        "commercial.food_and_drink.fruit_and_vegetable",
    ],

    "educacao": [
        "education.school",
        "childcare.kindergarten",
    ],

    "saude_hospital": [
        "healthcare.pharmacy",
        "healthcare.clinic_or_praxis",
        "healthcare.dentist",
        "healthcare.hospital",
    ],

    "lazer": [
        "leisure.park",
        "leisure.playground",
        "sport.fitness.fitness_centre",
        "sport.sports_centre",
    ],

    "equipamentos_regionais": [
        "education.university",
        "education.college",
        "commercial.shopping_mall",
    ],

    "servicos_e_alimentacao": [
        "catering.restaurant",
        "catering.cafe",
        "service.financial.bank",
        "service.financial.atm",
    ],

    "transporte": [
        "public_transport.bus",
        "public_transport.train",
        "public_transport.subway",
        "public_transport.tram",
    ],

    "imobiliaria": [
        "service.estate_agent",
        "office.estate_agent",
    ],
}


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


LIMITES_SERVICOS_ALIMENTACAO = {
    "restaurant": 2,
    "cafe": 2,
    "bank": 1,
    "atm": 1,
}


NORMALIZADORES = {
    "comercio": 7,
    "educacao": 4,
    "saude_basica": 5,
    "transporte": 8,
    "lazer": 5,
    "hospital": 2,
    "equipamentos_regionais": 2,
    "servicos_e_alimentacao": 5,
}


# =============================================================================
# GEOLOCALIZACAO
# =============================================================================

def _geocodificar(endereco: str) -> tuple:

    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": endereco,
                "format": "json",
                "limit": 1
            },
            headers={
                "User-Agent": "ProjetoImoveisIA/1.0"
            },
            timeout=10,
        )

        if r.status_code == 200 and r.json():
            data = r.json()[0]

            return (
                float(data["lat"]),
                float(data["lon"])
            )

    except Exception:
        pass


    maps_key = os.getenv("GOOGLE_MAPS_KEY", "")

    if maps_key:

        try:

            r = requests.get(
                "https://maps.googleapis.com/maps/api/geocode/json",
                params={
                    "address": endereco,
                    "key": maps_key
                },
                timeout=10,
            )

            if r.status_code == 200:

                results = r.json().get("results", [])

                if results:

                    loc = results[0]["geometry"]["location"]

                    return (
                        float(loc["lat"]),
                        float(loc["lng"])
                    )

        except Exception:
            pass

    return None, None


def _haversine(lat1, lon1, lat2, lon2) -> int:

    R = 6371000

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)

    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (
        math.sin(dphi / 2) ** 2
        +
        math.cos(phi1)
        * math.cos(phi2)
        * math.sin(dlambda / 2) ** 2
    )

    return round(
        R
        * 2
        * math.atan2(
            math.sqrt(a),
            math.sqrt(1 - a)
        )
    )


def _faixa_de(distancia: int) -> str:

    for limite_min, limite_max, nome_faixa in FAIXAS:

        limite_max_tolerado = limite_max * (1 + TOLERANCIA)

        if limite_min <= distancia <= limite_max_tolerado:
            return nome_faixa

    return None


# =============================================================================
# FUNCOES AUXILIARES
# =============================================================================

def _resultado_vazio_pois() -> dict:

    return {
        nome: {
            cat: []
            for cat in POIS_POR_CATEGORIA
        }
        for _, _, nome in FAIXAS
    }


# =============================================================================
# GEOAPIFY
# =============================================================================

def _geoapify_request(
    lat: float,
    lon: float,
    categorias: list,
    raio: int,
    limit: int = GEOAPIFY_LIMIT
) -> dict:

    import time

    api_key = (
        os.getenv("GEOAPIFY_API_KEY", "")
        or os.getenv("GEOAPIFY_KEY", "")
    )

    if not api_key:

        return {
            "ok": False,
            "http_status": None,
            "features": [],
            "tempo_s": 0.0,
            "erro": "GEOAPIFY_API_KEY nao configurada",
        }


    url = "https://api.geoapify.com/v2/places"

    params = {
        "categories": ",".join(categorias),
        "filter": f"circle:{lon},{lat},{raio}",
        "bias": f"proximity:{lon},{lat}",
        "limit": int(limit),
        "apiKey": api_key,
    }


    t0 = time.perf_counter()

    try:

        resp = requests.get(
            url,
            params=params,
            timeout=10
        )

        tempo = time.perf_counter() - t0


        if resp.status_code != 200:

            return {
                "ok": False,
                "http_status": resp.status_code,
                "features": [],
                "tempo_s": tempo,
                "erro": f"HTTP {resp.status_code}",
            }


        data = resp.json()

        features = (
            data.get("features", [])
            or []
        )


        return {
            "ok": True,
            "http_status": 200,
            "features": features,
            "tempo_s": tempo,
            "erro": None,
        }


    except Exception as e:

        return {
            "ok": False,
            "http_status": None,
            "features": [],
            "tempo_s": time.perf_counter() - t0,
            "erro": str(e),
        }


# =============================================================================
# GOOGLE FALLBACK
# =============================================================================

def _google_request(
    lat: float,
    lon: float,
    tipos: list,
    raio: int = RAIO_MAX,
    max_resultados: int = 20,
    telefone: bool = False
) -> dict:

    import time


    api_key = os.getenv("GOOGLE_MAPS_KEY", "")


    if not api_key:

        return {
            "ok": False,
            "http_status": None,
            "places": [],
            "tempo_s": 0.0,
            "erro": "GOOGLE_MAPS_KEY nao configurada",
        }


    url = "https://places.googleapis.com/v1/places:searchNearby"


    field_mask = (
        "places.id,"
        "places.displayName,"
        "places.location,"
        "places.primaryType,"
        "places.formattedAddress"
    )


    if telefone:

        field_mask += ",places.nationalPhoneNumber"


    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": field_mask,
    }


    body = {

        "includedTypes": tipos,

        "maxResultCount": max(
            1,
            min(
                int(max_resultados),
                20
            )
        ),

        "locationRestriction": {

            "circle": {

                "center": {
                    "latitude": lat,
                    "longitude": lon
                },

                "radius": float(raio),
            }
        },
    }


    t0 = time.perf_counter()


    try:

        resp = requests.post(
            url,
            json=body,
            headers=headers,
            timeout=10
        )

        tempo = time.perf_counter() - t0


        if resp.status_code != 200:

            return {
                "ok": False,
                "http_status": resp.status_code,
                "places": [],
                "tempo_s": tempo,
                "erro": f"HTTP {resp.status_code}",
            }


        return {
            "ok": True,
            "http_status": 200,
            "places": (
                resp.json().get("places", [])
                or []
            ),
            "tempo_s": tempo,
            "erro": None,
        }


    except Exception as e:

        return {
            "ok": False,
            "http_status": None,
            "places": [],
            "tempo_s": time.perf_counter() - t0,
            "erro": str(e),
        }


# =============================================================================
# NORMALIZACAO DE CATEGORIAS
# =============================================================================

def _tipo_geoapify(
    categorias: list,
    categoria_interna: str
) -> str:

    cats = set(categorias or [])


    if categoria_interna == "servicos_e_alimentacao":

        if any(
            c.startswith("catering.restaurant")
            for c in cats
        ):
            return "restaurant"

        if any(
            c.startswith("catering.cafe")
            for c in cats
        ):
            return "cafe"

        if "service.financial.bank" in cats:
            return "bank"

        if "service.financial.atm" in cats:
            return "atm"


    preferidos = {

        "comercio": [
            ("commercial.supermarket", "supermarket"),
            ("commercial.marketplace", "marketplace"),
            ("commercial.food_and_drink.bakery", "bakery"),
            ("commercial.convenience", "convenience"),
            ("commercial.food_and_drink.butcher", "butcher"),
            ("commercial.food_and_drink.fruit_and_vegetable", "greengrocer"),
        ],

        "educacao": [
            ("education.school", "school"),
            ("childcare.kindergarten", "kindergarten"),
        ],

        "saude_basica": [
            ("healthcare.pharmacy", "pharmacy"),
            ("healthcare.clinic_or_praxis", "clinic"),
            ("healthcare.dentist", "dentist"),
        ],

        "hospital": [
            ("healthcare.hospital", "hospital")
        ],

        "lazer": [
            ("leisure.park", "park"),
            ("leisure.playground", "playground"),
            ("sport.fitness.fitness_centre", "fitness_centre"),
            ("sport.sports_centre", "sports_centre"),
        ],

        "equipamentos_regionais": [
            ("education.university", "university"),
            ("education.college", "college"),
            ("commercial.shopping_mall", "mall"),
        ],
    }


    for chave, subtipo in preferidos.get(
        categoria_interna,
        []
    ):

        if (
            chave in cats
            or any(
                c.startswith(chave + ".")
                for c in cats
            )
        ):
            return subtipo


    return categoria_interna


def _categoria_saude_geoapify(
    categorias: list
) -> str:

    cats = set(categorias or [])


    if (
        "healthcare.hospital" in cats
        or any(
            c.startswith("healthcare.hospital.")
            for c in cats
        )
    ):
        return "hospital"


    return "saude_basica"


def _categoria_saude_google(
    primary_type: str
) -> str:

    if primary_type == "hospital":
        return "hospital"

    return "saude_basica"


def _tipos_google_grupo(
    grupo: str
) -> list:

    return {

        "comercio": [
            "supermarket",
            "grocery_store",
            "bakery",
            "convenience_store",
        ],

        "educacao": [
            "school",
            "primary_school",
            "secondary_school",
        ],

        "saude_hospital": [
            "pharmacy",
            "doctor",
            "dentist",
            "hospital",
        ],

        "lazer": [
            "park",
            "gym",
            "playground",
        ],

        "equipamentos_regionais": [
            "university",
            "shopping_mall",
        ],

        "servicos_e_alimentacao": [
            "restaurant",
            "cafe",
            "bank",
            "atm",
        ],

        "transporte": [
            "bus_station",
            "transit_station",
        ],

        "imobiliaria": [
            "real_estate_agency",
        ],

    }.get(
        grupo,
        []
    )


def _normalizar_google_tipo(
    primary_type: str,
    categoria_interna: str
) -> str:

    mapa = {

        "grocery_store": "supermarket",

        "convenience_store": "convenience",

        "primary_school": "school",

        "secondary_school": "school",

        "doctor": "doctors",

        "gym": "fitness_centre",

        "shopping_mall": "mall",
    }


    if categoria_interna == "servicos_e_alimentacao":

        if primary_type in LIMITES_SERVICOS_ALIMENTACAO:
            return primary_type

        return categoria_interna


    return mapa.get(
        primary_type,
        primary_type or categoria_interna
    )


def _adicionar_poi(
    resultado: dict,
    vistos: set,
    *,
    nome: str,
    tipo: str,
    categoria: str,
    lat_alvo: float,
    lon_alvo: float,
    lat_p: float,
    lon_p: float,
    fonte: str,
    place_id: str = None
) -> bool:

    dist = _haversine(
        lat_alvo,
        lon_alvo,
        lat_p,
        lon_p
    )


    faixa = _faixa_de(dist)


    if faixa is None:
        return False


    chave = (
        place_id
        or f"{round(lat_p, 5)}_{round(lon_p, 5)}"
    )


    if chave in vistos:
        return False


    vistos.add(chave)


    resultado[faixa][categoria].append({

        "nome": nome or "?",

        "tipo": tipo,

        "categoria": categoria,

        "distancia_metros": dist,

        "fonte": fonte,

        "place_id": place_id,

        "lat": lat_p,

        "lon": lon_p,
    })


    return True


# =============================================================================
# POIS GERAIS
# =============================================================================

def _buscar_pois_classificados(
    lat: float,
    lon: float
) -> tuple:

    import time


    resultado = _resultado_vazio_pois()

    vistos = set()


    diagnostico = {

        "geoapify_chamadas": 0,

        "geoapify_creditos_maximos": 0,

        "google_fallback_chamadas": 0,

        "tempo_busca_pois_s": 0.0,

        "grupos": {},
    }


    status_categorias = {

        cat: "nao_consultado"

        for cat in PESOS_DISTANCIA

        if cat != "transporte"
    }


    grupos_infra = [

        "comercio",

        "educacao",

        "saude_hospital",

        "lazer",

        "equipamentos_regionais",

        "servicos_e_alimentacao",
    ]


    t_total = time.perf_counter()


    for grupo in grupos_infra:


        consulta = _geoapify_request(

            lat,

            lon,

            GEOAPIFY_GRUPOS[grupo],

            RAIO_MAX,

            GEOAPIFY_LIMIT
        )


        diagnostico["geoapify_chamadas"] += 1

        diagnostico["geoapify_creditos_maximos"] += 1


        features = (

            consulta.get("features", [])

            if consulta.get("ok")

            else []
        )


        meta = {

            "fonte_primaria": "geoapify",

            "geoapify_ok": consulta.get(
                "ok",
                False
            ),

            "geoapify_http": consulta.get(
                "http_status"
            ),

            "geoapify_resultados": len(features),

            "geoapify_tempo_s": round(
                consulta.get(
                    "tempo_s",
                    0.0
                ),
                3
            ),

            "fallback_google": False,
        }


        adicionados = 0


        # -------------------------------------------------------------
        # GEOAPIFY FUNCIONOU
        # -------------------------------------------------------------

        if (
            consulta.get("ok")
            and features
        ):


            for feat in features:


                prop = (
                    feat.get(
                        "properties",
                        {}
                    )
                    or {}
                )


                geom = (
                    feat.get(
                        "geometry",
                        {}
                    )
                    or {}
                )


                coords = (
                    geom.get(
                        "coordinates",
                        []
                    )
                    or []
                )


                if len(coords) < 2:
                    continue


                lon_p = float(coords[0])

                lat_p = float(coords[1])


                cats = (
                    prop.get(
                        "categories",
                        []
                    )
                    or []
                )


                if grupo == "saude_hospital":

                    categoria = (
                        _categoria_saude_geoapify(
                            cats
                        )
                    )

                else:

                    categoria = grupo


                tipo = _tipo_geoapify(
                    cats,
                    categoria
                )


                if _adicionar_poi(

                    resultado,

                    vistos,

                    nome=prop.get(
                        "name",
                        "?"
                    ),

                    tipo=tipo,

                    categoria=categoria,

                    lat_alvo=lat,

                    lon_alvo=lon,

                    lat_p=lat_p,

                    lon_p=lon_p,

                    fonte="geoapify",

                    place_id=prop.get(
                        "place_id"
                    ),

                ):

                    adicionados += 1


            if grupo == "saude_hospital":

                status_categorias[
                    "saude_basica"
                ] = "geoapify"

                status_categorias[
                    "hospital"
                ] = "geoapify"

            else:

                status_categorias[
                    grupo
                ] = "geoapify"


        # -------------------------------------------------------------
        # GEOAPIFY FALHOU / ZERO -> GOOGLE
        # -------------------------------------------------------------

        else:


            meta[
                "fallback_google"
            ] = True


            fallback = _google_request(

                lat,

                lon,

                _tipos_google_grupo(
                    grupo
                ),

                RAIO_MAX,

                20,

                telefone=False
            )


            diagnostico[
                "google_fallback_chamadas"
            ] += 1


            places = (

                fallback.get(
                    "places",
                    []
                )

                if fallback.get(
                    "ok"
                )

                else []
            )


            meta.update({

                "google_ok": fallback.get(
                    "ok",
                    False
                ),

                "google_http": fallback.get(
                    "http_status"
                ),

                "google_resultados": len(
                    places
                ),

                "google_tempo_s": round(
                    fallback.get(
                        "tempo_s",
                        0.0
                    ),
                    3
                ),
            })


            if fallback.get("ok"):


                for place in places:


                    loc = (
                        place.get(
                            "location",
                            {}
                        )
                        or {}
                    )


                    lat_p = loc.get(
                        "latitude"
                    )

                    lon_p = loc.get(
                        "longitude"
                    )


                    if (
                        lat_p is None
                        or lon_p is None
                    ):
                        continue


                    primary = place.get(
                        "primaryType",
                        ""
                    )


                    if grupo == "saude_hospital":

                        categoria = (
                            _categoria_saude_google(
                                primary
                            )
                        )

                    else:

                        categoria = grupo


                    tipo = (
                        _normalizar_google_tipo(
                            primary,
                            categoria
                        )
                    )


                    if _adicionar_poi(

                        resultado,

                        vistos,

                        nome=place.get(
                            "displayName",
                            {}
                        ).get(
                            "text",
                            "?"
                        ),

                        tipo=tipo,

                        categoria=categoria,

                        lat_alvo=lat,

                        lon_alvo=lon,

                        lat_p=float(lat_p),

                        lon_p=float(lon_p),

                        fonte="google_fallback",

                        place_id=place.get(
                            "id"
                        ),

                    ):

                        adicionados += 1


                if grupo == "saude_hospital":

                    estado = (

                        "google_fallback"

                        if places

                        else "sem_pois_confirmado"
                    )

                    status_categorias[
                        "saude_basica"
                    ] = estado

                    status_categorias[
                        "hospital"
                    ] = estado


                else:

                    status_categorias[
                        grupo
                    ] = (

                        "google_fallback"

                        if places

                        else "sem_pois_confirmado"
                    )


            else:

                # As duas APIs falharam
                # -> score neutro

                if grupo == "saude_hospital":

                    status_categorias[
                        "saude_basica"
                    ] = "dados_insuficientes"

                    status_categorias[
                        "hospital"
                    ] = "dados_insuficientes"

                else:

                    status_categorias[
                        grupo
                    ] = "dados_insuficientes"


        meta[
            "pois_adicionados"
        ] = adicionados


        diagnostico[
            "grupos"
        ][grupo] = meta


        logger.info(

            f"  [Ag4][{grupo}] "

            f"Geoapify={meta['geoapify_resultados']} "

            f"| fallback_google={meta.get('fallback_google', False)} "

            f"| adicionados={adicionados}"
        )


    for faixa_data in resultado.values():

        for cat in faixa_data:

            faixa_data[cat].sort(
                key=lambda x:
                x["distancia_metros"]
            )


    diagnostico[
        "tempo_busca_pois_s"
    ] = round(
        time.perf_counter()
        - t_total,
        3
    )


    for _, _, nome_faixa in FAIXAS:

        total = sum(
            len(v)
            for v
            in resultado[
                nome_faixa
            ].values()
        )

        logger.info(
            f"  {nome_faixa}: "
            f"{total} POIs"
        )


    total_encontrados = sum(

        len(pois)

        for faixa_data
        in resultado.values()

        for pois
        in faixa_data.values()
    )


    logger.info(

        f"  Total: "
        f"{total_encontrados} POIs "

        f"| Geoapify chamadas="
        f"{diagnostico['geoapify_chamadas']} "

        f"| creditos_max="
        f"{diagnostico['geoapify_creditos_maximos']} "

        f"| Google fallback chamadas="
        f"{diagnostico['google_fallback_chamadas']} "

        f"| tempo="
        f"{diagnostico['tempo_busca_pois_s']:.3f}s"
    )


    return (
        resultado,
        diagnostico,
        status_categorias
    )


# =============================================================================
# TRANSPORTE
# =============================================================================

def _buscar_transporte(
    lat: float,
    lon: float
) -> dict:

    import time


    resultado = {

        "paradas": [],

        "estacoes": [],

        "rotas": [],

        "status": "dados_insuficientes",

        "fonte": None,

        "fallback_google": False,

        "tempo_s": 0.0,
    }


    t0 = time.perf_counter()


    consulta = _geoapify_request(

        lat,

        lon,

        GEOAPIFY_GRUPOS["transporte"],

        RAIO_MAX,

        GEOAPIFY_LIMIT
    )


    resultado[
        "geoapify_ok"
    ] = consulta.get(
        "ok",
        False
    )


    resultado[
        "geoapify_resultados"
    ] = (

        len(
            consulta.get(
                "features",
                []
            )
        )

        if consulta.get("ok")

        else 0
    )


    # -------------------------------------------------------------
    # GEOAPIFY
    # -------------------------------------------------------------

    if (
        consulta.get("ok")
        and consulta.get(
            "features"
        )
    ):


        vistos = set()


        for feat in consulta.get(
            "features",
            []
        ):


            prop = (
                feat.get(
                    "properties",
                    {}
                )
                or {}
            )


            geom = (
                feat.get(
                    "geometry",
                    {}
                )
                or {}
            )


            coords = (
                geom.get(
                    "coordinates",
                    []
                )
                or []
            )


            if len(coords) < 2:
                continue


            lon_p = float(
                coords[0]
            )

            lat_p = float(
                coords[1]
            )


            dist = _haversine(
                lat,
                lon,
                lat_p,
                lon_p
            )


            faixa = _faixa_de(
                dist
            )


            if faixa is None:
                continue


            place_id = (

                prop.get(
                    "place_id"
                )

                or f"{round(lat_p,5)}_{round(lon_p,5)}"
            )


            if place_id in vistos:
                continue


            vistos.add(
                place_id
            )


            cats = (
                prop.get(
                    "categories",
                    []
                )
                or []
            )


            tipo = (

                "bus"

                if any(
                    c.startswith(
                        "public_transport.bus"
                    )
                    for c in cats
                )

                else "station"
            )


            entrada = {

                "nome": prop.get(
                    "name",
                    "parada"
                ),

                "tipo": tipo,

                "ref": place_id,

                "distancia_metros": dist,

                "faixa": faixa,

                "fonte": "geoapify",

                "lat": lat_p,

                "lon": lon_p,
            }


            if tipo == "bus":

                resultado[
                    "paradas"
                ].append(
                    entrada
                )

            else:

                resultado[
                    "estacoes"
                ].append(
                    entrada
                )


        resultado[
            "fonte"
        ] = "geoapify"


        resultado[
            "status"
        ] = (

            "servido"

            if (
                resultado["paradas"]
                or resultado["estacoes"]
            )

            else "dados_insuficientes"
        )


    # -------------------------------------------------------------
    # GOOGLE FALLBACK
    # -------------------------------------------------------------

    else:


        resultado[
            "fallback_google"
        ] = True


        fallback = _google_request(

            lat,

            lon,

            _tipos_google_grupo(
                "transporte"
            ),

            RAIO_MAX,

            20,

            telefone=False
        )


        resultado[
            "google_ok"
        ] = fallback.get(
            "ok",
            False
        )


        resultado[
            "google_resultados"
        ] = (

            len(
                fallback.get(
                    "places",
                    []
                )
            )

            if fallback.get(
                "ok"
            )

            else 0
        )


        if fallback.get("ok"):


            vistos = set()


            for place in fallback.get(
                "places",
                []
            ):


                loc = (
                    place.get(
                        "location",
                        {}
                    )
                    or {}
                )


                lat_p = loc.get(
                    "latitude"
                )

                lon_p = loc.get(
                    "longitude"
                )


                if (
                    lat_p is None
                    or lon_p is None
                ):
                    continue


                lat_p = float(
                    lat_p
                )

                lon_p = float(
                    lon_p
                )


                dist = _haversine(
                    lat,
                    lon,
                    lat_p,
                    lon_p
                )


                faixa = _faixa_de(
                    dist
                )


                if faixa is None:
                    continue


                chave = (

                    place.get(
                        "id"
                    )

                    or f"{round(lat_p,5)}_{round(lon_p,5)}"
                )


                if chave in vistos:
                    continue


                vistos.add(
                    chave
                )


                primary = place.get(
                    "primaryType",
                    "transit_station"
                )


                entrada = {

                    "nome": place.get(
                        "displayName",
                        {}
                    ).get(
                        "text",
                        "parada"
                    ),

                    "tipo": primary,

                    "ref": chave,

                    "distancia_metros": dist,

                    "faixa": faixa,

                    "fonte": "google_fallback",

                    "lat": lat_p,

                    "lon": lon_p,
                }


                if primary == "bus_station":

                    resultado[
                        "estacoes"
                    ].append(
                        entrada
                    )

                else:

                    resultado[
                        "paradas"
                    ].append(
                        entrada
                    )


            resultado[
                "fonte"
            ] = "google_fallback"


            resultado[
                "status"
            ] = (

                "servido"

                if (
                    resultado["paradas"]
                    or resultado["estacoes"]
                )

                else "sem_pois_confirmado"
            )


        else:

            resultado[
                "status"
            ] = "dados_insuficientes"

            resultado[
                "fonte"
            ] = "indisponivel"


    resultado[
        "paradas"
    ].sort(
        key=lambda x:
        x["distancia_metros"]
    )


    resultado[
        "estacoes"
    ].sort(
        key=lambda x:
        x["distancia_metros"]
    )


    resultado[
        "tempo_s"
    ] = round(
        time.perf_counter()
        - t0,
        3
    )


    logger.info(

        f"  Transporte: "
        f"{len(resultado['paradas'])} paradas "

        f"| {len(resultado['estacoes'])} estacoes "

        f"| fonte={resultado['fonte']} "

        f"| status={resultado['status']} "

        f"| tempo={resultado['tempo_s']:.3f}s"
    )


    return resultado


# =============================================================================
# IMOBILIARIA
# =============================================================================

def _buscar_imobiliaria_proxima(
    lat: float,
    lon: float
) -> dict:

    import time


    t0 = time.perf_counter()


    retorno = {

        "encontrada": False,

        "nome": None,

        "telefone": None,

        "endereco": None,

        "distancia_metros": None,

        "fonte": None,

        "fallback_google": False,

        "geoapify_resultados": 0,

        "google_resultados": 0,

        "tempo_s": 0.0,
    }


    consulta = _geoapify_request(

        lat,

        lon,

        GEOAPIFY_GRUPOS[
            "imobiliaria"
        ],

        RAIO_IMOBILIARIA,

        GEOAPIFY_LIMIT
    )


    features = (

        consulta.get(
            "features",
            []
        )

        if consulta.get(
            "ok"
        )

        else []
    )


    retorno[
        "geoapify_resultados"
    ] = len(
        features
    )


    candidatos_geo = []


    for feat in features:


        prop = (
            feat.get(
                "properties",
                {}
            )
            or {}
        )


        geom = (
            feat.get(
                "geometry",
                {}
            )
            or {}
        )


        coords = (
            geom.get(
                "coordinates",
                []
            )
            or []
        )


        if len(coords) < 2:
            continue


        lon_p = float(
            coords[0]
        )

        lat_p = float(
            coords[1]
        )


        dist = _haversine(
            lat,
            lon,
            lat_p,
            lon_p
        )


        telefone = (

            prop.get(
                "contact",
                {}
            )
            or {}
        ).get(
            "phone"
        )


        candidatos_geo.append({

            "nome": prop.get(
                "name",
                "?"
            ),

            "telefone": telefone,

            "endereco": prop.get(
                "formatted"
            ),

            "distancia_metros": dist,

            "fonte": "geoapify",

            "place_id": prop.get(
                "place_id"
            ),
        })


    candidatos_geo.sort(
        key=lambda x:
        x["distancia_metros"]
    )


    com_telefone = next(

        (
            c
            for c
            in candidatos_geo
            if c.get(
                "telefone"
            )
        ),

        None
    )


    # -------------------------------------------------------------
    # GEOAPIFY ENCONTROU TELEFONE
    # -------------------------------------------------------------

    if com_telefone:


        retorno.update({

            "encontrada": True,

            **com_telefone
        })


    # -------------------------------------------------------------
    # GOOGLE FALLBACK PARA IMOBILIARIA
    # -------------------------------------------------------------

    else:


        retorno[
            "fallback_google"
        ] = True


        fallback = _google_request(

            lat,

            lon,

            _tipos_google_grupo(
                "imobiliaria"
            ),

            RAIO_IMOBILIARIA,

            20,

            telefone=True
        )


        places = (

            fallback.get(
                "places",
                []
            )

            if fallback.get(
                "ok"
            )

            else []
        )


        retorno[
            "google_resultados"
        ] = len(
            places
        )


        candidatos_google = []


        for place in places:


            loc = (
                place.get(
                    "location",
                    {}
                )
                or {}
            )


            lat_p = loc.get(
                "latitude"
            )

            lon_p = loc.get(
                "longitude"
            )


            if (
                lat_p is None
                or lon_p is None
            ):
                continue


            dist = _haversine(

                lat,

                lon,

                float(lat_p),

                float(lon_p)
            )


            candidatos_google.append({

                "nome": place.get(
                    "displayName",
                    {}
                ).get(
                    "text",
                    "?"
                ),

                "telefone": place.get(
                    "nationalPhoneNumber"
                ),

                "endereco": place.get(
                    "formattedAddress"
                ),

                "distancia_metros": dist,

                "fonte": "google_fallback",

                "place_id": place.get(
                    "id"
                ),
            })


        candidatos_google.sort(
            key=lambda x:
            x["distancia_metros"]
        )


        com_tel_google = next(

            (
                c
                for c
                in candidatos_google
                if c.get(
                    "telefone"
                )
            ),

            None
        )


        escolhido = (

            com_tel_google

            or (

                candidatos_google[0]

                if candidatos_google

                else None
            )
        )


        if escolhido:


            retorno.update({

                "encontrada": True,

                **escolhido
            })


        elif candidatos_geo:


            retorno.update({

                "encontrada": True,

                **candidatos_geo[0]
            })


    retorno[
        "tempo_s"
    ] = round(

        time.perf_counter()
        - t0,

        3
    )


    logger.info(

        f"  Imobiliaria: "

        f"encontrada={retorno['encontrada']} "

        f"| fonte={retorno['fonte']} "

        f"| telefone="
        f"{'sim' if retorno.get('telefone') else 'nao'} "

        f"| fallback_google="
        f"{retorno['fallback_google']} "

        f"| tempo="
        f"{retorno['tempo_s']:.3f}s"
    )


    return retorno


# =============================================================================
# SCORE
# =============================================================================

def _calcular_score(
    pois_por_faixa: dict,
    transporte: dict,
    status_categorias: dict = None
) -> dict:


    scores_categoria = {}

    detalhes_score = {}

    transporte_insuficiente = False

    status_categorias = (
        status_categorias
        or {}
    )


    for (
        categoria,
        pesos_faixa
    ) in PESOS_DISTANCIA.items():


        # ============================================================
        # TRANSPORTE
        # ============================================================

        if categoria == "transporte":


            status = transporte.get(
                "status",
                "dados_insuficientes"
            )


            if status == "servido":


                qtd_por_faixa = {}

                total_ponderado = 0.0


                for (
                    _,
                    _,
                    nome_faixa
                ) in FAIXAS:


                    peso = pesos_faixa.get(
                        nome_faixa,
                        0
                    )


                    paradas_faixa = [

                        p

                        for p
                        in (
                            transporte.get(
                                "paradas",
                                []
                            )
                            +
                            transporte.get(
                                "estacoes",
                                []
                            )
                        )

                        if p.get(
                            "faixa"
                        )
                        == nome_faixa
                    ]


                    qtd = len(
                        paradas_faixa
                    )


                    qtd_por_faixa[
                        nome_faixa
                    ] = qtd


                    total_ponderado += (
                        qtd
                        * peso
                    )


                normalizador = (
                    NORMALIZADORES.get(
                        "transporte",
                        6
                    )
                )


                score = max(

                    0.0,

                    min(

                        1.0,

                        round(
                            total_ponderado
                            / normalizador,
                            3
                        )
                    )
                )


                scores_categoria[
                    "transporte"
                ] = score


                detalhes_score[
                    "transporte"
                ] = {

                    "qtd_0_400":
                    qtd_por_faixa.get(
                        "0_400",
                        0
                    ),

                    "qtd_401_800":
                    qtd_por_faixa.get(
                        "401_800",
                        0
                    ),

                    "qtd_801_1500":
                    qtd_por_faixa.get(
                        "801_1500",
                        0
                    ),

                    "poi_efetivo":
                    round(
                        total_ponderado,
                        3
                    ),

                    "normalizador":
                    normalizador,

                    "score":
                    score,

                    "status":
                    status,
                }


            elif (
                status
                == "possui_indicios_de_atendimento"
            ):


                scores_categoria[
                    "transporte"
                ] = 0.4


                transporte_insuficiente = True


                detalhes_score[
                    "transporte"
                ] = {

                    "qtd_0_400": 0,

                    "qtd_401_800": 0,

                    "qtd_801_1500": 0,

                    "poi_efetivo": 0,

                    "normalizador":
                    NORMALIZADORES.get(
                        "transporte",
                        6
                    ),

                    "score": 0.4,

                    "status":
                    status,
                }


            elif (
                status
                == "sem_pois_confirmado"
            ):


                scores_categoria[
                    "transporte"
                ] = 0.0


                detalhes_score[
                    "transporte"
                ] = {

                    "qtd_0_400": 0,

                    "qtd_401_800": 0,

                    "qtd_801_1500": 0,

                    "poi_efetivo": 0,

                    "normalizador":
                    NORMALIZADORES.get(
                        "transporte",
                        6
                    ),

                    "score": 0.0,

                    "status":
                    status,
                }


            else:


                scores_categoria[
                    "transporte"
                ] = SCORE_NEUTRO


                transporte_insuficiente = True


                detalhes_score[
                    "transporte"
                ] = {

                    "qtd_0_400": 0,

                    "qtd_401_800": 0,

                    "qtd_801_1500": 0,

                    "poi_efetivo": None,

                    "normalizador":
                    NORMALIZADORES.get(
                        "transporte",
                        6
                    ),

                    "score":
                    SCORE_NEUTRO,

                    "status":
                    status,

                    "score_neutro_aplicado":
                    True,
                }


            continue


        # ============================================================
        # SCORE NEUTRO SE AS DUAS APIS FALHAREM
        # ============================================================

        if (
            status_categorias.get(
                categoria
            )
            == "dados_insuficientes"
        ):


            scores_categoria[
                categoria
            ] = SCORE_NEUTRO


            detalhes_score[
                categoria
            ] = {

                "qtd_0_400": 0,

                "qtd_401_800": 0,

                "qtd_801_1500": 0,

                "poi_efetivo": None,

                "normalizador":
                NORMALIZADORES.get(
                    categoria
                ),

                "score":
                SCORE_NEUTRO,

                "status":
                "dados_insuficientes",

                "score_neutro_aplicado":
                True,
            }


            continue


        # ============================================================
        # SERVICOS E ALIMENTACAO
        # ============================================================

        if (
            categoria
            == "servicos_e_alimentacao"
        ):


            todos_pois = []


            for (
                _,
                _,
                nome_faixa
            ) in FAIXAS:


                pois_faixa = (

                    pois_por_faixa
                    .get(
                        nome_faixa,
                        {}
                    )
                    .get(
                        categoria,
                        []
                    )
                )


                for poi in pois_faixa:


                    todos_pois.append({

                        **poi,

                        "faixa_original":
                        nome_faixa
                    })


            from collections import defaultdict


            por_subtipo = defaultdict(
                list
            )


            for poi in todos_pois:

                por_subtipo[
                    poi.get(
                        "tipo",
                        "?"
                    )
                ].append(
                    poi
                )


            pois_selecionados = []

            qtd_bruta_por_tipo = {}

            qtd_considerada_por_tipo = {}


            for (
                subtipo,
                pois_sub
            ) in por_subtipo.items():


                pois_sub.sort(

                    key=lambda x:
                    x.get(
                        "distancia_metros",
                        9999
                    )
                )


                qtd_bruta_por_tipo[
                    subtipo
                ] = len(
                    pois_sub
                )


                limite = (

                    LIMITES_SERVICOS_ALIMENTACAO
                    .get(
                        subtipo,
                        2
                    )
                )


                selecionados = (
                    pois_sub[
                        :limite
                    ]
                )


                qtd_considerada_por_tipo[
                    subtipo
                ] = len(
                    selecionados
                )


                pois_selecionados.extend(
                    selecionados
                )


            qtd_por_faixa = {

                "0_400": 0,

                "401_800": 0,

                "801_1500": 0
            }


            total_ponderado = 0.0

            tipos_encontrados = set()


            for poi in pois_selecionados:


                faixa_poi = (
                    poi.get(
                        "faixa_original"
                    )
                )


                if faixa_poi:


                    qtd_por_faixa[
                        faixa_poi
                    ] += 1


                    peso = pesos_faixa.get(
                        faixa_poi,
                        0
                    )


                    total_ponderado += (
                        peso
                    )


                    tipos_encontrados.add(
                        poi.get(
                            "tipo",
                            "?"
                        )
                    )


            normalizador = (
                NORMALIZADORES.get(
                    categoria,
                    4
                )
            )


            score = max(

                0.0,

                min(

                    1.0,

                    round(
                        total_ponderado
                        / normalizador,
                        3
                    )
                )
            )


            scores_categoria[
                categoria
            ] = score


            detalhes_score[
                categoria
            ] = {

                "qtd_0_400":
                qtd_por_faixa.get(
                    "0_400",
                    0
                ),

                "qtd_401_800":
                qtd_por_faixa.get(
                    "401_800",
                    0
                ),

                "qtd_801_1500":
                qtd_por_faixa.get(
                    "801_1500",
                    0
                ),

                "tipos_encontrados":
                sorted(
                    tipos_encontrados
                ),

                "quantidade_bruta_por_tipo":
                qtd_bruta_por_tipo,

                "quantidade_considerada_por_tipo":
                qtd_considerada_por_tipo,

                "poi_efetivo":
                round(
                    total_ponderado,
                    3
                ),

                "normalizador":
                normalizador,

                "score":
                score,
            }


            continue


        # ============================================================
        # OUTRAS CATEGORIAS
        # ============================================================

        CAP_POR_FAIXA = 5


        qtd_por_faixa = {}

        total_ponderado = 0.0

        tipos_encontrados = set()


        for (
            _,
            _,
            nome_faixa
        ) in FAIXAS:


            peso = pesos_faixa.get(
                nome_faixa,
                0
            )


            pois_faixa = (

                pois_por_faixa
                .get(
                    nome_faixa,
                    {}
                )
                .get(
                    categoria,
                    []
                )
            )


            qtd = min(

                len(
                    pois_faixa
                ),

                CAP_POR_FAIXA
            )


            qtd_por_faixa[
                nome_faixa
            ] = len(
                pois_faixa
            )


            total_ponderado += (
                qtd
                * peso
            )


            for poi in pois_faixa:

                tipos_encontrados.add(
                    poi.get(
                        "tipo",
                        "?"
                    )
                )


        normalizador = (
            NORMALIZADORES.get(
                categoria,
                3
            )
        )


        score = max(

            0.0,

            min(

                1.0,

                round(
                    total_ponderado
                    / normalizador,
                    3
                )
            )
        )


        scores_categoria[
            categoria
        ] = score


        detalhes_score[
            categoria
        ] = {

            "qtd_0_400":
            qtd_por_faixa.get(
                "0_400",
                0
            ),

            "qtd_401_800":
            qtd_por_faixa.get(
                "401_800",
                0
            ),

            "qtd_801_1500":
            qtd_por_faixa.get(
                "801_1500",
                0
            ),

            "tipos_encontrados":
            sorted(
                tipos_encontrados
            ),

            "poi_efetivo":
            round(
                total_ponderado,
                3
            ),

            "normalizador":
            normalizador,

            "score":
            score,
        }


    # ================================================================
    # SCORE FINAL
    # ================================================================

    if not scores_categoria:

        score_final = SCORE_NEUTRO

    else:

        score_final = round(

            max(

                0.0,

                min(

                    1.0,

                    sum(
                        scores_categoria.values()
                    )
                    / len(
                        scores_categoria
                    )
                )
            ),

            3
        )


    return {

        "score_final":
        score_final,

        "scores_categoria":
        scores_categoria,

        "detalhes_score":
        detalhes_score,

        "transporte_status":
        transporte.get(
            "status",
            "dados_insuficientes"
        ),

        "transporte_dados_insuficientes":
        transporte_insuficiente,
    }


# =============================================================================
# CLASSIFICACAO
# =============================================================================

def _classificar_infraestrutura(
    score: float
) -> str:

    if score < 0.30:

        return "insuficiente"

    elif score < 0.50:

        return "basica"

    elif score < 0.70:

        return "moderada"

    elif score < 0.85:

        return "boa"

    return "excelente"


MAPA_PERFIL_INFRAESTRUTURA = {

    "excelente":
    "infraestrutura_muito_alta",

    "boa":
    "infraestrutura_alta",

    "moderada":
    "infraestrutura_moderada",

    "basica":
    "infraestrutura_basica",

    "insuficiente":
    "infraestrutura_insuficiente",
}


def _calcular_impacto(
    score_final: float
) -> str:

    if score_final >= 0.85:

        return "muito_positivo"

    elif score_final >= 0.70:

        return "positivo"

    elif score_final >= 0.50:

        return "neutro"

    elif score_final >= 0.30:

        return "negativo"

    return "muito_negativo"


# =============================================================================
# LLM
# =============================================================================

def _analisar_infra_llm(
    pois_por_faixa: dict,
    scores: dict,
    endereco: str,
    transporte: dict
) -> dict:

    import re


    resumo_pois = ""


    for (
        _,
        _,
        nome_faixa
    ) in FAIXAS:


        cats = (
            pois_por_faixa.get(
                nome_faixa,
                {}
            )
        )


        total = sum(
            len(v)
            for v
            in cats.values()
        )


        resumo_pois += (

            f"\n  "
            f"{nome_faixa} "
            f"({total} POIs):"
        )


        for (
            cat,
            pois
        ) in cats.items():


            if (
                cat
                == "transporte"
            ):
                continue


            if pois:


                nomes = [

                    p["nome"]

                    for p
                    in pois[:3]
                ]


                resumo_pois += (

                    f"\n    "
                    f"{cat} "
                    f"({len(pois)}): "
                    f"{', '.join(nomes)}"
                )


    status_transp = (
        transporte.get(
            "status",
            "dados_insuficientes"
        )
    )


    paradas = transporte.get(
        "paradas",
        []
    )


    resumo_transporte = (

        f"Status: "
        f"{status_transp}, "
        f"{len(paradas)} "
        f"paradas encontradas"
    )


    scores_categoria = (
        scores.get(
            "scores_categoria",
            {}
        )
    )


    score_final = (
        scores.get(
            "score_final",
            SCORE_NEUTRO
        )
    )


    classificacao = (
        _classificar_infraestrutura(
            score_final
        )
    )


    scores_json = json.dumps(

        scores_categoria,

        ensure_ascii=False,

        indent=2
    )


    prompt = f"""
Avaliador imobiliario.

Interprete os resultados de infraestrutura abaixo.

NAO recalcule valores.
Apenas interprete.

Endereco:
{endereco}

POIs:
{resumo_pois}

Transporte:
{resumo_transporte}

Scores:
{scores_json}

Score final:
{score_final}

Classificacao:
{classificacao}

Retorne JSON:

{{
  "pontos_fortes": [],
  "pontos_de_atencao": [],
  "descricao_infraestrutura": "",
  "conclusao": ""
}}
"""


    # ----------------------------------------------------------------
    # GEMINI
    # ----------------------------------------------------------------

    import time as t_infra


    t0 = t_infra.time()


    try:


        from google import genai

        from google.genai import types


        google_key = (

            os.getenv(
                "GOOGLE_API_KEY_2",
                ""
            )

            or os.getenv(
                "GOOGLE_API_KEY",
                ""
            )
        )


        if google_key:


            client = genai.Client(
                api_key=google_key
            )


            response = (
                client.models.generate_content(

                    model=
                    "gemini-3.5-flash-lite",

                    contents=[

                        types.Content(

                            role="user",

                            parts=[

                                types.Part.from_text(
                                    text=prompt
                                )
                            ]
                        )
                    ],

                    config=
                    types.GenerateContentConfig(
                        temperature=0
                    ),
                )
            )


            conteudo = (
                response.text
                or ""
            )


            m = re.search(
                r'\{[\s\S]+\}',
                conteudo
            )


            if m:


                logger.info(

                    f"LLM interpretou "
                    f"(Gemini) em "
                    f"{t_infra.time()-t0:.1f}s"
                )


                return json.loads(
                    m.group(0)
                )


    except Exception as e:


        logger.warning(
            f"Gemini falhou: {e}"
        )


    # ----------------------------------------------------------------
    # GROQ
    # ----------------------------------------------------------------

    t0 = t_infra.time()


    try:


        from groq import Groq


        groq_key = os.getenv(
            "GROQ_API_KEY",
            ""
        )


        if groq_key:


            client_groq = Groq(
                api_key=groq_key
            )


            response = (
                client_groq
                .chat
                .completions
                .create(

                    model=
                    "openai/gpt-oss-20b",

                    messages=[{
                        "role":
                        "user",

                        "content":
                        prompt
                    }],

                    temperature=0,

                    max_completion_tokens=600,
                )
            )


            conteudo = (
                response
                .choices[0]
                .message
                .content
                or ""
            )


            m = re.search(
                r'\{[\s\S]+\}',
                conteudo
            )


            if m:


                logger.info(

                    f"LLM interpretou "
                    f"(Groq) em "
                    f"{t_infra.time()-t0:.1f}s"
                )


                return json.loads(
                    m.group(0)
                )


    except Exception as e:


        logger.warning(
            f"Groq falhou: {e}"
        )


    # ----------------------------------------------------------------
    # NVIDIA
    # ----------------------------------------------------------------

    t0 = t_infra.time()


    try:


        from openai import OpenAI

        import httpx


        nvidia_key = os.getenv(
            "NVIDIA_API_KEY",
            ""
        )


        if nvidia_key:


            client_nv = OpenAI(

                base_url=
                "https://integrate.api.nvidia.com/v1",

                api_key=
                nvidia_key,

                timeout=
                httpx.Timeout(
                    30.0,
                    connect=10.0
                ),

                max_retries=0,
            )


            response = (
                client_nv
                .chat
                .completions
                .create(

                    model=
                    "meta/llama-3.1-8b-instruct",

                    messages=[{
                        "role":
                        "user",

                        "content":
                        prompt
                    }],

                    max_tokens=600,

                    temperature=0,
                )
            )


            conteudo = (

                response
                .choices[0]
                .message
                .content

                or ""
            )


            m = re.search(
                r'\{[\s\S]+\}',
                conteudo
            )


            if m:


                logger.info(

                    f"LLM interpretou "
                    f"(NVIDIA) em "
                    f"{t_infra.time()-t0:.1f}s"
                )


                return json.loads(
                    m.group(0)
                )


    except Exception as e:


        logger.warning(
            f"NVIDIA falhou: {e}"
        )


    # ----------------------------------------------------------------
    # FALLBACK DETERMINISTICO
    # ----------------------------------------------------------------

    pontos_fortes = [

        cat

        for (
            cat,
            sc
        )
        in scores_categoria.items()

        if sc >= 0.70
    ]


    pontos_atencao = [

        cat

        for (
            cat,
            sc
        )
        in scores_categoria.items()

        if sc < 0.50
    ]


    return {

        "pontos_fortes":
        pontos_fortes[:4],

        "pontos_de_atencao":
        pontos_atencao[:4],

        "descricao_infraestrutura":
        (
            f"Infraestrutura "
            f"{classificacao} "
            f"com score "
            f"{score_final:.2f}."
        ),

        "conclusao":
        (
            f"Regiao classificada "
            f"como {classificacao}."
        ),
    }


# =============================================================================
# FUNCAO PUBLICA
# =============================================================================

def avaliar_infraestrutura(
    imovel_alvo: Optional[dict] = None,
    arquivo_entrada: str = "imoveis_comparaveis_ag2.json",
    arquivo_saida: str = "infra_avaliada_ag4.json",
) -> dict:


    logger.info(
        "=" * 55
    )


    logger.info(
        "AGENTE 4: "
        "AVALIADOR DE INFRAESTRUTURA"
    )


    logger.info(
        "=" * 55
    )


    # ----------------------------------------------------------------
    # CARREGA IMOVEL
    # ----------------------------------------------------------------

    if imovel_alvo is None:


        caminho = os.path.join(
            DATA_DIR,
            arquivo_entrada
        )


        if not os.path.exists(
            caminho
        ):


            logger.error(
                f"Arquivo nao encontrado: "
                f"{caminho}"
            )


            return {}


        with open(
            caminho,
            "r",
            encoding="utf-8"
        ) as f:


            dados = json.load(
                f
            )


        imovel_alvo = dados.get(
            "imovel_alvo",
            {}
        )


        logger.info(

            f"Imovel alvo: "

            f"{imovel_alvo.get('rua','?')}, "

            f"{imovel_alvo.get('numero','')}"
        )


    rua = (

        imovel_alvo.get(
            "rua",
            ""
        )

        or imovel_alvo.get(
            "street",
            ""
        )
    )


    numero = imovel_alvo.get(
        "numero",
        ""
    )


    bairro = (

        imovel_alvo.get(
            "bairro",
            ""
        )

        or imovel_alvo.get(
            "neighborhood",
            ""
        )
    )


    cidade = (

        imovel_alvo.get(
            "cidade",
            ""
        )

        or imovel_alvo.get(
            "city",
            ""
        )
    )


    estado = (

        imovel_alvo.get(
            "estado",
            ""
        )

        or imovel_alvo.get(
            "state",
            ""
        )
    )


    endereco = (

        f"{rua}, "
        f"{numero}, "
        f"{bairro}, "
        f"{cidade}, "
        f"{estado}, "
        f"Brasil"
    ).strip(
        ", "
    )


    # ----------------------------------------------------------------
    # REUTILIZA COORDENADAS AGENTE 2
    # ----------------------------------------------------------------

    lat = None

    lon = None


    caminho_zona = os.path.join(

        DATA_DIR,

        "zona_homogenea_ag2.json"
    )


    if os.path.exists(
        caminho_zona
    ):


        try:


            with open(

                caminho_zona,

                "r",

                encoding="utf-8"

            ) as f:


                zona_data = json.load(
                    f
                )


            coords = zona_data.get(
                "coordenadas_alvo",
                {}
            )


            if (
                coords.get("lat")
                and coords.get("lon")
            ):


                lat = coords[
                    "lat"
                ]


                lon = coords[
                    "lon"
                ]


                logger.info(

                    f"[Ag4][Geo] "
                    f"reutilizando coordenadas "

                    f"| lat={lat:.6f} "

                    f"| lon={lon:.6f}"
                )


        except Exception:
            pass


    # ----------------------------------------------------------------
    # GEOCODIFICACAO FALLBACK
    # ----------------------------------------------------------------

    if not lat:


        logger.info(

            f"Geocodificando: "
            f"{endereco}"
        )


        lat, lon = (
            _geocodificar(
                endereco
            )
        )


        if not lat:


            logger.error(

                "Nao foi possivel "
                "geocodificar "
                "o endereco"
            )


            return {}


    # ----------------------------------------------------------------
    # GEOAPIFY
    # ----------------------------------------------------------------

    logger.info(

        "[Ag4] "
        "Fonte principal=Geoapify "
        "| fallback=Google Places"
    )


    pois_por_faixa, diagnostico_busca, status_categorias = (

        _buscar_pois_classificados(

            lat,

            lon
        )
    )


    # ----------------------------------------------------------------
    # TRANSPORTE
    # ----------------------------------------------------------------

    transporte = (
        _buscar_transporte(
            lat,
            lon
        )
    )


    diagnostico_busca[
        "geoapify_chamadas"
    ] += 1


    diagnostico_busca[
        "geoapify_creditos_maximos"
    ] += 1


    if transporte.get(
        "fallback_google"
    ):


        diagnostico_busca[
            "google_fallback_chamadas"
        ] += 1


    # ----------------------------------------------------------------
    # IMOBILIARIA
    # ----------------------------------------------------------------

    imobiliaria_proxima = (

        _buscar_imobiliaria_proxima(

            lat,

            lon
        )
    )


    diagnostico_busca[
        "geoapify_chamadas"
    ] += 1


    diagnostico_busca[
        "geoapify_creditos_maximos"
    ] += 1


    if imobiliaria_proxima.get(
        "fallback_google"
    ):


        diagnostico_busca[
            "google_fallback_chamadas"
        ] += 1


    # ----------------------------------------------------------------
    # SCORE
    # ----------------------------------------------------------------

    scores = _calcular_score(

        pois_por_faixa,

        transporte,

        status_categorias
    )


    total_pois = sum(

        len(pois)

        for faixa_data
        in pois_por_faixa.values()

        for pois
        in faixa_data.values()
    )


    logger.info(

        f"[Ag4] POIs total="
        f"{total_pois} "

        f"| score_final="
        f"{scores['score_final']:.3f} "

        f"| metodo=deterministico"
    )


    logger.info(
        "Scores por categoria:"
    )


    for (
        cat,
        score
    ) in scores.get(
        "scores_categoria",
        {}
    ).items():


        logger.info(

            f"  {cat:20}: "
            f"{score:.3f}"
        )


    logger.info(

        f"[Ag4][APIs] "

        f"Geoapify chamadas="
        f"{diagnostico_busca.get('geoapify_chamadas',0)} "

        f"| creditos_max="
        f"{diagnostico_busca.get('geoapify_creditos_maximos',0)} "

        f"| Google fallback chamadas="
        f"{diagnostico_busca.get('google_fallback_chamadas',0)}"
    )


    # ----------------------------------------------------------------
    # LLM
    # ----------------------------------------------------------------

    analise = _analisar_infra_llm(

        pois_por_faixa,

        scores,

        endereco,

        transporte
    )


    # ----------------------------------------------------------------
    # CLASSIFICACAO
    # ----------------------------------------------------------------

    classificacao = (

        _classificar_infraestrutura(

            scores.get(
                "score_final",
                SCORE_NEUTRO
            )
        )
    )


    perfil_infraestrutura = (

        MAPA_PERFIL_INFRAESTRUTURA.get(

            classificacao,

            "infraestrutura_moderada"
        )
    )


    impacto_infraestrutura = (

        _calcular_impacto(

            scores.get(
                "score_final",
                SCORE_NEUTRO
            )
        )
    )


    # ----------------------------------------------------------------
    # SAIDA
    # ----------------------------------------------------------------

    saida = {

        "imovel_alvo":
        imovel_alvo,

        "coordenadas": {
            "lat": lat,
            "lon": lon
        },

        "fonte_infraestrutura":
        (
            "Geoapify (principal) "
            "+ Google Places "
            "(fallback)"
        ),

        "raio_maximo_metros":
        RAIO_MAX,

        "total_pois_validos":
        total_pois,

        "faixas_metros": {

            "0_400":
            "0-400m",

            "401_800":
            "401-800m",

            "801_1500":
            "801-1500m",
        },

        "tolerancia_pct":
        TOLERANCIA * 100,

        "pois_por_faixa":
        pois_por_faixa,

        "transporte":
        transporte,

        "imobiliaria_proxima":
        imobiliaria_proxima,

        "diagnostico_busca": {

            **diagnostico_busca,

            "status_categorias":
            status_categorias,

            "limite_por_consulta_geoapify":
            GEOAPIFY_LIMIT,

            "maximo_planejado_creditos_geoapify":
            8,
        },

        "scores": {

            "score_final":
            scores[
                "score_final"
            ],

            "classificacao_infraestrutura":
            classificacao,

            "perfil_infraestrutura":
            perfil_infraestrutura,

            "impacto_infraestrutura":
            impacto_infraestrutura,

            "scores_categoria":
            scores.get(
                "scores_categoria",
                {}
            ),

            "detalhes_score":
            scores.get(
                "detalhes_score",
                {}
            ),
        },

        "interpretacao_llm":
        analise,
    }


    # ----------------------------------------------------------------
    # SALVA
    # ----------------------------------------------------------------

    caminho_saida = os.path.join(

        DATA_DIR,

        arquivo_saida
    )


    with open(

        caminho_saida,

        "w",

        encoding="utf-8"

    ) as f:


        json.dump(

            saida,

            f,

            ensure_ascii=False,

            indent=2
        )


    logger.info(

        f"Salvo em: "
        f"{caminho_saida}"
    )


    logger.info(
        "=" * 55
    )


    return saida