"""
Agente 1 - Coletor de Dados Imobiliarios
==========================================

COMO FUNCIONA:
==============

Usa o Apify (ocrad) como fonte unica + requests.get pra publishedAt.
Funciona pra qualquer bairro, cidade e estado do Brasil.
O resultado final e um JSON ordenado por proximidade ao imovel alvo.

FONTE: Apify (ocrad~brazil-real-estate-scraper)
─────────────────────────────────────────────────
  Portais: ImovelWeb, VivaReal, LugarCerto, OLX, MercadoLivre
  Input:   URLs de listagem montadas automaticamente com bairro/cidade/estado
  Token:   APIFY_TOKEN_2 (conta separada, $5/mes gratis)
  Como:    o actor abre cada URL, executa JS, e extrai os anuncios
  Retorna: ~15-50 imoveis (depende do bairro)
  Limite:  20 casas / 10 terrenos / 30 apartamentos por URL (maxItems por URL)
  NOTA:    ZAP removido (95% duplicata do VivaReal, mesmo grupo OLX Brasil)

ENRIQUECIMENTO: publishedAt via requests.get + regex
─────────────────────────────────────────────────────
  O ocrad nao retorna publishedAt. Mas o VivaReal coloca
  a data de criacao no HTML estatico como JSON embutido:
    "createdAt":"2026-04-08T00:01:45.354Z"

  OLX: bloqueia requests.get com Cloudflare (403).
  A data aparece na listagem como "16/12/2024, 23:52" (com ano),
  mas na pagina individual so mostra "16/12 às 23:52" (sem ano).
  O ocrad nao extrai esse campo. Resultado: OLX fica sem publishedAt.

  Solucao (gratis, sem limite, sem LLM):
    1. requests.get(url) — pega o HTML estatico da pagina
    2. Regex extrai createdAt do JSON embutido (VivaReal: 100% sucesso)
    3. OLX/ImovelWeb/LugarCerto/MercadoLivre: sem publishedAt (bloqueio)
    4. ~1s por imovel (pausa entre requests)

FLUXO COMPLETO:
───────────────
  1. ocrad coleta brutos dos 5 portais (com JS)
  2. Normaliza (preco, quartos, area, rua, bairro, cidade, estado, iptu)
  3. Extrai publishedAt via requests.get + regex (VivaReal/ZAP)
  4. Remove duplicatas por URL
  5. Remove leiloes e imoveis sem preco/cidade
  6. Filtra por bairro (escopo)
  7. Normaliza bairros (acentos, prefixos)
  8. Ordena: mesma rua -> mesmo bairro -> cidade
  9. Salva em imoveis_coletados.json

SCHEMA DE SAIDA:
────────────────
  id, title, price, priceFormatted, condominiumFee, iptu,
  transactionType, propertyType, propertySubType,
  area, bedrooms, bathrooms, parkingSpaces,
  amenities, complexAmenities,
  street, neighborhood, city, state,
  images, imageCount, url,
  publishedAt, pricePerSqm, source, scrapedAt, data_coleta

ARQUIVOS GERADOS:
─────────────────
  data/imoveis_brutos_ocrad.json -> brutos do ocrad (schema original)
  data/imoveis_coletados.json    -> resultado final combinado e filtrado
"""

import os
import re
import json
import time
import logging
from collections import Counter
from datetime import datetime
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURACOES
# =============================================================================

# Token Apify — conta do ocrad ($5/mes gratis)
APIFY_TOKEN = os.getenv("APIFY_TOKEN_2", "") or os.getenv("APIFY_TOKEN", "")

APIFY_ACTOR_OCRAD = "ocrad~brazil-real-estate-scraper"
APIFY_BASE_URL = "https://api.apify.com/v2"

# URLs de listagem por portal para o ocrad/brazil-real-estate-scraper.
# Cada portal recebe URLs com bairro/cidade/estado.
# O actor abre cada URL, executa JS, e extrai os anuncios.
# Limite: 20 casas / 10 terrenos / 30 apartamentos por URL (maxItems por URL).
#
# OBSERVACOES:
#   - VivaReal e LugarCerto: funcionam corretamente (publishedAt + description extraidos).
#   - OLX: removida — Cloudflare bloqueia requests.get (403), publishedAt nao disponivel.
#   - ImovelWeb: comentada — URL funciona no navegador mas ocrad nao retorna resultados.
#   - MercadoLivre: comentada — mesmo problema do ImovelWeb.
#   - ZAP Imoveis: removido pois 95% dos anuncios sao duplicatas do VivaReal
#     (mesmo grupo OLX Brasil, mesmo posting_id).
#   - VivaReal e LugarCerto: funcionam corretamente (publishedAt + description extraidos).
#   - OLX: removida — Cloudflare bloqueia requests.get (403), publishedAt nao disponivel.
#   - ImovelWeb: comentada — URL funciona no navegador mas ocrad nao retorna resultados.
#   - MercadoLivre: comentada — mesmo problema do ImovelWeb.
URLS_LISTAGEM_PORTAIS = {
    # "imovelweb":    "https://www.imovelweb.com.br/{tipo_slug}-venda-{bairro_slug}-{cidade_slug}.html",
    "vivareal":       "https://www.vivareal.com.br/venda/{estado_nome}/{cidade_slug}/bairros/{bairro_slug}/{tipo_slug}/",
    "lugarcerto":     "https://www.lugarcerto.com.br/busca/compra-e-venda/{estado_sigla}/{cidade_slug}/{bairro_slug}/{tipo_slug}",
    # "olx":          "https://www.olx.com.br/imoveis/venda/estado-{estado_sigla}?q={tipo_slug}+a+venda+{bairro_slug}+{cidade_slug}+{estado_nome}",
    # "mercadolivre": "https://imoveis.mercadolivre.com.br/{tipo_slug}/venda/{estado_nome}/{cidade_slug}/{bairro_slug}/",
}

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
os.makedirs(DATA_DIR, exist_ok=True)

