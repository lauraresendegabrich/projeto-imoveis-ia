"""
Agente 2 - Identificador de Imoveis Comparaveis
=================================================

RESPONSABILIDADE:
    Recebe os imoveis coletados pelo Agente 1 e identifica quais sao
    realmente comparaveis. Primeiro executa uma pre-classificacao
    deterministica em Python, depois calcula score numerico para ordenar
    os sobreviventes e, por fim, usa LLM para o julgamento final de TODOS
    os candidatos que passaram pela pre-classificacao, processados em lotes.
    Depois valida geograficamente com imagem
    de satelite.

ENTRADA:
    - data/imoveis_completos_ag1.json (saida do Agente 1; fallback para imoveis_coletados_ag1.json)
    - imovel_alvo (dict com tipo, area, cidade e demais caracteristicas)
    - run_id opcional para isolar arquivos de uma avaliacao

SAIDA:
    - data/[run_id]/imoveis_comparaveis_ag2.json (pre-classificacao + ranking + clusters)
    - data/[run_id]/zona_homogenea_ag2.json (confirmados + nao verificados + terrenos + coordenadas alvo)
    - data/[run_id]/satelite_zona_homogenea_ag2.png (imagem com marcador)
    Sem run_id, mantem os caminhos legados diretamente em data/.

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
      - media da area de terreno SOMENTE quando o alvo e casa/sobrado

    A media e descritiva. O corte usa a area REAL do imovel alvo.

    Regra eliminatoria de area:
      - area construida: diferenca > 30% em relacao ao alvo -> incompatível
      - area de terreno: diferenca > 30% em relacao ao alvo -> incompatível
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

    Processamento:
      - TODOS os candidatos que passaram pela pre-classificacao vao para a LLM
      - processamento em lotes de ate 15 candidatos
      - nao existe limite total de candidatos para a LLM
      - o score numerico serve apenas para ordenar a sequencia dos lotes

    Cadeia de fallback:
      1. Qwen3-VL-8B — Google Colab
      2. Groq (GROQ_API_KEY) — openai/gpt-oss-120b
      3. Groq (GROQ_API_KEY_2) — openai/gpt-oss-120b
      4. Gemini — gemini-3.5-flash-lite
      5. NVIDIA NIM — openai/gpt-oss-20b
      6. Toda resposta e validada integralmente antes de ser aceita.
      7. Se NENHUM candidato for julgado por LLM, usa top 20 do ranking Python como fallback.

    A LLM recebe somente candidatos sem incompatibilidade objetiva detectada
    e realiza o julgamento final de comparabilidade.

  ETAPA 5 — ZONA HOMOGENEA
  ─────────────────────────
    Mantem a logica existente: geocodificacao do alvo, imagem hybrid,
    analise visual da zona e classificacao por distancia.

QUEM USA A SAIDA:
─────────────────
    Agente 3 -> zona_homogenea_ag2.json (Cluster A na_zona/fallback -> analisa fotos)
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

DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
os.makedirs(DATA_DIR, exist_ok=True)

RAIO_FALLBACK_METROS = 500
TOP_N_FALLBACK_PYTHON = 20

# Pre-classificacao de area (Agente 2).
# Limite padrao: candidato incompativel quando a area difere mais que isto do alvo.
LIMITE_AREA_PRE_CLASSIFICACAO = 0.30
# Relaxamento adaptativo: se o limite padrao deixar menos elegiveis que este minimo,
# a pre-classificacao e refeita com um limite mais generoso (abaixo) para nao
# estrangular a amostra em bairros com poucos anuncios comparaveis.
MIN_ELEGIVEIS_PRE_CLASSIFICACAO = 8
LIMITE_AREA_PRE_CLASSIFICACAO_RELAXADO = 0.45

# Zona homogenea: minimo de comparaveis confirmados (na_zona) desejado.
# Se a validacao geografica confirmar menos que isto, os imoveis "zona_nao_verificada"
# (geocodificados por bairro fora do raio, sem posicao propria) sao anexados como
# fallback de baixa confianca, para nao deixar o Agente 3/5 sem amostra (Opcao B).
MIN_CONFIRMADOS_ZONA = 3

# Barreira de sanidade para o raio livre escolhido pela LLM de visao.
# A LLM continua livre para escolher qualquer valor (437, 615, 882, 1340...),
# mas valores absurdos por erro de geracao sao limitados a esta faixa.
RAIO_MINIMO_SEGURANCA = 100
RAIO_MAXIMO_SEGURANCA = 3000


def _sanitizar_run_id(run_id: str | None) -> str | None:
    """Normaliza run_id para uso seguro em nome de diretorio."""
    if not run_id:
        return None
    seguro = re.sub(r"[^a-zA-Z0-9_.-]", "_", str(run_id).strip())[:80]
    return seguro or None


def _obter_data_dir(run_id: str | None = None) -> str:
    """Retorna diretorio da execucao; sem run_id mantem compatibilidade legada."""
    run_id = _sanitizar_run_id(run_id)
    pasta = os.path.join(DATA_DIR, f"run_{run_id}") if run_id else DATA_DIR
    os.makedirs(pasta, exist_ok=True)
    return pasta


def _salvar_json_atomico(dados, caminho: str) -> None:
    """Grava JSON sem deixar arquivo parcial se o processo for interrompido."""
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    temporario = f"{caminho}.tmp"
    with open(temporario, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2, default=str)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporario, caminho)


def _salvar_bytes_atomico(dados: bytes, caminho: str) -> None:
    """Grava bytes de forma atomica."""
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    temporario = f"{caminho}.tmp"
    with open(temporario, "wb") as f:
        f.write(dados)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporario, caminho)


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
    """Detecta tipos residenciais do grupo casa/sobrado sem confundir com apartamento/terreno."""
    tipo = _normalizar_texto(imovel.get("propertyType") or imovel.get("tipo") or "")
    if _eh_terreno(imovel):
        return False
    if any(x in tipo for x in ("apartamento", "apartment", "flat", "cobertura")):
        return False
    return any(x in tipo for x in ("casa", "house", "sobrado", "village"))


def _eh_terreno(imovel: dict) -> bool:
    """Detecta terreno/lote mesmo quando a origem usa nomenclaturas diferentes."""
    tipo = _normalizar_texto(imovel.get("propertyType") or imovel.get("tipo") or "")
    if not tipo:
        return False
    tipo_tokens = tipo.replace("_", " ").replace("-", " ")
    return bool(re.search(r"\b(terreno|terrenos|lote|lotes|land|lot|allotment)\b", tipo_tokens))


def _obter_numero_endereco(imovel: dict) -> str:
    """Busca numero do endereco em chaves comuns sem inventar valor."""
    for chave in ("number", "numero", "streetNumber", "street_number", "addressNumber", "numero_endereco"):
        valor = imovel.get(chave)
        if valor not in (None, ""):
            return str(valor).strip()
    return ""


def _validar_imovel_alvo(imovel_alvo: dict) -> list[str]:
    """Valida dados essenciais e retorna alertas nao bloqueantes."""
    if not isinstance(imovel_alvo, dict):
        raise ValueError("imovel_alvo deve ser um dict")

    tipo = imovel_alvo.get("propertyType") or imovel_alvo.get("tipo")
    if not tipo:
        raise ValueError("Agente 2: tipo do imovel alvo e obrigatorio (propertyType/tipo)")

    if _obter_area_construida(imovel_alvo) is None and not _eh_terreno(imovel_alvo):
        raise ValueError("Agente 2: area construida do imovel alvo e obrigatoria")

    cidade = imovel_alvo.get("city") or imovel_alvo.get("cidade")
    if not cidade:
        raise ValueError("Agente 2: cidade do imovel alvo e obrigatoria")

    alertas = []
    bairro = imovel_alvo.get("neighborhood") or imovel_alvo.get("bairro")
    if not bairro:
        alertas.append("Bairro do imovel alvo nao informado; validacao geografica pode ter menor precisao")
    if _eh_casa(imovel_alvo) and _obter_area_terreno(imovel_alvo) is None:
        alertas.append("Area de terreno do alvo nao informada; comparacao de terreno nao sera eliminatoria")
    return alertas

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


def _calcular_estatisticas_areas(candidatos: list[dict], imovel_alvo: dict) -> dict:
    """
    Calcula medias descritivas ignorando ausentes, zero e valores invalidos.

    A area de terreno e estatistica aplicavel SOMENTE quando o imovel alvo
    pertence ao grupo casa/sobrado. Para apartamento/flat/cobertura,
    media_area_terreno=None e amostras_area_terreno=0.
    """
    areas = [a for a in (_obter_area_construida(i) for i in candidatos) if a is not None]

    terreno_aplicavel = _eh_casa(imovel_alvo)
    if terreno_aplicavel:
        terrenos = [a for a in (_obter_area_terreno(i) for i in candidatos) if a is not None]
    else:
        terrenos = []

    return {
        "media_area_construida": round(sum(areas) / len(areas), 2) if areas else None,
        "media_area_terreno": round(sum(terrenos) / len(terrenos), 2) if terrenos else None,
        "amostras_area_construida": len(areas),
        "amostras_area_terreno": len(terrenos),
        "area_terreno_aplicavel": terreno_aplicavel,
    }


def _pre_classificar(
    alvo: dict,
    candidato: dict,
    caracteristicas_alvo: dict | None = None,
    limite_area_pct: float = LIMITE_AREA_PRE_CLASSIFICACAO,
) -> dict:
    """
    Pre-classificacao objetiva e eliminatoria.

    Regras finais combinadas:
      - diferenca de area construida > limite_area_pct em relacao ao alvo -> incompatível;
      - para casas, diferenca de area de terreno > limite_area_pct -> incompatível;
      - divergencia explicita em qualquer caracteristica objetiva -> incompatível;
      - dado ausente/desconhecido nunca elimina.

    O limite de area e parametrizavel para permitir um relaxamento adaptativo
    quando a pre-classificacao rigida deixa poucos elegiveis (ver identificar_comparaveis).
    """
    if caracteristicas_alvo is None:
        caracteristicas_alvo = _extrair_caracteristicas(alvo)
    caracteristicas_candidato = _extrair_caracteristicas(candidato)

    limite_pct_int = round(limite_area_pct * 100)

    motivos = []
    comparacoes_realizadas = 0

    area_alvo = _obter_area_construida(alvo)
    area_cand = _obter_area_construida(candidato)
    diferenca_area_pct = None

    if area_alvo is not None and area_cand is not None:
        comparacoes_realizadas += 1
        diferenca_area_pct = abs(area_cand - area_alvo) / area_alvo
        if diferenca_area_pct > limite_area_pct:
            motivos.append(
                f"area construida difere {diferenca_area_pct*100:.1f}% do alvo "
                f"({area_cand:.1f}m² vs {area_alvo:.1f}m²; limite {limite_pct_int}%)"
            )

    terreno_aplicavel = _eh_casa(alvo)
    area_terreno_alvo = _obter_area_terreno(alvo) if terreno_aplicavel else None
    area_terreno_cand = _obter_area_terreno(candidato) if terreno_aplicavel else None
    diferenca_terreno_pct = None

    # Area de terreno so existe nesta etapa quando o alvo e casa/sobrado.
    if terreno_aplicavel and area_terreno_alvo is not None and area_terreno_cand is not None:
        comparacoes_realizadas += 1
        diferenca_terreno_pct = abs(area_terreno_cand - area_terreno_alvo) / area_terreno_alvo
        if diferenca_terreno_pct > limite_area_pct:
            motivos.append(
                f"area de terreno difere {diferenca_terreno_pct*100:.1f}% do alvo "
                f"({area_terreno_cand:.1f}m² vs {area_terreno_alvo:.1f}m²; limite {limite_pct_int}%)"
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
            "limite_percentual": limite_pct_int,
        },
        "area_terreno": {
            "alvo": area_terreno_alvo,
            "candidato": area_terreno_cand,
            "diferenca_percentual": round(diferenca_terreno_pct * 100, 2) if diferenca_terreno_pct is not None else None,
            "limite_percentual": limite_pct_int,
            "aplicavel": terreno_aplicavel,
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
    Score numerico 0..1 usado para ordenar candidatos antes da LLM.

    Corrige dois problemas importantes:
      - normaliza strings numericas antes de comparar;
      - diferencia zero real (ex.: 0 vagas/0 quartos) de dado ausente (None).

    Campos ausentes em apenas um dos lados recebem similaridade 0.5 no peso.
    Quando ambos estao ausentes, o campo e ignorado.
    """
    pesos = {
        "area": 0.30,
        "bedrooms": 0.25,
        "pricePerSqm": 0.20,
        "bathrooms": 0.15,
        "parkingSpaces": 0.10,
    }

    def _numero_score(imovel: dict, campo: str) -> float | None:
        if campo == "area":
            return _obter_area_construida(imovel)
        if campo == "pricePerSqm":
            valor = imovel.get("pricePerSqm")
            if valor in (None, ""):
                # Calcula apenas se houver preco e area validos.
                preco = _para_float(imovel.get("price") or imovel.get("preco"))
                area = _obter_area_construida(imovel)
                if preco is not None and area is not None and area > 0:
                    return preco / area
                return None
            return _para_float(valor)

        valor = imovel.get(campo)
        if valor is None or valor == "" or isinstance(valor, bool):
            return None
        try:
            texto = str(valor).strip().replace(",", ".")
            numero = float(texto)
            # Para quartos/banheiros/vagas, zero e valor valido.
            return numero if numero >= 0 else None
        except (TypeError, ValueError):
            return None

    score_total = 0.0
    peso_total = 0.0

    for campo, peso in pesos.items():
        val_alvo = _numero_score(alvo, campo)
        val_cand = _numero_score(candidato, campo)

        if val_alvo is not None and val_cand is not None:
            # Dois zeros representam igualdade perfeita.
            if val_alvo == 0 and val_cand == 0:
                similaridade = 1.0
            else:
                maximo = max(abs(val_alvo), abs(val_cand))
                if maximo == 0:
                    similaridade = 1.0
                else:
                    distancia = abs(val_alvo - val_cand) / maximo
                    similaridade = max(0.0, 1.0 - distancia)
            score_total += similaridade * peso
            peso_total += peso
        elif val_alvo is not None or val_cand is not None:
            score_total += 0.5 * peso
            peso_total += peso
        # ambos ausentes -> ignora

    if peso_total == 0:
        return 0.0
    return round(score_total / peso_total, 4)

