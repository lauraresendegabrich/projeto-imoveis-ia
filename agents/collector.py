"""
Agente 1 - Coletor de Dados Imobiliarios
==========================================

RESPONSABILIDADE:
    Coleta imoveis comparaveis ao imovel alvo a partir de duas fontes:
    Amazon Athena (principal) e Apify/ocrad (fallback).
    Normaliza os campos, filtra leiloes/duplicatas, ordena por proximidade.

ENTRADA:
    - localizacao (cidade, estado)
    - tipo_imovel ("apartment" ou "house")
    - bairro e rua do imovel alvo

SAIDA:
    - data/imoveis_coletados_ag1.json (todos os imoveis finais)
    - data/imoveis_completos_ag1.json (so os que tem publishedAt)
    - data/imoveis_brutos_ocrad_ag1.json (brutos Apify, debug)

FLUXO COMPLETO:
===============

  ETAPA 1 — ATHENA (fonte principal)
  ───────────────────────────────────
    Consulta SQL na tabela vivareal (S3/Parquet).
    Para cada tipo de imovel, busca com limite proprio (rua + bairro somados):

    Para house:
      casa                        → limite 200
      two_story_house             → limite 50
      village_house               → limite 50
      residential_allotment_land  → limite 60
      allotment_land              → limite 60

    Para apartment:
      apartamento  → limite 200
      flat         → limite 50
      cobertura    → limite 50

    Logica por tipo:
      1. Busca na RUA (LIKE '%nome%', ate o limite do tipo)
      2. Se rua < limite, complementa com BAIRRO (restante = limite - qtd_rua)
      3. Se TODOS os tipos = 0 → expande pra CIDADE

    Fallback de acentos (buscar_rua):
      1. Nome completo
      2. Sem acento
      3. So a ultima palavra (ex: "Gomes" de "Rua Doutor Liraucio Gomes")

    Fallback de acentos (buscar_bairro):
      1. Nome exato
      2. Sem acento
      3. LIKE parte final (ex: "Guanabara" de "Jardim Guanabara")

  ETAPA 2 — APIFY (fallback, so roda se Athena < 10)
  ────────────────────────────────────────────────────
    Portais: VivaReal (30 itens) + LugarCerto (30 itens)
    Actor: ocrad~brazil-real-estate-scraper (navegador headless)
    Depois: requests.get em cada URL para extrair publishedAt do HTML

  ETAPA 3 — NORMALIZACAO DE CAMPOS
  ─────────────────────────────────
    Athena retorna campos com nomes diferentes. O codigo mapeia:
      preco → price (float)
      area_construida → area (float)
      quartos → bedrooms (int)
      banheiros → bathrooms (int)
      vagas → parkingSpaces (int)
      bairro → neighborhood
      rua → street
      latitude/longitude → lat/lon (float)
      data_publicacao → publishedAt
      fotos_urls → images (split por |, resolve templates)
      tipo → propertyType ("Casas"/"Apartamentos"/"Terrenos")

    Templates das fotos:
      {description} → "imovel"
      {action} → "fit-in"
      {width}x{height} → "870x653"

  ETAPA 4 — COMBINACAO
  ─────────────────────
    todos = athena_imoveis + apify_imoveis
    Athena fica primeiro na lista.

  ETAPA 5 — FILTROS
  ──────────────────
    1. Remove LEILOES (palavras-chave no titulo: leilao, judicial, caixa, etc.)
    2. Remove sem PRECO ou sem CIDADE/BAIRRO
    3. Remove DUPLICATAS por URL

  ETAPA 6 — ESCOPO
  ─────────────────
    Filtra so imoveis que contem a rua OU o bairro no campo correspondente.
    Normaliza acentos antes de comparar.
    Se nenhum match → fallback cidade toda.

  ETAPA 7 — ENRIQUECIMENTO
  ─────────────────────────
    Imoveis sem fotos: requests.get na URL (VivaReal) para extrair imagens.

  ETAPA 8 — ORDENACAO FINAL
  ──────────────────────────
    Prioridade 0: mesma rua (normaliza acentos pra comparar)
    Prioridade 1: mesmo bairro
    Prioridade 2: restante (cidade)

DEPENDENCIAS:
─────────────
  - requests (HTTP)
  - boto3 (Athena/AWS)
  - Apify token (APIFY_TOKEN_2 no .env)
  - AWS credentials (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY no .env)

COMO RODAR:
───────────
  .venv/Scripts/python.exe -m app.main
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
    Remove duplicatas com merge inteligente.
    1. Dedup por ID (listing_id): merge de campos, preserva o mais completo.
    2. Dedup por URL: mesmo imovel em fontes diferentes.
    3. Dedup secundaria: combinacao de rua+bairro+tipo+preco+area+quartos.
    """
    import unicodedata

    def _norm_str(s):
        if not s:
            return ""
        return unicodedata.normalize("NFD", str(s)).encode("ascii", "ignore").decode().lower().strip()

    def _merge(a: dict, b: dict) -> dict:
        """Merge dois registros do mesmo imovel, preservando dados mais completos."""
        resultado = dict(a)  # copia base

        # Fotos: manter lista nao vazia, unir sem duplicar
        fotos_a = a.get("images") or []
        fotos_b = b.get("images") or []
        if fotos_b and not fotos_a:
            resultado["images"] = fotos_b
        elif fotos_a and fotos_b:
            urls_vistas = set(fotos_a)
            merged = list(fotos_a)
            for f in fotos_b:
                if f not in urls_vistas:
                    merged.append(f)
                    urls_vistas.add(f)
            resultado["images"] = merged[:30]
        resultado["imageCount"] = len(resultado.get("images") or [])

        # Texto: manter o mais completo
        for campo in ["description", "title", "descricao", "titulo"]:
            val_a = a.get(campo) or ""
            val_b = b.get(campo) or ""
            if len(val_b) > len(val_a):
                resultado[campo] = val_b

        # Campos numericos/textuais: preencher ausentes
        campos_preencher = [
            "price", "preco", "area", "area_construida", "bedrooms", "quartos",
            "bathrooms", "banheiros", "parkingSpaces", "vagas", "suites",
            "street", "rua", "neighborhood", "bairro", "city", "cidade",
            "state", "estado", "lat", "lon", "latitude", "longitude",
            "publishedAt", "data_publicacao", "condominiumFee", "preco_condominio",
            "iptu", "pricePerSqm", "preco_por_m2", "url",
        ]
        for campo in campos_preencher:
            if not resultado.get(campo) and b.get(campo):
                resultado[campo] = b[campo]

        # Fontes: guardar origem combinada
        fontes_a = a.get("fontes_origem") or [a.get("source", "?")]
        fontes_b = b.get("fontes_origem") or [b.get("source", "?")]
        if isinstance(fontes_a, str):
            fontes_a = [fontes_a]
        if isinstance(fontes_b, str):
            fontes_b = [fontes_b]
        resultado["fontes_origem"] = list(set(fontes_a + fontes_b))

        return resultado

    # === PASSO 1: Dedup por ID (listing_id) ===
    por_id = {}
    sem_id = []
    merges_id = 0

    for im in imoveis:
        lid = im.get("listing_id") or im.get("id") or ""
        lid = str(lid).strip()
        if lid and lid != "None":
            if lid in por_id:
                # Merge
                logger.info(f"  [dedup] mesmo ID detectado: {lid}")
                logger.info(f"  [dedup] registro A: {por_id[lid].get('source','?')} | fotos={len(por_id[lid].get('images') or [])}")
                logger.info(f"  [dedup] registro B: {im.get('source','?')} | fotos={len(im.get('images') or [])}")
                por_id[lid] = _merge(por_id[lid], im)
                logger.info(f"  [dedup] merge concluido | fotos={len(por_id[lid].get('images') or [])} | fontes={','.join(por_id[lid].get('fontes_origem', []))}")
                merges_id += 1
            else:
                por_id[lid] = im
        else:
            sem_id.append(im)

    resultado_id = list(por_id.values()) + sem_id
    if merges_id:
        logger.info(f"  [dedup] {merges_id} merges por ID realizados")

    # === PASSO 2: Dedup por URL ===
    por_url = {}
    final = []
    for im in resultado_id:
        url = im.get("url", "")
        if url:
            if url not in por_url:
                por_url[url] = im
                final.append(im)
            else:
                # Merge silencioso
                idx = final.index(por_url[url])
                final[idx] = _merge(final[idx], im)
        else:
            final.append(im)

    # === PASSO 3: Dedup secundaria (combinacao de campos) ===
    chaves_vistas = {}
    resultado_final = []
    for im in final:
        rua_n = _norm_str(im.get("street") or im.get("rua"))
        bairro_n = _norm_str(im.get("neighborhood") or im.get("bairro"))
        tipo_n = _norm_str(im.get("propertyType") or im.get("tipo"))
        preco = im.get("price") or im.get("preco") or 0
        try:
            preco = int(float(preco))
        except (ValueError, TypeError):
            preco = 0
        area = im.get("area") or im.get("area_construida") or 0
        try:
            area = int(float(area))
        except (ValueError, TypeError):
            area = 0
        quartos = im.get("bedrooms") or im.get("quartos") or 0
        try:
            quartos = int(float(quartos))
        except (ValueError, TypeError):
            quartos = 0

        chave = f"{rua_n}|{bairro_n}|{tipo_n}|{preco}|{area}|{quartos}"
        if chave not in chaves_vistas:
            chaves_vistas[chave] = im
            resultado_final.append(im)
        else:
            # Merge silencioso
            idx = resultado_final.index(chaves_vistas[chave])
            resultado_final[idx] = _merge(resultado_final[idx], im)

    # Verificacao final
    ids_finais = [str(im.get("listing_id") or im.get("id") or "") for im in resultado_final if im.get("listing_id") or im.get("id")]
    ids_duplicados = len(ids_finais) - len(set(ids_finais))
    logger.info(f"  [dedup-check] IDs duplicados restantes: {ids_duplicados}")
    if ids_duplicados > 0:
        from collections import Counter
        contagem = Counter(ids_finais)
        for lid, cnt in contagem.most_common(3):
            if cnt > 1:
                logger.warning(f"  [dedup-check] ID {lid} aparece {cnt} vezes")

    return resultado_final


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

        # ── URLs das imagens (VivaReal: resizedimgs.vivareal.com)
        # Extrai hashes unicos das imagens e monta URLs canonicas
        # Cada hash diferente = foto diferente do imovel
        hashes = re.findall(
            r'resizedimgs\.vivareal\.com/img/vr-listing/([a-f0-9]{32})/',
            html
        )
        if hashes:
            # Remove duplicatas mantendo ordem
            hashes_unicos = list(dict.fromkeys(hashes))
            # Monta URL canonica de cada imagem (tamanho padrao 870x653)
            urls_imagens = [
                f"https://resizedimgs.vivareal.com/img/vr-listing/{h}/"
                f"imovel.webp?action=fit-in&dimension=870x653"
                for h in hashes_unicos
            ]
            resultado["images"] = urls_imagens
            resultado["imageCount"] = len(urls_imagens)

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
        # LugarCerto: /compra-e-venda/{estado}/{cidade}/{bairro}/{tipo}
        if not neighborhood:
            m = re.search(r"/compra-e-venda/\w{2}/([\w-]+)/([\w-]+)/(?:casa|terreno|apartamento)", from_lower)
            if m:
                if not city:
                    city = " ".join(w.capitalize() for w in m.group(1).split("-"))
                neighborhood = " ".join(w.capitalize() for w in m.group(2).split("-"))
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
        # Fallback: LugarCerto usa /compra-e-venda/{estado_sigla}/{cidade}/
        if not state:
            m = re.search(r"/compra-e-venda/(mg|sp|rj|pr|rs|ba|sc|go|df|pe|ce|es|pa|am|ms|mt|al|se|pb|rn|pi|to|ro|ac|ap|rr)/", from_lower)
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

    # ── FALLBACK: extrai bairro/cidade/rua do titulo do LugarCerto
    # Formato: "Casa, 3 Quartos, 2 Vagas  Rua Lírica, Santa Mônica, Belo Horizonte, MG"
    if not neighborhood and source == "Lugar Certo":
        title = imovel.get("title", "") or ""
        # Busca padrão: "  {Rua}, {Bairro}, {Cidade}, {Estado}" no final do título
        m = re.search(r"  (?:(.+?), )?(.+?), (.+?), ([A-Z]{2})$", title)
        if m:
            if m.group(1) and not street:
                street = m.group(1).strip()
            neighborhood = m.group(2).strip()
            if not city:
                city = m.group(3).strip()
            if not state:
                state = m.group(4).strip()

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
        logger.warning("[Ag1][Apify] APIFY_TOKEN nao configurado - pulando coleta")
        return []

    token_ocrad = APIFY_TOKEN

    partes = [p.strip() for p in localizacao.split(",")]
    cidade = partes[0]
    estado = partes[1].strip().upper() if len(partes) > 1 else "MG"

    # Monta URLs de listagem para todos os portais
    urls = _montar_urls_listagem(tipo_imovel, bairro, cidade, estado)
    if not urls:
        logger.warning("[Ag1][Apify] Nenhuma URL de listagem montada")
        return []

    logger.info(f"[Ag1][Apify] {len(urls)} URLs de listagem para raspar")
    for url, limite in urls:
        logger.info(f"[Ag1][Apify]   [{limite} itens] {url}")

    # Envia para o actor
    # NOTA: Apify Proxy (useApifyProxy) testado e NAO funciona no free tier.
    # Com proxy: 0 resultados. Sem proxy: funciona normalmente.
    # A documentacao recomenda proxy pra melhores resultados, mas e recurso pago.
    #
    # Limites por tipo de URL (definidos em _montar_urls_listagem):
    #   - casa:        20 itens
    #   - terreno:     10 itens
    #   - apartamento: 30 itens
    total_items = sum(limite for _, limite in urls)
    payload = {
        "urls": [{"url": url, "maxItems": limite} for url, limite in urls],
        "max_retries_per_url": 2,
        "ignore_url_failures": True,
        "maxPaidItems": total_items,
    }

    try:
        endpoint = f"{APIFY_BASE_URL}/acts/{APIFY_ACTOR_OCRAD}/runs?token={token_ocrad}&maxItems={total_items}"
        r = requests.post(endpoint, json=payload, timeout=30)
        r.raise_for_status()
        run_id = r.json().get("data", {}).get("id")
        logger.info(f"[Ag1][Apify] run iniciado: {run_id}")
    except Exception as e:
        logger.error(f"[Ag1][Apify] Erro ao iniciar run: {e}")
        return []

    # Polling ate concluir
    url_status = f"{APIFY_BASE_URL}/actor-runs/{run_id}?token={token_ocrad}"
    inicio = time.time()
    while time.time() - inicio < 600:
        try:
            status = requests.get(url_status, timeout=15).json().get("data", {}).get("status", "")
            logger.info(f"[Ag1][Apify] status: {status}")
            if status == "SUCCEEDED":
                break
            if status in ("FAILED", "ABORTED", "TIMED-OUT"):
                logger.error(f"[Ag1][Apify] run falhou: {status}")
                return []
        except Exception:
            pass
        time.sleep(10)

    # Baixa resultados
    try:
        url_items = f"{APIFY_BASE_URL}/actor-runs/{run_id}/dataset/items?token={token_ocrad}&format=json"
        brutos = requests.get(url_items, timeout=30).json()
    except Exception as e:
        logger.error(f"[Ag1][Apify] Erro ao baixar resultados: {e}")
        return []

    logger.info(f"[Ag1][Apify] {len(brutos)} brutos coletados")
    salvar_dados(brutos, "imoveis_brutos_ocrad_ag1.json")

    # Normaliza e filtra
    normalizados = [_normalizar_ocrad(i) for i in brutos]
    filtrados = [i for i in normalizados if _campos_ok(i) and not _eh_leilao(i)]

    # Extrai dados adicionais de cada imovel (publishedAt, description, bathrooms, etc.)
    # requests.get + regex: funciona pra VivaReal (dados no HTML estatico)
    # OLX/ImovelWeb/LugarCerto/MercadoLivre: ficam sem dados extras (bloqueio ou sem dados)
    logger.info(f"[Ag1][Apify] Extraindo publishedAt de {len(filtrados)} imoveis...")
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
        # Atualiza imagens se encontradas na pagina (mais completo que o ocrad)
        if dados_pagina.get("images"):
            im["images"] = dados_pagina["images"]
            im["imageCount"] = dados_pagina["imageCount"]
        time.sleep(1)
    logger.info(f"[Ag1][Apify] publishedAt extraido: {pub_ok}/{len(filtrados)}")

    # Log de fotos por imovel
    com_fotos_apify = 0
    sem_fotos_apify = 0
    total_fotos_apify = 0
    for im in filtrados:
        n_fotos = len(im.get("images") or [])
        im_id = im.get("id") or im.get("url", "?")[:40]
        portal = im.get("source", "?")
        logger.info(f"[Ag1][Apify][Fotos] id={im_id} | portal={portal} | fotos_retornadas={n_fotos} | fotos_validas={n_fotos}")
        if n_fotos > 0:
            com_fotos_apify += 1
            total_fotos_apify += n_fotos
        else:
            sem_fotos_apify += 1
    logger.info(f"[Ag1][Apify][Resumo Fotos] imoveis={len(filtrados)} | com_fotos={com_fotos_apify} | sem_fotos={sem_fotos_apify} | total_fotos={total_fotos_apify}")

    logger.info(f"[Ag1][Apify] {len(filtrados)} imoveis apos filtros")
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
    arquivo_processados: str = "imoveis_coletados_ag1.json",
) -> list[dict]:
    """
    Coleta imoveis comparaveis. Athena primeiro, Apify como fallback.

    Fluxo:
        1. Athena (S3/Parquet) — banco com milhares de anuncios historicos
        2. Se Athena retornar < 10, usa Apify (ocrad) como fallback
        3. Normaliza (preco, quartos, area, rua, bairro, cidade, estado, iptu)
        4. Remove duplicatas, leiloes, sem preco
        5. Filtra por bairro (escopo)
        6. Ordena: mesma rua -> bairro -> cidade
        7. Salva em imoveis_coletados.json

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
    logger.info(f"[Ag1] Iniciando coleta | {localizacao} | tipo={tipo_imovel} | bairro={bairro} | rua={rua}")

    partes = [p.strip() for p in localizacao.split(",")]
    cidade_nome = partes[0]
    estado_nome = partes[1].strip().upper() if len(partes) > 1 else "MG"

    # ── FONTE PRINCIPAL: Amazon Athena (S3/Parquet) ───────────────────
    # Base de dados com milhares de anúncios já coletados
    athena_imoveis = []
    if os.getenv("AWS_ACCESS_KEY_ID"):
        try:
            from services.athena_client import AthenaClient

            logger.info("=" * 55)
            logger.info("[Ag1][Athena] FONTE PRINCIPAL: Amazon Athena (S3/Parquet)")
            logger.info("=" * 55)
            logger.info(f"[Ag1][Athena] Buscando dados em {cidade_nome}/{bairro or 'cidade toda'}...")
            client = AthenaClient()

            # ── ESTRATEGIA DE BUSCA ───────────────────────────────────
            # Limite TOTAL por tipo (rua + bairro + cidade somados):
            #   house:     casas=200, sobrados=50, casas de vila=50, terrenos_res=60, lotes=60
            #   apartment: apartamentos=200, flats=50, coberturas=50
            # Busca primeiro na rua, depois complementa com bairro até o limite.
            # Se rua + bairro = 0, expande pra cidade.
            # ──────────────────────────────────────────────────────────

            LIMITES_POR_TIPO = {
                "house": {
                    "casa": 200,
                    "two_story_house": 50,
                    "village_house": 50,
                    "residential_allotment_land": 60,
                    "allotment_land": 60,
                },
                "apartment": {
                    "apartamento": 200,
                    "flat": 50,
                    "cobertura": 50,
                },
            }

            limites = LIMITES_POR_TIPO.get(tipo_imovel, LIMITES_POR_TIPO["house"])
            athena_imoveis = []

            for tipo_sql, limite_tipo in limites.items():
                # PASSO 1: Busca na rua
                imoveis_tipo_rua = []
                if rua and bairro:
                    imoveis_tipo_rua = client.buscar_rua(cidade_nome, bairro, rua, tipo=tipo_sql, limit=limite_tipo)

                # PASSO 2: Se rua < limite, complementa com bairro
                restante = limite_tipo - len(imoveis_tipo_rua)
                imoveis_tipo_bairro = []
                if restante > 0 and bairro:
                    imoveis_tipo_bairro = client.buscar_bairro(cidade_nome, bairro, tipo=tipo_sql, limit=restante)
                    # Remove duplicatas que já vieram na rua
                    urls_rua = {im.get("url") for im in imoveis_tipo_rua if im.get("url")}
                    imoveis_tipo_bairro = [im for im in imoveis_tipo_bairro if im.get("url") not in urls_rua]
                    # Corta no restante
                    imoveis_tipo_bairro = imoveis_tipo_bairro[:restante]

                total_tipo = imoveis_tipo_rua + imoveis_tipo_bairro
                if total_tipo:
                    logger.info(f"[Ag1][Athena]   {tipo_sql}: {len(imoveis_tipo_rua)} rua + {len(imoveis_tipo_bairro)} bairro = {len(total_tipo)} (limite {limite_tipo})")
                athena_imoveis.extend(total_tipo)

            # PASSO 3: Se nada encontrado, expande pra cidade
            if not athena_imoveis and bairro:
                logger.info(f"[Ag1][Athena] Bairro '{bairro}' sem resultados, expandindo pra cidade toda...")
                tipo_principal = list(limites.keys())[0]  # casa ou apartamento
                athena_imoveis = client.buscar_cidade(cidade_nome, estado=estado_nome, tipo=tipo_principal)

            # Remove duplicatas globais (mesmo URL em tipos diferentes)
            urls_vistas = set()
            athena_unicos = []
            for im in athena_imoveis:
                url_im = im.get("url", "")
                if url_im and url_im in urls_vistas:
                    continue
                if url_im:
                    urls_vistas.add(url_im)
                athena_unicos.append(im)
            athena_imoveis = athena_unicos

            logger.info(f"[Ag1][Athena] {len(athena_imoveis)} imoveis total")

            # Normaliza campos do Athena para o schema padrao
            for idx_athena, im in enumerate(athena_imoveis):
                im["source"] = "Athena/S3"

                # --- LOGS TEMPORARIOS DE DIAGNOSTICO (fotos) ---
                if idx_athena < 3:
                    colunas_foto = [k for k in im.keys() if any(x in k.lower() for x in ["foto", "image", "photo", "picture", "img"])]
                    logger.info(f"[Ag1][Athena] fotos_diag id={im.get('listing_id') or im.get('url','?')[:50]} | colunas={colunas_foto}")
                    logger.info(f"[Ag1][Athena] fotos_raw={str(im.get('fotos_urls',''))[:150]}")

                fotos_raw = im.get("fotos_urls") or ""
                if fotos_raw:
                    fotos_list = []
                    for foto_url in fotos_raw.split("|"):
                        foto_url = foto_url.strip()
                        if foto_url:
                            foto_url = foto_url.replace("{description}", "imovel")
                            foto_url = foto_url.replace("{action}", "fit-in")
                            foto_url = foto_url.replace("{width}x{height}", "870x653")
                            foto_url = foto_url.replace("{width}", "870")
                            foto_url = foto_url.replace("{height}", "653")
                            fotos_list.append(foto_url)
                    im["images"] = fotos_list[:30]
                    im["imageCount"] = len(im["images"])
                else:
                    im["images"] = []
                    im["imageCount"] = 0

                # Log apos normalizacao (primeiros 3)
                if idx_athena < 3:
                    logger.info(f"[Ag1][Athena] fotos_normalizadas={len(im['images'])}")

                if im.get("preco") and not im.get("price"):
                    try:
                        im["price"] = float(im["preco"])
                    except (ValueError, TypeError):
                        pass
                if im.get("area_construida") and not im.get("area"):
                    try:
                        im["area"] = float(im["area_construida"])
                    except (ValueError, TypeError):
                        pass
                if im.get("quartos") and not im.get("bedrooms"):
                    try:
                        im["bedrooms"] = int(float(im["quartos"]))
                    except (ValueError, TypeError):
                        pass
                if im.get("banheiros") and not im.get("bathrooms"):
                    try:
                        im["bathrooms"] = int(float(im["banheiros"]))
                    except (ValueError, TypeError):
                        pass
                if im.get("vagas") and not im.get("parkingSpaces"):
                    try:
                        im["parkingSpaces"] = int(float(im["vagas"]))
                    except (ValueError, TypeError):
                        pass
                im.setdefault("neighborhood", im.get("bairro"))
                im.setdefault("city", im.get("cidade"))
                im.setdefault("state", im.get("estado"))
                im.setdefault("street", im.get("rua"))
                im.setdefault("publishedAt", im.get("data_publicacao"))
                im.setdefault("description", im.get("descricao"))
                im.setdefault("title", im.get("titulo"))
                # Preço por m2
                if im.get("preco_por_m2") and not im.get("pricePerSqm"):
                    try:
                        im["pricePerSqm"] = float(im["preco_por_m2"])
                    except (ValueError, TypeError):
                        pass
                # Coordenadas
                if im.get("latitude") and im.get("longitude"):
                    try:
                        im["lat"] = float(im["latitude"])
                        im["lon"] = float(im["longitude"])
                    except (ValueError, TypeError):
                        pass
                tipo_raw = im.get("tipo", "")
                if tipo_raw in ("casa", "two_story_house", "village_house"):
                    im["propertyType"] = "Casas"
                elif tipo_raw in ("apartamento", "flat", "cobertura"):
                    im["propertyType"] = "Apartamentos"
                elif tipo_raw in ("residential_allotment_land", "allotment_land"):
                    im["propertyType"] = "Terrenos"
                else:
                    im["propertyType"] = tipo_raw

        except Exception as e:
            logger.warning(f"[Ag1][Athena] Indisponivel: {e}")

    # ── FALLBACK: Apify (ocrad) — só roda se Athena retornou pouco ───
    ocrad = []
    t_ocrad = 0.0
    if len(athena_imoveis) < 10:
        logger.info("=" * 55)
        logger.info("[Ag1][Apify] FALLBACK: Apify (ocrad) — Athena retornou poucos resultados")
        logger.info("=" * 55)
        t0 = time.time()
        ocrad = _coletar_ocrad(localizacao, tipo_imovel, bairro)
        t_ocrad = time.time() - t0
        logger.info(f"[Ag1][Apify] {len(ocrad)} imoveis | tempo: {t_ocrad:.1f}s")
    else:
        logger.info(f"[Ag1][Athena] Suficiente ({len(athena_imoveis)} imoveis) — Apify nao necessario")

    # Combina: Athena (principal) + Apify (fallback)
    todos = athena_imoveis + ocrad
    logger.info(f"Total combinado: {len(athena_imoveis)} Athena + {len(ocrad)} Apify = {len(todos)} imoveis")

    # ── FILTROS ───────────────────────────────────────────────────────
    combinados = [i for i in todos if not _eh_leilao(i) and _campos_ok(i)]
    combinados = _remover_duplicatas_url(combinados)
    logger.info(f"Apos filtros (sem duplicatas, sem leilao): {len(combinados)} imoveis")

    # ── ESCOPO ────────────────────────────────────────────────────────
    combinados, escopo = _aplicar_escopo(combinados, rua=rua, bairro=bairro)
    logger.info(f"Escopo final: {escopo.upper()} | {len(combinados)} comparaveis")

    # ── ENRIQUECIMENTO (fotos, description, publishedAt) ─────────────
    # Enriquece todos os imóveis que ainda não têm fotos
    sem_fotos = [i for i in combinados if not i.get("images")]
    if sem_fotos:
        logger.info(f"Enriquecendo {len(sem_fotos)} imoveis sem fotos...")
        enriq_ok = 0
        for im in sem_fotos:
            url_im = im.get("url", "")
            if not url_im or "vivareal" not in url_im:
                continue
            dados_pagina = _extrair_dados_pagina(url_im)
            if dados_pagina.get("images"):
                im["images"] = dados_pagina["images"]
                im["imageCount"] = dados_pagina["imageCount"]
                enriq_ok += 1
            if dados_pagina.get("publishedAt") and not im.get("publishedAt"):
                im["publishedAt"] = dados_pagina["publishedAt"]
            if dados_pagina.get("description") and not im.get("description"):
                im["description"] = dados_pagina["description"]
            time.sleep(0.5)
        logger.info(f"Enriquecimento: {enriq_ok}/{len(sem_fotos)} imoveis com fotos")

    # ── ORDENA ────────────────────────────────────────────────────────
    combinados = _ordenar_por_proximidade(combinados, rua=rua, bairro=bairro)

    # ── RESUMO FINAL ──────────────────────────────────────────────────
    t_total_final = time.time() - t_total
    portais  = Counter(i.get("source", "?") for i in combinados)
    com_rua  = sum(1 for i in combinados if i.get("street"))
    com_data = sum(1 for i in combinados if i.get("publishedAt"))
    com_bath = sum(1 for i in combinados if i.get("bathrooms"))
    com_fotos = sum(1 for i in combinados if i.get("images"))
    logger.info("=" * 55)
    logger.info(f"[Ag1] RESULTADO FINAL: {len(combinados)} comparaveis")
    logger.info(f"[Ag1]   Portais    : {dict(portais)}")
    logger.info(f"[Ag1]   Com rua    : {com_rua}/{len(combinados)}")
    logger.info(f"[Ag1]   Com data   : {com_data}/{len(combinados)}")
    logger.info(f"[Ag1]   Com banheir: {com_bath}/{len(combinados)}")
    logger.info(f"[Ag1]   Com fotos  : {com_fotos}/{len(combinados)}")
    if t_ocrad > 0:
        logger.info(f"[Ag1]   Tempo ocrad: {t_ocrad:.1f}s")
    logger.info(f"[Ag1]   TEMPO TOTAL: {t_total_final:.1f}s ({t_total_final/60:.1f} min)")
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
        salvar_dados(completos, "imoveis_completos_ag1.json")
    
    return combinados