# Palavras que indicam leilao - precos artificialmente baixos distorcem a analise
AUCTION_KEYWORDS = [
    "leilao", "leilão", "hasta publica", "hasta pública",
    "judicial", "extrajudicial", "arrematacao", "arrematação",
    "lance inicial", "lance minimo", "lance mínimo",
    "caixa economica", "caixa econômica", "banco imoveis",
]


# =============================================================================
# BLOCO 1 - UTILITARIOS COMUNS
# =============================================================================

def _slugify(texto: str) -> str:
    """
    Converte texto para slug no formato esperado pelo Apify.
    Ex: "Belo Horizonte" -> "belo-horizonte", "São Paulo" -> "sao-paulo"
    """
    texto = texto.lower()
    for src, dst in [("aáàãâä","a"),("eéèêë","e"),("iíìîï","i"),("oóòõôö","o"),("uúùûü","u"),("cç","c")]:
        for c in src[1:]:
            texto = texto.replace(c, dst[0])
    return re.sub(r"[^a-z0-9]+", "-", texto).strip("-")


def _eh_leilao(imovel: dict) -> bool:
    """
    Verifica se o anuncio e de leilao pelo titulo e tipo.
    Leiloes sao removidos porque seus precos sao artificialmente baixos
    e distorceriam a estimativa de valor justo.
    """
    texto = " ".join([str(imovel.get("title","")), str(imovel.get("propertyType",""))]).lower()
    return any(kw in texto for kw in AUCTION_KEYWORDS)


def _campos_ok(imovel: dict) -> bool:
    """Descarta imoveis sem preco ou sem localizacao minima (campos obrigatorios)."""
    return bool(imovel.get("price")) and bool(imovel.get("city") or imovel.get("neighborhood"))


def _remover_duplicatas_url(imoveis: list[dict]) -> list[dict]:
    """
    Remove duplicatas pela URL.
    Mais confiavel que hash quando combinamos duas fontes diferentes,
    pois o mesmo imovel pode ter area/preco ligeiramente diferente entre portais.
    """
    vistas: set[str] = set()
    unicos = []
    for i in imoveis:
        url = i.get("url", "")
        if url and url not in vistas:
            vistas.add(url)
            unicos.append(i)
    return unicos


def salvar_dados(imoveis: list[dict], nome_arquivo: str) -> str:
    """Salva lista de imoveis em JSON na pasta /data com encoding UTF-8."""
    caminho = os.path.join(DATA_DIR, nome_arquivo)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(imoveis, f, ensure_ascii=False, indent=2)
    logger.info(f"Dados salvos em: {caminho} ({len(imoveis)} registros)")
    return caminho


def carregar_dados(nome_arquivo: str) -> list[dict]:
    """Carrega dados de uma coleta anterior (modo cache — economiza requests)."""
    caminho = os.path.join(DATA_DIR, nome_arquivo)
    if not os.path.exists(caminho):
        return []
    with open(caminho, "r", encoding="utf-8") as f:
        return json.load(f)


# =============================================================================
# BLOCO 1B - EXTRACAO DE publishedAt E DESCRICAO
# =============================================================================

