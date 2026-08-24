"""
Agente 2 - Identificador de Imoveis Comparaveis
=================================================

RESPONSABILIDADE:
    Recebe os imoveis coletados pelo Agente 1 e identifica quais sao
    realmente comparaveis. Primeiro executa uma pre-classificacao
    deterministica em Python, depois calcula score numerico para ordenar
    os sobreviventes e, por fim, usa LLM para o julgamento final dos
    candidatos prioritarios. Depois valida geograficamente com imagem
    de satelite.

ENTRADA:
    - data/imoveis_completos_ag1.json (saida do Agente 1)
    - imovel_alvo (dict com area, bedrooms, bathrooms, parkingSpaces, etc.)

SAIDA:
    - data/imoveis_comparaveis_ag2.json (pre-classificacao + ranking + clusters)
    - data/zona_homogenea_ag2.json (confirmados na zona + coordenadas alvo)
    - data/satelite_zona_homogenea_ag2.png (imagem com marcador)

FLUXO COMPLETO:
===============

  ETAPA 1 — SEPARACAO DE TERRENOS
  ────────────────────────────────
    Terrenos (propertyType == "Terrenos") sao separados e nao entram
    na pre-classificacao/ranking/LLM de imoveis construidos.

  ETAPA 2 — ESTATISTICAS + PRE-CLASSIFICACAO (sem LLM)
  ─────────────────────────────────────────────────────
    Calcula, sobre os candidatos construidos:
      - media da area construida
      - media da area de terreno (quando informada)

    A media e descritiva. O corte usa a area REAL do imovel alvo.

    Regra eliminatoria de area:
      - area construida: diferenca > 50% em relacao ao alvo -> incompatível
      - area de terreno: diferenca > 50% em relacao ao alvo -> incompatível
        (aplicada para casas quando alvo e candidato possuem o dado)

    Caracteristicas objetivas comparadas:
      - piscina
      - churrasqueira
      - area/espaco gourmet
      - quintal/area externa
      - varanda/sacada
      - elevador
      - portaria
      - academia
      - salao de festas
      - playground
      - armarios/moveis planejados

    A caracteristica so elimina quando existe divergencia EXPLICITA:
      alvo=sim e candidato=nao, ou alvo=nao e candidato=sim.
    Campo nao informado = desconhecido e NAO elimina.

  ETAPA 3 — SCORE NUMERICO (sem LLM)
  ──────────────────────────────────
    Score 0.0-1.0 por distancia relativa:
      - area (m²):    30%
      - quartos:      25%
      - preco/m²:     20%
      - banheiros:    15%
      - vagas:        10%

    Formula: similaridade = 1 - |alvo - cand| / max(alvo, cand)
    O score serve para ordenar/priorizar os candidatos e NAO e enviado
    no prompt da LLM, evitando vies de ancoragem.

  ETAPA 4 — CLUSTERING VIA LLM
  ─────────────────────────────
    Somente candidatos que passaram pela pre-classificacao podem chegar
    a LLM. Sao priorizados pelo score numerico.

    Limites:
      - ate 30 candidatos para LLM
      - lotes de ate 15 candidatos
      - excedentes continuam no resultado usando fallback numerico

    Cadeia de fallback:
      1. Groq (GROQ_API_KEY) — openai/gpt-oss-120b
      2. Groq (GROQ_API_KEY_2) — openai/gpt-oss-120b
      3. Gemini — gemini-3.5-flash-lite
      4. NVIDIA NIM — meta/llama-3.3-70b-instruct
      5. Fallback numerico — score >= 0.60 -> A

    A LLM recebe somente candidatos sem incompatibilidade objetiva detectada
    e realiza o julgamento final de comparabilidade.

  ETAPA 5 — ZONA HOMOGENEA
  ─────────────────────────
    Mantem a logica existente: geocodificacao do alvo, imagem hybrid,
    analise visual da zona e classificacao por distancia.

QUEM USA A SAIDA:
─────────────────
    Agente 3 -> zona_homogenea_ag2.json (Cluster A + na_zona -> analisa fotos)
    Agente 4 -> zona_homogenea_ag2.json (coordenadas_alvo -> busca POIs)
    Agente 5 -> zona_homogenea_ag2.json (comparaveis_confirmados + terrenos -> preco)
    Interface -> satelite_zona_homogenea_ag2.png
"""

import os
import re
import json
import logging
import unicodedata
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


# =============================================================================
# BLOCO 1 - ESTATISTICAS E PRE-CLASSIFICACAO DETERMINISTICA
# =============================================================================

CARACTERISTICAS_PRE_CLASSIFICACAO = {
    "piscina": {
        "positivos": ["piscina"],
        "negativos": ["sem piscina", "nao possui piscina", "nao tem piscina", "não possui piscina", "não tem piscina"],
    },
    "churrasqueira": {
        "positivos": ["churrasqueira"],
        "negativos": ["sem churrasqueira", "nao possui churrasqueira", "nao tem churrasqueira", "não possui churrasqueira", "não tem churrasqueira"],
    },
    "area_gourmet": {
        "positivos": ["area gourmet", "espaco gourmet", "varanda gourmet", "área gourmet", "espaço gourmet"],
        "negativos": [
            "sem area gourmet", "sem espaco gourmet", "sem varanda gourmet",
            "nao possui area gourmet", "nao possui espaco gourmet", "nao tem area gourmet", "nao tem espaco gourmet",
            "não possui área gourmet", "não possui espaço gourmet", "não tem área gourmet", "não tem espaço gourmet",
        ],
    },
    "quintal_area_externa": {
        "positivos": ["quintal", "area externa", "área externa"],
        "negativos": [
            "sem quintal", "sem area externa", "nao possui quintal", "nao tem quintal",
            "nao possui area externa", "nao tem area externa", "não possui quintal", "não tem quintal",
            "não possui área externa", "não tem área externa",
        ],
    },
    "varanda": {
        "positivos": ["varanda", "sacada"],
        "negativos": [
            "sem varanda", "sem sacada", "nao possui varanda", "nao tem varanda",
            "nao possui sacada", "nao tem sacada", "não possui varanda", "não tem varanda",
            "não possui sacada", "não tem sacada",
        ],
    },
    "elevador": {
        "positivos": ["elevador"],
        "negativos": ["sem elevador", "nao possui elevador", "nao tem elevador", "não possui elevador", "não tem elevador"],
    },
    "portaria": {
        "positivos": ["portaria", "porteiro"],
        "negativos": [
            "sem portaria", "sem porteiro", "nao possui portaria", "nao tem portaria",
            "nao possui porteiro", "nao tem porteiro", "não possui portaria", "não tem portaria",
            "não possui porteiro", "não tem porteiro",
        ],
    },
    "academia": {
        "positivos": ["academia", "fitness"],
        "negativos": ["sem academia", "nao possui academia", "nao tem academia", "não possui academia", "não tem academia"],
    },
    "salao_festas": {
        "positivos": ["salao de festas", "salão de festas"],
        "negativos": [
            "sem salao de festas", "nao possui salao de festas", "nao tem salao de festas",
            "sem salão de festas", "não possui salão de festas", "não tem salão de festas",
        ],
    },
    "playground": {
        "positivos": ["playground", "parquinho"],
        "negativos": [
            "sem playground", "sem parquinho", "nao possui playground", "nao tem playground",
            "nao possui parquinho", "nao tem parquinho", "não possui playground", "não tem playground",
        ],
    },
    "armarios_planejados": {
        "positivos": [
            "armarios planejados", "armário planejado", "armários planejados",
            "moveis planejados", "móveis planejados", "cozinha planejada",
        ],
        "negativos": [
            "sem armarios planejados", "sem moveis planejados", "sem móveis planejados",
            "nao possui armarios planejados", "nao tem armarios planejados",
            "não possui armários planejados", "não tem armários planejados",
        ],
    },
}


