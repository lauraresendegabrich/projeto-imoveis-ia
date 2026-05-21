"""
Agente 3 - Analisador Qualitativo de Descricao e Imagens
==========================================================

ARQUITETURA:
    Titulo + Descricao + 8 Fotos espaçadas -> NVIDIA NIM (uma unica chamada) -> Python (valida + calcula) -> JSON

MODELO: mistralai/ministral-14b-instruct-2512 via NVIDIA NIM
    Multimodal (texto + imagem). Gratuito, sem limite diario. ~11s por imovel.
    Limite: 8 imagens por prompt. Fotos selecionadas de forma espaçada.

FLUXO:
    1. Carrega zona_homogenea_ag2.json (Agente 2 - Etapa 3)
    2. Filtra: cluster="A" E classificacao_zona="na_zona"
    3. Para cada imovel:
         a. Monta prompt com titulo, descricao e campos estruturados
         b. Seleciona ate 8 fotos espaçadas uniformemente (cobre mais ambientes)
         c. NVIDIA NIM analisa texto + fotos juntos e retorna JSON
         d. Python valida, normaliza vocabulario e calcula score
    4. Imovel alvo: analisado separadamente
    5. Salva em data/imoveis_analisados_ag3.json

ENTRADA:
    data/zona_homogenea_ag2.json
    data/imoveis_comparaveis_ag2.json (imovel alvo)

SAIDA:
    data/imoveis_analisados_ag3.json

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
# CHAMADA AO LLM VISION (texto + fotos juntos)
# =============================================================================

def _analisar_imovel_vision(imovel: dict) -> dict:
    """
    Envia titulo, descricao e TODAS as fotos para a NVIDIA NIM
    (mistral-large-3-675b-instruct-2512 — multimodal, gratuito).
    Uma unica chamada — o modelo analisa texto e imagens de forma integrada.
    Retorna {} em caso de falha.
    """
    try:
        from openai import OpenAI

        api_key = os.getenv("NVIDIA_API_KEY", "")
        if not api_key:
            # Fallback para Gemini
            api_key = os.getenv("GOOGLE_API_KEY", "")
            if api_key:
                return _analisar_imovel_vision_gemini(imovel)
            logger.warning("NVIDIA_API_KEY e GOOGLE_API_KEY nao configuradas")
            return {}

        client = OpenAI(base_url="https://integrate.api.nvidia.com/v1", api_key=api_key)

        titulo    = imovel.get("title", "") or ""
        descricao = imovel.get("description", "") or imovel.get("descricao", "") or ""
        tipo      = imovel.get("propertyType", "") or ""
        area      = imovel.get("area", "")
        quartos   = imovel.get("bedrooms", "")
        banheiros = imovel.get("bathrooms", "")
        vagas     = imovel.get("parkingSpaces", "")
        preco     = imovel.get("priceFormatted", "") or imovel.get("price", "")
        bairro    = imovel.get("neighborhood", "") or imovel.get("bairro", "") or ""
        cidade    = imovel.get("city", "") or imovel.get("cidade", "") or ""
        images    = imovel.get("images", []) or []

        prompt_texto = f"""Voce e um avaliador imobiliario especializado.
Analise o anuncio abaixo considerando o texto E as fotos juntos.
Retorne APENAS JSON valido, sem texto fora do JSON.

Dados do imovel:
- Titulo: {titulo[:200]}
- Descricao: {descricao[:500]}
- Tipo: {tipo} | Area: {area}m2 | Quartos: {quartos} | Banheiros: {banheiros} | Vagas: {vagas}
- Preco: {preco} | Bairro: {bairro} | Cidade: {cidade}

Regras:
1. Use o texto E as fotos para chegar a uma conclusao integrada.
2. Nao invente informacoes que nao aparecem no texto nem nas fotos.
3. Se nao houver evidencia suficiente, use "desconhecido".
4. Ausencia de informacao NAO e ponto negativo.
5. So classifique como negativo se houver evidencia explicita.
6. Se parkingSpaces > 0, inclua "vagas de garagem" em pontos_positivos.
7. Se mencionar ou visualizar suite, inclua "suite" em pontos_positivos.