def _extrair_dados_pagina(url: str) -> dict:
    """
    Extrai dados adicionais da pagina individual do anuncio via requests.get.
    Faz 1 unico request e extrai tudo que conseguir:
      - publishedAt (createdAt do JSON embutido)
      - description (descricao completa do anuncio)
      - bathrooms, parkingSpaces, suites (campos estruturados)
      - street, streetNumber (endereco completo)

    Funciona para:
      - VivaReal: 100% (dados no HTML estatico)
      - LugarCerto: parcial (dt_insercao + meta description)

    NAO funciona para:
      - OLX: Cloudflare bloqueia requests.get (403)
      - ImovelWeb/MercadoLivre: sem dados estruturados no HTML
    """
    resultado = {}
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    try:
        r = requests.get(url, headers=headers, timeout=30)
        if r.status_code != 200:
            return resultado
        html = r.text

        # ── publishedAt (createdAt no JSON embutido)
        m = re.search(r'createdAt[\\"\s:]+(\d{4}-\d{2}-\d{2}T[\d:.]+Z)', html)
        if m:
            resultado["publishedAt"] = m.group(1)
        else:
            # LugarCerto: "dt_insercao":"2023-07-01T23:59:00Z"
            m = re.search(r'dt_insercao[\\"\s:]+(\d{4}-\d{2}-\d{2}T[\d:.]+Z)', html)
            if m:
                resultado["publishedAt"] = m.group(1)

        # ── description (segunda ocorrencia = descricao completa do anuncio)
        descriptions = re.findall(r'"description"\s*:\s*"([^"]{50,})"', html)
        if len(descriptions) >= 2:
            desc = descriptions[1]
            # Decodifica unicode escapes (\u00e9 -> é, \n -> newline)
            try:
                desc = desc.encode("utf-8").decode("unicode_escape").encode("latin-1").decode("utf-8")
            except Exception:
                try:
                    desc = desc.encode("utf-8").decode("unicode_escape")
                except Exception:
                    pass
            # Limpa quebras de linha extras
            desc = re.sub(r"\\n", "\n", desc)
            desc = re.sub(r"\n{3,}", "\n\n", desc).strip()
            resultado["description"] = desc
        if not resultado.get("description"):
            # LugarCerto/outros: meta description (resumo com quartos, area, vagas)
            m = re.search(r'<meta[^>]*name="description"[^>]*content="([^"]+)"', html)
            if m and len(m.group(1)) > 50:
                resultado["description"] = m.group(1)

        # ── Campos estruturados do JSON embutido
        m = re.search(r'"bathrooms"\s*:\s*(\d+)', html)
        if m:
            resultado["bathrooms"] = int(m.group(1))

        m = re.search(r'"parkingSpaces"\s*:\s*(\d+)', html)
        if m:
            resultado["parkingSpaces"] = int(m.group(1))

        m = re.search(r'"suites"\s*:\s*(\d+)', html)
        if m:
            resultado["suites"] = int(m.group(1))

        # ── Endereco completo
        m = re.search(r'"street"\s*:\s*"([^"]+)"', html)
        if m:
            resultado["street"] = m.group(1)

        m = re.search(r'"streetNumber"\s*:\s*"([^"]+)"', html)
        if m:
            resultado["streetNumber"] = m.group(1)

    except Exception:
        pass

    return resultado


# =============================================================================
# BLOCO 2 - COLETA VIA APIFY (ocrad/brazil-real-estate-scraper)
# =============================================================================

def _montar_urls_listagem(tipo_imovel: str, bairro: str, cidade: str, estado: str = "MG") -> list[tuple]:
    """
    Monta URLs de listagem para cada portal suportado pelo ocrad.
    Funciona pra qualquer bairro, cidade e estado do Brasil.

    Retorna lista de tuplas (url, max_items) com limites por tipo:
      - casa/apartamento: 20 itens por URL
      - terreno:          10 itens por URL
      - apartamento:      30 itens por URL
    """
    # Mapeamento estado sigla -> nome completo (pra URL do VivaReal)
    ESTADOS_NOME = {
        "MG": "minas-gerais", "SP": "sao-paulo", "RJ": "rio-de-janeiro",
        "PR": "parana", "RS": "rio-grande-do-sul", "BA": "bahia",
        "SC": "santa-catarina", "GO": "goias", "DF": "distrito-federal",
        "PE": "pernambuco", "CE": "ceara", "ES": "espirito-santo",
        "PA": "para", "MA": "maranhao", "AM": "amazonas",
        "MS": "mato-grosso-do-sul", "MT": "mato-grosso",
        "AL": "alagoas", "SE": "sergipe", "PB": "paraiba",
        "RN": "rio-grande-do-norte", "PI": "piaui", "TO": "tocantins",
        "RO": "rondonia", "AC": "acre", "AP": "amapa", "RR": "roraima",
    }

    # Mapeamento de tipo para slugs de URL por portal
    TIPOS_POR_PORTAL = {
        "house": {
            "imovelweb":     ["casas", "terrenos"],
            "vivareal":      ["casa_residencial", "lote-terreno_residencial"],
            "lugarcerto":    ["casa", "terreno"],
            "olx":           ["casa", "terreno"],
            "mercadolivre":  ["casas", "terrenos"],
        },
        "apartment": {
            "imovelweb":     ["apartamentos"],
            "vivareal":      ["apartamento_residencial"],
            "lugarcerto":    ["apartamento"],
            "olx":           ["apartamento"],
            "mercadolivre":  ["apartamentos"],
        },
        "commercial": {
            "imovelweb":     ["comercial"],
            "vivareal":      ["comercial"],
            "lugarcerto":    ["comercial"],
            "olx":           ["comercial"],
            "mercadolivre":  ["comercial"],
        },
    }

    bairro_slug = _slugify(bairro)
    cidade_slug = _slugify(cidade)
    estado_sigla = estado.upper().strip()
    estado_nome = ESTADOS_NOME.get(estado_sigla, _slugify(estado))

    tipos_portais = TIPOS_POR_PORTAL.get(tipo_imovel, TIPOS_POR_PORTAL["house"])

    # Slugs que indicam terreno (para aplicar limite menor)
    SLUGS_TERRENO = {"terreno", "terrenos", "lote-terreno_residencial", "lote", "lotes"}

    # Limite por tipo de URL
    # apartment usa 30, terreno usa 10, casa usa 20
    def _limite(tipo_slug: str) -> int:
        if tipo_imovel == "apartment":
            return 30
        if tipo_slug in SLUGS_TERRENO:
            return 10
        return 20

    urls = []
    for portal, template in URLS_LISTAGEM_PORTAIS.items():
        slugs = tipos_portais.get(portal, ["imoveis"])
        for tipo_slug in slugs:
            try:
                url = template.format(
                    tipo_slug=tipo_slug,
                    bairro_slug=bairro_slug,
                    cidade_slug=cidade_slug,
                    estado_nome=estado_nome,
                    estado_sigla=estado_sigla.lower(),
                )
                urls.append((url, _limite(tipo_slug)))
            except Exception:
                pass

    return urls