def _normalizar_texto(valor) -> str:
    """Converte valor em texto minusculo, sem acentos e com espacos normalizados."""
    if valor is None:
        return ""
    if isinstance(valor, (dict, list, tuple, set)):
        try:
            valor = json.dumps(valor, ensure_ascii=False)
        except Exception:
            valor = str(valor)
    texto = str(valor).lower()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def _para_float(valor) -> float | None:
    """Converte numeros ou strings numericas para float; retorna None para ausentes/invalidos."""
    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        numero = float(valor)
        return numero if numero > 0 else None

    texto = str(valor).strip()
    if not texto:
        return None

    texto = re.sub(r"[^0-9,.-]", "", texto)
    if not texto:
        return None

    # Formatos BR: 1.234,56 -> 1234.56; 123,45 -> 123.45
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    else:
        # Se houver varios pontos, trata como separador de milhar.
        if texto.count(".") > 1:
            texto = texto.replace(".", "")

    try:
        numero = float(texto)
        return numero if numero > 0 else None
    except (ValueError, TypeError):
        return None


def _obter_area_construida(imovel: dict) -> float | None:
    """Busca a melhor chave disponivel para area construida/privativa."""
    for chave in ("area", "area_construida", "usableArea", "usable_area", "builtArea", "built_area"):
        numero = _para_float(imovel.get(chave))
        if numero is not None:
            return numero
    return None


def _obter_area_terreno(imovel: dict) -> float | None:
    """Busca a melhor chave disponivel para area de terreno/lote."""
    for chave in ("area_terreno", "lotArea", "lot_area", "landArea", "land_area"):
        numero = _para_float(imovel.get(chave))
        if numero is not None:
            return numero
    return None


def _eh_casa(imovel: dict) -> bool:
    """Detecta tipos residenciais do grupo casa/sobrado sem confundir com apartamento."""
    tipo = _normalizar_texto(imovel.get("propertyType") or imovel.get("tipo") or "")
    if any(x in tipo for x in ("apartamento", "apartment", "flat", "cobertura")):
        return False
    return any(x in tipo for x in ("casa", "house", "sobrado", "village"))


def _montar_texto_caracteristicas(imovel: dict) -> str:
    """Junta somente campos textuais/amenities usados na extracao objetiva."""
    partes = []
    for chave in ("title", "titulo", "description", "descricao", "amenities"):
        valor = imovel.get(chave)
        if valor not in (None, "", [], {}):
            partes.append(_normalizar_texto(valor))
    return " | ".join(p for p in partes if p)


def _extrair_caracteristicas(imovel: dict) -> dict:
    """
    Retorna True/False/None para cada caracteristica.

    True  = ha evidencia positiva.
    False = ha evidencia explicita de ausencia.
    None  = nao ha informacao suficiente.

    A negacao e verificada antes do termo positivo para evitar que
    "sem piscina" seja interpretado como piscina=True.
    """
    texto = _montar_texto_caracteristicas(imovel)
    resultado = {}

    for nome, regras in CARACTERISTICAS_PRE_CLASSIFICACAO.items():
        negativos = [_normalizar_texto(x) for x in regras["negativos"]]
        positivos = [_normalizar_texto(x) for x in regras["positivos"]]

        if any(termo and termo in texto for termo in negativos):
            resultado[nome] = False
        elif any(termo and termo in texto for termo in positivos):
            resultado[nome] = True
        else:
            resultado[nome] = None

    return resultado


def _calcular_estatisticas_areas(candidatos: list[dict]) -> dict:
    """Calcula medias descritivas ignorando ausentes, zero e valores invalidos."""
    areas = [a for a in (_obter_area_construida(i) for i in candidatos) if a is not None]
    terrenos = [a for a in (_obter_area_terreno(i) for i in candidatos) if a is not None]

    return {
        "media_area_construida": round(sum(areas) / len(areas), 2) if areas else None,
        "media_area_terreno": round(sum(terrenos) / len(terrenos), 2) if terrenos else None,
        "amostras_area_construida": len(areas),
        "amostras_area_terreno": len(terrenos),
    }