def _formatar_caracteristicas_prompt(imovel: dict) -> str:
    """Formata caracteristicas objetivas extraidas para contexto da LLM."""
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


def _resumir_descricao(imovel: dict, limite: int = 320) -> str:
    """Retorna descricao curta, limpa e sem quebras para caber nos lotes."""
    valor = imovel.get("description") or imovel.get("descricao") or imovel.get("title") or imovel.get("titulo") or ""
    texto = re.sub(r"\s+", " ", str(valor)).strip()
    if not texto:
        return "nao_informada"
    return texto[:limite] + ("..." if len(texto) > limite else "")

def _montar_prompt_clustering(alvo: dict, candidatos: list[dict]) -> str:
    """
    Prompt de comparabilidade sem preco/preco-m2 para evitar circularidade na precificacao.
    Inclui descricao curta e caracteristicas extraidas para dar contexto qualitativo a LLM.
    O score Python tambem nao e enviado, evitando ancoragem.
    """
    terreno_alvo = _obter_area_terreno(alvo) if _eh_casa(alvo) else None
    alvo_resumo = (
        f"Tipo={alvo.get('propertyType') or alvo.get('tipo') or '?'} "
        f"Area={_obter_area_construida(alvo) or '?'}m2 "
        f"Q={alvo.get('bedrooms', '?')} B={alvo.get('bathrooms', '?')} V={alvo.get('parkingSpaces', '?')} "
        f"Bairro={alvo.get('neighborhood') or alvo.get('bairro') or '?'} "
        f"Rua={alvo.get('street') or alvo.get('rua') or '?'}"
    )
    if terreno_alvo is not None:
        alvo_resumo += f" Terreno={terreno_alvo:.0f}m2"

    alvo_car = _formatar_caracteristicas_prompt(alvo)
    alvo_desc = _resumir_descricao(alvo)

    linhas = []
    for idx, c in enumerate(candidatos, 1):
        area_t = _obter_area_terreno(c) if _eh_casa(alvo) else None
        linha = (
            f"[{idx}] Tipo={c.get('propertyType') or c.get('tipo') or '?'} "
            f"Area={_obter_area_construida(c) or '?'}m2 "
            f"Q={c.get('bedrooms', '?')} B={c.get('bathrooms', '?')} V={c.get('parkingSpaces', '?')} "
            f"Bairro={c.get('neighborhood') or c.get('bairro') or '?'} "
            f"Rua={c.get('street') or c.get('rua') or '?'}"
        )
        if area_t is not None:
            linha += f" Terreno={area_t:.0f}m2"
        linha += f"\n    Caracteristicas: {_formatar_caracteristicas_prompt(c)}"
        linha += f"\n    Descricao: {_resumir_descricao(c)}"
        linhas.append(linha)

    candidatos_texto = "\n".join(linhas)

    return f"""Classifique cada candidato como A (comparavel) ou B (nao comparavel) em relacao ao imovel alvo.

Os candidatos ja passaram por uma pre-classificacao Python objetiva de area e divergencias explicitas.
Nao use preco nem valor por m2 como criterio: eles foram deliberadamente removidos para evitar circularidade na avaliacao.
Campo ausente significa DESCONHECIDO, nunca ausencia da caracteristica.

ALVO:
{alvo_resumo}
Caracteristicas: {alvo_car}
Descricao: {alvo_desc}

CANDIDATOS ({len(candidatos)}):
{candidatos_texto}

CRITERIOS DE JULGAMENTO:
1. Tipo/uso e contexto de localizacao sao prioritarios.
2. Area e numero de quartos sao muito relevantes.
3. Banheiros, vagas, terreno e caracteristicas estruturais ajudam a diferenciar o padrao.
4. Use a descricao somente para entender tipologia, padrao e caracteristicas; nao invente dados ausentes.
5. Nao rejeite por uma unica diferenca secundaria. Classifique B quando o CONJUNTO das diferencas tornar o candidato inadequado como referencia de mercado.
6. A = referencia suficientemente semelhante para compor a amostra de comparaveis.
7. B = referencia inadequada para a amostra.
8. score_similaridade deve ser INTEIRO de 0 a 100 e refletir sua propria avaliacao, nao um preco.

RETORNE SOMENTE JSON VALIDO, sem markdown e sem texto externo:
{{"classificacao":[{{"id":1,"cluster":"A","score_similaridade":85,"justificativa":"frase objetiva"}}]}}

REGRAS DE SAIDA OBRIGATORIAS:
- Todos os IDs de 1 a {len(candidatos)} devem aparecer EXATAMENTE uma vez.
- Nao omita candidatos.
- Nao repita IDs.
- cluster deve ser somente "A" ou "B".
- score_similaridade deve ser inteiro entre 0 e 100.
- justificativa deve ser texto nao vazio."""

def _obter_secret(nome: str) -> str:
    """
    Busca primeiro nas variaveis de ambiente.
    Se estiver no Streamlit Cloud, tenta st.secrets.
    """
    valor = os.getenv(nome, "")

    if valor:
        return valor

    try:
        import streamlit as st

        if nome in st.secrets:
            return str(st.secrets[nome])

    except Exception:
        pass

    return ""

def _log_resposta_llm(provider: str, resposta: str):
    """Mostra a resposta completa da LLM nos logs."""

    logger.info("")
    logger.info("=" * 80)
    logger.info(f"[DEBUG LLM] PROVIDER: {provider}")
    logger.info(f"[DEBUG LLM] TAMANHO: {len(resposta or '')} caracteres")
    logger.info("-" * 80)
    logger.info(resposta or "<RESPOSTA VAZIA>")
    logger.info("=" * 80)
    logger.info("")