def _normalizar_ocrad(imovel: dict) -> dict:
    """
    Normaliza o schema do ocrad para o schema padrao.
    Extrai dados de 3 fontes (em ordem de prioridade):
      1. Campos diretos do ocrad (price, features, location)
      2. URL do anuncio (quartos, area, tipo, bairro, cidade)
      3. URL de origem/from_url (bairro, cidade)
    """
    url = imovel.get("url", "") or ""
    url_lower = url.lower()

    # ── PRECO (vem como "R$ 530.000Cond. não informado • IPTU R$ 122")
    price = None
    price_raw = str(imovel.get("price", "") or "")
    m = re.search(r"R\$\s*([\d.]+)", price_raw)
    if m:
        try:
            price = int(m.group(1).replace(".", ""))
        except ValueError:
            pass
    if not price and price_raw:
        m = re.search(r"(\d[\d.]{4,})", price_raw.replace(",", ""))
        if m:
            try:
                price = int(m.group(1).replace(".", ""))
            except ValueError:
                pass

    # ── FEATURES
    features = imovel.get("features") or {}
    if isinstance(features, str):
        features = {}
    raw_features = features.get("raw", []) if isinstance(features, dict) else []

    # ── AREA (features -> URL -> raw_features)
    area = None
    area_raw = features.get("area", "")
    if area_raw:
        m = re.search(r"(\d+)", str(area_raw))
        if m:
            area = int(m.group(1))
    if not area:
        m = re.search(r"-(\d+)m2", url_lower)
        if m:
            area = int(m.group(1))
    if not area and raw_features:
        for feat in raw_features:
            m = re.search(r"(\d+)\s*(?:metros|m²|m2)", str(feat).lower())
            if m:
                area = int(m.group(1))
                break

    # ── QUARTOS (features -> URL -> raw_features)
    bedrooms = features.get("bedrooms")
    if not bedrooms:
        m = re.search(r"-(\d+)-quartos?", url_lower)
        if m:
            bedrooms = int(m.group(1))
    if not bedrooms and raw_features:
        for feat in raw_features:
            m = re.search(r"(\d+)\s*quartos?", str(feat).lower())
            if m:
                bedrooms = int(m.group(1))
                break

    # ── BANHEIROS (features -> raw_features -> titulo)
    bathrooms = features.get("bathrooms")
    if not bathrooms and raw_features:
        for feat in raw_features:
            m = re.search(r"(\d+)\s*(?:banheiros?|ban\.)", str(feat).lower())
            if m:
                bathrooms = int(m.group(1))
                break
    if not bathrooms:
        title = imovel.get("title", "") or ""
        m = re.search(r"(\d+)\s*banheiros?", title.lower())
        if m:
            bathrooms = int(m.group(1))

    # ── VAGAS (features -> raw_features -> titulo)
    parking = features.get("parking") or features.get("parkingSpaces")
    if not parking and raw_features:
        for feat in raw_features:
            m = re.search(r"(\d+)\s*(?:vagas?|garagem)", str(feat).lower())
            if m:
                parking = int(m.group(1))
                break
    if not parking:
        title = imovel.get("title", "") or ""
        m = re.search(r"(\d+)\s*(?:vagas?|garagem)", title.lower())
        if m:
            parking = int(m.group(1))

    # ── TIPO (da URL)
    property_type = None
    if re.search(r"/(?:venda-)?(?:casa|sobrado)-|/casas-|/sobrados-", url_lower):
        property_type = "Casas"
    elif re.search(r"/(?:venda-)?apartamento-|/apartamentos-", url_lower):
        property_type = "Apartamentos"
    elif re.search(r"/(?:venda-)?terreno|/terrenos|/lote", url_lower):
        property_type = "Terrenos"

    # ── LOCALIZACAO (location -> from_url)
    location = imovel.get("location", "") or ""
    neighborhood = None
    city = None
    state = None
    street = None
    parts = [p.strip() for p in location.replace(" - ", ", ").split(",")]
    if len(parts) >= 3:
        neighborhood = parts[0]
        city = parts[1]
        state = parts[2]
    elif len(parts) == 2:
        if len(parts[1]) == 2:
            city = parts[0]
            state = parts[1]
        else:
            city = parts[0]
            neighborhood = parts[1]
    elif len(parts) == 1 and parts[0]:
        if any(parts[0].startswith(p) for p in ["Rua ", "Avenida ", "Av. ", "Alameda ", "Travessa "]):
            street = parts[0]
        else:
            neighborhood = parts[0]

    from_url = imovel.get("from_url", "") or ""
    # Extrai bairro/cidade do from_url genericamente
    if not neighborhood or not city:
        from_lower = from_url.lower()
        # ImovelWeb: /casas-venda-{bairro}-{cidade}.html
        m = re.search(r"/\w+-venda-([\w-]+)-([\w-]+)\.html", from_lower)
        if m:
            if not neighborhood:
                neighborhood = " ".join(w.capitalize() for w in m.group(1).split("-"))
            if not city:
                city = " ".join(w.capitalize() for w in m.group(2).split("-"))
        # VivaReal: /bairros/{bairro}/
        if not neighborhood:
            m = re.search(r"/bairros/([\w-]+)/", from_lower)
            if m:
                neighborhood = " ".join(w.capitalize() for w in m.group(1).split("-"))
        # VivaReal: /venda/{estado-nome}/{cidade}/bairros/{bairro}/
        if not city:
            m = re.search(r"/venda/([\w-]+)/([\w-]+)/bairros/", from_lower)
            if m:
                estado_nome_url = m.group(1)
                city = " ".join(w.capitalize() for w in m.group(2).split("-"))
                # Converte nome do estado pra sigla
                estados_reverso = {v: k for k, v in {
                    "MG": "minas-gerais", "SP": "sao-paulo", "RJ": "rio-de-janeiro",
                    "PR": "parana", "RS": "rio-grande-do-sul", "BA": "bahia",
                    "SC": "santa-catarina", "GO": "goias", "DF": "distrito-federal",
                    "PE": "pernambuco", "CE": "ceara", "ES": "espirito-santo",
                    "MS": "mato-grosso-do-sul", "MT": "mato-grosso",
                    "AL": "alagoas", "SE": "sergipe", "PB": "paraiba",
                    "RN": "rio-grande-do-norte", "PI": "piaui", "TO": "tocantins",
                }.items()}
                state = estados_reverso.get(estado_nome_url, estado_nome_url.upper()[:2])
        # ZAP: {estado_sigla}+{cidade}++{bairro}
        if not city:
            m = re.search(r"/(\w{2})\+([\w-]+)\+\+([\w-]+)", from_lower)
            if m:
                state = m.group(1).upper()
                city = " ".join(w.capitalize() for w in m.group(2).split("-"))
                if not neighborhood:
                    neighborhood = " ".join(w.capitalize() for w in m.group(3).split("-"))

    if state is None:
        # Extrai estado da URL (VivaReal: /minas-gerais/, /sao-paulo/, etc.)
        estados_url = {
            "minas-gerais": "MG", "sao-paulo": "SP", "rio-de-janeiro": "RJ",
            "parana": "PR", "rio-grande-do-sul": "RS", "bahia": "BA",
            "santa-catarina": "SC", "goias": "GO", "distrito-federal": "DF",
            "pernambuco": "PE", "ceara": "CE", "espirito-santo": "ES",
        }
        from_lower = (from_url or url).lower()
        for slug, uf in estados_url.items():
            if slug in from_lower:
                state = uf
                break
        # Fallback: ZAP usa sigla (mg+, sp+, rj+)
        if not state:
            m = re.search(r"/(mg|sp|rj|pr|rs|ba|sc|go|df|pe|ce|es)\+", from_lower)
            if m:
                state = m.group(1).upper()

    # ── IPTU e CONDOMINIO (do price_raw)
    iptu = None
    condo = None
    m = re.search(r"IPTU\s*R\$\s*([\d.]+)", price_raw)
    if m:
        try:
            iptu = int(m.group(1).replace(".", ""))
        except ValueError:
            pass
    m = re.search(r"Cond\.\s*R\$\s*([\d.]+)", price_raw)
    if m:
        try:
            condo = int(m.group(1).replace(".", ""))
        except ValueError:
            pass

    # ── SOURCE
    source_map = {
        "zap-imoveis": "ZAP Imoveis",
        "viva-real": "VivaReal",
        "imovel-web": "ImovelWeb",
        "olx": "OLX",
        "lugar-certo": "Lugar Certo",
        "mercado-livre": "Mercado Livre",
    }
    source = source_map.get(imovel.get("source_site", ""), imovel.get("source_site", "ocrad"))

    price_per_sqm = round(price / area, 2) if price and area and area > 0 else None
    price_fmt = f"R$ {price:,.0f}".replace(",", ".") if price else None

    return {
        "id":               imovel.get("posting_id") or url,
        "title":            imovel.get("title"),
        "description":      None,
        "price":            price,
        "priceFormatted":   price_fmt,
        "condominiumFee":   condo,
        "iptu":             iptu,
        "transactionType":  "sale",
        "propertyType":     property_type,
        "propertySubType":  None,
        "area":             area,
        "bedrooms":         bedrooms,
        "bathrooms":        bathrooms,
        "parkingSpaces":    parking,
        "amenities":        None,
        "complexAmenities": None,
        "street":           street,
        "neighborhood":     neighborhood,
        "city":             city,
        "state":            state,
        "images":           imovel.get("images") or [],
        "imageCount":       len(imovel.get("images") or []),
        "url":              url,
        "publishedAt":      None,
        "pricePerSqm":      price_per_sqm,
        "source":           source,
        "scrapedAt":        datetime.now().isoformat(),
        "data_coleta":      datetime.now().isoformat(),
    }