def _pre_classificar(alvo: dict, candidato: dict, caracteristicas_alvo: dict | None = None) -> dict:
    """
    Pre-classificacao objetiva e eliminatoria.

    Regras finais combinadas:
      - diferenca de area construida > 50% em relacao ao alvo -> incompatível;
      - para casas, diferenca de area de terreno > 50% -> incompatível;
      - divergencia explicita em qualquer caracteristica objetiva -> incompatível;
      - dado ausente/desconhecido nunca elimina.
    """
    if caracteristicas_alvo is None:
        caracteristicas_alvo = _extrair_caracteristicas(alvo)
    caracteristicas_candidato = _extrair_caracteristicas(candidato)

    motivos = []
    comparacoes_realizadas = 0

    area_alvo = _obter_area_construida(alvo)
    area_cand = _obter_area_construida(candidato)
    diferenca_area_pct = None

    if area_alvo is not None and area_cand is not None:
        comparacoes_realizadas += 1
        diferenca_area_pct = abs(area_cand - area_alvo) / area_alvo
        if diferenca_area_pct > 0.50:
            motivos.append(
                f"area construida difere {diferenca_area_pct*100:.1f}% do alvo "
                f"({area_cand:.1f}m² vs {area_alvo:.1f}m²; limite 50%)"
            )

    area_terreno_alvo = _obter_area_terreno(alvo)
    area_terreno_cand = _obter_area_terreno(candidato)
    diferenca_terreno_pct = None

    # Area de terreno so e comparada para alvo do grupo casa/sobrado.
    if _eh_casa(alvo) and area_terreno_alvo is not None and area_terreno_cand is not None:
        comparacoes_realizadas += 1
        diferenca_terreno_pct = abs(area_terreno_cand - area_terreno_alvo) / area_terreno_alvo
        if diferenca_terreno_pct > 0.50:
            motivos.append(
                f"area de terreno difere {diferenca_terreno_pct*100:.1f}% do alvo "
                f"({area_terreno_cand:.1f}m² vs {area_terreno_alvo:.1f}m²; limite 50%)"
            )

    divergencias_caracteristicas = []
    for nome in CARACTERISTICAS_PRE_CLASSIFICACAO:
        valor_alvo = caracteristicas_alvo.get(nome)
        valor_cand = caracteristicas_candidato.get(nome)
        if valor_alvo is not None and valor_cand is not None:
            comparacoes_realizadas += 1
            if valor_alvo != valor_cand:
                divergencias_caracteristicas.append(nome)
                alvo_txt = "sim" if valor_alvo else "nao"
                cand_txt = "sim" if valor_cand else "nao"
                motivos.append(f"{nome} divergente (alvo={alvo_txt}, candidato={cand_txt})")

    incompativel = bool(motivos)
    if incompativel:
        classe = "incompativel"
    elif comparacoes_realizadas == 0:
        classe = "dados_insuficientes"
    else:
        classe = "compativel"

    return {
        "classe": classe,
        "elegivel_llm": not incompativel,
        "enviado_llm": False,
        "motivos_incompatibilidade": motivos,
        "area_construida": {
            "alvo": area_alvo,
            "candidato": area_cand,
            "diferenca_percentual": round(diferenca_area_pct * 100, 2) if diferenca_area_pct is not None else None,
            "limite_percentual": 50,
        },
        "area_terreno": {
            "alvo": area_terreno_alvo,
            "candidato": area_terreno_cand,
            "diferenca_percentual": round(diferenca_terreno_pct * 100, 2) if diferenca_terreno_pct is not None else None,
            "limite_percentual": 50,
            "aplicavel": bool(_eh_casa(alvo)),
        },
        "caracteristicas_alvo": caracteristicas_alvo,
        "caracteristicas_candidato": caracteristicas_candidato,
        "divergencias_caracteristicas": divergencias_caracteristicas,
    }


# =============================================================================
# BLOCO 2 - SIMILARIDADE NUMERICA
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
# BLOCO 3 - CLUSTERING VIA LLM
# =============================================================================

def _formatar_caracteristicas_prompt(imovel: dict) -> str:
    """Formata caracteristicas objetivas sem incluir score numerico."""
    car = _extrair_caracteristicas(imovel)
    partes = []
    for nome, valor in car.items():
        if valor is True:
            partes.append(f"{nome}=sim")
        elif valor is False:
            partes.append(f"{nome}=nao")
        else:
            partes.append(f"{nome}=nao_informado")
    return ", ".join(partes)


def _montar_prompt_clustering(alvo: dict, candidatos: list[dict]) -> str:
    """
    Prompt compacto para caber no limite de 8000 tokens do Groq free tier.

    Os candidatos ja passaram pela pre-classificacao objetiva.
    O score numerico NAO e colocado no prompt para nao ancorar a LLM.
    """
    # Alvo: formato de linha unica compacta
    terreno_alvo = _obter_area_terreno(alvo)
    alvo_resumo = (
        f"Tipo={alvo.get('propertyType','?')} | "
        f"Area={alvo.get('area','?')}m² | "
        f"Quartos={alvo.get('bedrooms','?')} | "
        f"Banheiros={alvo.get('bathrooms','?')} | "
        f"Vagas={alvo.get('parkingSpaces','?')} | "
        f"Bairro={alvo.get('neighborhood','?')} | "
        f"Rua={alvo.get('street','?')}"
    )
    if terreno_alvo:
        alvo_resumo += f" | Terreno={terreno_alvo:.0f}m²"

    # Candidatos: 1 linha por candidato (maximo ~80 chars cada)
    linhas = []
    for idx, c in enumerate(candidatos, 1):
        area_t = _obter_area_terreno(c)
        linha = (
            f"[{idx}] {c.get('propertyType','?')} "
            f"{c.get('area','?')}m² "
            f"{c.get('bedrooms','?')}q "
            f"{c.get('bathrooms','?')}b "
            f"{c.get('parkingSpaces','?')}v "
            f"R${c.get('pricePerSqm','?')}/m² "
            f"{(c.get('neighborhood') or '?')[:15]} "
            f"{(c.get('street') or '?')[:20]}"
        )
        if area_t:
            linha += f" T={area_t:.0f}"
        linhas.append(linha)

    candidatos_texto = "\n".join(linhas)

    prompt = f"""Classifique candidatos como A (comparavel) ou B (nao comparavel) em relacao ao alvo.
Candidatos ja passaram por filtro de area (±50%) e caracteristicas objetivas em Python.

ALVO: {alvo_resumo}

CANDIDATOS:
{candidatos_texto}

REGRAS:
- A: score>=60, B: score<60
- Tipo/uso compativeis, localizacao e area sao prioritarios
- Quartos e configuracao geral sao relevantes
- Banheiros/vagas/diferenciais sao secundarios
- Preco nunca elimina sozinho
- Campo ausente = desconhecido, nao ausencia
- Diferencas pequenas isoladas nao causam B

RESPONDA JSON array:
[{{"id":1,"cluster":"A","score_similaridade":85,"justificativa":"..."}},...]
Todos os {len(candidatos)} IDs devem aparecer. Justificativa curta."""

    return prompt

