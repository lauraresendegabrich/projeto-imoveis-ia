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
      1. Uma query unificada por subtipo busca RUA OU BAIRRO.
      2. Mesma rua recebe prioridade 0; mesmo bairro, prioridade 1.
      3. Comparacao de rua/bairro e tolerante a caixa, acentos e prefixos comuns.
      4. Se nenhum subtipo retornar resultado local, expande para a CIDADE
         consultando TODOS os subtipos do tipo de imovel.

  ETAPA 2 — APIFY (fallback, so roda se Athena util/local < 10)
  ────────────────────────────────────────────────────
    Portais: VivaReal + LugarCerto (unicos ativos).
    Max itens por URL varia por tipo: casa 20 / terreno 10 / apartamento 30.
    Actor: ocrad~brazil-real-estate-scraper (navegador headless)
    Depois: requests.get em cada URL para extrair publishedAt, descricao e fotos.

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

  ETAPA 5 — FILTROS E DEDUPLICACAO COM MERGE
  ──────────────────
    1. Remove LEILOES: palavras-chave (leilao, judicial, arrematacao,
       caixa economica, lance inicial, etc.) no titulo, no tipo OU na descricao.
       Muitos leiloes so se revelam na descricao, por isso ela tambem e checada.
    2. Remove sem PRECO (>0) ou sem CIDADE/BAIRRO.
    3. DEDUPLICA com MERGE (combina em vez de descartar) por ID com namespace da
       fonte, depois URL normalizada e, somente quando faltam ambos, fingerprint
       conservadora. O merge preserva o registro mais completo (fotos, descricao,
       lat/lon, publishedAt, banheiros, vagas).

  ETAPA 6 — ESCOPO
  ─────────────────
    Filtra so imoveis que correspondem a rua OU ao bairro do alvo.
    Normaliza acentos, caixa, pontuacao e prefixos comuns antes de comparar.
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
  - Credenciais AWS via cadeia padrao do boto3 (env, profile, IAM Role etc.)

COMO RODAR:
───────────
  .venv/Scripts/python.exe -m app.main