def _coletar_ocrad(
    localizacao: str,
    tipo_imovel: str,
    bairro: str,
) -> list[dict]:
    """
    Coleta imoveis via Apify (ocrad/brazil-real-estate-scraper).

    FLUXO:
      1. Monta URLs de listagem para cada portal (com bairro e cidade)
      2. Envia todas as URLs para o actor
      3. Actor raspa cada portal (com JS) e retorna os anuncios
      4. Normaliza para o schema padrao
      5. Extrai publishedAt via requests.get + regex (VivaReal/ZAP)
    """
    if not APIFY_TOKEN:
        logger.warning("APIFY_TOKEN nao configurado - pulando coleta ocrad")
        return []

    token_ocrad = APIFY_TOKEN

    partes = [p.strip() for p in localizacao.split(",")]
    cidade = partes[0]
    estado = partes[1].strip().upper() if len(partes) > 1 else "MG"

    # Monta URLs de listagem para todos os portais
    urls = _montar_urls_listagem(tipo_imovel, bairro, cidade, estado)
    if not urls:
        logger.warning("ocrad: nenhuma URL de listagem montada")
        return []

    logger.info(f"ocrad: {len(urls)} URLs de listagem para raspar")
    for url, limite in urls:
        logger.info(f"  [{limite} itens] {url}")

    # Envia para o actor
    # NOTA: Apify Proxy (useApifyProxy) testado e NAO funciona no free tier.
    # Com proxy: 0 resultados. Sem proxy: funciona normalmente.
    # A documentacao recomenda proxy pra melhores resultados, mas e recurso pago.
    #
    # Limites por tipo de URL (definidos em _montar_urls_listagem):
    #   - casa:        20 itens
    #   - terreno:     10 itens
    #   - apartamento: 30 itens
    payload = {
        "urls": [{"url": url, "maxItems": limite} for url, limite in urls],
        "max_retries_per_url": 2,
        "ignore_url_failures": True,
    }

    try:
        endpoint = f"{APIFY_BASE_URL}/acts/{APIFY_ACTOR_OCRAD}/runs?token={token_ocrad}"
        r = requests.post(endpoint, json=payload, timeout=30)
        r.raise_for_status()
        run_id = r.json().get("data", {}).get("id")
        logger.info(f"ocrad run iniciado: {run_id}")
    except Exception as e:
        logger.error(f"ocrad: erro ao iniciar run: {e}")
        return []

    # Polling ate concluir
    url_status = f"{APIFY_BASE_URL}/actor-runs/{run_id}?token={token_ocrad}"
    inicio = time.time()
    while time.time() - inicio < 600:
        try:
            status = requests.get(url_status, timeout=15).json().get("data", {}).get("status", "")
            logger.info(f"ocrad status: {status}")
            if status == "SUCCEEDED":
                break
            if status in ("FAILED", "ABORTED", "TIMED-OUT"):
                logger.error(f"ocrad run falhou: {status}")
                return []
        except Exception:
            pass
        time.sleep(10)

    # Baixa resultados
    try:
        url_items = f"{APIFY_BASE_URL}/actor-runs/{run_id}/dataset/items?token={token_ocrad}&format=json"
        brutos = requests.get(url_items, timeout=30).json()
    except Exception as e:
        logger.error(f"ocrad: erro ao baixar resultados: {e}")
        return []

    logger.info(f"ocrad: {len(brutos)} brutos coletados")
    salvar_dados(brutos, "imoveis_brutos_ocrad.json")

    # Normaliza e filtra
    normalizados = [_normalizar_ocrad(i) for i in brutos]
    filtrados = [i for i in normalizados if _campos_ok(i) and not _eh_leilao(i)]

    # Extrai dados adicionais de cada imovel (publishedAt, description, bathrooms, etc.)
    # requests.get + regex: funciona pra VivaReal (dados no HTML estatico)
    # OLX/ImovelWeb/LugarCerto/MercadoLivre: ficam sem dados extras (bloqueio ou sem dados)
    logger.info(f"Extraindo publishedAt de {len(filtrados)} imoveis...")
    pub_ok = 0
    for im in filtrados:
        url_im = im.get("url", "")
        if not url_im:
            continue
        dados_pagina = _extrair_dados_pagina(url_im)
        if dados_pagina.get("publishedAt"):
            im["publishedAt"] = dados_pagina["publishedAt"]
            pub_ok += 1
        if dados_pagina.get("description"):
            im["description"] = dados_pagina["description"]
        # Preenche campos que estavam null com dados da pagina
        if not im.get("bathrooms") and dados_pagina.get("bathrooms"):
            im["bathrooms"] = dados_pagina["bathrooms"]
        if not im.get("parkingSpaces") and dados_pagina.get("parkingSpaces"):
            im["parkingSpaces"] = dados_pagina["parkingSpaces"]
        if not im.get("street") and dados_pagina.get("street"):
            street = dados_pagina["street"]
            if dados_pagina.get("streetNumber"):
                street += ", " + dados_pagina["streetNumber"]
            im["street"] = street
        time.sleep(1)
    logger.info(f"publishedAt extraido: {pub_ok}/{len(filtrados)}")

    logger.info(f"ocrad: {len(filtrados)} imoveis apos filtros")
    return filtrados


