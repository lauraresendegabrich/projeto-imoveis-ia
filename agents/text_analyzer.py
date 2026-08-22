"""
Agente 3 - Analisador Qualitativo de Descricao e Imagens
==========================================================

RESPONSABILIDADE:
    Analisa fotos e descricao dos imoveis comparaveis (Cluster A + na_zona)
    para determinar estado de conservacao, padrao de acabamento e score qualitativo.
    Usa modelos de visao multimodal (texto + imagens em uma unica chamada).

ENTRADA:
    - data/zona_homogenea_ag2.json (fonte principal — Cluster A + na_zona)
    - data/imoveis_comparaveis_ag2.json (fallback — Cluster A sem filtro zona)

SAIDA:
    - data/imoveis_analisados_ag3.json

FLUXO:
    1. Carrega zona_homogenea_ag2.json (Agente 2 - Etapa 4)
    2. Filtra: cluster="A" E classificacao_zona="na_zona"
    3. Para cada imovel:
         a. Seleciona fotos espacadas conforme o provedor (Gemini 4, Groq 2, NVIDIA 1)
         b. Monta prompt com titulo, descricao, campos estruturados e fotos
         c. LLM multimodal analisa texto + fotos juntos e retorna JSON
         d. Python valida, normaliza vocabulario e calcula score deterministico
    4. Imovel alvo: analisado separadamente
    5. Salva em data/imoveis_analisados_ag3.json

CADEIA DE FALLBACK (LLMs):
    1. Gemini Flash Lite (GOOGLE_API_KEY) — operacionalmente ate 4 fotos por chamada
    2. Groq qwen3.6-27b (GROQ_API_KEY) — operacionalmente ate 2 fotos por chamada
    3. NVIDIA NIM llama-3.2-11b-vision (NVIDIA_API_KEY) — 1 foto por chamada

CALCULO DO SCORE (deterministico, Python):
    Base: 0.50
    + ajuste conservacao: novo(+0.20), reformado(+0.15), bom(+0.10), regular(-0.05), precisa_reforma(-0.25)
    + ajuste padrao: alto_padrao(+0.15), medio(+0.07), simples(-0.03)
    + bonus positivos: acabamento diferenciado(+0.05), varanda gourmet(+0.04), etc. (max +0.15)
    + penalizacoes: documentacao_irregular(-0.20), infiltracao(-0.15), etc. (max -0.30)
    Score final: clamp [0.0, 1.0]

CLASSIFICACAO:
    < 0.40 → desfavoravel
    0.40-0.60 → neutro
    0.60-0.80 → favoravel
    >= 0.80 → muito_favoravel

REGRA NEUTRA:
    Se estado=desconhecido E padrao=desconhecido E sem negativos E confianca=baixa:
    → score = 0.50 (neutro, nao penaliza nem bonifica sem evidencia)

SAIDA POR IMOVEL:
    - estado_conservacao (novo/reformado/bom/regular/precisa_reforma/desconhecido)
    - padrao_acabamento (alto_padrao/medio/simples/desconhecido)
    - pontos_positivos (lista)
    - pontos_negativos (lista)
    - qualidade_imagens (boa/razoavel/ruim)
    - confianca_extracao (alta/media/baixa)
    - evidencias (conservacao: [], acabamento: [])
    - score_qualitativo (0.0-1.0)
    - classificacao_qualitativa (desfavoravel/neutro/favoravel/muito_favoravel)

QUEM USA A SAIDA:
    Agente 5 → padrao_acabamento do alvo (medio/alto/baixo)
    Agente 5 → score_qualitativo (liquidez experimental)
    Interface → exibe estado, padrao, score pro usuario

DEPENDENCIAS:
    - google-genai (Gemini 3.5 Flash Lite)
    - groq (qwen3.6-27b)
    - openai (NVIDIA NIM)

COMO RODAR:
    .venv/Scripts/python.exe -m tests.test_text_analyzer
"""

import os
import re
import json
import time
import logging
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

LIMITACOES_PADRAO = [
    "A analise depende da qualidade e completude da descricao e das fotos do anuncio.",
    "As informacoes extraidas devem ser validadas por vistoria ou fonte oficial.",
]

# Limites operacionais do Agente 3.
# A interface pode continuar aceitando ate 8 URLs, mas cada provedor recebe
# somente a quantidade adequada ao seu perfil de uso.
MAX_FOTOS_INTERFACE = 8
MAX_FOTOS_GEMINI = 4
MAX_FOTOS_GROQ = 2
MAX_FOTOS_NVIDIA = 1
MAX_DESC_CHARS = 1500
MAX_AMENITIES = 20