def _chamar_qwen_colab(
    prompt: str,
    imagem_bytes: bytes | None = None,
    max_new_tokens: int = 1600,
) -> str:
    """
    Chama o Qwen3-VL-8B hospedado no Google Colab.

    Se o Colab estiver offline, houver timeout ou qualquer erro,
    retorna "" para permitir o fallback para os outros providers.
    """
    import base64
    import requests

    url = _obter_secret("QWEN_API_URL").rstrip("/")
    api_key = _obter_secret("QWEN_API_KEY")

    if not url or not api_key:
        logger.info("[QWEN] URL/key nao configuradas")
        return ""

    payload = {
        "prompt": prompt,
        "max_new_tokens": max_new_tokens,
    }

    if imagem_bytes:
        # A API nova aceita uma lista. Na zona homogenea o Agente 2 envia
        # somente uma imagem de satelite.
        payload["imagens_base64"] = [
            base64.b64encode(imagem_bytes).decode("utf-8")
        ]

    headers = {
        "Authorization": f"Bearer {api_key}"
    }

    try:
        response = requests.post(
            f"{url}/gerar",
            json=payload,
            headers=headers,

            # 5s para conectar.
            # Ate 180s para a inferencia.
            timeout=(5, 180),
        )

        if response.status_code != 200:
            logger.warning(
                f"[QWEN] HTTP {response.status_code}: "
                f"{response.text[:300]}"
            )
            return ""

        dados = response.json()

        resposta = str(
            dados.get("resposta") or ""
        ).strip()

        if not resposta:
            logger.warning("[QWEN] Resposta vazia")
            return ""

        num_imagens = dados.get("num_imagens")
        if num_imagens is None:
            num_imagens = 1 if dados.get("usou_imagem", False) else 0

        logger.info(
            f"[QWEN] resposta OK | "
            f"tempo={dados.get('tempo_segundos', '?')}s | "
            f"num_imagens={num_imagens}"
        )

        return resposta

    except requests.Timeout:
        logger.warning(
            "[QWEN] Timeout — seguindo para fallback"
        )
        return ""

    except requests.ConnectionError:
        logger.warning(
            "[QWEN] Colab offline — seguindo para fallback"
        )
        return ""

    except Exception as e:
        logger.warning(
            f"[QWEN] Falhou: {type(e).__name__}: {e}"
        )
        return ""


def _extrair_json_classificacao(texto: str) -> dict | None:
    """Extrai objeto {classificacao:[...]} ou converte array direto para esse formato."""
    if not texto:
        return None
    texto = re.sub(r"```json\s*", "", texto, flags=re.I)
    texto = re.sub(r"```\s*", "", texto)
    texto = texto.strip()
    if "</think>" in texto:
        texto = texto.split("</think>", 1)[1].strip()

    # Primeiro tenta objeto JSON balanceado pelo primeiro/ultimo delimitador.
    inicio = texto.find("{")
    fim = texto.rfind("}")
    if inicio >= 0 and fim > inicio:
        try:
            data = json.loads(texto[inicio:fim + 1])
            if isinstance(data, dict):
                return data
        except Exception:
            pass

    inicio = texto.find("[")
    fim = texto.rfind("]")
    if inicio >= 0 and fim > inicio:
        try:
            data = json.loads(texto[inicio:fim + 1])
            if isinstance(data, list):
                return {"classificacao": data}
        except Exception:
            pass
    return None


def _normalizar_score_llm(valor) -> int | None:
    """Aceita 85, 85.0, '85' ou '85%' e retorna inteiro 0..100."""
    if valor is None or isinstance(valor, bool):
        return None
    try:
        if isinstance(valor, str):
            valor = valor.strip().replace("%", "").replace(",", ".")
        numero = float(valor)
        if not (0 <= numero <= 100):
            return None
        return int(round(numero))
    except (TypeError, ValueError):
        return None


def _validar_classificacao_llm(texto: str, total_esperado: int) -> dict | None:
    """
    Valida integralmente a resposta antes de aceitar um provider.
    Exige IDs 1..N exatamente uma vez, cluster A/B, score 0..100 e justificativa nao vazia.
    """
    data = _extrair_json_classificacao(texto)
    if not data:
        return None
    classificacoes = data.get("classificacao")
    if not isinstance(classificacoes, list) or len(classificacoes) != total_esperado:
        return None

    ids = []
    normalizadas = []
    for item in classificacoes:
        if not isinstance(item, dict):
            return None
        try:
            idx = int(item.get("id"))
        except (TypeError, ValueError):
            return None
        cluster = str(item.get("cluster") or "").strip().upper()
        score = _normalizar_score_llm(item.get("score_similaridade"))
        justificativa = str(item.get("justificativa") or "").strip()
        if cluster not in {"A", "B"} or score is None or not justificativa:
            return None
        ids.append(idx)
        normalizadas.append({
            "id": idx,
            "cluster": cluster,
            "score_similaridade": score,
            "justificativa": justificativa,
        })

    esperados = list(range(1, total_esperado + 1))
    if sorted(ids) != esperados or len(set(ids)) != total_esperado:
        return None

    normalizadas.sort(key=lambda x: x["id"])
    return {"classificacao": normalizadas}


def _resposta_clustering_json_valida(texto: str, total_esperado: int | None = None) -> bool:
    """Compatibilidade: valida estrutura completa quando total e informado."""
    if total_esperado is None:
        data = _extrair_json_classificacao(texto)
        return bool(data and isinstance(data.get("classificacao"), list) and data["classificacao"])
    return _validar_classificacao_llm(texto, total_esperado) is not None

def _chamar_llm(prompt: str, candidatos: list[dict]) -> dict | None:
    """
    Tenta providers em sequencia e SO aceita uma resposta integralmente valida.

    Retorno:
      {"resposta": <json-normalizado>, "provider_llm": ..., "modelo_llm": ..., "conta_llm": ...}
      ou None se todos falharem/retornarem formato invalido.
    """
    import time as t_mod

    tentativas = []

    qwen_url = _obter_secret("QWEN_API_URL")
    if qwen_url:
        tentativas.append((
            "qwen_colab", "Qwen3-VL-8B", "QWEN_API_KEY",
            lambda: _chamar_qwen_colab(prompt, max_new_tokens=1600),
        ))

    tentativas.append((
        "groq", "openai/gpt-oss-120b", "GROQ_API_KEY",
        lambda: _chamar_groq(prompt, os.getenv("GROQ_API_KEY", ""), model="openai/gpt-oss-120b"),
    ))

    if os.getenv("GROQ_API_KEY_2", ""):
        tentativas.append((
            "groq", "openai/gpt-oss-120b", "GROQ_API_KEY_2",
            lambda: _chamar_groq(prompt, os.getenv("GROQ_API_KEY_2", ""), model="openai/gpt-oss-120b"),
        ))

    google_key = os.getenv("GOOGLE_API_KEY_2", "") or os.getenv("GOOGLE_API_KEY", "")
    if google_key:
        tentativas.append((
            "gemini", "gemini-3.5-flash-lite", "GOOGLE_API_KEY_2/GOOGLE_API_KEY",
            lambda: _chamar_gemini(prompt, google_key),
        ))

    nvidia_key = os.getenv("NVIDIA_API_KEY", "")
    if nvidia_key:
        tentativas.append((
            "nvidia", "openai/gpt-oss-20b", "NVIDIA_API_KEY",
            lambda: _chamar_nvidia(prompt, nvidia_key),
        ))

    for provider, modelo, conta, chamar in tentativas:
        logger.info(f"[Ag2][Clustering] Tentando {provider} / {modelo}...")
        t0 = t_mod.time()
        try:
            resposta = chamar() or ""
        except Exception as e:
            logger.warning(f"[Ag2][Clustering] {provider}/{modelo} falhou: {type(e).__name__}: {e}")
            resposta = ""

        if not resposta:
            logger.info(f"[Ag2][Clustering] {provider}/{modelo} sem resposta — proximo provider")
            continue

        _log_resposta_llm(f"{provider} | {modelo}", resposta)
        validada = _validar_classificacao_llm(resposta, len(candidatos))
        if validada is None:
            logger.warning(
                f"[Ag2][Clustering] {provider}/{modelo} respondeu em {t_mod.time()-t0:.1f}s, "
                "mas a classificacao esta incompleta/invalida — tentando proximo provider"
            )
            continue

        logger.info(f"[Ag2][Clustering] resposta valida: {provider}/{modelo} em {t_mod.time()-t0:.1f}s")
        return {
            "resposta": json.dumps(validada, ensure_ascii=False),
            "provider_llm": provider,
            "modelo_llm": modelo,
            "conta_llm": conta,
        }

    logger.warning("[Ag2][Clustering] Todos os providers falharam ou retornaram JSON invalido")
    return None