"""

import os
import re
import json
import time
import logging
import unicodedata
from collections import Counter
from datetime import datetime
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

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



def _normalizar_texto(texto: object) -> str:
    """Normaliza texto para comparacoes: sem acento, lowercase e espacos consistentes."""
    if texto is None:
        return ""
    valor = unicodedata.normalize("NFD", str(texto))
    valor = valor.encode("ascii", "ignore").decode().lower().strip()
    valor = re.sub(r"[^a-z0-9]+", " ", valor)
    return re.sub(r"\s+", " ", valor).strip()


def _chave_bairro(bairro: object) -> str:
    """Canoniza abreviacoes sem confundir, por exemplo, Jardim X com Vila X."""
    valor = _normalizar_texto(bairro)
    if not valor:
        return ""
    partes = valor.split()
    aliases = {
        "jd": "jardim", "vl": "vila", "pq": "parque", "res": "residencial",
        "cj": "conjunto", "lot": "loteamento",
    }
    if partes and partes[0] in aliases:
        partes[0] = aliases[partes[0]]
    return " ".join(partes)


def _core_bairro(bairro: object) -> str:
    valor = _chave_bairro(bairro)
    partes = valor.split()
    prefixos = {"jardim", "vila", "parque", "residencial", "conjunto", "loteamento"}
    if partes and partes[0] in prefixos:
        partes = partes[1:]
    return " ".join(partes) or valor


def _chave_rua(rua: object) -> str:
    """Normaliza logradouro e remove numero de porta quando ele vem explicitamente separado."""
    if rua is None:
        return ""
    bruto = str(rua).strip()
    # Remove apenas numero explicitamente separado por virgula ou por marcador n/numero.
    bruto = re.sub(r",\s*(?:n(?:[ºo°.]*)\s*)?\d+[a-zA-Z-]*.*$", "", bruto, flags=re.I)
    bruto = re.sub(r"\s+(?:n(?:[ºo°.]*)|numero)\s*\d+[a-zA-Z-]*.*$", "", bruto, flags=re.I)
    valor = _normalizar_texto(bruto)
    if not valor:
        return ""
    prefixos = {
        "rua", "r", "avenida", "av", "alameda", "travessa", "praca", "estrada",
        "rodovia", "largo",
    }
    partes = valor.split()
    while partes and partes[0] in prefixos:
        partes.pop(0)
    return " ".join(partes) or valor


def _textos_equivalentes(a: str, b: str) -> bool:
    """Comparacao tolerante sem aceitar string vazia como match."""
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    # Ultimo termo ajuda em abreviacoes como "R. Dr. Liraucio Gomes" x "Rua Doutor Liraucio Gomes".
    ultimo_a = a.split()[-1]
    ultimo_b = b.split()[-1]
    return len(ultimo_a) >= 4 and ultimo_a == ultimo_b


def _mesma_rua(valor: object, alvo: object) -> bool:
    return _textos_equivalentes(_chave_rua(valor), _chave_rua(alvo))


def _mesmo_bairro(valor: object, alvo: object) -> bool:
    a = _chave_bairro(valor)
    b = _chave_bairro(alvo)
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    # Aceita forma sem prefixo apenas quando um dos lados realmente veio sem prefixo.
    core_a = _core_bairro(valor)
    core_b = _core_bairro(alvo)
    return core_a == core_b and (a == core_a or b == core_b)


def _to_float_safe(valor: object, default: float | None = None) -> float | None:
    try:
        if valor is None or valor == "":
            return default
        if isinstance(valor, str):
            limpo = valor.strip().replace("R$", "").replace(" ", "")
            # Trata formato BR apenas quando ha separador de milhar/ponto e/ou virgula decimal.
            if "," in limpo:
                limpo = limpo.replace(".", "").replace(",", ".")
            valor = limpo
        return float(valor)
    except (TypeError, ValueError):
        return default


def _to_int_safe(valor: object, default: int = 0) -> int:
    convertido = _to_float_safe(valor, None)
    return int(convertido) if convertido is not None else default


def _normalizar_url(url: object) -> str:
    """Normaliza URL removendo tracking sem descartar parametros funcionais."""
    if not url:
        return ""
    bruto = str(url).strip()
    try:
        parsed = urlsplit(bruto)
        tracking = {"source", "from", "gclid", "fbclid", "ref", "referrer"}
        query = []
        for chave, valor in parse_qsl(parsed.query, keep_blank_values=True):
            k = chave.lower()
            if k.startswith("utm_") or k in tracking:
                continue
            query.append((chave, valor))
        query.sort()
        path = parsed.path.rstrip("/") or parsed.path
        return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, urlencode(query), ""))
    except Exception:
        return bruto.rstrip("/").lower()


def _parametros_cache(localizacao: str, tipo_imovel: str, bairro: str, rua: str) -> dict:
    return {
        "localizacao": _normalizar_texto(localizacao),
        "tipo_imovel": _normalizar_texto(tipo_imovel),
        "bairro": _chave_bairro(bairro),
        "rua": _chave_rua(rua),
    }


def _caminho_meta_cache(nome_arquivo: str) -> str:
    return os.path.join(DATA_DIR, f"{nome_arquivo}.meta.json")


def _cache_compativel(nome_arquivo: str, esperado: dict) -> bool:
    caminho = _caminho_meta_cache(nome_arquivo)
    if not os.path.exists(caminho):
        return False
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            meta = json.load(f)
        return meta.get("consulta") == esperado
    except Exception as exc:
        logger.warning(f"[Ag1][Cache] Nao foi possivel validar metadata: {exc}")
        return False


def _salvar_meta_cache(nome_arquivo: str, consulta: dict) -> None:
    caminho = _caminho_meta_cache(nome_arquivo)
    temporario = f"{caminho}.tmp-{os.getpid()}-{time.time_ns()}"
    payload = {"consulta": consulta, "salvo_em": datetime.now().isoformat()}
    try:
        with open(temporario, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(temporario, caminho)
    finally:
        if os.path.exists(temporario):
            try:
                os.remove(temporario)
            except OSError:
                pass


def _eh_leilao(imovel: dict) -> bool:
    """
    Verifica se o anuncio e de leilao pelo titulo, tipo e descricao.
    Muitos leiloes tem titulo generico ("Casa 3 quartos a venda") e so revelam
    a natureza de leilao na descricao ("imovel em leilao judicial", "arrematacao").
    Por isso a descricao tambem e inspecionada. Cobre os nomes de campo em ingles
    (title/description) e em portugues (titulo/descricao) vindos do Athena.
    Leiloes sao removidos porque seus precos sao artificialmente baixos
    e distorceriam a estimativa de valor justo.
    """
    texto = " ".join([
        str(imovel.get("title") or imovel.get("titulo") or ""),
        str(imovel.get("propertyType") or imovel.get("tipo") or ""),
        str(imovel.get("description") or imovel.get("descricao") or ""),
    ]).lower()
    return any(kw in texto for kw in AUCTION_KEYWORDS)


def _campos_ok(imovel: dict) -> bool:
    """Descarta preco invalido/nao positivo e imovel sem localizacao minima."""
    preco = _to_float_safe(imovel.get("price") or imovel.get("preco"), None)
    localizacao_ok = bool(
        imovel.get("city") or imovel.get("cidade")
        or imovel.get("neighborhood") or imovel.get("bairro")
    )
    return preco is not None and preco > 0 and localizacao_ok


def _remover_duplicatas_url(imoveis: list[dict]) -> list[dict]:
    """
    Remove duplicatas sem apagar unidades legitimas do mesmo predio.

    Ordem:
      1. ID com namespace da fonte (evita colisao de IDs entre portais).
      2. URL normalizada.
      3. Fingerprint conservadora SOMENTE para registros sem ID e sem URL.
    """

    def _namespace_id(imovel: dict) -> str:
        source = _normalizar_texto(imovel.get("source") or imovel.get("source_site") or "")
        # A tabela Athena deste agente e a tabela vivareal; permite casar Athena com VivaReal.
        if source in {"athena s3", "vivareal", "viva real"}:
            return "vivareal"
        return source or "desconhecida"

    def _merge(a: dict, b: dict) -> dict:
        resultado = dict(a)

        fotos_a = list(a.get("images") or [])
        fotos_b = list(b.get("images") or [])
        if fotos_a or fotos_b:
            resultado["images"] = list(dict.fromkeys(fotos_a + fotos_b))[:30]
        resultado["imageCount"] = len(resultado.get("images") or [])

        for campo in ["description", "title", "descricao", "titulo"]:
            val_a = a.get(campo) or ""
            val_b = b.get(campo) or ""
            if len(str(val_b)) > len(str(val_a)):
                resultado[campo] = val_b

        campos_preencher = [
            "price", "preco", "area", "area_construida", "bedrooms", "quartos",
            "bathrooms", "banheiros", "parkingSpaces", "vagas", "suites",
            "street", "rua", "neighborhood", "bairro", "city", "cidade",
            "state", "estado", "lat", "lon", "latitude", "longitude",
            "publishedAt", "data_publicacao", "condominiumFee", "preco_condominio",
            "iptu", "pricePerSqm", "preco_por_m2", "url", "listing_id", "id",
        ]
        for campo in campos_preencher:
            if not resultado.get(campo) and b.get(campo) is not None:
                resultado[campo] = b[campo]

        fontes = []
        for origem in (a, b):
            existentes = origem.get("fontes_origem")
            if isinstance(existentes, str):
                existentes = [existentes]
            for fonte in (existentes or [origem.get("source") or "?"]):
                if fonte and fonte not in fontes:
                    fontes.append(fonte)
        resultado["fontes_origem"] = fontes
        return resultado

    # PASSO 1 — ID com namespace da fonte.
    por_id: dict[str, dict] = {}
    sem_id: list[dict] = []
    merges_id = 0
    for im in imoveis:
        lid = im.get("listing_id") or im.get("posting_id") or im.get("id")
        lid = str(lid).strip() if lid is not None else ""
        # Em alguns normalizadores, id cai para a propria URL; deixa URL para o passo 2.
        if lid and lid.lower() != "none" and not lid.lower().startswith(("http://", "https://")):
            chave_id = f"{_namespace_id(im)}::{lid}"
            if chave_id in por_id:
                por_id[chave_id] = _merge(por_id[chave_id], im)
                merges_id += 1
            else:
                por_id[chave_id] = im
        else:
            sem_id.append(im)
    resultado_id = list(por_id.values()) + sem_id
    if merges_id:
        logger.info(f"  [dedup] {merges_id} merges por ID namespaced")

    # PASSO 2 — URL normalizada.
    por_url: dict[str, int] = {}
    por_url_final: list[dict] = []
    merges_url = 0
    for im in resultado_id:
        url = _normalizar_url(im.get("url"))
        if not url:
            por_url_final.append(im)
            continue
        if url not in por_url:
            por_url[url] = len(por_url_final)
            por_url_final.append(im)
        else:
            idx = por_url[url]
            por_url_final[idx] = _merge(por_url_final[idx], im)
            merges_url += 1
    if merges_url:
        logger.info(f"  [dedup] {merges_url} merges por URL")

    # PASSO 3 — fingerprint conservadora apenas quando nao ha ID/URL.
    chaves: dict[str, int] = {}
    resultado_final: list[dict] = []
    merges_fp = 0
    for im in por_url_final:
        possui_id = bool(im.get("listing_id") or im.get("posting_id") or (
            im.get("id") and not str(im.get("id")).lower().startswith(("http://", "https://"))
        ))
        possui_url = bool(_normalizar_url(im.get("url")))

        chave = ""
        if not possui_id and not possui_url:
            titulo = _normalizar_texto(im.get("title") or im.get("titulo"))
            source = _normalizar_texto(im.get("source"))
            local = _chave_rua(im.get("street") or im.get("rua")) or _chave_bairro(
                im.get("neighborhood") or im.get("bairro")
            )
            preco = _to_int_safe(im.get("price") or im.get("preco"))
            area = _to_int_safe(im.get("area") or im.get("area_construida"))
            quartos = _to_int_safe(im.get("bedrooms") or im.get("quartos"))
            # Exige titulo+fonte+localizacao e dados numericos; reduz falsos positivos.
            if titulo and source and local and preco > 0 and area > 0:
                chave = f"{source}|{titulo}|{local}|{preco}|{area}|{quartos}"

        if chave and chave in chaves:
            idx = chaves[chave]
            resultado_final[idx] = _merge(resultado_final[idx], im)
            merges_fp += 1
        else:
            if chave:
                chaves[chave] = len(resultado_final)
            resultado_final.append(im)

    if merges_fp:
        logger.info(f"  [dedup] {merges_fp} merges por fingerprint conservadora")

    ids_finais = []
    for im in resultado_final:
        lid = im.get("listing_id") or im.get("posting_id") or im.get("id")
        if lid and not str(lid).lower().startswith(("http://", "https://")):
            ids_finais.append(f"{_namespace_id(im)}::{str(lid).strip()}")
    ids_duplicados = len(ids_finais) - len(set(ids_finais))
    logger.info(f"  [dedup-check] IDs namespaced duplicados restantes: {ids_duplicados}")
    return resultado_final

def salvar_dados(imoveis: list[dict], nome_arquivo: str) -> str:
    """Salva JSON de forma atomica para evitar arquivo parcial em caso de interrupcao."""
    caminho = os.path.join(DATA_DIR, nome_arquivo)
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    temporario = f"{caminho}.tmp-{os.getpid()}-{time.time_ns()}"
    try:
        with open(temporario, "w", encoding="utf-8") as f:
            json.dump(imoveis, f, ensure_ascii=False, indent=2)
        os.replace(temporario, caminho)
    finally:
        if os.path.exists(temporario):
            try:
                os.remove(temporario)
            except OSError:
                pass
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
                except Exception as exc:
                    logger.debug(f"[Ag1][Enriquecimento] Nao foi possivel decodificar description: {exc}")
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

    except Exception as exc:
        logger.debug(f"[Ag1][Enriquecimento] Falha ao ler {url}: {exc}")

    return resultado


# =============================================================================
# BLOCO 2 - COLETA VIA APIFY (ocrad/brazil-real-estate-scraper)
# =============================================================================

def _montar_urls_listagem(tipo_imovel: str, bairro: str, cidade: str, estado: str = "MG") -> list[tuple]:
    """
    Monta URLs de listagem para cada portal suportado pelo ocrad.
    Funciona pra qualquer bairro, cidade e estado do Brasil.

    Retorna lista de tuplas (url, max_items) com limites por tipo:
      - casa:         20 itens por URL
      - terreno:      10 itens por URL
      - apartamento:  30 itens por URL
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

    # Mapeamento de tipo para slugs de URL por portal.
    # So estao aqui os portais ativos em URLS_LISTAGEM_PORTAIS (vivareal e lugarcerto).
    # imovelweb/olx/mercadolivre foram removidos porque nao retornam dados via ocrad.
    TIPOS_POR_PORTAL = {
        "house": {
            "vivareal":      ["casa_residencial", "lote-terreno_residencial"],
            "lugarcerto":    ["casa", "terreno"],
        },
        "apartment": {
            "vivareal":      ["apartamento_residencial"],
            "lugarcerto":    ["apartamento"],
        },
    }

    bairro_slug = _slugify(bairro)
    cidade_slug = _slugify(cidade)
    estado_sigla = estado.upper().strip()
    estado_nome = ESTADOS_NOME.get(estado_sigla, _slugify(estado))

    if tipo_imovel not in TIPOS_POR_PORTAL:
        raise ValueError(f"tipo_imovel nao suportado no Apify: {tipo_imovel}")
    tipos_portais = TIPOS_POR_PORTAL[tipo_imovel]

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
            except Exception as exc:
                logger.warning(f"[Ag1][Apify] Nao foi possivel montar URL para {portal}/{tipo_slug}: {exc}")

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
        if not run_id:
            raise RuntimeError("Apify iniciou a requisicao, mas nao retornou run_id")
        logger.info(f"[Ag1][Apify] run iniciado: {run_id}")
    except Exception as e:
        logger.error(f"[Ag1][Apify] Erro ao iniciar run: {e}")
        return []

    # Polling ate concluir. Nao baixa dataset se a execucao ainda estiver RUNNING.
    url_status = f"{APIFY_BASE_URL}/actor-runs/{run_id}?token={token_ocrad}"
    inicio = time.monotonic()
    concluiu = False
    ultimo_status = ""
    while time.monotonic() - inicio < 600:
        try:
            resp_status = requests.get(url_status, timeout=15)
            resp_status.raise_for_status()
            ultimo_status = resp_status.json().get("data", {}).get("status", "")
            logger.info(f"[Ag1][Apify] status: {ultimo_status}")
            if ultimo_status == "SUCCEEDED":
                concluiu = True
                break
            if ultimo_status in ("FAILED", "ABORTED", "TIMED-OUT"):
                logger.error(f"[Ag1][Apify] run falhou: {ultimo_status}")
                return []
        except Exception as exc:
            logger.warning(f"[Ag1][Apify] Falha temporaria consultando status: {exc}")
        time.sleep(10)

    if not concluiu:
        logger.error(
            f"[Ag1][Apify] timeout aguardando run {run_id}; ultimo_status={ultimo_status or 'desconhecido'}"
        )
        return []

    # Baixa resultados somente depois de SUCCEEDED.
    try:
        url_items = f"{APIFY_BASE_URL}/actor-runs/{run_id}/dataset/items?token={token_ocrad}&format=json"
        resp_items = requests.get(url_items, timeout=30)
        resp_items.raise_for_status()
        brutos = resp_items.json()
        if not isinstance(brutos, list):
            raise RuntimeError("Dataset do Apify nao retornou uma lista")
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