def _chamar_llm(prompt: str) -> str:
    """
    Chama a LLM com cadeia de fallback:
      1. Groq (GROQ_API_KEY) — openai/gpt-oss-120b (principal)
      2. Gemini — gemini-3.5-flash-lite (primeiro fallback)
      3. NVIDIA NIM — meta/llama-3.3-70b-instruct (ultimo fallback, timeout 30s)
      4. Se tudo falhar → retorna "" (fallback numerico)
    """
    import time as t_mod

    # Tentativa 1: Groq (principal)
    t0 = t_mod.time()
    resposta = _chamar_groq(prompt, os.getenv("GROQ_API_KEY", ""), model="openai/gpt-oss-120b")
    if resposta:
        logger.info(f"[Ag2][Clustering] LLM respondeu: Groq openai/gpt-oss-120b em {t_mod.time()-t0:.1f}s")
        return resposta

    # Tentativa 1b: Groq conta 2
    groq_key_2 = os.getenv("GROQ_API_KEY_2", "")
    if groq_key_2:
        logger.info("[Ag2][Clustering] Groq 1 falhou — tentando GROQ_API_KEY_2...")
        t0 = t_mod.time()
        resposta = _chamar_groq(prompt, groq_key_2, model="openai/gpt-oss-120b")
        if resposta:
            logger.info(f"[Ag2][Clustering] LLM respondeu: Groq KEY2 em {t_mod.time()-t0:.1f}s")
            return resposta

    # Tentativa 2: Gemini (primeiro fallback)
    google_key = os.getenv("GOOGLE_API_KEY_2", "") or os.getenv("GOOGLE_API_KEY", "")
    if google_key:
        logger.info("[Ag2][Clustering] Groq falhou — tentando Gemini...")
        t0 = t_mod.time()
        resposta = _chamar_gemini(prompt, google_key)
        if resposta:
            logger.info(f"[Ag2][Clustering] LLM respondeu: Gemini em {t_mod.time()-t0:.1f}s")
            return resposta

    # Tentativa 3: NVIDIA NIM (ultimo fallback — timeout 30s, sem retries longos)
    nvidia_key = os.getenv("NVIDIA_API_KEY", "")
    if nvidia_key:
        logger.info("[Ag2][Clustering] Gemini falhou — tentando NVIDIA NIM (timeout 30s)...")
        t0 = t_mod.time()
        resposta = _chamar_nvidia(prompt, nvidia_key)
        if resposta:
            logger.info(f"[Ag2][Clustering] LLM respondeu: NVIDIA NIM em {t_mod.time()-t0:.1f}s")
            return resposta

    logger.warning("[Ag2][Clustering] Todas as LLMs falharam — usando fallback numerico")
    return ""


def _chamar_nvidia(prompt: str, api_key: str) -> str:
    """Chama NVIDIA NIM (meta/llama-3.3-70b-instruct). Timeout 30s, sem retries longos."""
    if not api_key:
        return ""
    try:
        from openai import OpenAI
        import httpx
        client = OpenAI(
            base_url="https://integrate.api.nvidia.com/v1",
            api_key=api_key,
            timeout=httpx.Timeout(30.0, connect=10.0),
            max_retries=0,
        )

        response = client.chat.completions.create(
            model="meta/llama-3.3-70b-instruct",
            messages=[
                {"role": "system", "content": "Responda SOMENTE com JSON valido, sem markdown, sem texto extra."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=4096,
        )

        texto = response.choices[0].message.content or ""
        if texto:
            logger.info(f"    [LLM] NVIDIA NIM meta/llama-3.3-70b-instruct respondeu OK")
        return texto
    except Exception as e:
        logger.warning(f"    [LLM] NVIDIA NIM falhou: {e}")
        return ""


def _chamar_groq(prompt: str, api_key: str, model: str = "openai/gpt-oss-120b") -> str:
    """Chama Groq com Structured Outputs (JSON Schema strict). Retorna "" se falhar."""
    if not api_key:
        return ""
    try:
        from groq import Groq
        client = Groq(api_key=api_key)

        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            reasoning_effort="low",
            reasoning_format="hidden",
            temperature=0.1,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "classificacao_comparaveis",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "classificacao": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "id": {"type": "integer"},
                                        "cluster": {"type": "string", "enum": ["A", "B"]},
                                        "score_similaridade": {"type": "integer"},
                                        "justificativa": {"type": "string"}
                                    },
                                    "required": ["id", "cluster", "score_similaridade", "justificativa"],
                                    "additionalProperties": False
                                }
                            }
                        },
                        "required": ["classificacao"],
                        "additionalProperties": False
                    }
                }
            },
            max_completion_tokens=6000,
        )

        texto = response.choices[0].message.content or ""
        if texto:
            logger.info(f"    [LLM] Groq {model} respondeu OK")
        return texto
    except Exception as e:
        logger.warning(f"    [LLM] Groq {model} falhou: {e}")
        return ""


def _chamar_gemini(prompt: str, api_key: str) -> str:
    """Chama Gemini (gemini-3.5-flash-lite) com resposta JSON forcada. Retorna "" se falhar."""
    if not api_key:
        return ""
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-3.5-flash-lite",
            contents=[types.Content(role="user", parts=[types.Part.from_text(text=prompt)])],
            config=types.GenerateContentConfig(
                temperature=0,
                response_mime_type="application/json",
            ),
        )
        logger.info("    [LLM] Gemini 3.5 Flash Lite respondeu OK")
        return response.text or ""
    except Exception as e:
        logger.warning(f"    [LLM] Gemini falhou: {e}")
        return ""


def _parsear_resposta_llm(resposta: str, candidatos: list[dict]) -> list[dict]:
    """
    Parseia a resposta JSON da LLM e aplica nos candidatos.
    Se a LLM falhar, usa fallback baseado no score numerico.
    """
    # Remove bloco <think>...</think> se presente
    if '</think>' in resposta:
        resposta = resposta.split('</think>', 1)[1].strip()
    resposta = re.sub(r'```json\s*', '', resposta)
    resposta = re.sub(r'```\s*', '', resposta)
    
    # Tenta extrair JSON da resposta
    # Primeiro tenta achar objeto com "classificacao"
    m = re.search(r'\{[\s\S]*"classificacao"[\s\S]*\}', resposta)
    if not m:
        # Fallback: tenta achar um array direto (Gemini pode retornar só o array)
        m_arr = re.search(r'\[[\s\S]*\]', resposta)
        if m_arr:
            try:
                arr = json.loads(m_arr.group(0))
                if isinstance(arr, list) and len(arr) > 0:
                    # Wrapa em {"classificacao": [...]}
                    m_text = json.dumps({"classificacao": arr})
                    m = type('Match', (), {'group': lambda self, x=0: m_text})()
            except json.JSONDecodeError:
                pass
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
            candidatos[idx]["justificativa"] = item.get("justificativa", "")
            candidatos[idx]["classificado_por"] = "llm"
            # Score da LLM (0-100) sobrescreve o numérico se disponivel
            llm_score = item.get("score_similaridade")
            if llm_score is not None:
                candidatos[idx]["score_similaridade"] = float(llm_score) / 100.0  # normaliza pra 0-1

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
            c["classificado_por"] = "fallback_numerico"
        else:
            c["cluster"] = "B"
            c["justificativa"] = f"Score numerico {score:.2f} < {THRESHOLD} (threshold)"
            c["classificado_por"] = "fallback_numerico"

    return ordenados