Retorne exatamente este JSON:
{{
  "estado_conservacao": "novo|reformado|bom|regular|precisa_reforma|desconhecido",
  "padrao_acabamento": "alto_padrao|medio|simples|desconhecido",
  "pontos_positivos": [],
  "pontos_negativos": [],
  "confianca_extracao": "baixa|media|alta",
  "observacoes": []
}}"""

        # Monta conteudo com texto + ate 8 imagens ESPAÇADAS (cobre mais ambientes)
        # Seleciona fotos distribuidas uniformemente ao longo do anuncio
        if len(images) <= 8:
            fotos_selecionadas = images
        else:
            # Pega fotos espaçadas: 1a, e depois distribuidas uniformemente
            step = len(images) / 8
            indices = [int(i * step) for i in range(8)]
            fotos_selecionadas = [images[i] for i in indices]

        content = [{"type": "text", "text": prompt_texto}]
        for url in fotos_selecionadas:
            content.append({"type": "image_url", "image_url": {"url": url}})

        response = client.chat.completions.create(
            model="mistralai/ministral-14b-instruct-2512",
            messages=[{"role": "user", "content": content}],
            max_tokens=512,
            temperature=0,
        )

        texto_resp = response.choices[0].message.content or ""
        m = re.search(r"\{[\s\S]+\}", texto_resp)
        if not m:
            logger.warning("NVIDIA NIM nao retornou JSON valido")
            return {}

        return json.loads(m.group(0))

    except json.JSONDecodeError:
        logger.warning("JSON invalido retornado pela NVIDIA NIM")
        return {}
    except Exception as e:
        logger.error(f"Erro ao chamar NVIDIA NIM: {e}")
        return {}


def _analisar_imovel_vision_gemini(imovel: dict) -> dict:
    """Fallback: usa Gemini se NVIDIA NIM nao estiver disponivel."""
    try:
        from google import genai
        from google.genai import types

        api_key = os.getenv("GOOGLE_API_KEY", "")
        if not api_key:
            return {}

        client = genai.Client(api_key=api_key)
        titulo    = imovel.get("title", "") or ""
        descricao = imovel.get("description", "") or imovel.get("descricao", "") or ""
        images    = imovel.get("images", []) or []

        prompt = f"Analise este imovel. Titulo: {titulo[:200]}. Descricao: {descricao[:300]}. Retorne JSON com estado_conservacao, padrao_acabamento, pontos_positivos, pontos_negativos, confianca_extracao, observacoes."
        parts = [types.Part.from_text(text=prompt)]
        for url in images:
            parts.append(types.Part.from_uri(file_uri=url, mime_type="image/webp"))

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[types.Content(role="user", parts=parts)],
            config=types.GenerateContentConfig(temperature=0),
        )
        texto_resp = response.text or ""
        m = re.search(r"\{[\s\S]+\}", texto_resp)
        if not m:
            return {}
        return json.loads(m.group(0))
    except Exception as e:
        logger.error(f"Gemini fallback falhou: {e}")
        return {}


# =============================================================================
# CALCULO DE SCORE
# =============================================================================

def _calcular_score(estado: str, padrao: str,
                    pontos_positivos: list, pontos_negativos: list) -> float:
    score = 0.50

    ajuste_conservacao = {
        "novo":            +0.20,
        "reformado":       +0.15,
        "bom":             +0.10,
        "regular":         -0.08,
        "precisa_reforma": -0.25,
        "desconhecido":     0.00,
    }
    score += ajuste_conservacao.get(estado, 0.00)

    ajuste_padrao = {
        "alto_padrao": +0.15,
        "medio":       +0.08,
        "simples":      0.00,
        "desconhecido": 0.00,
    }
    score += ajuste_padrao.get(padrao, 0.00)

    # Bonus por pontos positivos (limitado a +0.20)
    bonus = min(len(pontos_positivos) * 0.03, 0.20)
    score += bonus

    # Penalizacoes por pontos negativos explicitos
    # Regra: evitar dupla penalizacao — se o estado ja penalizou por "precisa_reforma",
    # nao penalizar novamente se "precisa de reforma" aparecer nos pontos negativos
    penalizacoes_aplicadas = set()

    # Se estado ja e precisa_reforma, marca como ja penalizado
    if estado == "precisa_reforma":
        penalizacoes_aplicadas.add("reforma")
    if estado == "regular":
        penalizacoes_aplicadas.add("regular")

    for ponto in pontos_negativos:
        p = ponto.lower()
        if ("documentacao" in p or "irregular" in p) and "documentacao" not in penalizacoes_aplicadas:
            score -= 0.20
            penalizacoes_aplicadas.add("documentacao")
        elif ("infiltracao" in p or "umidade" in p) and "umidade" not in penalizacoes_aplicadas:
            score -= 0.15
            penalizacoes_aplicadas.add("umidade")
        elif ("precisa" in p or "reforma" in p) and "reforma" not in penalizacoes_aplicadas:
            score -= 0.25
            penalizacoes_aplicadas.add("reforma")
        elif "reforma" not in p and "infiltra" not in p and "umidade" not in p and "document" not in p:
            score -= 0.08

    return round(max(0.0, min(1.0, score)), 4)


def _classificar(score: float) -> str:
    if score < 0.40:    return "desfavoravel"
    elif score <= 0.60: return "neutro"
    elif score <= 0.80: return "favoravel"
    else:               return "muito_favoravel"


# =============================================================================
# ANALISE DE UM IMOVEL
# =============================================================================

def _analisar_imovel(imovel: dict) -> dict:
    id_imovel = str(imovel.get("id", ""))
    titulo    = imovel.get("title", "") or ""
    descricao = imovel.get("description", "") or imovel.get("descricao", "") or ""
    images    = imovel.get("images", []) or []
    texto     = f"{titulo} {descricao}".strip()

    # Descricao insuficiente e sem fotos
    if not texto or len(texto) < 10:
        return {
            "id_imovel": id_imovel, "status": "descricao_insuficiente",
            "estado_conservacao": "desconhecido", "padrao_acabamento": "desconhecido",
            "pontos_positivos": [], "pontos_negativos": [],
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
        dados = {
            "estado_conservacao": "desconhecido",
            "padrao_acabamento": "desconhecido",
            "pontos_positivos": [],
            "pontos_negativos": [],
            "confianca_extracao": "baixa",
            "observacoes": ["LLM Vision indisponivel."],
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

    if not isinstance(pontos_pos, list): pontos_pos = []
    if not isinstance(pontos_neg, list): pontos_neg = []
    if not isinstance(observacoes, list): observacoes = []

    # Observacao quando estado desconhecido
    if estado == "desconhecido":
        msg = "Nao foram encontradas evidencias suficientes para inferir o estado de conservacao do imovel."
        if not any("evidencias" in str(o) for o in observacoes):
            observacoes = [msg] + observacoes

    # Calcula score
    score = _calcular_score(estado, padrao, pontos_pos, pontos_neg)

    # Regra: sem evidencia = neutro
    if (estado == "desconhecido" and padrao == "desconhecido"
            and not pontos_neg and confianca == "baixa"):
        score = 0.50

    classificacao = _classificar(score)

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

    # Analise textual resumida
    partes = []
    if estado != "desconhecido":
        partes.append(f"Estado: {estado}")
    if padrao != "desconhecido":
        partes.append(f"Padrao: {padrao}")
    if pontos_pos:
        partes.append(f"Positivos: {', '.join(pontos_pos[:5])}")
    if pontos_neg:
        partes.append(f"Negativos: {', '.join(pontos_neg[:3])}")
    analise_qualitativa = ". ".join(partes) + "." if partes else "Sem evidencias relevantes."

    return {
        "id_imovel":             id_imovel,
        "status":                "ok",
        "estado_conservacao":    estado,
        "padrao_acabamento":     padrao,
        "pontos_positivos":      pontos_pos,
        "pontos_negativos":      pontos_neg,
        "confianca_extracao":    confianca,
        "fotos_analisadas":      min(len(images), 8),
        "total_fotos_disponiveis": len(images),
        "observacoes":           observacoes,
        "scores":                {"score_qualitativo": score},
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

    if comparaveis is None:
        caminho_zona = os.path.join(DATA_DIR, arquivo_entrada)
        if not os.path.exists(caminho_zona):
            logger.error(f"Arquivo nao encontrado: {caminho_zona}")
            return {}
        with open(caminho_zona, "r", encoding="utf-8") as f:
            dados_zona = json.load(f)
        confirmados = dados_zona.get("comparaveis_confirmados", [])
        comparaveis = [
            c for c in confirmados
            if c.get("cluster") == "A" and c.get("classificacao_zona") == "na_zona"
        ]
        logger.info(f"zona_homogenea_ag2.json: {len(confirmados)} confirmados -> "
                    f"{len(comparaveis)} com Cluster A + na_zona")

    if imovel_alvo is None:
        caminho_comp = os.path.join(DATA_DIR, "imoveis_comparaveis_ag2.json")
        if os.path.exists(caminho_comp):
            with open(caminho_comp, "r", encoding="utf-8") as f:
                dados_comp = json.load(f)
            imovel_alvo = dados_comp.get("imovel_alvo", {})
        else:
            imovel_alvo = {}

    logger.info("Analisando imovel alvo...")
    analise_alvo = _analisar_imovel(imovel_alvo)
    imovel_alvo["analise_qualitativa"] = analise_alvo
    logger.info(f"  Alvo: estado={analise_alvo['estado_conservacao']} | "
                f"padrao={analise_alvo['padrao_acabamento']} | "
                f"score={analise_alvo['scores']['score_qualitativo']} | "
                f"class={analise_alvo['classificacao_qualitativa']} | "
                f"fotos={analise_alvo['fotos_analisadas']}")
    time.sleep(5.0)  # 5s entre chamadas

    logger.info(f"Analisando {len(comparaveis)} comparaveis (Cluster A + na_zona)...")
    com_ok = 0
    com_insuficiente = 0

    for idx, im in enumerate(comparaveis, 1):
        loc = im.get("street") or im.get("neighborhood", "?")
        n_fotos = len((im.get("images") or []))
        logger.info(f"  [{idx}/{len(comparaveis)}] {loc} | {n_fotos} fotos")
        t0 = time.time()
        analise = _analisar_imovel(im)
        t1 = time.time()
        im["analise_qualitativa"] = analise
        logger.info(f"    -> {t1-t0:.1f}s | estado={analise['estado_conservacao']} | score={analise['scores']['score_qualitativo']}")
        if analise["status"] == "ok":
            com_ok += 1
        else:
            com_insuficiente += 1
        time.sleep(5.0)  # 5s entre chamadas — NVIDIA NIM com modelo 14B

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
    return saida