# =============================================================================
# BLOCO 3 - ORDENACAO E ESCOPO
# =============================================================================

def _ordenar_por_proximidade(imoveis: list[dict], rua: str, bairro: str) -> list[dict]:
    """
    Ordena os imoveis no JSON final:
        1. Mesma rua primeiro
        2. Mesmo bairro
        3. Restante (cidade)
    Normaliza acentos para comparacao.
    """
    import unicodedata

    def _norm(t: str) -> str:
        return unicodedata.normalize("NFD", t).encode("ascii", "ignore").decode().lower().strip()

    rua_n    = _norm(rua)    if rua    else ""
    bairro_n = _norm(bairro) if bairro else ""

    def _prio(i: dict) -> int:
        s = _norm(i.get("street") or "")
        n = _norm(i.get("neighborhood") or "")
        if rua_n    and rua_n    in s:           return 0
        if bairro_n and (bairro_n in n or bairro_n in s): return 1
        return 2

    ordenados = sorted(imoveis, key=_prio)
    grupos = Counter(_prio(i) for i in ordenados)
    logger.info(f"Ordenacao: {grupos[0]} na rua | {grupos[1]} no bairro | {grupos[2]} na cidade")
    return ordenados


def _aplicar_escopo(imoveis: list[dict], rua: str, bairro: str) -> tuple[list[dict], str]:
    """
    Mostra todos os imoveis da rua e do bairro (sem limites minimos).
    So descarta os que sao de outra cidade/bairro sem relacao.
    """
    import unicodedata

    def _norm(t: str) -> str:
        return unicodedata.normalize("NFD", t).encode("ascii", "ignore").decode().lower().strip()

    # Junta tudo que for da rua OU do bairro
    resultado = []
    rua_n = _norm(rua) if rua else ""
    bairro_n = _norm(bairro) if bairro else ""

    for i in imoveis:
        street_n = _norm(i.get("street") or "")
        neigh_n = _norm(i.get("neighborhood") or "")

        na_rua = rua_n and rua_n in street_n
        no_bairro = bairro_n and (bairro_n in neigh_n or bairro_n in street_n)

        if na_rua or no_bairro:
            resultado.append(i)

    # Se nao encontrou nada no bairro/rua, usa todos (fallback cidade)
    if not resultado:
        logger.info(f"Escopo: CIDADE -> {len(imoveis)} imoveis (nenhum no bairro/rua)")
        return imoveis, "cidade"

    logger.info(f"Escopo: RUA+BAIRRO -> {len(resultado)} imoveis")
    return resultado, "rua+bairro"