def _filtrar_matches_locais(imoveis: list[dict], rua: str, bairro: str) -> list[dict]:
    """Retorna somente matches reais de rua/bairro, sem fallback para cidade."""
    if not rua and not bairro:
        return list(imoveis)

    resultado = []
    for imovel in imoveis:
        na_rua = bool(rua) and _mesma_rua(imovel.get("street") or imovel.get("rua"), rua)
        no_bairro = bool(bairro) and _mesmo_bairro(
            imovel.get("neighborhood") or imovel.get("bairro"), bairro
        )
        if na_rua or no_bairro:
            resultado.append(imovel)
    return resultado


def _ordenar_por_proximidade(imoveis: list[dict], rua: str, bairro: str) -> list[dict]:
    """Ordena: mesma rua -> mesmo bairro -> restante da cidade."""

    def _prio(imovel: dict) -> int:
        if rua and _mesma_rua(imovel.get("street") or imovel.get("rua"), rua):
            return 0
        if bairro and _mesmo_bairro(imovel.get("neighborhood") or imovel.get("bairro"), bairro):
            return 1
        return 2

    ordenados = sorted(imoveis, key=_prio)
    grupos = Counter(_prio(i) for i in ordenados)
    logger.info(f"Ordenacao: {grupos[0]} na rua | {grupos[1]} no bairro | {grupos[2]} na cidade")
    return ordenados