# =============================================================================
# BLOCO 4 - FUNCAO PUBLICA
# =============================================================================

def identificar_comparaveis(
    imovel_alvo: dict,
    imoveis_coletados: Optional[list[dict]] = None,
    arquivo_entrada: str = "imoveis_completos_ag1.json",
    arquivo_saida: str = "imoveis_comparaveis_ag2.json",
    usar_llm: bool = True,
) -> dict:
    """
    Identifica comparaveis com pre-classificacao objetiva + score numerico + LLM.

    Ordem:
      1. carrega dados;
      2. separa terrenos;
      3. calcula medias descritivas de area;
      4. pre-classifica e elimina incompatibilidades objetivas;
      5. calcula score numerico para ordenar/priorizar;
      6. envia ate 30 sobreviventes para LLM em lotes de ate 15;
      7. excedentes usam fallback numerico;
      8. junta Cluster A, Cluster B e terrenos sem perder candidatos.
    """
    logger.info("=" * 60)
    logger.info("AGENTE 2: IDENTIFICADOR DE COMPARAVEIS")
    logger.info("=" * 60)

    # ── 1. CARREGA DADOS ───────────────────────────────────────────
    if imoveis_coletados is None:
        caminho = os.path.join(DATA_DIR, arquivo_entrada)
        if not os.path.exists(caminho):
            caminho = os.path.join(DATA_DIR, "imoveis_coletados_ag1.json")
        if not os.path.exists(caminho):
            logger.error("Nenhum arquivo de imoveis encontrado")
            return {"imovel_alvo": imovel_alvo, "comparaveis": [], "resumo": {}}

        with open(caminho, "r", encoding="utf-8") as f:
            imoveis_coletados = json.load(f)
        logger.info(f"Carregados: {len(imoveis_coletados)} imoveis de {caminho}")

    # Trabalha sobre uma lista concreta.
    imoveis_coletados = list(imoveis_coletados or [])

    # ── 2. SEPARA TERRENOS ─────────────────────────────────────────
    terrenos = [i for i in imoveis_coletados if (i.get("propertyType") or "").lower() == "terrenos"]
    filtrados = [i for i in imoveis_coletados if (i.get("propertyType") or "").lower() != "terrenos"]
    logger.info(
        f"[Ag2][PreClassificacao] Recebidos construidos: {len(filtrados)} | "
        f"terrenos separados: {len(terrenos)}"
    )

    # ── 3. MEDIAS DESCRITIVAS ──────────────────────────────────────
    estatisticas_areas = _calcular_estatisticas_areas(filtrados)
    area_alvo = _obter_area_construida(imovel_alvo)
    terreno_alvo = _obter_area_terreno(imovel_alvo)
    caracteristicas_alvo = _extrair_caracteristicas(imovel_alvo)

    logger.info(
        f"[Ag2][PreClassificacao] Media area construida: "
        f"{estatisticas_areas['media_area_construida']} "
        f"(n={estatisticas_areas['amostras_area_construida']})"
    )
    logger.info(
        f"[Ag2][PreClassificacao] Media area terreno: "
        f"{estatisticas_areas['media_area_terreno']} "
        f"(n={estatisticas_areas['amostras_area_terreno']})"
    )
    logger.info(
        f"[Ag2][PreClassificacao] Referencia REAL do alvo: "
        f"area={area_alvo}m² | terreno={terreno_alvo}m²"
    )
    logger.info(
        "[Ag2][PreClassificacao] Caracteristicas alvo: "
        + json.dumps(caracteristicas_alvo, ensure_ascii=False)
    )

    # ── 4. PRE-CLASSIFICACAO ELIMINATORIA ──────────────────────────
    elegiveis = []
    incompativeis_pre = []

    for im in filtrados:
        pre = _pre_classificar(imovel_alvo, im, caracteristicas_alvo=caracteristicas_alvo)
        im["pre_classificacao"] = pre

        if pre["elegivel_llm"]:
            elegiveis.append(im)
        else:
            # Mantem no resultado, mas nao gasta LLM.
            im["cluster"] = "B"
            im["ranking_llm"] = None
            im["classificado_por"] = "python_pre_classificacao"
            motivos = pre.get("motivos_incompatibilidade") or []
            im["justificativa"] = "Pre-classificacao: " + "; ".join(motivos)
            incompativeis_pre.append(im)

    logger.info(
        f"[Ag2][PreClassificacao] compativeis/dados_insuficientes={len(elegiveis)} | "
        f"incompativeis={len(incompativeis_pre)}"
    )

    # ── 5. SCORE NUMERICO ──────────────────────────────────────────
    # Calcula para todos os construidos por compatibilidade de saida/auditoria,
    # mas APENAS os elegiveis podem seguir para LLM.
    for im in filtrados:
        im["score_similaridade"] = _calcular_score_similaridade(imovel_alvo, im)

    elegiveis.sort(key=lambda x: x.get("score_similaridade", 0), reverse=True)

    logger.info("[Ag2][Score] Top 5 entre os sobreviventes da pre-classificacao:")
    for i, im in enumerate(elegiveis[:5]):
        logger.info(
            f"  [{i+1}] score={im.get('score_similaridade', 0):.3f} | "
            f"{im.get('area','?')}m² | {im.get('bedrooms','?')}q | "
            f"{im.get('priceFormatted','?')} | {im.get('street') or im.get('neighborhood','?')}"
        )

    # ── 6. CLUSTERING VIA LLM ──────────────────────────────────────
    MAX_PARA_LLM = 30
    TAMANHO_LOTE = 15

    if usar_llm:
        import time as t_ag2

        candidatos_llm_enviar = elegiveis[:MAX_PARA_LLM]
        candidatos_resto = elegiveis[MAX_PARA_LLM:]

        for im in candidatos_llm_enviar:
            im["pre_classificacao"]["enviado_llm"] = True
        for im in candidatos_resto:
            im["pre_classificacao"]["enviado_llm"] = False

        # Os excedentes nao somem: continuam pelo fallback numerico.
        if candidatos_resto:
            logger.info(
                f"[Ag2][Clustering] {len(candidatos_resto)} candidatos elegiveis fora do top "
                f"{MAX_PARA_LLM}; classificacao por score numerico"
            )
            candidatos_resto = _fallback_numerico(candidatos_resto)

        todos_classificados = []
        lotes = [
            candidatos_llm_enviar[i:i + TAMANHO_LOTE]
            for i in range(0, len(candidatos_llm_enviar), TAMANHO_LOTE)
        ]

        logger.info(
            f"[Ag2][Clustering] Selecionados para LLM: {len(candidatos_llm_enviar)} "
            f"em {len(lotes)} lote(s) de ate {TAMANHO_LOTE}"
        )

        t_inicio_clustering = t_ag2.time()
        for num_lote, lote in enumerate(lotes, 1):
            logger.info(f"[Ag2][Clustering] Lote {num_lote}/{len(lotes)}: {len(lote)} candidatos...")
            t_lote = t_ag2.time()
            prompt = _montar_prompt_clustering(imovel_alvo, lote)
            resposta = _chamar_llm(prompt)

            if resposta:
                logger.info(
                    f"[Ag2][Clustering] Lote {num_lote}: resposta OK "
                    f"({len(resposta)} chars) em {t_ag2.time()-t_lote:.1f}s"
                )
                lote = _parsear_resposta_llm(resposta, lote)
            else:
                logger.warning(f"[Ag2][Clustering] Lote {num_lote}: LLM sem resposta — fallback numerico")
                lote = _fallback_numerico(lote)

            todos_classificados.extend(lote)

            if num_lote < len(lotes):
                t_ag2.sleep(3)

        logger.info(f"[Ag2][Clustering] Tempo total: {t_ag2.time()-t_inicio_clustering:.1f}s")
        classificados_elegiveis = todos_classificados + candidatos_resto
    else:
        logger.info("[Ag2][Clustering] LLM desativada — usando apenas score numerico nos elegiveis")
        classificados_elegiveis = _fallback_numerico(elegiveis)

    # Ranking global somente entre os elegiveis que chegaram ao julgamento final.
    classificados_elegiveis.sort(key=lambda x: x.get("score_similaridade", 0), reverse=True)
    for ranking, c in enumerate(classificados_elegiveis, 1):
        c["ranking_llm"] = ranking

    # ── 7. RESULTADO FINAL ──────────────────────────────────────────
    todos_construidos = classificados_elegiveis + incompativeis_pre

    cluster_a = sorted(
        [c for c in todos_construidos if c.get("cluster") == "A"],
        key=lambda x: x.get("ranking_llm") or 999999,
    )
    cluster_b = [c for c in todos_construidos if c.get("cluster") != "A"]

    for t in terrenos:
        t["cluster"] = "terreno"
        t["ranking_llm"] = None
        t["classificado_por"] = "separacao_tipo"
        t["justificativa"] = "Terreno separado do ranking — tipo incomparavel com imovel construido"

    resultado_final = cluster_a + cluster_b + terrenos

    resumo_pre = {
        "total_construidos": len(filtrados),
        "elegiveis_apos_pre_classificacao": len(elegiveis),
        "incompativeis_pre_classificacao": len(incompativeis_pre),
        "selecionados_para_llm": min(len(elegiveis), MAX_PARA_LLM) if usar_llm else 0,
        "limite_llm": MAX_PARA_LLM,
        "tamanho_lote_llm": TAMANHO_LOTE,
        "regra_area_percentual": 50,
        "caracteristicas_eliminatorias": list(CARACTERISTICAS_PRE_CLASSIFICACAO.keys()),
        "estatisticas_areas": estatisticas_areas,
        "referencia_alvo": {
            "area_construida": area_alvo,
            "area_terreno": terreno_alvo,
        },
        "caracteristicas_alvo": caracteristicas_alvo,
    }

    resumo = {
        "total_analisados": len(filtrados),
        "cluster_a": len(cluster_a),
        "cluster_b": len(cluster_b),
        "terrenos_excluidos": len(terrenos),
        "metodo": (
            "pre_classificacao_python + similaridade_numerica + clustering_llm"
            if usar_llm
            else "pre_classificacao_python + similaridade_numerica"
        ),
        "pre_classificacao": resumo_pre,
    }

    logger.info("=" * 60)
    logger.info(
        f"RESULTADO: {resumo['cluster_a']} similares | {resumo['cluster_b']} nao similares | "
        f"{resumo['terrenos_excluidos']} terrenos separados"
    )
    logger.info(
        f"[Ag2][PreClassificacao] eliminados antes da LLM: "
        f"{resumo_pre['incompativeis_pre_classificacao']}"
    )
    logger.info(f"[Ag2][Clustering] enviados para LLM: {resumo_pre['selecionados_para_llm']}")
    logger.info("=" * 60)

    # ── 8. SALVA ────────────────────────────────────────────────────
    saida = {
        "imovel_alvo": imovel_alvo,
        "comparaveis": resultado_final,
        "terrenos": terrenos,
        "estatisticas_areas": estatisticas_areas,
        "pre_classificacao": resumo_pre,
        "resumo": resumo,
    }

    caminho_saida = os.path.join(DATA_DIR, arquivo_saida)
    with open(caminho_saida, "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=2, default=str)
    logger.info(f"Salvo em: {caminho_saida}")

    return saida


# =============================================================================
# BLOCO 5 - ZONA HOMOGENEA (Google Maps + Vision)
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
    Envia imagem de satelite para analise visual e identificacao da zona homogenea.

    Cadeia de fallback:
      1. NVIDIA NIM (google/gemma-4-31b-it) — VLM com 128k contexto
      2. Gemini (gemini-3.5-flash-lite) — com response_mime_type JSON
      3. Fallback: raio padrao 500m

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

    nvidia_key = os.getenv("NVIDIA_API_KEY", "")
    google_key = os.getenv("GOOGLE_API_KEY", "")
    if not nvidia_key and not google_key:
        logger.warning("Nenhuma API key de visao configurada — usando raio padrao")
        return {"raio_metros": 500}

    # Converte pra JPEG com qualidade 85 (mantém resolução original 1280x1280)
    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(imagem_bytes))
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=85)
        imagem_comprimida = buffer.getvalue()
        img_b64 = base64.b64encode(imagem_comprimida).decode("utf-8")
        img_mime = "image/jpeg"
        logger.info(f"Imagem: {img.width}x{img.height} | {len(imagem_bytes)//1024}KB -> {len(imagem_comprimida)//1024}KB (JPEG 85%)")
    except Exception:
        img_b64 = base64.b64encode(imagem_bytes).decode("utf-8")
        img_mime = "image/png"

    prompt = f"""Analise a imagem de satélite centrada no imóvel (marcador vermelho).
Endereço: {endereco_alvo}

Sugira um raio para a ZONA HOMOGÊNEA usando SOMENTE elementos visíveis.
Não use conhecimento externo. Não faça inferências sobre preço ou perfil socioeconômico.

ANALISE:
1. Padrão construtivo: casas | sobrados | predios_baixos | predios_medios | torres_altas | misto | indefinido
2. Homogeneidade visual: alta | media | baixa | indefinida
3. Densidade urbana: baixa | media | alta | indefinida
4. Transição visual: nenhuma_relevante | proxima | intermediaria | distante | indefinida

RAIO (escolha SOMENTE): 300 | 500 | 700 | 1000 | 1500 metros
300=mudanças próximas | 500=homogêneo entorno | 700=predominante | 1000=amplo | 1500=muito homogêneo

RESPONDA SOMENTE JSON:
{{
  "padrao_construtivo": "...",
  "homogeneidade_visual": "...",
  "densidade_urbana": "...",
  "transicao_visual": "...",
  "raio_sugerido_metros": 700,
  "justificativa_raio": "...",
  "descricao_zona_homogenea": "...",
  "confianca": "alta | media | baixa"
}}"""

    # Tentativa 1: Gemini (principal — rapido e confiavel)
    import time as t_zona
    if google_key:
        t0 = t_zona.time()
        resultado = _chamar_gemini_visao(prompt, imagem_bytes, google_key)
        if resultado:
            logger.info(f"[Ag2][Zona] provedor=Gemini | tempo={t_zona.time()-t0:.1f}s")
            return resultado
        logger.info("[Ag2][Zona] Gemini visao falhou — tentando Groq Vision...")

    # Tentativa 2: Groq Vision (qwen3.6-27b)
    groq_key = os.getenv("GROQ_API_KEY", "")
    if groq_key:
        t0 = t_zona.time()
        resultado = _chamar_groq_visao(prompt, img_b64, img_mime, groq_key)
        if resultado:
            logger.info(f"[Ag2][Zona] provedor=Groq | tempo={t_zona.time()-t0:.1f}s")
            return resultado
        logger.info("[Ag2][Zona] Groq Vision falhou — tentando NVIDIA NIM (timeout 30s)...")

    # Tentativa 3: NVIDIA NIM (ultimo fallback — timeout 30s)
    if nvidia_key:
        t0 = t_zona.time()
        resultado = _chamar_nvidia_visao(prompt, img_b64, img_mime, nvidia_key)
        if resultado:
            logger.info(f"[Ag2][Zona] provedor=NVIDIA | tempo={t_zona.time()-t0:.1f}s")
            return resultado

    return {"raio_metros": 500, "descricao_zona_homogenea": "Analise visual nao disponivel"}