def _selecionar_fotos(images: list, limite: int) -> list:
    """Seleciona fotos espacadas para evitar varias imagens quase iguais."""
    images = [u for u in (images or []) if isinstance(u, str) and u.strip()]
    if not images or limite <= 0:
        return []
    if len(images) <= limite:
        return images
    if limite == 1:
        return [images[len(images) // 2]]

    step = (len(images) - 1) / (limite - 1)
    indices = [round(i * step) for i in range(limite)]
    return [images[i] for i in indices]


def _normalizar_amenities(valor, limite: int = MAX_AMENITIES) -> list:
    """Converte amenities em uma lista curta e legivel para o prompt."""
    if not valor:
        return []

    if isinstance(valor, dict):
        itens = []
        for chave, v in valor.items():
            if isinstance(v, bool):
                if v:
                    itens.append(str(chave))
            elif v not in (None, "", [], {}):
                itens.append(f"{chave}: {v}")
    elif isinstance(valor, (list, tuple, set)):
        itens = [str(x) for x in valor if x not in (None, "")]
    else:
        texto = str(valor).strip()
        if not texto:
            return []
        sep = "|" if "|" in texto else ","
        itens = [x.strip() for x in texto.split(sep) if x.strip()]

    # remove duplicatas preservando ordem
    vistos = set()
    saida = []
    for item in itens:
        chave = item.casefold()
        if chave in vistos:
            continue
        vistos.add(chave)
        saida.append(item)
        if len(saida) >= limite:
            break
    return saida


def _prompt_compacto(imovel: dict, qtd_fotos: int) -> str:
    """Prompt enxuto usado nos fallbacks para reduzir consumo de tokens."""
    titulo = imovel.get("title", "") or ""
    descricao = imovel.get("description", "") or imovel.get("descricao", "") or ""
    tipo = imovel.get("propertyType", "") or ""
    area = imovel.get("area", "")
    quartos = imovel.get("bedrooms", "")
    banheiros = imovel.get("bathrooms", "")
    suites = imovel.get("suites", "") or ""
    vagas = imovel.get("parkingSpaces", "")
    area_terreno = imovel.get("lotArea", "") or imovel.get("area_terreno", "") or ""
    amenities = _normalizar_amenities(imovel.get("amenities"))
    amenities_txt = "; ".join(amenities) if amenities else "nao informado"

    return f"""Voce e um avaliador imobiliario especializado em analise qualitativa.
Foram fornecidas exatamente {qtd_fotos} imagem(ns) nesta chamada.
Use somente o que estiver visivel nas imagens, explicitamente escrito na descricao ou nos campos estruturados.

DADOS
Titulo: {titulo[:200]}
Descricao: {descricao[:MAX_DESC_CHARS]}
Tipo: {tipo} | Area: {area} m2 | Area do terreno: {area_terreno} m2 | Quartos: {quartos} | Banheiros: {banheiros} | Suites: {suites} | Vagas: {vagas}
Amenities informadas no anuncio: {amenities_txt}

REGRAS
- Nao invente nem complete frases truncadas.
- Nao diga que recebeu quantidade de imagens diferente de {qtd_fotos}.
- Se as imagens mostrarem o mesmo ambiente, registre isso em limitacoes_analise.
- Poucas fotos, ambientes nao fotografados, descricao incompleta ou imagens repetidas sao LIMITACOES DA ANALISE, nunca defeitos do imovel.
- Limitacoes da analise nao entram em pontos_negativos.
- Acabamento antigo, madeira aparente, piso antigo ou estilo simples nao sao defeitos por si so.
- So use pontos_negativos para problemas objetivos: infiltracao/umidade, danos visiveis, pintura deteriorada, acabamento desgastado, necessidade clara de reforma ou documentacao irregular explicitamente informada.
- Estado de conservacao e padrao de acabamento sao conceitos independentes.
- Se faltarem evidencias para classificar, use desconhecido e reduza a confianca.
- Nao use localizacao, preco, preco por m2, IPTU ou valor de condominio para inferir conservacao ou padrao.
- Amenities sao evidencia textual do anuncio; nao trate amenidades do condominio como prova de acabamento interno da unidade.

Retorne SOMENTE JSON valido, sem Markdown:
{{
  "estado_conservacao": "novo|reformado|bom|regular|precisa_reforma|desconhecido",
  "padrao_acabamento": "alto_padrao|medio|simples|desconhecido",
  "pontos_positivos": [],
  "pontos_negativos": [],
  "limitacoes_analise": [],
  "qualidade_imagens": "boa|razoavel|ruim",
  "confianca_extracao": "baixa|media|alta",
  "evidencias": {{"conservacao": [], "acabamento": []}},
  "observacoes": []
}}"""

# Normalizacao de vocabulario
_NORM_CONSERVACAO = {
    "novo": "novo", "lancamento": "novo", "lançamento": "novo",
    "nunca habitado": "novo", "reformado": "reformado",
    "recém reformado": "reformado", "recem reformado": "reformado",
    "bom": "bom", "excelente": "bom", "ótimo": "bom", "otimo": "bom",
    "impecável": "bom", "impecavel": "bom", "pronto para morar": "bom",
    "regular": "regular", "precisa_reforma": "precisa_reforma",
    "precisa de reforma": "precisa_reforma", "necessita reforma": "precisa_reforma",
    "desconhecido": "desconhecido", "indefinido": "desconhecido",
}

_NORM_ACABAMENTO = {
    "alto_padrao": "alto_padrao", "alto padrao": "alto_padrao",
    "alto padrão": "alto_padrao", "alto": "alto_padrao",
    "luxo": "alto_padrao", "premium": "alto_padrao",
    "medio": "medio", "médio": "medio", "bom": "medio",
    "simples": "simples", "desconhecido": "desconhecido",
    "indefinido": "desconhecido",
}


def _normalizar_conservacao(v: str) -> str:
    return _NORM_CONSERVACAO.get(str(v).lower().strip(), "desconhecido")


def _normalizar_acabamento(v: str) -> str:
    return _NORM_ACABAMENTO.get(str(v).lower().strip(), "desconhecido")


# =============================================================================
# PROVIDER STATE (circuit breaker por execucao)
# =============================================================================

_provider_state = {
    "gemini": {"available": True, "reason": None, "chamadas": 0, "sucessos": 0, "erros_429": 0, "puladas": 0},
    "groq": {"available": True, "reason": None, "last_request": 0.0, "chamadas": 0, "sucessos": 0, "erros_429": 0},
    "nvidia": {"available": True, "reason": None, "chamadas": 0, "sucessos": 0, "erros": 0},
}

GROQ_INTERVALO_PREVENTIVO = 8.0  # segundos entre chamadas ao Groq Vision


def _reset_provider_state():
    """Reseta o estado dos provedores (chamado no inicio de cada execucao)."""
    _provider_state["gemini"] = {"available": True, "reason": None, "chamadas": 0, "sucessos": 0, "erros_429": 0, "puladas": 0}
    _provider_state["groq"] = {"available": True, "reason": None, "last_request": 0.0, "chamadas": 0, "sucessos": 0, "erros_429": 0}
    _provider_state["nvidia"] = {"available": True, "reason": None, "chamadas": 0, "sucessos": 0, "erros": 0}


# =============================================================================
# CHAMADA AO LLM VISION (texto + fotos juntos)
# =============================================================================

def _analisar_imovel_vision(imovel: dict) -> dict:
    """
    Envia titulo, descricao e fotos para o Gemini (multimodal).
    Circuit breaker: se Gemini deu 429 nesta execucao, pula direto pro Groq.
    Retorna {} em caso de falha total.
    """
    # Tentativa 1: Gemini (se disponivel)
    if _provider_state["gemini"]["available"]:
        resultado = _tentar_gemini(imovel)
        if resultado:
            return resultado
    else:
        _provider_state["gemini"]["puladas"] += 1
        logger.info(f"[Ag3][LLM] Gemini pulado | motivo={_provider_state['gemini']['reason']}")

    # Tentativa 2: Groq (com intervalo preventivo)
    if _provider_state["groq"]["available"]:
        resultado = _tentar_groq(imovel)
        if resultado:
            return resultado

    # Tentativa 3: NVIDIA NIM (ultimo fallback)
    return _analisar_imovel_vision_nvidia(imovel)


def _tentar_gemini(imovel: dict) -> dict:
    """Tenta Gemini. Se 429, ativa circuit breaker."""
    try:
        from google import genai
        from google.genai import types

        api_key = os.getenv("GOOGLE_API_KEY_2", "") or os.getenv("GOOGLE_API_KEY", "")
        if not api_key:
            return {}

        _provider_state["gemini"]["chamadas"] += 1
        client = genai.Client(api_key=api_key)

        titulo = imovel.get("title", "") or ""
        descricao = imovel.get("description", "") or imovel.get("descricao", "") or ""
        tipo = imovel.get("propertyType", "") or ""
        area = imovel.get("area", "")
        quartos = imovel.get("bedrooms", "")
        banheiros = imovel.get("bathrooms", "")
        suites = imovel.get("suites", "") or ""
        vagas = imovel.get("parkingSpaces", "")
        area_terreno = imovel.get("lotArea", "") or imovel.get("area_terreno", "") or ""
        amenities = _normalizar_amenities(imovel.get("amenities"))
        amenities_txt = "; ".join(amenities) if amenities else "nao informado"
        images = imovel.get("images", []) or []
        fotos_selecionadas = _selecionar_fotos(images, MAX_FOTOS_GEMINI)
        qtd_fotos = len(fotos_selecionadas)

        prompt_texto = f"""Voce e um avaliador imobiliario especializado em analise qualitativa de imoveis por texto e imagens.
Todas as imagens pertencem ao MESMO imovel. Foram fornecidas exatamente {qtd_fotos} imagem(ns) nesta chamada.
Voce NAO deve calcular preco, valor de mercado, score ou classificacao favoravel/desfavoravel; o Python faz isso depois.

DADOS DO IMOVEL
Titulo: {titulo[:200]}
Descricao:
{descricao[:MAX_DESC_CHARS]}
Tipo: {tipo}
Area: {area} m2 | Area do terreno: {area_terreno} m2 | Quartos: {quartos} | Banheiros: {banheiros} | Suites: {suites} | Vagas: {vagas}
Amenities informadas no anuncio: {amenities_txt}

REGRAS FUNDAMENTAIS
1. Use SOMENTE informacoes visiveis nas imagens, explicitamente presentes na descricao ou nos campos estruturados.
2. Nao invente, nao complete frases truncadas e nao presuma caracteristicas comuns a imoveis semelhantes.
3. Se faltarem evidencias, use "desconhecido" e reduza a confianca.
4. Ausencia de informacao NAO e defeito do imovel.
5. Poucas fotos, ambientes nao fotografados, imagens repetidas/concentradas no mesmo ambiente e descricao incompleta devem ir apenas em "limitacoes_analise". Nunca coloque esses itens em "pontos_negativos".
6. Nao diga que recebeu quantidade de imagens diferente de {qtd_fotos}. Se as imagens estiverem concentradas no mesmo ambiente, diga isso, sem alterar a quantidade.
7. Acabamento antigo nao significa ma conservacao. Madeira aparente, piso antigo, revestimento antigo ou estilo simples nao sao negativos por si so.
8. Pontos negativos exigem evidencia concreta: documentacao irregular explicitamente informada, infiltracao/umidade, necessidade clara de reforma, pintura deteriorada, acabamento desgastado ou danos visiveis.
9. Estado de conservacao e padrao de acabamento sao independentes.
10. Nao use preco, preco por m2, bairro, cidade, rua, IPTU ou condominio para inferir conservacao ou padrao. Esses dados nem sao fornecidos no prompt.
11. Amenities sao evidencia textual do anuncio. Use apenas as que forem relevantes ao imovel; amenidades do condominio nao provam acabamento interno da unidade.
12. Considere todas as imagens em conjunto. Nao generalize um problema localizado para todo o imovel.
13. Se vagas > 0, pode incluir "vagas de garagem" em pontos_positivos. Se houver suite explicita, pode incluir "suite".

CATEGORIAS
estado_conservacao: novo | reformado | bom | regular | precisa_reforma | desconhecido
padrao_acabamento: alto_padrao | medio | simples | desconhecido
qualidade_imagens: boa | razoavel | ruim
confianca_extracao: baixa | media | alta

Retorne SOMENTE JSON valido:
{{
  "estado_conservacao": "desconhecido",
  "padrao_acabamento": "desconhecido",
  "pontos_positivos": [],
  "pontos_negativos": [],
  "limitacoes_analise": [],
  "qualidade_imagens": "razoavel",
  "confianca_extracao": "baixa",
  "evidencias": {{"conservacao": [], "acabamento": []}},
  "observacoes": []
}}"""

        parts = [types.Part.from_text(text=prompt_texto)]
        for url in fotos_selecionadas:
            try:
                parts.append(types.Part.from_uri(file_uri=url, mime_type="image/webp"))
            except Exception:
                pass

        texto_resp = ""
        for tentativa in range(2):
            try:
                response = client.models.generate_content(
                    model="gemini-3.5-flash-lite",
                    contents=[types.Content(role="user", parts=parts)],
                    config=types.GenerateContentConfig(temperature=0),
                )
                texto_resp = response.text or ""
                break
            except Exception as e:
                if "500" in str(e) and tentativa == 0:
                    logger.warning("Gemini 500 — retry em 3s...")
                    time.sleep(3)
                    continue
                raise

        m = re.search(r"\{[\s\S]+\}", texto_resp)
        if not m:
            logger.warning("Gemini nao retornou JSON valido")
            return {}

        resultado = json.loads(m.group(0))
        resultado["fotos_analisadas"] = qtd_fotos
        resultado["llm_usada"] = "gemini-3.5-flash-lite"
        _provider_state["gemini"]["sucessos"] += 1
        return resultado

    except Exception as e:
        err_str = str(e).lower()
        if "429" in err_str or "resource_exhausted" in err_str or "quota" in err_str:
            _provider_state["gemini"]["available"] = False
            _provider_state["gemini"]["reason"] = "quota_esgotada_nesta_execucao"
            _provider_state["gemini"]["erros_429"] += 1
            logger.warning("[Ag3][LLM] Gemini 429 -> circuit_breaker ativado")
        else:
            logger.error(f"[Ag3][LLM] Gemini falhou: {e}")
        return _tentar_groq(imovel)

def _tentar_groq(imovel: dict) -> dict:
    """Wrapper Groq com intervalo preventivo e controle de 429."""
    # Intervalo preventivo entre chamadas
    elapsed = time.time() - _provider_state["groq"]["last_request"]
    if elapsed < GROQ_INTERVALO_PREVENTIVO and _provider_state["groq"]["last_request"] > 0:
        espera = GROQ_INTERVALO_PREVENTIVO - elapsed
        logger.info(f"[Ag3][Groq] aguardando {espera:.1f}s para respeitar limite preventivo")
        time.sleep(espera)

    _provider_state["groq"]["chamadas"] += 1
    _provider_state["groq"]["last_request"] = time.time()
    resultado = _analisar_imovel_vision_groq(imovel)
    if resultado:
        _provider_state["groq"]["sucessos"] += 1
    return resultado


def _analisar_imovel_vision_groq(imovel: dict) -> dict:
    """Fallback Groq: prompt compacto, ate 2 fotos espacadas."""
    try:
        from groq import Groq

        api_key = os.getenv("GROQ_API_KEY", "")
        if not api_key:
            return _analisar_imovel_vision_nvidia(imovel)

        client = Groq(api_key=api_key, max_retries=0)
        images = imovel.get("images", []) or []
        fotos_selecionadas = _selecionar_fotos(images, MAX_FOTOS_GROQ)
        prompt_texto = _prompt_compacto(imovel, len(fotos_selecionadas))

        content = [{"type": "text", "text": prompt_texto}]
        for url in fotos_selecionadas:
            content.append({"type": "image_url", "image_url": {"url": url}})

        response = client.chat.completions.create(
            model="qwen/qwen3.6-27b",
            messages=[{"role": "user", "content": content}],
            temperature=0,
            max_completion_tokens=1400,
        )

        texto_resp = response.choices[0].message.content or ""
        if "</think>" in texto_resp:
            texto_resp = texto_resp.split("</think>", 1)[1].strip()
        texto_resp = re.sub(r"```json\s*", "", texto_resp)
        texto_resp = re.sub(r"```\s*", "", texto_resp)
        m = re.search(r"\{[\s\S]+\}", texto_resp)
        if not m:
            logger.warning("[Ag3][Groq] nao retornou JSON valido — tentando NVIDIA NIM")
            return _analisar_imovel_vision_nvidia(imovel)

        resultado = json.loads(m.group(0))
        resultado["fotos_analisadas"] = len(fotos_selecionadas)
        resultado["llm_usada"] = "groq-qwen3.6-27b"
        return resultado

    except Exception as e:
        err_str = str(e)
        if "429" in err_str:
            _provider_state["groq"]["erros_429"] += 1
            import re as _re_retry
            retry_match = _re_retry.search(r"(\d+(?:\.\d+)?)\s*s", err_str)
            retry_after = retry_match.group(1) if retry_match else "?"
            logger.warning(f"[Ag3][Groq] 429 | retry_after={retry_after}s")

            if retry_after != "?" and float(retry_after) <= 15:
                wait = float(retry_after) + 1
                _provider_state["groq"].setdefault("tempo_espera_total", 0.0)
                _provider_state["groq"]["tempo_espera_total"] = _provider_state["groq"].get("tempo_espera_total", 0.0) + wait
                logger.info(f"[Ag3][Groq] aguardando {wait:.0f}s (retry_after curto)")
                time.sleep(wait)
                try:
                    client2 = Groq(api_key=api_key, max_retries=0)
                    response2 = client2.chat.completions.create(
                        model="qwen/qwen3.6-27b",
                        messages=[{"role": "user", "content": content}],
                        temperature=0,
                        max_completion_tokens=1400,
                    )
                    texto_resp2 = response2.choices[0].message.content or ""
                    if "</think>" in texto_resp2:
                        texto_resp2 = texto_resp2.split("</think>", 1)[1].strip()
                    texto_resp2 = re.sub(r"```json\s*", "", texto_resp2)
                    texto_resp2 = re.sub(r"```\s*", "", texto_resp2)
                    m2 = re.search(r"\{[\s\S]+\}", texto_resp2)
                    if m2:
                        resultado2 = json.loads(m2.group(0))
                        resultado2["fotos_analisadas"] = len(fotos_selecionadas)
                        resultado2["llm_usada"] = "groq-qwen3.6-27b"
                        _provider_state["groq"]["sucessos"] += 1
                        return resultado2
                except Exception:
                    pass

            logger.info("[Ag3][Groq] 429 nao resolvido — tentando NVIDIA NIM")
        else:
            logger.error(f"[Ag3][Groq] falhou: {e}")
        return _analisar_imovel_vision_nvidia(imovel)

def _analisar_imovel_vision_nvidia(imovel: dict) -> dict:
    """Ultimo fallback: NVIDIA NIM, uma foto representativa."""
    try:
        from openai import OpenAI

        api_key = os.getenv("NVIDIA_API_KEY", "")
        if not api_key:
            logger.warning("NVIDIA_API_KEY nao configurada")
            return {}

        client = OpenAI(base_url="https://integrate.api.nvidia.com/v1", api_key=api_key)
        images = imovel.get("images", []) or []
        fotos_selecionadas = _selecionar_fotos(images, MAX_FOTOS_NVIDIA)
        prompt_texto = _prompt_compacto(imovel, len(fotos_selecionadas))

        content = [{"type": "text", "text": prompt_texto}]
        if fotos_selecionadas:
            content.append({"type": "image_url", "image_url": {"url": fotos_selecionadas[0]}})

        response = client.chat.completions.create(
            model="meta/llama-3.2-11b-vision-instruct",
            messages=[{"role": "user", "content": content}],
            max_tokens=900,
            temperature=0,
        )

        texto_resp = response.choices[0].message.content or ""
        m = re.search(r"\{[\s\S]+\}", texto_resp)
        if not m:
            logger.warning("NVIDIA NIM nao retornou JSON valido")
            return {}

        resultado_nim = json.loads(m.group(0))
        resultado_nim["fotos_analisadas"] = len(fotos_selecionadas)
        resultado_nim["llm_usada"] = "nvidia-llama-3.2-11b-vision"
        return resultado_nim

    except json.JSONDecodeError:
        logger.warning("JSON invalido retornado pela NVIDIA NIM")
        return {}
    except Exception as e:
        logger.error(f"Erro ao chamar NVIDIA NIM: {e}")
        return {}


# =============================================================================
# CALCULO DE SCORE
# =============================================================================

def _calcular_score(estado: str, padrao: str,
                    pontos_positivos: list, pontos_negativos: list,
                    confianca: str = "baixa") -> dict:
    """
    Calcula o score qualitativo de um imóvel a partir da análise da LLM.
    Retorna dict com score_qualitativo, classificacao e detalhes_calculo.
    """
    # ============================================================
    # 1. SCORE BASE
    # ============================================================
    score_base = 0.50
    score = score_base

    # ============================================================
    # 2. PESOS DE CONSERVAÇÃO
    # ============================================================
    pesos_conservacao = {
        "novo": 0.20,
        "reformado": 0.15,
        "bom": 0.10,
        "regular": -0.08,
        "precisa_reforma": -0.25,
        "desconhecido": 0.00,
    }

    # ============================================================
    # 3. PESOS DO PADRÃO DE ACABAMENTO
    # ============================================================
    pesos_padrao = {
        "alto_padrao": 0.15,
        "medio": 0.07,
        "simples": -0.03,
        "desconhecido": 0.00,
    }

    # ============================================================
    # 4. PESOS DOS DIFERENCIAIS POSITIVOS
    # ============================================================
    pesos_positivos_map = {
        "acabamento diferenciado": 0.05,
        "cozinha planejada": 0.03,
        "armarios planejados": 0.03,
        "armários planejados": 0.03,
        "varanda gourmet": 0.04,
        "vista livre": 0.03,
        "boa iluminacao natural": 0.02,
        "boa iluminação natural": 0.02,
        "integracao de ambientes": 0.02,
        "integração de ambientes": 0.02,
        "area externa privativa": 0.04,
        "área externa privativa": 0.04,
        "churrasqueira": 0.02,
        "churrasqueira privativa": 0.02,
        "piscina privativa": 0.04,
    }
    LIMITE_BONUS_POSITIVOS = 0.15

    # ============================================================
    # 5. PENALIZAÇÕES
    # ============================================================
    pesos_negativos_map = {
        "documentacao_irregular": -0.20,
        "documentação irregular": -0.20,
        "infiltracao_umidade": -0.15,
        "infiltração_umidade": -0.15,
        "infiltracao": -0.15,
        "infiltração": -0.15,
        "umidade": -0.15,
        "precisa_reforma": -0.25,
        "precisa reforma": -0.25,
        "danos_visiveis": -0.10,
        "danos visíveis": -0.10,
        "pintura_deteriorada": -0.06,
        "pintura deteriorada": -0.06,
        "acabamento_desgastado": -0.06,
        "acabamento desgastado": -0.06,
    }
    LIMITE_PENALIZACOES = -0.30

    # ============================================================
    # 6. REGRA NEUTRA
    # ============================================================
    if (estado == "desconhecido"
            and padrao == "desconhecido"
            and len(pontos_negativos) == 0
            and confianca == "baixa"):
        return {
            "score_qualitativo": 0.50,
            "classificacao": "neutro",
            "detalhes_calculo": {
                "score_base": 0.50,
                "ajuste_conservacao": 0.00,
                "ajuste_padrao": 0.00,
                "bonus_positivos": 0.00,
                "penalizacoes": 0.00,
                "regra_neutra_aplicada": True,
            }
        }

    # ============================================================
    # 7. CONSERVAÇÃO
    # ============================================================
    ajuste_conservacao = pesos_conservacao.get(estado, 0.00)
    score += ajuste_conservacao

    # ============================================================
    # 8. PADRÃO DE ACABAMENTO
    # ============================================================
    ajuste_padrao = pesos_padrao.get(padrao, 0.00)
    score += ajuste_padrao

    # ============================================================
    # 9. BÔNUS POSITIVOS
    # ============================================================
    bonus_positivos = 0.00
    positivos_aplicados = []

    for positivo in pontos_positivos:
        positivo_normalizado = str(positivo).strip().lower()

        # Vagas e suítes ficam no JSON para descrição,
        # mas NÃO alteram o score qualitativo.
        if positivo_normalizado in [
            "vagas de garagem", "vaga de garagem", "suite", "suíte"
        ]:
            continue

        # Evita dupla bonificação: se já classificamos como reformado,
        # "imóvel reformado" não gera outro bônus.
        if (positivo_normalizado in ["imovel reformado", "imóvel reformado"]
                and estado == "reformado"):
            continue

        peso = pesos_positivos_map.get(positivo_normalizado)
        if peso is not None:
            bonus_positivos += peso
            positivos_aplicados.append({"item": positivo, "peso": peso})

    # Limita bônus máximo
    bonus_positivos = min(bonus_positivos, LIMITE_BONUS_POSITIVOS)
    score += bonus_positivos

    # ============================================================
    # 10. PENALIZAÇÕES
    # ============================================================
    penalizacoes = 0.00
    negativos_aplicados = []

    for negativo in pontos_negativos:
        negativo_normalizado = str(negativo).strip().lower()

        # Regra anti-dupla penalização:
        # Se o estado geral já foi classificado como "precisa_reforma",
        # não descontamos novamente pelo mesmo problema.
        if (estado == "precisa_reforma"
                and negativo_normalizado in [
                    "precisa_reforma", "precisa reforma",
                    "necessita reforma", "necessidade de reforma"
                ]):
            continue

        peso = pesos_negativos_map.get(negativo_normalizado)
        # Segurança: somente problemas previstos na tabela alteram o score.
        # Observações livres da LLM nunca recebem penalização genérica.
        if peso is None:
            continue

        penalizacoes += peso
        negativos_aplicados.append({"item": negativo, "peso": peso})

    # Limite máximo de penalização
    penalizacoes = max(penalizacoes, LIMITE_PENALIZACOES)
    score += penalizacoes

    # ============================================================
    # 11. CLAMP DO SCORE
    # ============================================================
    score = max(0.0, min(1.0, score))
    score = round(score, 3)

    # ============================================================
    # 12. CLASSIFICAÇÃO FINAL
    # ============================================================
    if score < 0.40:
        classificacao = "desfavoravel"
    elif score < 0.60:
        classificacao = "neutro"
    elif score < 0.80:
        classificacao = "favoravel"
    else:
        classificacao = "muito_favoravel"

    # ============================================================
    # 13. RESULTADO
    # ============================================================
    return {
        "score_qualitativo": score,
        "classificacao": classificacao,
        "detalhes_calculo": {
            "score_base": score_base,
            "estado_conservacao": estado,
            "ajuste_conservacao": ajuste_conservacao,
            "padrao_acabamento": padrao,
            "ajuste_padrao": ajuste_padrao,
            "bonus_positivos": round(bonus_positivos, 3),
            "penalizacoes": round(penalizacoes, 3),
            "positivos_aplicados": positivos_aplicados,
            "negativos_aplicados": negativos_aplicados,
            "regra_neutra_aplicada": False,
        }
    }


def _classificar(score: float) -> str:
    if score < 0.40:    return "desfavoravel"
    elif score <= 0.60: return "neutro"
    elif score <= 0.80: return "favoravel"
    else:               return "muito_favoravel"


# =============================================================================
# ANALISE DE UM IMOVEL
# =============================================================================

def _analisar_imovel(imovel: dict, is_alvo: bool = False) -> dict:
    id_imovel = str(imovel.get("id", "") or imovel.get("listing_id", "") or "")
    # Se não tem id, usa parte da URL como identificador
    if not id_imovel and not is_alvo:
        url = imovel.get("url", "")
        if url:
            id_imovel = url.split("/")[-2] if url.endswith("/") else url.split("/")[-1]
            id_imovel = id_imovel[:20]
    label = "alvo" if is_alvo else (id_imovel or "sem_id")

    titulo    = imovel.get("title", "") or ""
    descricao = imovel.get("description", "") or imovel.get("descricao", "") or ""
    images    = imovel.get("images", []) or []
    texto     = f"{titulo} {descricao}".strip()

    logger.info(f"    [diag] id={label} | fotos_brutas={len(images)} | limite_interface={MAX_FOTOS_INTERFACE} | titulo={len(titulo)} chars | desc={len(descricao)} chars")

    # Descricao insuficiente e sem fotos
    if (not texto or len(texto) < 10) and not images:
        return {
            "id_imovel": id_imovel, "status": "descricao_insuficiente",
            "estado_conservacao": "desconhecido", "padrao_acabamento": "desconhecido",
            "pontos_positivos": [], "pontos_negativos": [],
            "limitacoes_analise": ["Sem descricao suficiente e sem fotos para analise."],
            "confianca_extracao": "baixa",
            "observacoes": ["Descricao insuficiente para analise."],
            "scores": {"score_qualitativo": 0.50},
            "classificacao_qualitativa": "neutro",
            "justificativa": "Sem evidencias suficientes para justificar ajuste no valor.",
            "analise_qualitativa": "Descricao insuficiente para analise.",
            "limitacoes": LIMITACOES_PADRAO,
        }

    # Chama LLM Vision (texto + fotos juntos)
    dados = _analisar_imovel_vision(imovel)

    # Fallback se falhar
    if not dados:
        obs_fallback = []
        if not images:
            obs_fallback.append("Nenhuma foto disponivel para analise visual. A avaliacao foi feita apenas com base no texto do anuncio.")
        else:
            obs_fallback.append("Nao foi possivel analisar as fotos neste momento. A avaliacao foi feita apenas com base no texto do anuncio.")
        dados = {
            "estado_conservacao": "desconhecido",
            "padrao_acabamento": "desconhecido",
            "pontos_positivos": [],
            "pontos_negativos": [],
            "limitacoes_analise": obs_fallback.copy(),
            "confianca_extracao": "baixa",
            "observacoes": obs_fallback,
        }

    # Normaliza
    estado    = _normalizar_conservacao(dados.get("estado_conservacao", "desconhecido"))
    padrao    = _normalizar_acabamento(dados.get("padrao_acabamento", "desconhecido"))
    confianca = str(dados.get("confianca_extracao", "baixa")).lower().strip()
    if confianca not in ("alta", "media", "baixa"):
        confianca = "baixa"

    pontos_pos = dados.get("pontos_positivos", [])
    pontos_neg = dados.get("pontos_negativos", [])
    observacoes = dados.get("observacoes", [])
    limitacoes_analise = dados.get("limitacoes_analise", [])
    qualidade_imagens = str(dados.get("qualidade_imagens", "razoavel")).lower().strip()
    if qualidade_imagens not in ("boa", "razoavel", "ruim"):
        qualidade_imagens = "razoavel"
    evidencias = dados.get("evidencias", {})
    if not isinstance(evidencias, dict):
        evidencias = {}

    if not isinstance(pontos_pos, list): pontos_pos = []
    if not isinstance(pontos_neg, list): pontos_neg = []
    if not isinstance(observacoes, list): observacoes = []
    if not isinstance(limitacoes_analise, list): limitacoes_analise = []

    # Observacao quando estado desconhecido
    if estado == "desconhecido":
        msg = "Nao foram encontradas evidencias suficientes para inferir o estado de conservacao do imovel."
        if not any("evidencias" in str(o) for o in observacoes):
            observacoes = [msg] + observacoes

    # Calcula score
    resultado_score = _calcular_score(estado, padrao, pontos_pos, pontos_neg, confianca)
    score = resultado_score["score_qualitativo"]
    classificacao = resultado_score["classificacao"]
    detalhes_calculo = resultado_score["detalhes_calculo"]

    # Regra: sem evidencia = neutro (já coberta pela regra neutra no _calcular_score)

    # Justificativa geral
    partes_just = []
    if estado != "desconhecido":
        partes_just.append(f"estado de conservacao: {estado}")
    if padrao != "desconhecido":
        partes_just.append(f"padrao de acabamento: {padrao}")
    if pontos_pos:
        partes_just.append(f"{len(pontos_pos)} pontos positivos identificados")
    if pontos_neg:
        partes_just.append(f"{len(pontos_neg)} pontos negativos identificados")
    partes_just.append(f"score qualitativo {score} -> classificacao {classificacao}")
    justificativa = ". ".join(partes_just) + "." if partes_just else "Sem evidencias suficientes para justificar ajuste no valor."

    # Analise textual resumida (linguagem natural pro usuario)
    partes = []
    if estado != "desconhecido":
        desc_estado = {
            "novo": "Imóvel novo ou nunca habitado",
            "reformado": "Imóvel recentemente reformado",
            "bom": "Imóvel em bom estado de conservação",
            "regular": "Imóvel com estado de conservação regular",
            "precisa_reforma": "Imóvel que necessita de reformas",
        }
        partes.append(desc_estado.get(estado, f"Estado: {estado}"))
    if padrao != "desconhecido":
        desc_padrao = {
            "alto_padrao": "com acabamento de alto padrão",
            "medio": "com acabamento padrão médio",
            "simples": "com acabamento simples",
        }
        partes.append(desc_padrao.get(padrao, f"padrão {padrao}"))
    if pontos_pos and not pontos_neg:
        partes.append(f"Destaques: {', '.join(str(p) for p in pontos_pos[:3]).lower()}")
    elif pontos_neg and not pontos_pos:
        partes.append(f"Atenção: {', '.join(str(n) for n in pontos_neg[:2]).lower()}")
    elif pontos_pos and pontos_neg:
        partes.append(f"Destaques: {', '.join(str(p) for p in pontos_pos[:2]).lower()}")
        partes.append(f"porém {str(pontos_neg[0]).lower()}")
    if confianca == "baixa":
        partes.append("Análise limitada por poucas fotos ou descrição vaga")
    analise_qualitativa = ". ".join(partes) + "." if partes else "Sem evidências suficientes para uma análise detalhada."

    return {
        "id_imovel":             id_imovel,
        "status":                "ok",
        "estado_conservacao":    estado,
        "padrao_acabamento":     padrao,
        "pontos_positivos":      pontos_pos,
        "pontos_negativos":      pontos_neg,
        "qualidade_imagens":     qualidade_imagens,
        "confianca_extracao":    confianca,
        "evidencias":            evidencias,
        "fotos_analisadas":      int(dados.get("fotos_analisadas", 0) or 0),
        "total_fotos_disponiveis": len(images),
        "llm_usada":             dados.get("llm_usada", "fallback"),
        "observacoes":           observacoes,
        "limitacoes_analise":    limitacoes_analise,
        "scores":                {"score_qualitativo": score},
        "detalhes_calculo":      detalhes_calculo,
        "classificacao_qualitativa": classificacao,
        "justificativa":         justificativa,
        "analise_qualitativa":   analise_qualitativa,
        "limitacoes":            LIMITACOES_PADRAO,
    }


# =============================================================================
# FUNCOES PUBLICAS
# =============================================================================

def analisar_descricao(descricao: str) -> dict:
    """Analisa a descricao de um unico imovel. Uso avulso."""
    return _analisar_imovel({"id": "", "description": descricao})


def analisar_comparaveis(
    imovel_alvo: Optional[dict] = None,
    comparaveis: Optional[list] = None,
    arquivo_entrada: str = "zona_homogenea_ag2.json",
    arquivo_saida: str = "imoveis_analisados_ag3.json",
    apenas_cluster_a: bool = True,
) -> dict:
    """
    Analisa os imoveis comparaveis do Agente 2 usando texto + fotos juntos.
    Fonte: zona_homogenea_ag2.json - filtra cluster=A + na_zona.
    """
    logger.info("=" * 60)
    logger.info("AGENTE 3: ANALISADOR TEXTUAL")
    logger.info("=" * 60)

    # Reset provider state pra esta execucao
    _reset_provider_state()
    logger.info(f"[Ag3][Provider] Gemini disponivel={_provider_state['gemini']['available']}")
    logger.info(f"[Ag3][Provider] Groq disponivel={_provider_state['groq']['available']}")

    if comparaveis is None:
        caminho_zona = os.path.join(DATA_DIR, arquivo_entrada)
        if os.path.exists(caminho_zona):
            with open(caminho_zona, "r", encoding="utf-8") as f:
                dados_zona = json.load(f)
            confirmados = dados_zona.get("comparaveis_confirmados", [])
            comparaveis = [
                c for c in confirmados
                if c.get("cluster") == "A" and c.get("classificacao_zona") == "na_zona"
            ]
            logger.info(f"zona_homogenea_ag2.json: {len(confirmados)} confirmados -> "
                        f"{len(comparaveis)} com Cluster A + na_zona")
        else:
            logger.warning(f"Zona homogenea nao disponivel — usando comparaveis do Ag. 2 direto")
            caminho_comp = os.path.join(DATA_DIR, "imoveis_comparaveis_ag2.json")
            if os.path.exists(caminho_comp):
                with open(caminho_comp, "r", encoding="utf-8") as f:
                    dados_comp = json.load(f)
                comparaveis = [
                    c for c in dados_comp.get("comparaveis", [])
                    if c.get("cluster") == "A"
                ]
                logger.info(f"Fallback: {len(comparaveis)} comparaveis do Cluster A (sem filtro de zona)")
            else:
                logger.error(f"Nenhum arquivo de comparaveis encontrado")
                return {}

    if imovel_alvo is None:
        caminho_comp = os.path.join(DATA_DIR, "imoveis_comparaveis_ag2.json")
        if os.path.exists(caminho_comp):
            with open(caminho_comp, "r", encoding="utf-8") as f:
                dados_comp = json.load(f)
            imovel_alvo = dados_comp.get("imovel_alvo", {})
        else:
            imovel_alvo = {}

    logger.info("Analisando imovel alvo...")
    analise_alvo = _analisar_imovel(imovel_alvo, is_alvo=True)
    imovel_alvo["analise_qualitativa"] = analise_alvo
    logger.info(f"[Ag3][Alvo] fotos_recebidas={len(imovel_alvo.get('images') or [])} | "
                f"fotos_enviadas={analise_alvo['fotos_analisadas']} | "
                f"LLM={analise_alvo.get('llm_usada', 'fallback')} | "
                f"estado={analise_alvo['estado_conservacao']} | "
                f"padrao={analise_alvo['padrao_acabamento']} | "
                f"score={analise_alvo['scores']['score_qualitativo']} | "
                f"class={analise_alvo['classificacao_qualitativa']}")
    time.sleep(2.0)  # 2s entre chamadas

    # Limita a 10 comparaveis (os mais similares por score/ranking)
    MAX_COMPARAVEIS_AG3 = 10
    if len(comparaveis) > MAX_COMPARAVEIS_AG3:
        # Ordena por ranking_llm (menor = melhor) e pega os top 10
        comparaveis.sort(key=lambda x: x.get("ranking_llm") or 999)
        logger.info(f"Limitando de {len(comparaveis)} para {MAX_COMPARAVEIS_AG3} comparaveis (top ranking)")
        comparaveis = comparaveis[:MAX_COMPARAVEIS_AG3]

    logger.info(f"Analisando {len(comparaveis)} comparaveis (Cluster A + na_zona)...")
    com_ok = 0
    com_insuficiente = 0

    for idx, im in enumerate(comparaveis, 1):
        loc = im.get("street") or im.get("neighborhood", "?")
        n_fotos = len((im.get("images") or []))
        im_id = im.get("id") or im.get("listing_id") or loc[:20]
        logger.info(f"[Ag3][Comparavel {idx}/{len(comparaveis)}] id={im_id} | fotos={n_fotos}")
        t0 = time.time()
        analise = _analisar_imovel(im)
        t1 = time.time()
        im["analise_qualitativa"] = analise
        llm_usada = analise.get("llm_usada", "fallback")
        logger.info(f"[Ag3][Comparavel {idx}/{len(comparaveis)}] LLM={llm_usada} | tempo={t1-t0:.1f}s | "
                    f"estado={analise['estado_conservacao']} | score={analise['scores']['score_qualitativo']}")
        if analise["status"] == "ok":
            com_ok += 1
        else:
            com_insuficiente += 1
        time.sleep(5.0)  # 5s entre chamadas — respeita 15 req/min do Gemini free tier

    scores_finais = [c["analise_qualitativa"]["scores"]["score_qualitativo"] for c in comparaveis]

    resumo = {
        "total_analisados":       len(comparaveis),
        "analisados_ok":          com_ok,
        "descricao_insuficiente": com_insuficiente,
        "filtro":                 "cluster=A + classificacao_zona=na_zona",
        "score_qualitativo_medio": round(sum(scores_finais) / len(scores_finais), 4) if scores_finais else None,
    }

    logger.info("=" * 60)
    logger.info(f"RESULTADO: {com_ok} ok | {com_insuficiente} insuficientes")
    logger.info(f"  Score qualitativo medio: {resumo['score_qualitativo_medio']}")
    logger.info("=" * 60)

    saida = {"imovel_alvo": imovel_alvo, "comparaveis": comparaveis, "resumo": resumo}
    caminho_saida = os.path.join(DATA_DIR, arquivo_saida)
    with open(caminho_saida, "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=2)
    logger.info(f"Salvo em: {caminho_saida}")

    # Resumo LLM da execucao
    g = _provider_state["gemini"]
    gr = _provider_state["groq"]
    tempo_espera = gr.get("tempo_espera_total", 0.0)
    logger.info(f"[Ag3][Resumo LLM] Gemini chamadas={g['chamadas']} | sucessos={g['sucessos']} | 429={g['erros_429']} | puladas={g['puladas']}")
    logger.info(f"[Ag3][Resumo LLM] Groq chamadas={gr['chamadas']} | sucessos={gr['sucessos']} | 429={gr['erros_429']} | tempo_espera_quota={tempo_espera:.0f}s")

    return saida