def _chamar_nvidia(prompt: str, api_key: str) -> str:
    """Chama NVIDIA NIM (openai/gpt-oss-20b). Timeout 30s, sem retries longos.

    O antigo meta/llama-3.3-70b-instruct foi descontinuado (EOL 2026-08-26).
    O openai/gpt-oss-20b e o modelo de texto gratuito vivo no endpoint NVIDIA.
    """
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
            model="openai/gpt-oss-20b",
            messages=[
                {"role": "system", "content": "Responda SOMENTE com JSON valido, sem markdown, sem texto extra."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=4096,
        )

        texto = response.choices[0].message.content or ""
        if texto:
            logger.info(f"    [LLM] NVIDIA NIM openai/gpt-oss-20b respondeu OK")
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
            max_completion_tokens=2500,
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


def _marcar_sem_julgamento_llm(
    candidatos: list[dict],
    motivo: str,
    classificado_por: str,
    lote_llm: int | None = None,
) -> list[dict]:
    """Marca falha tecnica sem fingir que o candidato foi julgado como nao comparavel."""
    for c in candidatos:
        c["cluster"] = None
        c["status_julgamento"] = "NAO_JULGADO"
        c["ranking_llm"] = None
        c["score_llm"] = None
        c["classificado_por"] = classificado_por
        c["provider_llm"] = None
        c["modelo_llm"] = None
        c["lote_llm"] = lote_llm
        c["justificativa"] = motivo
    return candidatos

def _parsear_resposta_llm(
    resposta: str,
    candidatos: list[dict],
    provider_llm: str,
    modelo_llm: str,
    lote_llm: int,
    conta_llm: str = "",
) -> list[dict]:
    """Aplica uma resposta JA validada e preserva score Python separado do score LLM."""
    data = _validar_classificacao_llm(resposta, len(candidatos))
    if data is None:
        return _marcar_sem_julgamento_llm(
            candidatos,
            "Resposta LLM ficou invalida na etapa de aplicacao",
            "llm_resposta_invalida",
            lote_llm=lote_llm,
        )

    por_id = {item["id"]: item for item in data["classificacao"]}
    for idx, candidato in enumerate(candidatos, 1):
        item = por_id[idx]
        candidato["cluster"] = item["cluster"]
        candidato["status_julgamento"] = "JULGADO_LLM"
        candidato["score_llm"] = round(item["score_similaridade"] / 100.0, 4)
        candidato["justificativa"] = item["justificativa"]
        candidato["classificado_por"] = "llm"
        candidato["provider_llm"] = provider_llm
        candidato["modelo_llm"] = modelo_llm
        candidato["conta_llm"] = conta_llm
        candidato["lote_llm"] = lote_llm
        # score_similaridade permanece como alias legado do score Python.
        if "score_pre_llm" not in candidato:
            candidato["score_pre_llm"] = candidato.get("score_similaridade", 0.0)
    return candidatos

def _fallback_numerico(candidatos: list[dict], top_n: int | None = None) -> list[dict]:
    """
    Fallback deterministico.

    - top_n=None: comportamento manual/usar_llm=False, threshold 0.60.
    - top_n=N: usado SOMENTE quando nenhum provider LLM julgou nenhum candidato;
      promove os N melhores do ranking Python para Cluster A.
    """
    ordenados = sorted(candidatos, key=lambda x: x.get("score_pre_llm", x.get("score_similaridade", 0)), reverse=True)

    if top_n is not None:
        limite = min(max(int(top_n), 0), len(ordenados))
        for ranking, c in enumerate(ordenados, 1):
            score = c.get("score_pre_llm", c.get("score_similaridade", 0)) or 0
            c["ranking_llm"] = None
            c["score_llm"] = None
            c["provider_llm"] = None
            c["modelo_llm"] = None
            c["status_julgamento"] = "FALLBACK_PYTHON"
            c["classificado_por"] = "fallback_python_top20"
            if ranking <= limite:
                c["cluster"] = "A"
                c["justificativa"] = f"Fallback tecnico: top {limite} do ranking Python (score={score:.3f})"
            else:
                c["cluster"] = "B"
                c["justificativa"] = f"Fallback tecnico: fora do top {limite} do ranking Python (score={score:.3f})"
        return ordenados

    THRESHOLD = 0.60
    for ranking, c in enumerate(ordenados, 1):
        score = c.get("score_pre_llm", c.get("score_similaridade", 0)) or 0
        c["ranking_llm"] = ranking
        c["score_llm"] = None
        c["provider_llm"] = None
        c["modelo_llm"] = None
        c["status_julgamento"] = "FALLBACK_PYTHON"
        c["classificado_por"] = "fallback_numerico"
        if score >= THRESHOLD:
            c["cluster"] = "A"
            c["justificativa"] = f"Score Python {score:.2f} >= {THRESHOLD}"
        else:
            c["cluster"] = "B"
            c["justificativa"] = f"Score Python {score:.2f} < {THRESHOLD}"
    return ordenados

def identificar_comparaveis(
    imovel_alvo: dict,
    imoveis_coletados: Optional[list[dict]] = None,
    arquivo_entrada: str = "imoveis_completos_ag1.json",
    arquivo_saida: str = "imoveis_comparaveis_ag2.json",
    usar_llm: bool = True,
    run_id: str | None = None,
) -> dict:
    """Identifica comparaveis com pre-classificacao + score Python + julgamento LLM validado."""
    logger.info("=" * 60)
    logger.info("AGENTE 2: IDENTIFICADOR DE COMPARAVEIS")
    logger.info("=" * 60)

    alertas_entrada = _validar_imovel_alvo(imovel_alvo)
    run_dir = _obter_data_dir(run_id)

    # 1. Carrega dados
    if imoveis_coletados is None:
        # Com run_id, JAMAIS buscar arquivo global: isso quebraria o isolamento entre
        # avaliacoes (poderia carregar dados de uma execucao anterior). Sem run_id,
        # usa os caminhos legados diretamente em data/.
        if _sanitizar_run_id(run_id):
            candidatos_caminho = [
                os.path.join(run_dir, arquivo_entrada),
                os.path.join(run_dir, "imoveis_coletados_ag1.json"),
            ]
        else:
            candidatos_caminho = [
                os.path.join(DATA_DIR, arquivo_entrada),
                os.path.join(DATA_DIR, "imoveis_coletados_ag1.json"),
            ]
        caminho = next((p for p in candidatos_caminho if os.path.exists(p)), None)
        if not caminho:
            logger.error("Nenhum arquivo de imoveis encontrado")
            return {
                "status": "erro_sem_entrada",
                "run_id": _sanitizar_run_id(run_id),
                "imovel_alvo": imovel_alvo,
                "comparaveis": [],
                "terrenos": [],
                "alertas": alertas_entrada + ["Nenhum arquivo do Agente 1 encontrado"],
                "resumo": {},
            }
        try:
            with open(caminho, "r", encoding="utf-8") as f:
                imoveis_coletados = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            raise RuntimeError(f"Agente 2: falha ao ler entrada {caminho}: {e}") from e
        logger.info(f"Carregados: {len(imoveis_coletados)} imoveis de {caminho}")

    imoveis_coletados = list(imoveis_coletados or [])

    # 2. Separa terrenos de forma robusta
    terrenos = [i for i in imoveis_coletados if _eh_terreno(i)]
    filtrados = [i for i in imoveis_coletados if not _eh_terreno(i)]
    logger.info(f"[Ag2][PreClassificacao] construidos={len(filtrados)} | terrenos_separados={len(terrenos)}")

    # 3. Estatisticas / referencia
    estatisticas_areas = _calcular_estatisticas_areas(filtrados, imovel_alvo)
    area_alvo = _obter_area_construida(imovel_alvo)
    terreno_alvo = _obter_area_terreno(imovel_alvo) if _eh_casa(imovel_alvo) else None
    caracteristicas_alvo = _extrair_caracteristicas(imovel_alvo)

    # 4. Pre-classificacao (com relaxamento adaptativo do limite de area).
    #
    # Primeiro roda com o limite padrao (30%). Se sobrarem poucos elegiveis, um
    # corte rigido pode estar estrangulando a amostra em bairros com poucos
    # anuncios; nesse caso refaz a pre-classificacao com um limite mais generoso
    # (45%). As caracteristicas eliminatorias continuam valendo em ambos os casos.
    def _rodar_pre_classificacao(limite_area_pct: float):
        aprovados = []
        reprovados = []
        for im in filtrados:
            pre = _pre_classificar(
                imovel_alvo, im,
                caracteristicas_alvo=caracteristicas_alvo,
                limite_area_pct=limite_area_pct,
            )
            im["pre_classificacao"] = pre
            if pre["elegivel_llm"]:
                aprovados.append(im)
            else:
                reprovados.append(im)
        return aprovados, reprovados

    limite_area_usado = LIMITE_AREA_PRE_CLASSIFICACAO
    elegiveis, incompativeis_pre = _rodar_pre_classificacao(limite_area_usado)

    if len(elegiveis) < MIN_ELEGIVEIS_PRE_CLASSIFICACAO and len(filtrados) > len(elegiveis):
        logger.info(
            f"[Ag2][PreClassificacao] apenas {len(elegiveis)} elegiveis com limite "
            f"{round(LIMITE_AREA_PRE_CLASSIFICACAO*100)}%; relaxando para "
            f"{round(LIMITE_AREA_PRE_CLASSIFICACAO_RELAXADO*100)}% (minimo desejado="
            f"{MIN_ELEGIVEIS_PRE_CLASSIFICACAO})"
        )
        limite_area_usado = LIMITE_AREA_PRE_CLASSIFICACAO_RELAXADO
        elegiveis, incompativeis_pre = _rodar_pre_classificacao(limite_area_usado)
        logger.info(
            f"[Ag2][PreClassificacao] apos relaxamento: elegiveis={len(elegiveis)} | "
            f"reprovados={len(incompativeis_pre)}"
        )

    # Anota os reprovados com os campos padrao de descarte.
    for im in incompativeis_pre:
        pre = im.get("pre_classificacao") or {}
        im["cluster"] = "B"
        im["status_julgamento"] = "REPROVADO_PRE_CLASSIFICACAO"
        im["ranking_llm"] = None
        im["score_llm"] = None
        im["classificado_por"] = "python_pre_classificacao"
        im["provider_llm"] = None
        im["modelo_llm"] = None
        motivos = pre.get("motivos_incompatibilidade") or []
        im["justificativa"] = "Pre-classificacao: " + "; ".join(motivos)

    # 4b. Detalhamento auditavel dos reprovados: quantos cairam por cada motivo
    # e quais caracteristicas mais eliminaram. Um imovel pode ter mais de um motivo.
    logger.info(
        f"[Ag2][PreClassificacao] limite_area={round(limite_area_usado*100)}% | "
        f"area_alvo={area_alvo}m2 | terreno_alvo={terreno_alvo}m2 | "
        f"elegiveis={len(elegiveis)} | reprovados={len(incompativeis_pre)}"
    )
    if incompativeis_pre:
        por_area = por_terreno = por_caracteristica = 0
        contagem_caracteristicas: dict[str, int] = {}
        for im in incompativeis_pre:
            pre = im.get("pre_classificacao") or {}
            dif_area = (pre.get("area_construida") or {}).get("diferenca_percentual")
            lim_area = (pre.get("area_construida") or {}).get("limite_percentual")
            dif_terr = (pre.get("area_terreno") or {}).get("diferenca_percentual")
            lim_terr = (pre.get("area_terreno") or {}).get("limite_percentual")
            divergencias = pre.get("divergencias_caracteristicas") or []
            if dif_area is not None and lim_area is not None and dif_area > lim_area:
                por_area += 1
            if dif_terr is not None and lim_terr is not None and dif_terr > lim_terr:
                por_terreno += 1
            if divergencias:
                por_caracteristica += 1
                for nome in divergencias:
                    contagem_caracteristicas[nome] = contagem_caracteristicas.get(nome, 0) + 1
        logger.info(
            f"[Ag2][PreClassificacao] motivos da reprovacao (podem se sobrepor): "
            f"area_construida>{round(limite_area_usado*100)}%={por_area} | "
            f"area_terreno>{round(limite_area_usado*100)}%={por_terreno} | "
            f"caracteristica_divergente={por_caracteristica}"
        )
        if contagem_caracteristicas:
            top = sorted(contagem_caracteristicas.items(), key=lambda kv: kv[1], reverse=True)
            detalhe = " | ".join(f"{nome}={qtd}" for nome, qtd in top)
            logger.info(f"[Ag2][PreClassificacao] caracteristicas que mais eliminaram: {detalhe}")
        # Amostra dos primeiros reprovados com a justificativa completa, para auditoria.
        for im in incompativeis_pre[:5]:
            ident = im.get("listing_id") or im.get("id") or im.get("url") or "?"
            motivos_txt = "; ".join((im.get("pre_classificacao") or {}).get("motivos_incompatibilidade") or [])
            logger.info(f"  [reprovado] id={ident} | {motivos_txt}")
        if len(incompativeis_pre) > 5:
            logger.info(f"  [reprovado] ... e mais {len(incompativeis_pre) - 5} imovel(is)")

    # 5. Score Python robusto; preserva campo legado e novo campo auditavel.
    for im in filtrados:
        score = _calcular_score_similaridade(imovel_alvo, im)
        im["score_pre_llm"] = score
        im["score_similaridade"] = score  # alias legado

    elegiveis.sort(key=lambda x: x.get("score_pre_llm", 0), reverse=True)
    for ranking_pre, im in enumerate(elegiveis, 1):
        im["ranking_pre_llm"] = ranking_pre

    TAMANHO_LOTE = 15
    llm_tentados = 0
    llm_classificados = 0
    llm_nao_julgados = 0
    classificados_elegiveis = []

    # 6. LLM
    if usar_llm and elegiveis:
        import time as t_ag2
        for im in elegiveis:
            im["pre_classificacao"]["enviado_llm"] = True

        lotes = [elegiveis[i:i + TAMANHO_LOTE] for i in range(0, len(elegiveis), TAMANHO_LOTE)]
        logger.info(f"[Ag2][Clustering] {len(elegiveis)} elegiveis em {len(lotes)} lote(s)")

        for num_lote, lote in enumerate(lotes, 1):
            llm_tentados += len(lote)
            prompt = _montar_prompt_clustering(imovel_alvo, lote)
            retorno_llm = _chamar_llm(prompt, lote)
            if retorno_llm:
                lote = _parsear_resposta_llm(
                    retorno_llm["resposta"], lote,
                    provider_llm=retorno_llm["provider_llm"],
                    modelo_llm=retorno_llm["modelo_llm"],
                    conta_llm=retorno_llm.get("conta_llm", ""),
                    lote_llm=num_lote,
                )
                llm_classificados += len(lote)
            else:
                lote = _marcar_sem_julgamento_llm(
                    lote,
                    "Nenhum provider retornou classificacao completa e valida",
                    "llm_indisponivel",
                    lote_llm=num_lote,
                )
                llm_nao_julgados += len(lote)
            classificados_elegiveis.extend(lote)
            if num_lote < len(lotes):
                t_ag2.sleep(3)

        # Se TODOS os julgamentos LLM falharam, top 20 do Python vira fallback.
        if llm_classificados == 0 and elegiveis:
            logger.warning(
                f"[Ag2][Fallback] Nenhum candidato foi julgado por LLM; usando top {TOP_N_FALLBACK_PYTHON} do ranking Python"
            )
            classificados_elegiveis = _fallback_numerico(elegiveis, top_n=TOP_N_FALLBACK_PYTHON)
            llm_nao_julgados = len(elegiveis)
    elif usar_llm:
        classificados_elegiveis = []
    else:
        classificados_elegiveis = _fallback_numerico(elegiveis)

    # Ranking LLM apenas para candidatos realmente julgados pela LLM.
    julgados = [c for c in classificados_elegiveis if c.get("status_julgamento") == "JULGADO_LLM"]
    julgados.sort(key=lambda x: (x.get("score_llm") if x.get("score_llm") is not None else -1), reverse=True)
    for ranking, c in enumerate(julgados, 1):
        c["ranking_llm"] = ranking

    todos_construidos = classificados_elegiveis + incompativeis_pre
    cluster_a = sorted(
        [c for c in todos_construidos if c.get("cluster") == "A"],
        key=lambda x: (
            0 if x.get("ranking_llm") is not None else 1,
            x.get("ranking_llm") or x.get("ranking_pre_llm") or 999999,
        ),
    )
    cluster_b = [c for c in todos_construidos if c.get("cluster") == "B"]
    nao_julgados = [c for c in todos_construidos if c.get("cluster") is None]

    for t in terrenos:
        t["cluster"] = "terreno"
        t["status_julgamento"] = "SEPARADO_TIPO"
        t["ranking_llm"] = None
        t["classificado_por"] = "separacao_tipo"
        t["justificativa"] = "Terreno separado do ranking de imoveis construidos"

    resultado_final = cluster_a + cluster_b + nao_julgados + terrenos

    resumo_pre = {
        "total_construidos": len(filtrados),
        "elegiveis_apos_pre_classificacao": len(elegiveis),
        "incompativeis_pre_classificacao": len(incompativeis_pre),
        "regra_area_percentual": round(limite_area_usado * 100),
        "regra_area_percentual_padrao": round(LIMITE_AREA_PRE_CLASSIFICACAO * 100),
        "relaxamento_area_acionado": limite_area_usado != LIMITE_AREA_PRE_CLASSIFICACAO,
        "caracteristicas_eliminatorias": list(CARACTERISTICAS_PRE_CLASSIFICACAO.keys()),
        "estatisticas_areas": estatisticas_areas,
        "referencia_alvo": {"area_construida": area_alvo, "area_terreno": terreno_alvo},
        "caracteristicas_alvo": caracteristicas_alvo,
    }

    resumo = {
        "total_analisados": len(filtrados),
        "cluster_a": len(cluster_a),
        "cluster_b": len(cluster_b),
        "nao_julgados": len(nao_julgados),
        "terrenos_separados": len(terrenos),
        "llm_tentados": llm_tentados,
        "llm_classificados": llm_classificados,
        "llm_nao_julgados": llm_nao_julgados,
        "fallback_python_top20_acionado": bool(usar_llm and elegiveis and llm_classificados == 0),
        "metodo": "pre_classificacao_python + score_python + clustering_llm_validado" if usar_llm else "pre_classificacao_python + score_python",
        "pre_classificacao": resumo_pre,
    }

    status = "ok"
    if not cluster_a and elegiveis:
        status = "alerta_sem_cluster_a"
    if not filtrados and not terrenos:
        status = "erro_sem_candidatos"

    saida = {
        "status": status,
        "run_id": _sanitizar_run_id(run_id),
        "imovel_alvo": imovel_alvo,
        "comparaveis": resultado_final,
        "cluster_a": cluster_a,
        "cluster_b": cluster_b,
        "nao_julgados": nao_julgados,
        "terrenos": terrenos,
        "estatisticas_areas": estatisticas_areas,
        "pre_classificacao": resumo_pre,
        "alertas": alertas_entrada,
        "resumo": resumo,
    }

    # Resumo final auditavel (mesmo padrao do Agente 1): consolida numeros e status.
    logger.info("=" * 55)
    logger.info(f"[Ag2] RESULTADO FINAL: status={status}")
    logger.info(f"[Ag2]   Construidos analisados : {len(filtrados)}")
    logger.info(f"[Ag2]   Elegiveis pos-pre-class: {len(elegiveis)} | reprovados_pre: {len(incompativeis_pre)}")
    logger.info(f"[Ag2]   Cluster A (comparaveis): {len(cluster_a)}")
    logger.info(f"[Ag2]   Cluster B (descartados): {len(cluster_b)}")
    logger.info(f"[Ag2]   Nao julgados (falha LLM): {len(nao_julgados)}")
    logger.info(f"[Ag2]   Terrenos separados     : {len(terrenos)}")
    logger.info(f"[Ag2]   LLM: tentados={llm_tentados} | classificados={llm_classificados} | nao_julgados={llm_nao_julgados}")
    if resumo["fallback_python_top20_acionado"]:
        logger.info(f"[Ag2]   [!] Fallback Python top {TOP_N_FALLBACK_PYTHON} acionado (nenhum julgamento LLM)")
    logger.info("=" * 55)

    caminho_saida = os.path.join(run_dir, arquivo_saida)
    _salvar_json_atomico(saida, caminho_saida)
    saida["arquivo_saida"] = caminho_saida
    logger.info(f"Salvo em: {caminho_saida}")
    return saida

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
    Analisa visualmente a zona. Providers de visao:
      1. Qwen3-VL-8B Colab
      2. Gemini gemini-3.5-flash-lite
      3. Groq qwen/qwen3.8-27b
      4. NVIDIA meta/llama-3.2-11b-vision-instruct
      5. fallback unico RAIO_FALLBACK_METROS
    """
    import base64
    import time as t_zona

    nvidia_key = os.getenv("NVIDIA_API_KEY", "")
    google_key = os.getenv("GOOGLE_API_KEY", "")
    groq_key = os.getenv("GROQ_API_KEY", "")
    qwen_url = _obter_secret("QWEN_API_URL")
    qwen_key = _obter_secret("QWEN_API_KEY")
    qwen_disponivel = bool(qwen_url and qwen_key)

    fallback = {
        "raio_metros": RAIO_FALLBACK_METROS,
        "raio_sugerido_metros": RAIO_FALLBACK_METROS,
        "descricao_zona_homogenea": "Analise visual nao disponivel; raio fallback aplicado",
        "confianca": "baixa",
        "provider_visao": "fallback",
    }
    if not qwen_disponivel and not google_key and not groq_key and not nvidia_key:
        logger.warning("Nenhum provider de visao configurado — usando raio fallback")
        return fallback

    try:
        from PIL import Image
        import io
        img = Image.open(io.BytesIO(imagem_bytes))
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=85)
        imagem_comprimida = buffer.getvalue()
        img_b64 = base64.b64encode(imagem_comprimida).decode("utf-8")
        img_mime = "image/jpeg"
    except Exception:
        img_b64 = base64.b64encode(imagem_bytes).decode("utf-8")
        img_mime = "image/png"

    prompt = f"""Analise a imagem de satelite centrada no imovel alvo (marcador vermelho).
Endereco: {endereco_alvo}

Defina uma ZONA HOMOGENEA usando SOMENTE elementos visiveis.
Nao use conhecimento externo, preco, renda ou perfil socioeconomico.

ANALISE:
1. Padrao construtivo aparente.
2. Homogeneidade visual.
3. Densidade urbana.
4. Existencia e proximidade de transicoes visuais relevantes.
5. Escolha LIVREMENTE um raio em metros que melhor represente a area visualmente homogenea.
   Nao escolha a partir de uma lista fixa. Use um numero inteiro e justifique visualmente.

RESPONDA SOMENTE JSON:
{{
  "padrao_construtivo": "...",
  "homogeneidade_visual": "alta | media | baixa | indefinida",
  "densidade_urbana": "baixa | media | alta | indefinida",
  "transicao_visual": "...",
  "raio_sugerido_metros": 650,
  "justificativa_raio": "...",
  "descricao_zona_homogenea": "...",
  "confianca": "alta | media | baixa"
}}"""

    if qwen_disponivel:
        t0 = t_zona.time()
        resposta = _chamar_qwen_colab(prompt=prompt, imagem_bytes=imagem_bytes, max_new_tokens=1024)
        if resposta:
            _log_resposta_llm("Qwen3-VL-8B Colab - Zona Homogenea", resposta)
            resultado = _parsear_json_zona(resposta)
            if resultado:
                resultado["provider_visao"] = "qwen_colab"
                resultado["modelo_visao"] = "Qwen3-VL-8B"
                logger.info(f"[Ag2][Zona] Qwen em {t_zona.time()-t0:.1f}s")
                return resultado

    if google_key:
        resultado = _chamar_gemini_visao(prompt, imagem_bytes, google_key)
        if resultado:
            resultado["provider_visao"] = "gemini"
            resultado["modelo_visao"] = "gemini-3.5-flash-lite"
            return resultado

    if groq_key:
        resultado = _chamar_groq_visao(prompt, img_b64, img_mime, groq_key)
        if resultado:
            resultado["provider_visao"] = "groq"
            resultado["modelo_visao"] = "qwen/qwen3.8-27b"
            return resultado

    if nvidia_key:
        resultado = _chamar_nvidia_visao(prompt, img_b64, img_mime, nvidia_key)
        if resultado:
            resultado["provider_visao"] = "nvidia"
            resultado["modelo_visao"] = "meta/llama-3.2-11b-vision-instruct"
            return resultado

    return fallback

def _chamar_nvidia_visao(prompt: str, img_b64: str, img_mime: str, api_key: str) -> dict | None:
    """Chama NVIDIA NIM (meta/llama-3.2-11b-vision-instruct) para analise visual.

    O antigo google/gemma-4-31b-it foi descontinuado. O llama-3.2-11b-vision-instruct
    e o VLM gratuito vivo no endpoint NVIDIA. Timeout 30s, sem retries.
    """
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
            model="meta/llama-3.2-11b-vision-instruct",
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
        logger.info(f"NVIDIA NIM (llama-3.2-11b-vision-instruct) respondeu ({len(texto)} chars)")

        return _validar_zona_llm(texto)

    except Exception as e:
        logger.warning(f"    [LLM] NVIDIA NIM visao falhou: {e}")
        return None


def _chamar_groq_visao(prompt: str, img_b64: str, img_mime: str, api_key: str) -> dict | None:
    """Chama Groq (qwen3.8-27b) com imagem para zona homogenea. Retorna dict ou None.

    O qwen3.6-27b foi descontinuado (decommission 14/09/2026); qwen3.8-27b e o
    substituto oficial do Groq e tambem aceita imagem.
    """
    try:
        from groq import Groq
        client = Groq(api_key=api_key)

        response = client.chat.completions.create(
            model="qwen/qwen3.8-27b",
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
            # JSON Schema Mode: o qwen3.8-27b suporta oficialmente e garante a
            # estrutura completa da zona, reduzindo respostas incompletas.
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "zona_homogenea",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "padrao_construtivo": {"type": "string"},
                            "homogeneidade_visual": {"type": "string"},
                            "densidade_urbana": {"type": "string"},
                            "transicao_visual": {"type": "string"},
                            "raio_sugerido_metros": {"type": "integer"},
                            "justificativa_raio": {"type": "string"},
                            "descricao_zona_homogenea": {"type": "string"},
                            "confianca": {"type": "string"},
                        },
                        "required": list(CAMPOS_OBRIGATORIOS_ZONA),
                        "additionalProperties": False,
                    },
                },
            },
        )

        texto = response.choices[0].message.content or ""
        logger.info(f"Groq Vision (qwen3.8-27b) respondeu ({len(texto)} chars)")

        return _validar_zona_llm(texto)

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

        return _validar_zona_llm(texto)

    except Exception as e:
        logger.warning(f"    [LLM] Gemini visao falhou: {e}")
        return None


def _parsear_json_zona(texto: str) -> dict | None:
    """Parseia zona e converte raio numerico/string para inteiro sem lista fixa."""
    if not texto:
        return None
    if "</think>" in texto:
        texto = texto.split("</think>", 1)[1].strip()
    texto = re.sub(r"```json\s*", "", texto, flags=re.I)
    texto = re.sub(r"```\s*", "", texto).strip()

    inicio = texto.find("{")
    if inicio < 0:
        return None
    # Balanceamento que IGNORA chaves dentro de strings JSON. Sem isso, um valor
    # como "confianca": "}" (lixo gerado por alguns modelos) fecharia o objeto no
    # lugar errado e produziria JSON invalido.
    nivel = 0
    fim = -1
    em_string = False
    escape = False
    for i in range(inicio, len(texto)):
        ch = texto[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            em_string = not em_string
            continue
        if em_string:
            continue
        if ch == "{":
            nivel += 1
        elif ch == "}":
            nivel -= 1
            if nivel == 0:
                fim = i
                break
    if fim <= inicio:
        return None

    try:
        resultado = json.loads(texto[inicio:fim + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(resultado, dict):
        return None
    if not any(k in resultado for k in ("raio_sugerido_metros", "raio_metros", "padrao_construtivo")):
        return None

    raio_raw = resultado.get("raio_sugerido_metros", resultado.get("raio_metros"))
    if raio_raw is None:
        raio = RAIO_FALLBACK_METROS
    else:
        try:
            if isinstance(raio_raw, str):
                m = re.search(r"-?\d+(?:[.,]\d+)?", raio_raw)
                if not m:
                    raise ValueError("raio sem numero")
                raio_raw = m.group(0).replace(",", ".")
            raio = int(round(float(raio_raw)))
        except (TypeError, ValueError):
            raio = RAIO_FALLBACK_METROS

    # A LLM escolhe livremente o raio; aplicamos apenas uma barreira de sanidade
    # para evitar valores absurdos por erro de geracao (ex.: 50000m).
    if raio <= 0:
        raio = RAIO_FALLBACK_METROS
    elif raio < RAIO_MINIMO_SEGURANCA:
        logger.info(f"[Ag2][Zona] raio {raio}m abaixo do minimo; ajustado para {RAIO_MINIMO_SEGURANCA}m")
        raio = RAIO_MINIMO_SEGURANCA
    elif raio > RAIO_MAXIMO_SEGURANCA:
        logger.info(f"[Ag2][Zona] raio {raio}m acima do maximo; ajustado para {RAIO_MAXIMO_SEGURANCA}m")
        raio = RAIO_MAXIMO_SEGURANCA
    resultado["raio_metros"] = raio
    resultado["raio_sugerido_metros"] = raio
    return resultado


# Campos obrigatorios da resposta de visao da zona homogenea.
CAMPOS_OBRIGATORIOS_ZONA = (
    "padrao_construtivo",
    "homogeneidade_visual",
    "densidade_urbana",
    "transicao_visual",
    "raio_sugerido_metros",
    "justificativa_raio",
    "descricao_zona_homogenea",
    "confianca",
)


def _validar_zona_llm(texto: str) -> dict | None:
    """
    Validacao rigorosa da resposta de visao (mesmo rigor do clustering).

    So aceita quando a resposta traz TODOS os campos obrigatorios preenchidos.
    Se qualquer campo faltar/vier vazio, retorna None para o roteador tentar o
    proximo provider, em vez de aceitar uma resposta incompleta e completar com
    defaults (que mascarava falhas do provider).
    """
    dados = _parsear_json_zona(texto)
    if not dados:
        return None
    for campo in CAMPOS_OBRIGATORIOS_ZONA:
        valor = dados.get(campo)
        if valor is None:
            logger.info(f"[Ag2][Zona] resposta incompleta: campo '{campo}' ausente — proximo provider")
            return None
        # Campos textuais nao podem vir vazios; raio ja foi normalizado para int > 0.
        if isinstance(valor, str) and not valor.strip():
            logger.info(f"[Ag2][Zona] resposta incompleta: campo '{campo}' vazio — proximo provider")
            return None
    return dados

def _geocodificar(endereco: str) -> tuple:
    """Geocodifica uma tentativa: Nominatim primeiro, Google depois."""
    import requests
    if not endereco or not str(endereco).strip():
        return None, None

    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": endereco, "format": "json", "limit": 1, "countrycodes": "br"},
            headers={"User-Agent": "ProjetoImoveisIA/1.0"},
            timeout=10,
        )
        if r.status_code == 200 and r.json():
            data = r.json()[0]
            return float(data["lat"]), float(data["lon"])
    except Exception as e:
        logger.debug(f"Nominatim falhou para {endereco!r}: {e}")

    maps_key = os.getenv("GOOGLE_MAPS_KEY", "")
    if maps_key:
        try:
            r = requests.get(
                "https://maps.googleapis.com/maps/api/geocode/json",
                params={"address": endereco, "key": maps_key, "region": "br"},
                timeout=10,
            )
            if r.status_code == 200:
                results = r.json().get("results", [])
                if results:
                    loc = results[0]["geometry"]["location"]
                    return float(loc["lat"]), float(loc["lng"])
        except Exception as e:
            logger.debug(f"Google Geocoding falhou para {endereco!r}: {e}")
    return None, None


def _inferir_componentes_endereco(endereco: str, cidade: str = "", estado: str = "") -> dict:
    """Tenta aproveitar componentes do endereco textual apenas para fallbacks, sem exigir formato fixo."""
    partes = [p.strip() for p in str(endereco or "").split(",") if p.strip()]
    numero = next((p for p in partes if re.fullmatch(r"\d+[A-Za-z]?", p)), "")
    rua = partes[0] if partes else ""
    bairro = ""
    cidade_norm = _normalizar_texto(cidade)
    for i, p in enumerate(partes):
        if cidade_norm and _normalizar_texto(p) == cidade_norm and i > 0:
            anterior = partes[i - 1]
            if anterior != numero and _normalizar_texto(anterior) != _normalizar_texto(rua):
                bairro = anterior
            break
    return {"rua": rua, "numero": numero, "bairro": bairro}


def _geocodificar_com_fallback(
    *,
    endereco_principal: str = "",
    rua: str = "",
    numero: str = "",
    bairro: str = "",
    cidade: str = "",
    estado: str = "",
    permitir_cidade: bool = False,
) -> tuple[float | None, float | None, str | None, str | None]:
    """
    Tenta do mais preciso ao menos preciso.
    Retorna (lat, lon, nivel, endereco_usado).
    niveis: endereco_completo, rua_numero, rua, bairro, cidade.
    """
    import time
    tentativas = []

    def add(nivel: str, partes: list[str]):
        endereco = ", ".join(str(p).strip() for p in partes if p not in (None, "") and str(p).strip())
        if endereco and endereco not in [x[1] for x in tentativas]:
            tentativas.append((nivel, endereco))

    add("endereco_completo", [endereco_principal])
    if rua and numero:
        add("rua_numero", [rua, numero, bairro, cidade, estado, "Brasil"])
    if rua:
        add("rua", [rua, bairro, cidade, estado, "Brasil"])
    if bairro:
        add("bairro", [bairro, cidade, estado, "Brasil"])
    if permitir_cidade and cidade:
        add("cidade", [cidade, estado, "Brasil"])

    for idx, (nivel, endereco) in enumerate(tentativas):
        lat, lon = _geocodificar(endereco)
        if lat is not None and lon is not None:
            return lat, lon, nivel, endereco
        if idx < len(tentativas) - 1:
            time.sleep(1.05)
    return None, None, None, None

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


def _classificar_por_distancia(distancia_metros: float, raio_zona: int | float = RAIO_FALLBACK_METROS) -> str:
    """Classifica usando exatamente o raio escolhido/normalizado, sem minimo artificial de 400m."""
    try:
        raio = float(raio_zona)
    except (TypeError, ValueError):
        raio = float(RAIO_FALLBACK_METROS)
    if raio <= 0:
        raio = float(RAIO_FALLBACK_METROS)
    return "na_zona" if distancia_metros <= raio else "fora_zona"

def _classificar_imovel_na_zona(
    im: dict,
    lat_alvo: float,
    lon_alvo: float,
    raio: float,
    cidade: str,
    estado: str,
) -> str:
    """
    Geocodifica um imovel (reusa lat/lon do Athena quando existem) e classifica
    em na_zona / fora_zona / zona_nao_verificada, gravando os campos no proprio dict.
    Retorna a classificacao. Usada tanto para comparaveis quanto para terrenos.
    """
    rua = im.get("street") or im.get("rua") or ""
    bairro = im.get("neighborhood") or im.get("bairro") or ""
    numero = _obter_numero_endereco(im)
    lat_existente = im.get("lat") if im.get("lat") is not None else im.get("latitude")
    lon_existente = im.get("lon") if im.get("lon") is not None else im.get("longitude")

    lat = lon = None
    nivel = None
    endereco_usado = None
    if lat_existente is not None and lon_existente is not None:
        try:
            lat, lon = float(lat_existente), float(lon_existente)
            nivel = "coordenadas_athena"
            endereco_usado = "lat/lon existentes"
        except (TypeError, ValueError):
            lat = lon = None

    if lat is None or lon is None:
        lat, lon, nivel, endereco_usado = _geocodificar_com_fallback(
            rua=rua,
            numero=numero,
            bairro=bairro,
            cidade=cidade or im.get("city") or im.get("cidade") or "",
            estado=estado or im.get("state") or im.get("estado") or "",
            permitir_cidade=False,
        )

    if lat is None or lon is None:
        im["distancia_metros"] = None
        im["classificacao_zona"] = "zona_nao_verificada"
        im["coordenadas"] = None
        im["geocodificacao_nivel"] = None
        im["endereco_geocodificado"] = None
        return "zona_nao_verificada"

    dist = _distancia_haversine(lat_alvo, lon_alvo, lat, lon)
    im["distancia_metros"] = round(dist)
    im["coordenadas"] = {"lat": lat, "lon": lon}
    im["geocodificacao_nivel"] = nivel
    im["endereco_geocodificado"] = endereco_usado
    im["confianca_geocodificacao"] = "baixa" if nivel == "bairro" else "alta"

    # A geocodificacao no nivel bairro usa o centroide do bairro como aproximacao
    # da posicao do imovel (nao ha rua/coordenada propria). A regra:
    #   - se o centroide do bairro cai DENTRO do raio da zona, aceitamos como
    #     na_zona (o bairro em si pertence a zona homogenea do alvo);
    #   - se cai FORA do raio, nao afirmamos que o imovel esta fora (a posicao
    #     real e desconhecida): marcamos zona_nao_verificada, categoria que nao
    #     descarta o imovel e permite recupera-lo depois via fallback (Opcao B).
    classificacao = _classificar_por_distancia(dist, raio)
    if nivel == "bairro" and classificacao == "fora_zona":
        classificacao = "zona_nao_verificada"
    im["classificacao_zona"] = classificacao
    return classificacao


def analisar_zona_homogenea(
    endereco_alvo: str,
    imoveis: list[dict],
    cidade: str = "",
    estado: str = "",
    lat_alvo_precomp: float = None,
    lon_alvo_precomp: float = None,
    bairro_alvo: str = "",
    rua_alvo: str = "",
    numero_alvo: str = "",
    terrenos: Optional[list[dict]] = None,
    run_id: str | None = None,
) -> dict:
    """
    Valida geograficamente os comparaveis.

    Ordem de geocodificacao do candidato quando Athena nao trouxe lat/lon:
      1. rua + numero + bairro + cidade + estado;
      2. rua + bairro + cidade + estado;
      3. bairro + cidade + estado;
      4. se tudo falhar -> zona_nao_verificada (NAO vira fora_zona).

    Para o alvo, tenta endereco completo e fallbacks progressivos. Se nenhuma forma
    geocodificar, nao confirma todos: retorna comparaveis_nao_verificados.
    """
    logger.info("=" * 55)
    logger.info("ZONA HOMOGENEA: Google Maps + LLM Vision")
    logger.info("=" * 55)
    run_dir = _obter_data_dir(run_id)
    imoveis = list(imoveis or [])

    # Garante passagem de terrenos ao Agente 5. Se nao vierem explicitamente,
    # tenta recuperar da saida da mesma execucao.
    if terrenos is None:
        terrenos = []
        caminho_comp = os.path.join(run_dir, "imoveis_comparaveis_ag2.json")
        if os.path.exists(caminho_comp):
            try:
                with open(caminho_comp, "r", encoding="utf-8") as f:
                    terrenos = list((json.load(f) or {}).get("terrenos") or [])
            except Exception as e:
                logger.warning(f"Nao foi possivel recuperar terrenos da saida do Agente 2: {e}")
    else:
        terrenos = list(terrenos or [])

    # 1. Geocodificacao do alvo
    nivel_geo_alvo = "coordenadas_precomputadas" if lat_alvo_precomp is not None and lon_alvo_precomp is not None else None
    endereco_geo_alvo = endereco_alvo
    if lat_alvo_precomp is not None and lon_alvo_precomp is not None:
        try:
            lat_alvo, lon_alvo = float(lat_alvo_precomp), float(lon_alvo_precomp)
        except (TypeError, ValueError):
            lat_alvo = lon_alvo = None
    else:
        inferidos = _inferir_componentes_endereco(endereco_alvo, cidade, estado)
        rua_fb = rua_alvo or inferidos["rua"]
        numero_fb = numero_alvo or inferidos["numero"]
        bairro_fb = bairro_alvo or inferidos["bairro"]
        lat_alvo, lon_alvo, nivel_geo_alvo, endereco_geo_alvo = _geocodificar_com_fallback(
            endereco_principal=endereco_alvo,
            rua=rua_fb,
            numero=numero_fb,
            bairro=bairro_fb,
            cidade=cidade,
            estado=estado,
            # cidade isolada e grosseira demais para declarar zona confirmada.
            permitir_cidade=False,
        )

    if lat_alvo is None or lon_alvo is None:
        logger.warning("Nao foi possivel geocodificar o alvo nem pelos fallbacks — zona nao verificada")
        for im in imoveis:
            im["distancia_metros"] = None
            im["classificacao_zona"] = "zona_nao_verificada"
            im["coordenadas"] = None
            im["geocodificacao_nivel"] = None
        resultado = {
            "status": "zona_nao_verificada",
            "run_id": _sanitizar_run_id(run_id),
            "zona_homogenea": {
                "raio_metros": RAIO_FALLBACK_METROS,
                "raio_sugerido_metros": RAIO_FALLBACK_METROS,
                "descricao_zona_homogenea": "Alvo nao geocodificado; nenhuma confirmacao geografica foi feita",
                "confianca": "baixa",
            },
            "comparaveis_confirmados": [],
            "fora_zona": [],
            "comparaveis_nao_verificados": imoveis,
            # Sem alvo geocodificado, nenhum terreno pode ser validado geograficamente.
            "terrenos": [],
            "terrenos_confirmados": [],
            "terrenos_fora_zona": [],
            "terrenos_nao_verificados": terrenos,
            "imagem_satelite": None,
            "coordenadas_alvo": None,
            "geocodificacao_alvo": {"nivel": None, "endereco_usado": None},
        }
        _salvar_json_atomico(resultado, os.path.join(run_dir, "zona_homogenea_ag2.json"))
        return resultado

    logger.info(f"[Ag2][Zona] Alvo {lat_alvo:.6f}, {lon_alvo:.6f} | nivel={nivel_geo_alvo}")

    # 2. Imagem satelite; se falhar, usa o MESMO raio fallback de toda a cadeia.
    imagem = _obter_imagem_satelite(endereco_alvo, lat=lat_alvo, lon=lon_alvo)
    img_path = None
    if imagem:
        img_path = os.path.join(run_dir, "satelite_zona_homogenea_ag2.png")
        _salvar_bytes_atomico(imagem, img_path)
        zona = _analisar_zona_homogenea(imagem, endereco_alvo)
    else:
        logger.warning("Nao gerou imagem de satelite — usando raio fallback unico")
        zona = {
            "raio_metros": RAIO_FALLBACK_METROS,
            "raio_sugerido_metros": RAIO_FALLBACK_METROS,
            "descricao_zona_homogenea": "Imagem de satelite indisponivel; raio fallback aplicado",
            "confianca": "baixa",
            "provider_visao": "fallback_sem_imagem",
        }

    raio_zona = _parsear_json_zona(json.dumps(zona, ensure_ascii=False)) if zona else None
    zona = raio_zona or zona or {}
    raio = zona.get("raio_metros", RAIO_FALLBACK_METROS)

    # Rotulos amigaveis para o nivel de geocodificacao registrado em cada imovel.
    _ROTULO_NIVEL_GEO = {
        "coordenadas_athena": "coord_propria",   # lat/lon veio da fonte, mais preciso
        "endereco_completo": "endereco",
        "rua_numero": "rua+numero",
        "rua": "rua",
        "bairro": "bairro(centroide)",           # aproximacao — mesmo ponto p/ todo o bairro
        "cidade": "cidade(centroide)",
    }

    def _log_classificacao(im: dict, idx: int, total: int, classificacao: str, prefixo: str = ""):
        """Loga a classificacao de um imovel com detalhes de como foi geolocalizado."""
        rotulo = im.get("street") or im.get("rua") or im.get("neighborhood") or im.get("bairro") or "?"
        nivel = im.get("geocodificacao_nivel")
        nivel_txt = _ROTULO_NIVEL_GEO.get(nivel, nivel or "sem_geo")
        confianca = im.get("confianca_geocodificacao") or "?"
        dist = im.get("distancia_metros")
        dist_txt = f"{dist}m" if dist is not None else "dist=?"
        cabec = f"  [{prefixo}{idx}/{total}]"
        if classificacao == "zona_nao_verificada":
            # Mostra a distancia aproximada mesmo quando nao verificado (ajuda a auditar).
            aprox = f" | ~{dist_txt} (centroide)" if dist is not None else ""
            logger.info(
                f"{cabec} zona_nao_verificada | geo={nivel_txt} | conf={confianca}{aprox} | {rotulo}"
            )
        else:
            logger.info(
                f"{cabec} {dist_txt} | {classificacao} | geo={nivel_txt} | conf={confianca} | "
                f"raio={raio}m | {rotulo}"
            )

    # 3. Geocodifica/classifica candidatos construidos
    logger.info(f"[Ag2][Zona] classificando {len(imoveis)} comparaveis | raio={raio}m")
    confirmados = []
    fora = []
    nao_verificados = []

    for idx, im in enumerate(imoveis, 1):
        classificacao = _classificar_imovel_na_zona(im, lat_alvo, lon_alvo, raio, cidade, estado)
        if classificacao == "zona_nao_verificada":
            nao_verificados.append(im)
        elif classificacao == "na_zona":
            confirmados.append(im)
        else:
            fora.append(im)
        _log_classificacao(im, idx, len(imoveis), classificacao)

    # Diagnostico agregado: como os comparaveis foram geolocalizados.
    if imoveis:
        contagem_niveis: dict[str, int] = {}
        for im in imoveis:
            nivel = im.get("geocodificacao_nivel") or "sem_geo"
            contagem_niveis[nivel] = contagem_niveis.get(nivel, 0) + 1
        niveis_txt = " | ".join(
            f"{_ROTULO_NIVEL_GEO.get(n, n)}={q}"
            for n, q in sorted(contagem_niveis.items(), key=lambda kv: kv[1], reverse=True)
        )
        logger.info(f"[Ag2][Zona] geolocalizacao dos comparaveis: {niveis_txt}")
        logger.info(
            f"[Ag2][Zona] comparaveis: na_zona={len(confirmados)} | "
            f"fora_zona={len(fora)} | nao_verificados={len(nao_verificados)}"
        )

    # 3b. Terrenos passam pela MESMA validacao geografica. Terreno influencia
    # diretamente a decomposicao de preco de casas no Agente 5, entao nao pode
    # entrar sem validar distancia. Separa em confirmados/fora/nao_verificados.
    terrenos_confirmados = []
    terrenos_fora_zona = []
    terrenos_nao_verificados = []
    if terrenos:
        logger.info(f"[Ag2][Zona] classificando {len(terrenos)} terreno(s) | raio={raio}m")
    for idx, t in enumerate(terrenos, 1):
        classificacao = _classificar_imovel_na_zona(t, lat_alvo, lon_alvo, raio, cidade, estado)
        if classificacao == "zona_nao_verificada":
            terrenos_nao_verificados.append(t)
        elif classificacao == "na_zona":
            terrenos_confirmados.append(t)
        else:
            terrenos_fora_zona.append(t)
        _log_classificacao(t, idx, len(terrenos), classificacao, prefixo="terreno ")

    # 3c. Fallback de baixa confianca (Opcao B).
    # Quando poucos comparaveis foram confirmados geograficamente, os imoveis
    # "zona_nao_verificada" (posicao real desconhecida) sao anexados a lista de
    # confirmados para que os Agentes 3/5 tenham amostra suficiente. Eles ficam
    # marcados para que a jusante saiba que entraram por fallback, com confianca baixa.
    fallback_zona_acionado = False
    confirmados_efetivos = list(confirmados)
    terrenos_efetivos = list(terrenos_confirmados)
    if len(confirmados) < MIN_CONFIRMADOS_ZONA and nao_verificados:
        fallback_zona_acionado = True
        logger.info(
            f"[Ag2][Zona] apenas {len(confirmados)} confirmados na zona (minimo desejado="
            f"{MIN_CONFIRMADOS_ZONA}); anexando {len(nao_verificados)} nao_verificados "
            f"como fallback de baixa confianca"
        )
        for im in nao_verificados:
            im["incluido_por_fallback_zona"] = True
            im["confianca_zona"] = "baixa"
        confirmados_efetivos = confirmados + nao_verificados
    # Terrenos seguem a mesma politica: sem terreno confirmado, usa os nao verificados.
    if not terrenos_confirmados and terrenos_nao_verificados:
        fallback_zona_acionado = True
        logger.info(
            f"[Ag2][Zona] nenhum terreno confirmado na zona; anexando "
            f"{len(terrenos_nao_verificados)} terreno(s) nao_verificado(s) como fallback"
        )
        for t in terrenos_nao_verificados:
            t["incluido_por_fallback_zona"] = True
            t["confianca_zona"] = "baixa"
        terrenos_efetivos = list(terrenos_nao_verificados)

    status = "ok"
    if nao_verificados:
        status = "ok_com_nao_verificados"
    if not confirmados and imoveis:
        status = "alerta_sem_confirmados" if not nao_verificados else "alerta_zona_inconclusiva"

    # O Agente 5 le os terrenos de comparaveis_confirmados (separa por tipo la dentro).
    # Incluimos os terrenos validados na zona nessa lista para que o Ag5 os utilize
    # no calculo de m2 de terreno, mantendo tambem os campos dedicados abaixo.
    resultado = {
        "status": status,
        "run_id": _sanitizar_run_id(run_id),
        "zona_homogenea": zona,
        "comparaveis_confirmados": confirmados_efetivos + terrenos_efetivos,
        "fora_zona": fora,
        "comparaveis_nao_verificados": nao_verificados,
        # terrenos agora validados geograficamente. "terrenos" aponta para os
        # confirmados (na zona) para o Agente 5 usar so os que sao referencia real;
        # inclui os nao verificados apenas quando nenhum terreno foi confirmado.
        "terrenos": terrenos_efetivos,
        "terrenos_confirmados": terrenos_confirmados,
        "terrenos_fora_zona": terrenos_fora_zona,
        "terrenos_nao_verificados": terrenos_nao_verificados,
        "imagem_satelite": img_path,
        "coordenadas_alvo": {"lat": lat_alvo, "lon": lon_alvo},
        "geocodificacao_alvo": {
            "nivel": nivel_geo_alvo,
            "endereco_usado": endereco_geo_alvo,
            "confianca": "baixa" if nivel_geo_alvo == "bairro" else "alta",
        },
        "resumo_zona": {
            "raio_usado_metros": raio,
            "confirmados": len(confirmados),
            "fora_zona": len(fora),
            "nao_verificados": len(nao_verificados),
            "terrenos_confirmados": len(terrenos_confirmados),
            "terrenos_fora_zona": len(terrenos_fora_zona),
            "terrenos_nao_verificados": len(terrenos_nao_verificados),
            "fallback_zona_acionado": fallback_zona_acionado,
            "min_confirmados_desejado": MIN_CONFIRMADOS_ZONA,
        },
    }

    caminho_saida = os.path.join(run_dir, "zona_homogenea_ag2.json")
    _salvar_json_atomico(resultado, caminho_saida)
    resultado["arquivo_saida"] = caminho_saida
    logger.info(f"Salvo em: {caminho_saida}")
    return resultado