def _chamar_nvidia_visao(prompt: str, img_b64: str, img_mime: str, api_key: str) -> dict | None:
    """Chama NVIDIA NIM (google/gemma-4-31b-it) para analise visual. Timeout 30s, sem retries."""
    try:
        from openai import OpenAI
        import httpx
        client = OpenAI(
            base_url="https://integrate.api.nvidia.com/v1",
            api_key=api_key,
            timeout=httpx.Timeout(30.0, connect=10.0),
            max_retries=0,
        )

        response = client.chat.completions.create(
            model="google/gemma-4-31b-it",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{img_mime};base64,{img_b64}"}
                        }
                    ]
                }
            ],
            temperature=0.1,
            max_tokens=1024,
        )

        texto = response.choices[0].message.content or ""
        logger.info(f"NVIDIA NIM (gemma-4-31b-it) respondeu ({len(texto)} chars)")

        return _parsear_json_zona(texto)

    except Exception as e:
        logger.warning(f"    [LLM] NVIDIA NIM visao falhou: {e}")
        return None


def _chamar_groq_visao(prompt: str, img_b64: str, img_mime: str, api_key: str) -> dict | None:
    """Chama Groq (qwen3.6-27b) com imagem para zona homogenea. Retorna dict ou None."""
    try:
        from groq import Groq
        client = Groq(api_key=api_key)

        response = client.chat.completions.create(
            model="qwen/qwen3.6-27b",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{img_mime};base64,{img_b64}"}
                        }
                    ]
                }
            ],
            temperature=0,
            max_completion_tokens=1024,
        )

        texto = response.choices[0].message.content or ""
        logger.info(f"Groq Vision (qwen3.6-27b) respondeu ({len(texto)} chars)")

        return _parsear_json_zona(texto)

    except Exception as e:
        logger.warning(f"    [LLM] Groq Vision falhou: {e}")
        return None