def _aplicar_escopo(imoveis: list[dict], rua: str, bairro: str) -> tuple[list[dict], str]:
    """Mantem rua/bairro quando houver match; caso contrario usa cidade inteira."""
    resultado = _filtrar_matches_locais(imoveis, rua=rua, bairro=bairro)
    if rua or bairro:
        if resultado:
            logger.info(f"Escopo: RUA+BAIRRO -> {len(resultado)} imoveis")
            return resultado, "rua+bairro"
        logger.info(f"Escopo: CIDADE -> {len(imoveis)} imoveis (nenhum match local)")
        return imoveis, "cidade"
    return imoveis, "cidade"


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
    Coleta imoveis para o Agente 2. Athena e a fonte principal; Apify complementa
    quando a quantidade UTIL e LOCAL do Athena fica abaixo de 10.

    Tipos documentados/suportados: "apartment" e "house".
    """
    tipos_suportados = {"apartment", "house"}
    tipo_imovel = (tipo_imovel or "").strip().lower()
    if tipo_imovel not in tipos_suportados:
        raise ValueError(
            f"tipo_imovel invalido: {tipo_imovel!r}. Use 'apartment' ou 'house'."
        )

    partes = [p.strip() for p in (localizacao or "").split(",") if p.strip()]
    if not partes:
        raise ValueError("localizacao e obrigatoria. Exemplo: 'Campinas, SP'.")
    cidade_nome = partes[0]
    estado_nome = partes[1].upper() if len(partes) > 1 else "MG"
    if len(estado_nome) != 2:
        logger.warning(
            f"[Ag1] Estado {estado_nome!r} nao parece uma sigla UF de 2 letras; usando como informado."
        )

    consulta_cache = _parametros_cache(localizacao, tipo_imovel, bairro, rua)
    if usar_cache:
        if _cache_compativel(arquivo_processados, consulta_cache):
            dados = carregar_dados(arquivo_processados)
            if dados:
                logger.info(f"[Ag1][Cache] Cache compativel carregado: {len(dados)} imoveis")
                return dados
            logger.info("[Ag1][Cache] Cache compativel existe, mas esta vazio; nova coleta sera feita")
        else:
            logger.info("[Ag1][Cache] Cache ausente ou de outra consulta; ignorando arquivo antigo")

    t_total = time.time()
    logger.info(
        f"[Ag1] Iniciando coleta | {cidade_nome}/{estado_nome} | "
        f"tipo={tipo_imovel} | bairro={bairro} | rua={rua}"
    )

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
    limites = LIMITES_POR_TIPO[tipo_imovel]

    # ── FONTE PRINCIPAL: Amazon Athena ────────────────────────────────
    athena_imoveis: list[dict] = []
    try:
        from services.athena_client import AthenaClient

        logger.info("=" * 55)
        logger.info("[Ag1][Athena] FONTE PRINCIPAL: Amazon Athena (S3/Parquet)")
        logger.info("=" * 55)
        client = AthenaClient()
        queries_executadas = 0

        for tipo_sql, limite_tipo in limites.items():
            try:
                if bairro or rua:
                    resultado_tipo = client.buscar_bairro_rua(
                        cidade=cidade_nome,
                        bairro=bairro,
                        rua=rua,
                        estado=estado_nome,
                        tipo=tipo_sql,
                        limit=limite_tipo,
                    )
                else:
                    resultado_tipo = client.buscar_cidade(
                        cidade=cidade_nome,
                        estado=estado_nome,
                        tipo=tipo_sql,
                        limit=limite_tipo,
                    )
                queries_executadas += 1
            except Exception as exc:
                logger.warning(f"[Ag1][Athena] Falha no subtipo {tipo_sql}: {exc}")
                continue

            mesma_rua = sum(
                1 for im in resultado_tipo
                if rua and (
                    im.get("prioridade") in (0, "0")
                    or _mesma_rua(im.get("rua") or im.get("street"), rua)
                )
            )
            logger.info(
                f"[Ag1][Athena] {tipo_sql}: retornados={len(resultado_tipo)} | "
                f"mesma_rua={mesma_rua} | limite={limite_tipo}"
            )
            athena_imoveis.extend(resultado_tipo)

        logger.info(f"[Ag1][Athena] queries_executadas={queries_executadas}")

        # Se nenhuma busca local retornou nada, consulta TODOS os subtipos na cidade.
        if not athena_imoveis and (bairro or rua):
            logger.info("[Ag1][Athena] Nenhum resultado local; expandindo todos os subtipos para a cidade")
            for tipo_sql, limite_tipo in limites.items():
                try:
                    resultado_cidade = client.buscar_cidade(
                        cidade=cidade_nome,
                        estado=estado_nome,
                        tipo=tipo_sql,
                        limit=limite_tipo,
                    )
                    queries_executadas += 1
                    athena_imoveis.extend(resultado_cidade)
                    logger.info(
                        f"[Ag1][Athena][Cidade] {tipo_sql}: {len(resultado_cidade)} retornados"
                    )
                except Exception as exc:
                    logger.warning(f"[Ag1][Athena][Cidade] Falha no subtipo {tipo_sql}: {exc}")

        # Normalizacao registro a registro: um dado ruim nao derruba toda a fonte.
        normalizados_athena: list[dict] = []
        for idx_athena, original in enumerate(athena_imoveis):
            try:
                im = dict(original)
                im["source"] = "Athena/S3"

                fotos_raw = im.get("fotos_urls") or ""
                fotos_list = []
                if isinstance(fotos_raw, str) and fotos_raw:
                    for foto_url in fotos_raw.split("|"):
                        foto_url = foto_url.strip()
                        if not foto_url:
                            continue
                        foto_url = foto_url.replace("{description}", "imovel")
                        foto_url = foto_url.replace("{action}", "fit-in")
                        foto_url = foto_url.replace("{width}x{height}", "870x653")
                        foto_url = foto_url.replace("{width}", "870")
                        foto_url = foto_url.replace("{height}", "653")
                        fotos_list.append(foto_url)
                elif isinstance(im.get("images"), list):
                    fotos_list = im.get("images") or []
                im["images"] = list(dict.fromkeys(fotos_list))[:30]
                im["imageCount"] = len(im["images"])

                if idx_athena < 3:
                    logger.info(
                        f"[Ag1][Athena] fotos_diag id={im.get('listing_id') or im.get('url','?')[:50]} | "
                        f"fotos_normalizadas={len(im['images'])}"
                    )

                if not im.get("price"):
                    im["price"] = _to_float_safe(im.get("preco"), None)
                if not im.get("area"):
                    im["area"] = _to_float_safe(im.get("area_construida"), None)
                if im.get("bedrooms") is None:
                    valor = _to_float_safe(im.get("quartos"), None)
                    im["bedrooms"] = int(valor) if valor is not None else None
                if im.get("bathrooms") is None:
                    valor = _to_float_safe(im.get("banheiros"), None)
                    im["bathrooms"] = int(valor) if valor is not None else None
                if im.get("parkingSpaces") is None:
                    valor = _to_float_safe(im.get("vagas"), None)
                    im["parkingSpaces"] = int(valor) if valor is not None else None

                # Nao usar setdefault: chave existente com None precisa ser preenchida.
                mapeamentos = {
                    "neighborhood": "bairro",
                    "city": "cidade",
                    "state": "estado",
                    "street": "rua",
                    "publishedAt": "data_publicacao",
                    "description": "descricao",
                    "title": "titulo",
                }
                for destino, origem in mapeamentos.items():
                    if not im.get(destino) and im.get(origem) is not None:
                        im[destino] = im.get(origem)

                if not im.get("pricePerSqm"):
                    im["pricePerSqm"] = _to_float_safe(im.get("preco_por_m2"), None)
                if im.get("latitude") is not None and im.get("longitude") is not None:
                    lat = _to_float_safe(im.get("latitude"), None)
                    lon = _to_float_safe(im.get("longitude"), None)
                    if lat is not None and lon is not None:
                        im["lat"] = lat
                        im["lon"] = lon

                tipo_raw = im.get("tipo", "")
                if tipo_raw in ("casa", "two_story_house", "village_house"):
                    im["propertyType"] = "Casas"
                elif tipo_raw in ("apartamento", "flat", "cobertura"):
                    im["propertyType"] = "Apartamentos"
                elif tipo_raw in ("residential_allotment_land", "allotment_land"):
                    im["propertyType"] = "Terrenos"
                elif not im.get("propertyType"):
                    im["propertyType"] = tipo_raw

                normalizados_athena.append(im)
            except Exception as exc:
                logger.warning(f"[Ag1][Athena] Registro ignorado por erro de normalizacao: {exc}")

        athena_imoveis = _remover_duplicatas_url(normalizados_athena)
        logger.info(f"[Ag1][Athena] {len(athena_imoveis)} imoveis unicos normalizados")

    except Exception as exc:
        # Inclui ausencia de boto3/credenciais/role/servico. O fallback continua funcionando.
        logger.warning(f"[Ag1][Athena] Indisponivel: {exc}")
        athena_imoveis = []

    # Diagnostico seguro; nunca deve derrubar a coleta.
    if athena_imoveis:
        try:
            ids = []
            for im in athena_imoveis:
                lid = im.get("listing_id") or im.get("id")
                if lid:
                    ids.append(str(lid))
            logger.info(
                f"[Ag1][Athena][Dedup-Diag] total={len(athena_imoveis)} | "
                f"ids={len(ids)} | ids_duplicados={len(ids)-len(set(ids))}"
            )
            chaves_diag = []
            for im in athena_imoveis:
                chaves_diag.append(
                    f"{_chave_rua(im.get('street') or im.get('rua'))}|"
                    f"{_chave_bairro(im.get('neighborhood') or im.get('bairro'))}|"
                    f"{_normalizar_texto(im.get('propertyType') or im.get('tipo'))}|"
                    f"{_to_int_safe(im.get('price') or im.get('preco'))}|"
                    f"{_to_int_safe(im.get('area') or im.get('area_construida'))}|"
                    f"{_to_int_safe(im.get('bedrooms') or im.get('quartos'))}"
                )
            potenciais = sum(1 for _, qtd in Counter(chaves_diag).items() if qtd > 1)
            if potenciais:
                logger.info(
                    f"[Ag1][Athena][Dedup-Diag] grupos potencialmente parecidos (nao removidos): {potenciais}"
                )
        except Exception as exc:
            logger.warning(f"[Ag1][Athena][Dedup-Diag] Diagnostico ignorado por erro: {exc}")

    # ── FALLBACK: mede Athena UTIL + LOCAL, nao o bruto ───────────────
    athena_validos = [i for i in athena_imoveis if _campos_ok(i) and not _eh_leilao(i)]
    athena_validos = _remover_duplicatas_url(athena_validos)
    athena_locais = _filtrar_matches_locais(athena_validos, rua=rua, bairro=bairro)
    qtd_util_fallback = len(athena_locais) if (rua or bairro) else len(athena_validos)

    ocrad: list[dict] = []
    t_ocrad = 0.0
    if qtd_util_fallback < 10:
        logger.info("=" * 55)
        logger.info(
            f"[Ag1][Apify] FALLBACK: Athena tem apenas {qtd_util_fallback} resultados uteis/locais (<10)"
        )
        logger.info("=" * 55)
        t0 = time.time()
        try:
            ocrad = _coletar_ocrad(localizacao, tipo_imovel, bairro)
        except Exception as exc:
            logger.warning(f"[Ag1][Apify] Fallback falhou sem interromper o agente: {exc}")
            ocrad = []
        t_ocrad = time.time() - t0
        logger.info(f"[Ag1][Apify] {len(ocrad)} imoveis | tempo: {t_ocrad:.1f}s")
    else:
        logger.info(
            f"[Ag1][Athena] Suficiente: {qtd_util_fallback} imoveis uteis/locais; Apify nao necessario"
        )

    # ── COMBINA + FILTRA + DEDUP ──────────────────────────────────────
    todos = athena_imoveis + ocrad
    logger.info(
        f"Total combinado: {len(athena_imoveis)} Athena + {len(ocrad)} Apify = {len(todos)} imoveis"
    )
    combinados = [i for i in todos if not _eh_leilao(i) and _campos_ok(i)]
    combinados = _remover_duplicatas_url(combinados)
    logger.info(f"Apos filtros (validos, sem leilao, sem duplicatas fortes): {len(combinados)}")

    # ── ESCOPO ────────────────────────────────────────────────────────
    combinados, escopo = _aplicar_escopo(combinados, rua=rua, bairro=bairro)
    logger.info(f"Escopo final: {escopo.upper()} | {len(combinados)} candidatos para o Agente 2")

    # ── ENRIQUECIMENTO ────────────────────────────────────────────────
    sem_fotos = [i for i in combinados if not i.get("images")]
    if sem_fotos:
        logger.info(f"Enriquecendo {len(sem_fotos)} imoveis sem fotos...")
        enriq_ok = 0
        for im in sem_fotos:
            url_im = im.get("url", "") or ""
            if not url_im or "vivareal" not in url_im.lower():
                continue
            dados_pagina = _extrair_dados_pagina(url_im)
            if dados_pagina.get("images"):
                im["images"] = dados_pagina["images"]
                im["imageCount"] = dados_pagina.get("imageCount", len(im["images"]))
                enriq_ok += 1
            if dados_pagina.get("publishedAt") and not im.get("publishedAt"):
                im["publishedAt"] = dados_pagina["publishedAt"]
            if dados_pagina.get("description") and not im.get("description"):
                im["description"] = dados_pagina["description"]
            time.sleep(0.5)
        logger.info(f"Enriquecimento: {enriq_ok}/{len(sem_fotos)} imoveis com fotos")

    # ── ORDENACAO ─────────────────────────────────────────────────────
    combinados = _ordenar_por_proximidade(combinados, rua=rua, bairro=bairro)

    # Limpeza cosmetica minima: nao inventa acentos; apenas remove prefixos indevidos do scraper.
    prefixos_tipo = ["lote terreno ", "lote ", "terreno ", "casa ", "apartamento ", "sobrado "]
    for im in combinados:
        for campo in ("neighborhood", "city"):
            valor = im.get(campo)
            if not isinstance(valor, str) or not valor.strip():
                continue
            valor = valor.strip()
            valor_lower = valor.lower()
            for prefixo in prefixos_tipo:
                if valor_lower.startswith(prefixo):
                    valor = valor[len(prefixo):].strip()
                    break
            im[campo] = valor

    # ── RESUMO ────────────────────────────────────────────────────────
    t_total_final = time.time() - t_total
    portais = Counter(i.get("source", "?") for i in combinados)
    com_rua = sum(1 for i in combinados if i.get("street"))
    com_data = sum(1 for i in combinados if i.get("publishedAt"))
    com_bath = sum(1 for i in combinados if i.get("bathrooms") is not None)
    com_fotos = sum(1 for i in combinados if i.get("images"))
    logger.info("=" * 55)
    logger.info(f"[Ag1] RESULTADO FINAL: {len(combinados)} candidatos")
    logger.info(f"[Ag1]   Portais    : {dict(portais)}")
    logger.info(f"[Ag1]   Com rua    : {com_rua}/{len(combinados)}")
    logger.info(f"[Ag1]   Com data   : {com_data}/{len(combinados)}")
    logger.info(f"[Ag1]   Com banheir: {com_bath}/{len(combinados)}")
    logger.info(f"[Ag1]   Com fotos  : {com_fotos}/{len(combinados)}")
    if t_ocrad > 0:
        logger.info(f"[Ag1]   Tempo ocrad: {t_ocrad:.1f}s")
    logger.info(f"[Ag1]   TEMPO TOTAL: {t_total_final:.1f}s ({t_total_final/60:.1f} min)")
    logger.info("=" * 55)

    # JSONs continuam como snapshots/debug. O pipeline deve usar o retorno em memoria.
    salvar_dados(combinados, arquivo_processados)
    _salvar_meta_cache(arquivo_processados, consulta_cache)

    # Sempre sobrescreve, inclusive com [], para nunca reaproveitar "completos" de outra coleta.
    completos = [i for i in combinados if i.get("publishedAt")]
    salvar_dados(completos, "imoveis_completos_ag1.json")

    return combinados