# =============================================================================
# BLOCO 4 - FUNCAO PUBLICA UNICA
# =============================================================================

def coletar_imoveis(
    localizacao: str,
    tipo_imovel: str = "apartment",
    bairro: str = "",
    rua: str = "",
    usar_cache: bool = False,
    arquivo_processados: str = "imoveis_coletados.json",
) -> list[dict]:
    """
    Coleta imoveis comparaveis usando Apify (ocrad).

    Fluxo:
        1. ocrad raspa listagens de 5 portais (ImovelWeb, VivaReal, LugarCerto, OLX, MercadoLivre)
        2. Normaliza (preco, quartos, area, rua, bairro, cidade, estado, iptu)
        3. Extrai publishedAt via requests.get + regex
        4. Remove duplicatas, leiloes, sem preco
        5. Filtra por bairro (escopo)
        6. Normaliza bairros (acentos)
        7. Ordena: mesma rua -> bairro -> cidade
        8. Salva em imoveis_coletados.json

    Parametros
    ----------
    localizacao : str
        Cidade e estado. Ex: "Belo Horizonte, MG"
    tipo_imovel : str
        "apartment" -> so Apartamentos
        "house"     -> Casas e Terrenos
        "commercial" -> Comercial
    bairro : str
        Bairro do imovel alvo. Ex: "Sao Gabriel"
    rua : str
        Rua do imovel alvo. Ex: "Rua Walter Ianni"
    usar_cache : bool
        Se True, carrega dados existentes sem nova coleta.

    Retorna
    -------
    list[dict]
        Imoveis comparaveis no schema padrao + campo street.
    """
    if usar_cache:
        dados = carregar_dados(arquivo_processados)
        if dados:
            logger.info(f"Cache carregado: {len(dados)} imoveis")
            return dados

    t_total = time.time()
    logger.info(f"Iniciando coleta | {localizacao} | tipo={tipo_imovel} | bairro={bairro} | rua={rua}")

    # ── FONTE: Apify (ocrad) ──────────────────────────────────────────
    logger.info("=" * 55)
    logger.info("FONTE: Apify (ocrad) — ImovelWeb, VivaReal, LugarCerto, OLX, MercadoLivre")
    logger.info("=" * 55)
    t0 = time.time()
    ocrad = _coletar_ocrad(localizacao, tipo_imovel, bairro)
    t_ocrad = time.time() - t0
    logger.info(f"Apify ocrad: {len(ocrad)} imoveis | tempo: {t_ocrad:.1f}s")

    # ── FILTROS ───────────────────────────────────────────────────────
    combinados = [i for i in ocrad if not _eh_leilao(i) and _campos_ok(i)]
    combinados = _remover_duplicatas_url(combinados)
    logger.info(f"Apos filtros (sem duplicatas, sem leilao): {len(combinados)} imoveis")

    # ── ESCOPO ────────────────────────────────────────────────────────
    combinados, escopo = _aplicar_escopo(combinados, rua=rua, bairro=bairro)
    logger.info(f"Escopo final: {escopo.upper()} | {len(combinados)} comparaveis")

    # ── ORDENA ────────────────────────────────────────────────────────
    combinados = _ordenar_por_proximidade(combinados, rua=rua, bairro=bairro)

    # ── RESUMO FINAL ──────────────────────────────────────────────────
    t_total_final = time.time() - t_total
    portais  = Counter(i.get("source", "?") for i in combinados)
    com_rua  = sum(1 for i in combinados if i.get("street"))
    com_data = sum(1 for i in combinados if i.get("publishedAt"))
    com_bath = sum(1 for i in combinados if i.get("bathrooms"))
    logger.info("=" * 55)
    logger.info(f"RESULTADO FINAL: {len(combinados)} comparaveis")
    logger.info(f"  Portais    : {dict(portais)}")
    logger.info(f"  Com rua    : {com_rua}/{len(combinados)}")
    logger.info(f"  Com data   : {com_data}/{len(combinados)}")
    logger.info(f"  Com banheir: {com_bath}/{len(combinados)}")
    logger.info(f"  Tempo ocrad: {t_ocrad:.1f}s")
    logger.info(f"  TEMPO TOTAL: {t_total_final:.1f}s ({t_total_final/60:.1f} min)")
    logger.info("=" * 55)

    # ── NORMALIZA BAIRRO ──────────────────────────────────────────────
    import unicodedata
    prefixos_tipo = ["lote terreno ", "lote ", "terreno ", "casa ", "apartamento ", "sobrado "]
    for i in combinados:
        for campo in ("neighborhood", "city"):
            valor = i.get(campo)
            if not valor:
                continue
            # Remove prefixos de tipo
            valor_lower = valor.lower()
            for prefixo in prefixos_tipo:
                if valor_lower.startswith(prefixo):
                    valor = valor[len(prefixo):]
                    valor_lower = valor.lower()
            # Restaura acentos comuns
            if valor == unicodedata.normalize("NFD", valor).encode("ascii", "ignore").decode():
                valor = valor.replace("Sao ", "São ").replace("Santo ", "Santo ").replace("Santa ", "Santa ")
            i[campo] = valor.strip()

    salvar_dados(combinados, arquivo_processados)
    
    # Salva separado: so imoveis com publishedAt (dados completos pra analise)
    completos = [i for i in combinados if i.get("publishedAt")]
    if completos:
        salvar_dados(completos, "imoveis_completos.json")
    
    return combinados