def _chamar_gemini_visao(prompt: str, imagem_bytes: bytes, api_key: str) -> dict | None:
    """Chama Gemini (gemini-3.5-flash-lite) com imagem e response_mime_type JSON. Retorna dict ou None."""
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=api_key)

        # Envia imagem como bytes inline
        parts = [
            types.Part.from_text(text=prompt),
            types.Part.from_bytes(data=imagem_bytes, mime_type="image/png"),
        ]

        response = client.models.generate_content(
            model="gemini-3.5-flash-lite",
            contents=[types.Content(role="user", parts=parts)],
            config=types.GenerateContentConfig(
                temperature=0,
                response_mime_type="application/json",
            ),
        )
        texto = response.text or ""
        logger.info(f"Gemini visao respondeu ({len(texto)} chars)")

        return _parsear_json_zona(texto)

    except Exception as e:
        logger.warning(f"    [LLM] Gemini visao falhou: {e}")
        return None


def _parsear_json_zona(texto: str) -> dict | None:
    """Parseia o JSON da zona homogenea da resposta da LLM. Retorna dict ou None."""
    # Remove <think>...</think>
    if '</think>' in texto:
        texto = texto.split('</think>', 1)[1].strip()

    # Remove markdown code blocks
    texto = re.sub(r'```json\s*', '', texto)
    texto = re.sub(r'```\s*', '', texto)
    texto = texto.strip()

    # Tenta encontrar JSON balanceado
    inicio = texto.find('{')
    if inicio >= 0:
        nivel = 0
        fim = -1
        for i in range(inicio, len(texto)):
            if texto[i] == '{':
                nivel += 1
            elif texto[i] == '}':
                nivel -= 1
                if nivel == 0:
                    fim = i
                    break
        if fim > inicio:
            bloco = texto[inicio:fim+1]
            try:
                resultado = json.loads(bloco)
                # Valida que tem campos esperados
                if "raio_sugerido_metros" in resultado or "padrao_construtivo" in resultado:
                    # Normaliza raio
                    if "raio_sugerido_metros" in resultado:
                        resultado["raio_metros"] = resultado["raio_sugerido_metros"]
                    raios_validos = [300, 500, 700, 1000, 1500]
                    raio = resultado.get("raio_metros", 700)
                    if isinstance(raio, (int, float)):
                        raio = int(raio)
                        if raio not in raios_validos:
                            raio = min(raios_validos, key=lambda x: abs(x - raio))
                        resultado["raio_metros"] = raio
                        resultado["raio_sugerido_metros"] = raio
                    return resultado
            except json.JSONDecodeError:
                pass


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
    lat_alvo_precomp: float = None,
    lon_alvo_precomp: float = None,
) -> dict:
    """
    Analisa a zona homogenea do imovel alvo e valida os comparaveis.

    FLUXO:
      1. Geocodificacao do endereco alvo (Nominatim → lat/lng)
      2. Geracao da imagem da regiao (Google Maps Static API, hybrid, scale=2, marcador)
      3. Analise visual da regiao (NVIDIA NIM gemma-4-31b-it; fallback: Gemini)
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
    logger.info("ZONA HOMOGENEA: Google Maps + LLM Vision")
    logger.info("=" * 55)

    # ── 1. GEOCODIFICACAO DO ALVO ─────────────────────────────────
    if lat_alvo_precomp and lon_alvo_precomp:
        lat_alvo, lon_alvo = lat_alvo_precomp, lon_alvo_precomp
        logger.info(f"[Ag2][Geo] reutilizando coordenadas do alvo | lat={lat_alvo:.6f} | lon={lon_alvo:.6f}")
    else:
        logger.info("[Ag2][Zona] Geocodificando: %s", endereco_alvo)
        lat_alvo, lon_alvo = _geocodificar(endereco_alvo)
    if not lat_alvo:
        logger.warning("Nao geocodificou o alvo — usando todos os imoveis como confirmados")
        return {
            "zona_homogenea": {},
            "comparaveis_confirmados": imoveis,
            "fora_zona": [],
            "imagem_satelite": None,
        }
    logger.info(f"[Ag2][Zona] Alvo: {lat_alvo:.6f}, {lon_alvo:.6f}")

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
        logger.info("Enviando imagem para cadeia LLM Vision...")
        zona = _analisar_zona_homogenea(imagem, endereco_alvo)
        logger.info(f"Zona: padrao={zona.get('padrao_construtivo','?')} | "
                    f"homogeneidade={zona.get('homogeneidade_visual','?')} | "
                    f"densidade={zona.get('densidade_urbana','?')} | "
                    f"raio={zona.get('raio_sugerido_metros', zona.get('raio_metros','?'))}m")
        # Loga o JSON completo retornado pela LLM
        campos_zona = {k: v for k, v in zona.items() if k != "descricao_zona_homogenea" or "<think>" not in str(v)}
        logger.info(f"Zona JSON: {json.dumps(campos_zona, ensure_ascii=False)}")

    # ── 4. GEOCODING DOS IMOVEIS + CLASSIFICACAO POR DISTANCIA ────
    import time
    raio_zona = zona.get("raio_sugerido_metros", zona.get("raio_metros", 700))
    logger.info(f"Geocodificando {len(imoveis)} imoveis (raio da LLM: {raio_zona}m, minimo: {max(raio_zona, 400)}m)...")

    confirmados = []      # na_zona (por distancia ou por bairro)
    fora = []             # fora_zona

    for idx, im in enumerate(imoveis):
        rua = im.get("street", "")
        bairro = im.get("neighborhood", "")

        # Se já tem coordenadas (Athena), usa direto sem geocodificar
        lat_existente = im.get("lat")
        lon_existente = im.get("lon")
        if lat_existente and lon_existente:
            try:
                lat = float(lat_existente)
                lon = float(lon_existente)
                dist = _distancia_haversine(lat_alvo, lon_alvo, lat, lon)
                classificacao = _classificar_por_distancia(dist, raio_zona)
                im["distancia_metros"] = round(dist)
                im["classificacao_zona"] = classificacao
                im["coordenadas"] = {"lat": lat, "lon": lon}
                if classificacao == "na_zona":
                    confirmados.append(im)
                else:
                    fora.append(im)
                logger.info(f"  [{idx+1}/{len(imoveis)}] {dist:.0f}m | {classificacao} | {rua or bairro} (coords existentes)")
                continue
            except (ValueError, TypeError):
                pass

        # Se nao tem rua especifica e nao tem coordenadas, nao tem como verificar
        # Descarta — sem localizacao verificavel
        if not rua:
            im["distancia_metros"] = None
            im["classificacao_zona"] = "fora_zona"
            im["coordenadas"] = None
            fora.append(im)
            logger.info(f"  [{idx+1}/{len(imoveis)}] fora_zona (sem localizacao verificavel) | {bairro}")
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
            # Geocoding falhou — sem localizacao verificavel, descarta
            im["distancia_metros"] = None
            im["classificacao_zona"] = "fora_zona"
            im["coordenadas"] = None
            fora.append(im)
            logger.info(f"  [{idx+1}/{len(imoveis)}] fora_zona (geocoding falhou) | {rua}")

    # ── 5. RESUMO ─────────────────────────────────────────────────
    raio_usado = max(raio_zona, 400)
    logger.info("=" * 55)
    logger.info(f"[Ag2][Zona] raio={raio_zona}m | na_zona={len(confirmados)} | fora_zona={len(fora)}")
    logger.info("=" * 55)

    resultado = {
        "zona_homogenea": zona,
        "comparaveis_confirmados": confirmados,
        "fora_zona": fora,
        "imagem_satelite": img_path,
        "coordenadas_alvo": {"lat": lat_alvo, "lon": lon_alvo},
    }

    # Salva resultado em JSON
    caminho_saida = os.path.join(DATA_DIR, "zona_homogenea_ag2.json")
    with open(caminho_saida, "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2, default=str)
    logger.info(f"Salvo em: {caminho_saida}")

    return resultado