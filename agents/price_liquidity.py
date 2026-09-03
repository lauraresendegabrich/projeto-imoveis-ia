"""
Agente 5 - Estimador de Preco e Liquidez
==========================================

RESPONSABILIDADE:
    Calcula o valor estimado do imovel alvo reproduzindo a metodologia
    da planilha do professor. Separa terreno e construcao, usa TRIMMEAN(0.5),
    e aplica desconto fixo de 10% para valor de liquidez.
    Adicionalmente, gera estimativa experimental de liquidez (nao altera precos).

ENTRADA:
    - data/zona_homogenea_ag2.json (comparaveis confirmados + terrenos)
    - data/imoveis_analisados_ag3.json (score qualitativo + padrao)
    - data/infra_avaliada_ag4.json (score infraestrutura)
    - imovel_alvo (dict com area, area_terreno, tipo, etc.)

SAIDA:
    - data/preco_liquidez_ag5.json

CALCULO OFICIAL (fiel a planilha):
==================================

  ETAPA 1 — VALOR M2 DO TERRENO
  ──────────────────────────────
    Para cada terreno da zona homogenea:
      valor_m2 = preco / area
      Se topografia "acentuado": valor_m2 *= 0.80 (desconto 20%)

    menor_m2_terreno = MIN de todos
    medio_m2_terreno = TRIMMEAN(0.5) de todos

  ETAPA 2 — DECISAO: SEPARAR TERRENO OU NAO
  ───────────────────────────────────────────
    Apartamento/Sala: terreno = 0 (condominial)
    Terreno puro: so terreno, construcao = 0
    Casa com area_terreno: separa
    Casa sem area_terreno: usa preco/m2 total (nao separa)

  ETAPA 3 — DUAS SERIES DE M2 CONSTRUCAO
  ────────────────────────────────────────
    Para cada comparavel construido:
      Se condominial: m2 = preco / area_construida (nas duas series)
      Se casa (separando terreno):
        Serie MIN/TERRENO: m2 = (preco - menor_m2_terreno * area_terreno_comp) / area_construida
        Serie MED/TERRENO: m2 = (preco - medio_m2_terreno * area_terreno_comp) / area_construida
      Valores <= 0: descartados (terreno vale mais que o imovel)

    Combina as duas series:
      menor_m2_construcao = MIN da lista combinada
      medio_m2_construcao = TRIMMEAN(0.5) da lista combinada

  ETAPA 4 — VALOR DO TERRENO DO ALVO
  ────────────────────────────────────
    Se separa: valor_terreno = m2_terreno * area_terreno_alvo
    Se condominial: valor_terreno = 0

  ETAPA 5 — VALOR DA CONSTRUCAO DO ALVO
  ───────────────────────────────────────
    Se terreno puro: valor_construcao = 0
    Senao: valor_construcao = m2_construcao * area_construida_alvo

  ETAPA 6 — VALOR DO IMOVEL
  ──────────────────────────
    Casa/Loja/Galpao: valor = terreno + construcao
    Apartamento/Sala: valor = construcao
    Terreno: valor = terreno

  ETAPA 7 — VALOR DE LIQUIDEZ
  ────────────────────────────
    valor_liquidez = valor_medio * 0.90 (desconto fixo 10%)
    Agentes 3 e 4 NAO alteram este valor.

TRIMMEAN(0.5) — REPRODUZ EXCEL EXATO:
──────────────────────────────────────
    1. Remove valores invalidos (nulos, <= 0)
    2. Ordena
    3. n * 0.5 = quantidade candidata a exclusao
    4. Floor par (arredonda para baixo ate multiplo de 2)
    5. Remove metade do inicio, metade do final
    6. Media aritmetica dos restantes
    7. Se quantidade = 0: media de todos
    Nunca usa mediana como fallback.

LIQUIDEZ EXPERIMENTAL (separada da planilha):
=============================================
    score_liquidez = 0.35 * score_ag3 + 0.40 * score_ag4 + 0.25 * (1 - desconto)
    Classificacao: alta (>=0.80), media_alta (>=0.65), media (>=0.50), baixa (<0.50)
    NAO modifica valor_minimo, valor_medio nem valor_liquidez.

SAIDA JSON:
───────────
    "avaliacao_planilha": { valor_minimo, valor_medio, desconto, valor_liquidez }
    "liquidez_experimental": { score, classificacao, tempo_estimado, aviso }
    "auditoria": { todos os valores intermediarios }

QUEM USA:
─────────
    Interface → exibe valor estimado + liquidez pro usuario

DEPENDENCIAS:
─────────────
    Nenhuma LLM. Apenas Python puro (statistics, json).

COMO RODAR:
───────────
    .venv/Scripts/python.exe -m agents.price_liquidity
"""

import json
import os
import re
from pathlib import Path
from statistics import mean, median
from typing import Any, Dict, List, Optional, Tuple


# ============================================================
# CONSTANTES
# ============================================================

TIPOS_CONDOMINIAIS = {
    "apartamento", "apto", "studio", "kitnet",
    "flat", "sala", "loja", "comercial",
}

TIPOS_TERRENO = {
    "terreno", "lote", "terrenos",
}

CAMINHO_ZONA = "data/zona_homogenea_ag2.json"
CAMINHO_AG3 = "data/imoveis_analisados_ag3.json"
CAMINHO_AG4 = "data/infra_avaliada_ag4.json"
CAMINHO_SAIDA = "data/preco_liquidez_ag5.json"

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


# ============================================================
# FUNCOES AUXILIARES
# ============================================================

def converter_numero(valor: Any) -> Optional[float]:
    """Converte valores variados (int, float, str brasileiro) para float."""
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    if isinstance(valor, str):
        texto = valor.strip()
        if not texto:
            return None
        texto = re.sub(r"[^\d,.-]", "", texto)
        if not texto:
            return None
        # Formato brasileiro: 1.500.000,00
        if "," in texto and "." in texto:
            texto = texto.replace(".", "").replace(",", ".")
        elif "," in texto:
            texto = texto.replace(",", ".")
        elif texto.count(".") > 1:
            texto = texto.replace(".", "")
        try:
            return float(texto)
        except ValueError:
            return None
    return None


def normalizar_tipo(tipo: str) -> str:
    """Normaliza o tipo do imovel para categorias padrao."""
    tipo = str(tipo or "").strip().lower()
    if "apart" in tipo or tipo == "apto":
        return "apartamento"
    if "terreno" in tipo or "lote" in tipo:
        return "terreno"
    if "casa" in tipo or "sobrado" in tipo:
        return "casa"
    if "sala" in tipo or "comercial" in tipo or "loja" in tipo:
        return "sala"
    return tipo


def normalizar_padrao(padrao: str) -> str:
    """Normaliza o padrao construtivo para: baixo, medio, alto."""
    padrao = str(padrao or "").strip().lower()
    if padrao in ["alto", "alto_padrao", "alto padrão", "luxo", "premium"]:
        return "alto"
    if padrao in ["baixo", "baixo_padrao", "baixo padrão", "simples", "popular"]:
        return "baixo"
    return "medio"


def calcular_media_aparada(valores: List[float], proporcao: float = 0.5) -> float:
    """
    Media aparada (TRIMMEAN): reproduz exatamente o TRIMMEAN(range, 0.5) do Excel.

    Passos:
      1. Remove valores invalidos/nulos (mantém apenas > 0)
      2. Ordena os valores
      3. Calcula n * proporcao como quantidade total candidata a exclusao
      4. Arredonda para baixo ate o multiplo de 2 mais proximo (floor par)
      5. Remove metade do inicio e metade do final
      6. Calcula a media aritmetica dos valores restantes
      7. Se quantidade a remover = 0, calcula media de todos os valores validos

    Nunca usa mediana como fallback.
    """
    valores = sorted([v for v in valores if v and v > 0])
    if not valores:
        raise ValueError("Lista de valores vazia.")
    n = len(valores)
    quantidade_remover = int(n * proporcao)
    # Arredonda para baixo ate multiplo de 2
    if quantidade_remover % 2 != 0:
        quantidade_remover -= 1
    # Se quantidade a remover >= n, reduz ate sobrar pelo menos 1 valor
    while quantidade_remover >= n:
        quantidade_remover -= 2
    if quantidade_remover < 0:
        quantidade_remover = 0
    remover_cada_lado = quantidade_remover // 2
    if remover_cada_lado > 0:
        valores_filtrados = valores[remover_cada_lado: n - remover_cada_lado]
    else:
        valores_filtrados = valores
    return mean(valores_filtrados)


def calcular_estatistica(valores: List[float], metodo: str = "mediana") -> float:
    """Calcula estatistica central: media, mediana ou media_aparada."""
    valores = [v for v in valores if v and v > 0]
    if not valores:
        raise ValueError("Nao ha valores validos.")
    if metodo == "media":
        return mean(valores)
    if metodo == "media_aparada":
        return calcular_media_aparada(valores, proporcao=0.5)
    return median(valores)


def arredondar_mil(valor: float) -> int:
    """Arredonda para o milhar mais proximo."""
    return int(round(valor / 1000) * 1000)


# ============================================================
# LEITURA DOS DADOS DOS AGENTES ANTERIORES
# ============================================================

def carregar_json(caminho: str) -> Any:
    """Carrega um arquivo JSON. Retorna {} se nao existir."""
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def salvar_json(dados: Any, caminho: str) -> None:
    """Salva dados em JSON."""
    Path(caminho).parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)


def carregar_dados_pipeline() -> Tuple[Dict, List[Dict], List[Dict], Dict, Dict]:
    """
    Le os JSONs dos agentes anteriores e retorna:
    - imovel_alvo (dict)
    - terrenos_zona (list) — terrenos confirmados na zona (ou anexados por fallback
      quando nenhum foi confirmado — ver Opcao B no Agente 2)
    - comparaveis_zona (list) — imoveis construidos na zona (inclui os de fallback)
    - dados_ag3 (dict) — resultado completo do agente 3
    - dados_ag4 (dict) — resultado completo do agente 4
    """
    # Zona homogenea (Ag. 2)
    zona = carregar_json(CAMINHO_ZONA)
    todos_comparaveis = zona.get("comparaveis_confirmados", [])

    # Fallback: se zona homogenea nao existe, usa comparaveis do Ag. 2 direto
    if not todos_comparaveis:
        import logging
        logger_local = logging.getLogger(__name__)
        caminho_ag2 = os.path.join(DATA_DIR, "imoveis_comparaveis_ag2.json")
        if os.path.exists(caminho_ag2):
            ag2 = carregar_json(caminho_ag2)
            todos_comparaveis = [c for c in ag2.get("comparaveis", []) if c.get("cluster") == "A"]
            logger_local.info(f"Fallback zona: usando {len(todos_comparaveis)} comparaveis do Cluster A")

    # Separar terrenos dos construidos (sem duplicatas por url)
    terrenos_zona = []
    comparaveis_zona = []
    urls_vistos = set()

    for imovel in todos_comparaveis:
        # Deduplicação por URL (mais confiável que id)
        url = imovel.get("url", "")
        if url and url in urls_vistos:
            continue
        if url:
            urls_vistos.add(url)

        tipo = normalizar_tipo(imovel.get("propertyType", ""))
        if tipo in TIPOS_TERRENO:
            terrenos_zona.append(imovel)
        else:
            comparaveis_zona.append(imovel)

    # Agente 3 (analise qualitativa)
    dados_ag3 = carregar_json(CAMINHO_AG3)

    # Agente 4 (infraestrutura)
    dados_ag4 = carregar_json(CAMINHO_AG4)

    # Imovel alvo — pega do Ag. 3 (tem os dados completos)
    # Fallback: se Ag. 3 nao tem, pega do Ag. 2 (imoveis_comparaveis)
    imovel_alvo = dados_ag3.get("imovel_alvo", {})
    if not imovel_alvo:
        ag2 = carregar_json(os.path.join(DATA_DIR, "imoveis_comparaveis_ag2.json"))
        imovel_alvo = ag2.get("imovel_alvo", {})

    return imovel_alvo, terrenos_zona, comparaveis_zona, dados_ag3, dados_ag4


# ============================================================
# EXTRACAO DE CAMPOS DOS IMOVEIS REAIS
# ============================================================

def extrair_preco(imovel: Dict[str, Any]) -> Optional[float]:
    """Extrai o preco do imovel."""
    for campo in ["price", "preco", "valor"]:
        val = converter_numero(imovel.get(campo))
        if val and val > 0:
            return val
    return None


def extrair_area(imovel: Dict[str, Any]) -> Optional[float]:
    """Extrai a area construida (campo 'area' nos dados reais)."""
    for campo in ["area", "area_construida", "usableArea", "area_m2"]:
        val = converter_numero(imovel.get(campo))
        if val and val > 0:
            return val
    return None


def extrair_area_terreno_imovel(imovel: Dict[str, Any]) -> Optional[float]:
    """
    Extrai area do terreno. Para terrenos, usa 'area'.
    Para casas, tenta extrair da descricao (ex: '230m de terreno').
    """
    # Campo direto
    for campo in ["area_terreno_m2", "area_terreno", "lotArea"]:
        val = converter_numero(imovel.get(campo))
        if val and val > 0:
            return val

    # Para terrenos, a area principal E a area do terreno
    tipo = normalizar_tipo(imovel.get("propertyType", ""))
    if tipo in TIPOS_TERRENO:
        return extrair_area(imovel)

    # Tenta extrair da descricao
    descricao = imovel.get("description", "") or ""
    # Padroes: "346 metros quadrados", "230m de terreno", "terreno 300 m²"
    padroes = [
        r"terreno[:\s]+(\d+)\s*m",
        r"(\d+)\s*m[²2]?\s*de\s*terreno",
        r"[aá]rea\s*do\s*terreno\s*(\d+)",
        r"terreno\s*(?:com\s*)?(\d+)\s*m",
    ]
    for padrao in padroes:
        match = re.search(padrao, descricao, re.IGNORECASE)
        if match:
            val = float(match.group(1))
            if val > 0:
                return val

    return None


def extrair_padrao_do_ag3(imovel_id: str, dados_ag3: Dict) -> str:
    """
    Busca o padrao_acabamento do imovel no resultado do Agente 3.
    Retorna 'medio' se nao encontrar.
    """
    # Verifica no imovel alvo
    alvo = dados_ag3.get("imovel_alvo", {})
    analise_alvo = alvo.get("analise_qualitativa", {})
    if not imovel_id or imovel_id == alvo.get("id", ""):
        padrao = analise_alvo.get("padrao_acabamento", "")
        return normalizar_padrao(padrao)

    # Verifica nos comparaveis
    for comp in dados_ag3.get("comparaveis", []):
        if comp.get("id") == imovel_id:
            analise = comp.get("analise_qualitativa", {})
            padrao = analise.get("padrao_acabamento", "")
            return normalizar_padrao(padrao)

    return "medio"


def extrair_score_ag3(dados_ag3: Dict) -> Optional[float]:
    """Extrai o score qualitativo do imovel alvo do Ag. 3."""
    alvo = dados_ag3.get("imovel_alvo", {})
    analise = alvo.get("analise_qualitativa", {})
    scores = analise.get("scores", {})
    val = converter_numero(scores.get("score_qualitativo"))
    if val is not None:
        return val
    # Fallback
    return converter_numero(analise.get("score_qualitativo"))


def extrair_score_ag4(dados_ag4: Dict) -> Optional[float]:
    """Extrai o score de infraestrutura do Ag. 4."""
    scores = dados_ag4.get("scores", {})
    val = converter_numero(scores.get("score_final"))
    if val is not None:
        return val
    # Fallback no resumo
    resumo = dados_ag4.get("resumo_scores", {})
    return converter_numero(resumo.get("score_final"))


# ============================================================
# CALCULO DO M2 DA ZONA HOMOGENEA
# ============================================================

def calcular_valores_m2_terreno(terrenos: List[Dict[str, Any]]) -> List[float]:
    """
    Calcula o valor do m2 dos terrenos da zona homogenea.
    valor_m2_terreno = preco / area
    Se topografia = "Aclive/Declive acentuado", aplica fator 0.80 (desconto 20%).
    """
    valores = []
    for terreno in terrenos:
        preco = extrair_preco(terreno)
        area = extrair_area(terreno)
        if not preco or not area or area <= 0:
            # Tenta pricePerSqm direto
            val_direto = converter_numero(terreno.get("pricePerSqm"))
            if val_direto and val_direto > 0:
                valores.append(val_direto)
            continue

        valor_m2 = preco / area

        # Fator topografia: Aclive/Declive acentuado = 0.80
        topografia = (terreno.get("topografia") or terreno.get("topography") or "").strip().lower()
        if "acentuado" in topografia:
            valor_m2 *= 0.80

        valores.append(valor_m2)

    return valores


def calcular_valor_m2_construcao(
    imovel: Dict[str, Any],
    valor_m2_terreno_zona: float,
    dados_ag3: Dict
) -> Optional[float]:
    """
    Calcula o valor do m2 da construcao de um imovel.
    Segue a logica da planilha do professor:

    Para casa (nao condominial):
        valor_terreno_estimado = area_terreno * m2_terreno_zona
        valor_construcao = preco - valor_terreno_estimado
        valor_m2_construcao = valor_construcao / area_construida

    Para apartamento/condominial:
        valor_m2 = preco / area_construida (terreno nao se separa)

    Para terreno:
        retorna None (nao tem construcao)
    """
    preco = extrair_preco(imovel)
    area_construida = extrair_area(imovel)
    tipo = normalizar_tipo(imovel.get("propertyType", ""))

    if not preco or not area_construida or area_construida <= 0:
        return None

    # Condominial: preco / area direto
    if tipo in TIPOS_CONDOMINIAIS:
        return preco / area_construida

    # Terreno puro: nao tem construcao
    if tipo in TIPOS_TERRENO:
        return None

    # Casa/sobrado: desconta o terreno
    if valor_m2_terreno_zona > 0:
        area_terreno = extrair_area_terreno_imovel(imovel)
        if area_terreno and area_terreno > 0:
            valor_terreno_estimado = area_terreno * valor_m2_terreno_zona
            valor_construcao = preco - valor_terreno_estimado
            if valor_construcao > 0:
                return valor_construcao / area_construida
            # Se deu negativo, o terreno vale mais que o imovel — ignora
            return None

    # Fallback: preco / area (quando nao tem m2 terreno ou area_terreno)
    return preco / area_construida


def agrupar_m2_construcao_por_padrao(
    comparaveis: List[Dict[str, Any]],
    valor_m2_terreno_zona: float,
    dados_ag3: Dict,
    separar_terreno: bool = False
) -> Dict[str, List[float]]:
    """
    Agrupa valores de m2 de construcao por padrao (baixo/medio/alto).

    Se separar_terreno=True, calcula m2 descontando o terreno
    (so usa comparaveis que tem area_terreno).
    Se separar_terreno=False, usa preco/area direto.
    """
    grupos = {"baixo": [], "medio": [], "alto": []}

    for imovel in comparaveis:
        tipo = normalizar_tipo(imovel.get("propertyType", ""))
        if tipo in TIPOS_TERRENO:
            continue

        # Se estamos separando terreno, so usa comparaveis com area_terreno
        if separar_terreno and tipo == "casa":
            area_terreno = extrair_area_terreno_imovel(imovel)
            if not area_terreno or area_terreno <= 0:
                continue

        # Pega padrao do Ag. 3
        imovel_id = imovel.get("id", "")
        padrao = extrair_padrao_do_ag3(imovel_id, dados_ag3)

        valor_m2 = calcular_valor_m2_construcao(
            imovel=imovel,
            valor_m2_terreno_zona=valor_m2_terreno_zona,
            dados_ag3=dados_ag3
        )

        if valor_m2 and valor_m2 > 0:
            grupos[padrao].append(valor_m2)

    return grupos


# ============================================================
# TEMPO DE LIQUIDEZ
# ============================================================

def calcular_score_liquidez(
    score_agente3: Optional[float],
    score_agente4: Optional[float],
    desconto_liquidez: float
) -> float:
    """
    Score de liquidez combinando qualidade, infraestrutura e preco.
    Pesos: qualidade 35%, infraestrutura 40%, preco 25%.
    """
    score_qualidade = score_agente3 if score_agente3 is not None else 0.50
    score_infra = score_agente4 if score_agente4 is not None else 0.50
    score_preco = 1 - desconto_liquidez

    score = (
        0.35 * score_qualidade +
        0.40 * score_infra +
        0.25 * score_preco
    )
    return max(0.0, min(1.0, score))


def classificar_tempo_liquidez(score: float) -> Tuple[str, str]:
    """Classifica o tempo estimado de venda com base no score."""
    if score >= 0.80:
        return "alta", "30 a 60 dias"
    if score >= 0.65:
        return "media_alta", "60 a 90 dias"
    if score >= 0.50:
        return "media", "90 a 150 dias"
    return "baixa", "acima de 150 dias"


# ============================================================
# FUNCAO PRINCIPAL — AGENTE 5
# ============================================================

def executar_agente5(
    imovel_alvo: Dict[str, Any],
    terrenos_zona: List[Dict[str, Any]],
    comparaveis_zona: List[Dict[str, Any]],
    dados_ag3: Dict[str, Any],
    dados_ag4: Dict[str, Any],
    desconto_liquidez: float = 0.10
) -> Dict[str, Any]:
    """
    Agente 5 - Estimador de Preco e Liquidez.
    Segue a logica da planilha do professor (celulas C62-C70).

    Usa TRIMMEAN(0.5) para calcular medias — remove 25% menores e 25% maiores,
    eliminando anuncios com precos fora da realidade.
    Equivalente ao campo "Excluir extremos: Sim" da planilha.
    """
    avisos = []
    metodo_media = "media_aparada"

    # Tipo do imovel alvo
    tipo_alvo = normalizar_tipo(
        imovel_alvo.get("propertyType", "") or imovel_alvo.get("tipo", "")
    )

    # Areas do imovel alvo
    area_construida_alvo = extrair_area(imovel_alvo) or 0.0
    area_terreno_alvo = extrair_area_terreno_imovel(imovel_alvo) or 0.0

    # Padrao do imovel alvo (vem do Ag. 3)
    padrao_alvo = extrair_padrao_do_ag3("", dados_ag3)

    # Scores dos agentes
    score_agente3 = extrair_score_ag3(dados_ag3)
    score_agente4 = extrair_score_ag4(dados_ag4)

    eh_condominial = tipo_alvo in TIPOS_CONDOMINIAIS
    eh_terreno = tipo_alvo in TIPOS_TERRENO

    # ========================================================
    # 1. VALOR M2 DO TERRENO DA ZONA HOMOGENEA
    # ========================================================

    valores_m2_terreno = calcular_valores_m2_terreno(terrenos_zona)

    if valores_m2_terreno:
        menor_m2_terreno = min(valores_m2_terreno)
        medio_m2_terreno = calcular_estatistica(valores_m2_terreno, metodo=metodo_media)
    else:
        menor_m2_terreno = 0.0
        medio_m2_terreno = 0.0
        if not eh_condominial and area_terreno_alvo > 0:
            avisos.append(
                "Nao foram encontrados terrenos comparaveis para calcular o valor m2 do terreno."
            )

    # ========================================================
    # 2. DECISAO: SEPARAR TERRENO OU NAO
    # Regra da planilha:
    # - Se condominial (apto/sala): terreno = 0
    # - Se casa/sobrado com area_terreno: separa
    # - Se casa sem area_terreno: usa m2 total (nao separa)
    # ========================================================

    if eh_condominial or eh_terreno:
        separar_terreno = False
    elif area_terreno_alvo > 0 and valores_m2_terreno:
        separar_terreno = True
    else:
        separar_terreno = False

    # ========================================================
    # 3. DUAS SERIES DE M2 DA CONSTRUCAO (fiel a planilha)
    # Serie 1: desconta terreno usando m2_terreno_MINIMO
    # Serie 2: desconta terreno usando m2_terreno_MEDIO
    # Para apto/sala: preco/area direto (sem desconto terreno)
    # ========================================================

    valores_m2_construcao_min_terreno = []
    valores_m2_construcao_med_terreno = []

    for imovel in comparaveis_zona:
        tipo_comp = normalizar_tipo(imovel.get("propertyType", ""))
        if tipo_comp in TIPOS_TERRENO:
            continue

        preco_comp = extrair_preco(imovel)
        area_construida_comp = extrair_area(imovel)
        if not preco_comp or not area_construida_comp or area_construida_comp <= 0:
            continue

        # Apartamento/Sala: preco/area direto (terreno = 0)
        if tipo_comp in TIPOS_CONDOMINIAIS:
            m2_valor = preco_comp / area_construida_comp
            valores_m2_construcao_min_terreno.append(m2_valor)
            valores_m2_construcao_med_terreno.append(m2_valor)
            continue

        # Casa/Loja/Galpao: desconta terreno
        if separar_terreno:
            area_terreno_comp = extrair_area_terreno_imovel(imovel)
            if not area_terreno_comp or area_terreno_comp <= 0:
                # Sem area terreno: usa preco/area como fallback
                m2_valor = preco_comp / area_construida_comp
                valores_m2_construcao_min_terreno.append(m2_valor)
                valores_m2_construcao_med_terreno.append(m2_valor)
                continue

            # Serie MIN/TERRENO
            valor_terreno_est_min = menor_m2_terreno * area_terreno_comp
            valor_constr_min = preco_comp - valor_terreno_est_min
            if valor_constr_min > 0:
                valores_m2_construcao_min_terreno.append(valor_constr_min / area_construida_comp)

            # Serie MED/TERRENO
            valor_terreno_est_med = medio_m2_terreno * area_terreno_comp
            valor_constr_med = preco_comp - valor_terreno_est_med
            if valor_constr_med > 0:
                valores_m2_construcao_med_terreno.append(valor_constr_med / area_construida_comp)
        else:
            # Nao separa terreno: preco/area direto
            m2_valor = preco_comp / area_construida_comp
            valores_m2_construcao_min_terreno.append(m2_valor)
            valores_m2_construcao_med_terreno.append(m2_valor)

    # Combina as duas series para MIN e MEDIA
    todos_valores_construcao = valores_m2_construcao_min_terreno + valores_m2_construcao_med_terreno

    if todos_valores_construcao:
        menor_m2_construcao = min(todos_valores_construcao)
        medio_m2_construcao = calcular_estatistica(todos_valores_construcao, metodo=metodo_media)
    else:
        menor_m2_construcao = 0.0
        medio_m2_construcao = 0.0
        if not eh_terreno and area_construida_alvo > 0:
            avisos.append(
                "Nao foram encontrados imoveis comparaveis para calcular o valor m2 da construcao."
            )

    # ========================================================
    # 4. CALCULO DO TERRENO
    # ========================================================

    if separar_terreno:
        valor_terreno_minimo = menor_m2_terreno * area_terreno_alvo
        valor_terreno_medio = medio_m2_terreno * area_terreno_alvo
        terreno_aplicado = True
    else:
        valor_terreno_minimo = 0.0
        valor_terreno_medio = 0.0
        terreno_aplicado = False
        if not eh_condominial and not eh_terreno and area_terreno_alvo <= 0:
            avisos.append(
                "Area do terreno do imovel alvo nao informada. "
                "O calculo usou apenas o valor da construcao (preco/m2 total dos comparaveis)."
            )

    # ========================================================
    # 5. CALCULO DA CONSTRUCAO
    # ========================================================

    if eh_terreno or area_construida_alvo <= 0:
        valor_construcao_minimo = 0.0
        valor_construcao_medio = 0.0
        construcao_aplicada = False
    else:
        valor_construcao_minimo = menor_m2_construcao * area_construida_alvo
        valor_construcao_medio = medio_m2_construcao * area_construida_alvo
        construcao_aplicada = True

    # ========================================================
    # 5. VALOR MINIMO E VALOR MEDIO
    # ========================================================

    if eh_condominial:
        valor_minimo_imovel = valor_construcao_minimo
        valor_medio_imovel = valor_construcao_medio
    else:
        valor_minimo_imovel = valor_terreno_minimo + valor_construcao_minimo
        valor_medio_imovel = valor_terreno_medio + valor_construcao_medio

    # ========================================================
    # 6. VALOR DE LIQUIDEZ (desconto de 10%)
    # ========================================================

    valor_liquidez = valor_medio_imovel * (1 - desconto_liquidez)

    # ========================================================
    # 7. LIQUIDEZ EXPERIMENTAL (nao faz parte da planilha)
    # Heuristica multiagente para discussao metodologica.
    # NAO modifica valor_minimo, valor_medio nem valor_liquidez.
    # ========================================================

    score_liquidez = calcular_score_liquidez(score_agente3, score_agente4, desconto_liquidez)
    classificacao_liquidez, tempo_estimado = classificar_tempo_liquidez(score_liquidez)

    # ========================================================
    # 8. RESULTADO FINAL
    # ========================================================

    resultado = {
        "agente": "Agente 5 - Estimador de Preco e Liquidez",
        "metodo": "Valor m2 da zona homogenea (terreno + construcao por padrao)",
        "excluir_extremos": True,
        "metodo_estatistico": "TRIMMEAN(0.5) — remove 25% menores e 25% maiores",
        "imovel_alvo": {
            "tipo": tipo_alvo,
            "area_terreno_m2": area_terreno_alvo,
            "area_construida_m2": area_construida_alvo,
            "padrao_construtivo": padrao_alvo,
        },
        "valor_m2_zona_homogenea": {
            "terreno": {
                "quantidade_amostras": len(valores_m2_terreno),
                "menor_valor_m2": round(menor_m2_terreno, 2),
                "valor_m2_referencia": round(medio_m2_terreno, 2),
                "metodo": metodo_media,
                "valores_individuais": [round(v, 2) for v in valores_m2_terreno],
            },
            "construcao": {
                "serie_min_terreno": {
                    "quantidade_amostras": len(valores_m2_construcao_min_terreno),
                    "valores_m2": [round(v, 2) for v in valores_m2_construcao_min_terreno],
                },
                "serie_med_terreno": {
                    "quantidade_amostras": len(valores_m2_construcao_med_terreno),
                    "valores_m2": [round(v, 2) for v in valores_m2_construcao_med_terreno],
                },
                "combinados": {
                    "quantidade_total": len(todos_valores_construcao),
                    "menor_valor_m2": round(menor_m2_construcao, 2),
                    "valor_m2_referencia": round(medio_m2_construcao, 2),
                    "metodo": metodo_media,
                },
            },
        },
        "calculo_terreno": {
            "aplicado": terreno_aplicado,
            "formula": "valor_m2_terreno_zona * area_terreno",
            "valor_m2_menor": round(menor_m2_terreno, 2),
            "valor_m2_referencia": round(medio_m2_terreno, 2),
            "area_terreno_m2": area_terreno_alvo,
            "valor_terreno_minimo": round(valor_terreno_minimo, 2),
            "valor_terreno_medio": round(valor_terreno_medio, 2),
        },
        "calculo_construcao": {
            "aplicado": construcao_aplicada,
            "formula": "valor_m2_construcao * area_construida",
            "valor_m2_menor": round(menor_m2_construcao, 2),
            "valor_m2_referencia": round(medio_m2_construcao, 2),
            "area_construida_m2": area_construida_alvo,
            "valor_construcao_minimo": round(valor_construcao_minimo, 2),
            "valor_construcao_medio": round(valor_construcao_medio, 2),
        },
        "avaliacao_planilha": {
            "valor_minimo_imovel": round(valor_minimo_imovel, 2),
            "valor_medio_imovel": round(valor_medio_imovel, 2),
            "desconto_liquidez_percentual": round(desconto_liquidez * 100, 1),
            "valor_liquidez": round(valor_liquidez, 2),
            "valor_liquidez_arredondado": arredondar_mil(valor_liquidez),
        },
        "liquidez_experimental": {
            "score_liquidez": round(score_liquidez, 3),
            "classificacao": classificacao_liquidez,
            "tempo_estimado": tempo_estimado,
            "metodo": "heuristica_experimental",
            "pesos": "qualidade 35% + infraestrutura 40% + fator_preco 25%",
            "score_agente3_usado": round(score_agente3, 3) if score_agente3 is not None else None,
            "score_agente4_usado": round(score_agente4, 3) if score_agente4 is not None else None,
            "aviso": "Resultado experimental ainda nao validado com Days on Market dos comparaveis.",
        },
        "auditoria": {
            "valores_m2_terreno": [round(v, 2) for v in valores_m2_terreno],
            "valor_m2_terreno_minimo": round(menor_m2_terreno, 2),
            "valor_m2_terreno_medio": round(medio_m2_terreno, 2),
            "m2_construcao_min_terreno": [round(v, 2) for v in valores_m2_construcao_min_terreno],
            "m2_construcao_med_terreno": [round(v, 2) for v in valores_m2_construcao_med_terreno],
            "valores_m2_construcao_combinados": [round(v, 2) for v in todos_valores_construcao],
            "valor_m2_construcao_minimo": round(menor_m2_construcao, 2),
            "valor_m2_construcao_medio": round(medio_m2_construcao, 2),
        },
        "avisos": avisos,
        "justificativa": (
            f"O valor do imovel foi estimado a partir do m2 da zona homogenea. "
            f"Terreno: {len(valores_m2_terreno)} amostras, m2 referencia R$ {medio_m2_terreno:.2f}. "
            f"Construcao: {len(todos_valores_construcao)} amostras (2 series combinadas), "
            f"m2 referencia R$ {medio_m2_construcao:.2f}. "
            f"Valor medio estimado: R$ {valor_medio_imovel:,.2f}. "
            f"Valor de liquidez (desconto 10%%): R$ {valor_liquidez:,.2f}."
        ),
    }

    return resultado


# ============================================================
# FUNCAO DE ENTRADA (chamada pelo pipeline)
# ============================================================

def estimar_preco(imovel_alvo_extra: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Funcao principal do Agente 5.
    Le os JSONs dos agentes anteriores, calcula e salva o resultado.

    Parametros
    ----------
    imovel_alvo_extra : dict (opcional)
        Campos adicionais do imovel alvo (ex: area_terreno do main.py)
        que complementam os dados do Ag. 3.
    """
    import logging
    logger = logging.getLogger(__name__)

    logger.info("Agente 5: carregando dados dos agentes anteriores...")

    imovel_alvo, terrenos_zona, comparaveis_zona, dados_ag3, dados_ag4 = (
        carregar_dados_pipeline()
    )

    # Complementa imovel_alvo com dados extras (ex: area_terreno do main.py)
    if imovel_alvo_extra:
        for chave, valor in imovel_alvo_extra.items():
            if chave not in imovel_alvo or imovel_alvo.get(chave) is None:
                imovel_alvo[chave] = valor

    logger.info(
        f"[Ag5] Imovel alvo: {imovel_alvo.get('propertyType', '?')} "
        f"- {imovel_alvo.get('area', '?')}m2 "
        f"- {imovel_alvo.get('neighborhood', '?')}"
    )
    logger.info(f"[Ag5] Terrenos na zona: {len(terrenos_zona)}")
    logger.info(f"[Ag5] Comparaveis na zona: {len(comparaveis_zona)}")

    resultado = executar_agente5(
        imovel_alvo=imovel_alvo,
        terrenos_zona=terrenos_zona,
        comparaveis_zona=comparaveis_zona,
        dados_ag3=dados_ag3,
        dados_ag4=dados_ag4,
        desconto_liquidez=0.10,
    )

    salvar_json(resultado, CAMINHO_SAIDA)
    logger.info(f"[Ag5] Resultado salvo em {CAMINHO_SAIDA}")
    audit = resultado.get("auditoria", {})
    logger.info(f"[Ag5] m2 terreno: min R$ {audit.get('valor_m2_terreno_minimo', 0):,.2f} | medio R$ {audit.get('valor_m2_terreno_medio', 0):,.2f} ({len(audit.get('valores_m2_terreno', []))} amostras)")
    logger.info(f"[Ag5] m2 construcao: min R$ {audit.get('valor_m2_construcao_minimo', 0):,.2f} | medio R$ {audit.get('valor_m2_construcao_medio', 0):,.2f} ({len(audit.get('valores_m2_construcao_combinados', []))} amostras)")
    ct = resultado.get("calculo_terreno", {})
    cc = resultado.get("calculo_construcao", {})
    logger.info(f"[Ag5] Terreno: {'aplicado' if ct.get('aplicado') else 'nao aplicado'} | area={ct.get('area_terreno_m2', 0)}m2 | valor medio R$ {ct.get('valor_terreno_medio', 0):,.2f}")
    logger.info(f"[Ag5] Construcao: area={cc.get('area_construida_m2', 0)}m2 | valor medio R$ {cc.get('valor_construcao_medio', 0):,.2f}")
    ap = resultado["avaliacao_planilha"]
    logger.info(f"[Ag5] Valor medio: R$ {ap['valor_medio_imovel']:,.2f}")
    logger.info(f"[Ag5] Valor liquidez: R$ {ap['valor_liquidez']:,.2f} (desconto {ap['desconto_liquidez_percentual']}%)")

    return resultado


# ============================================================
# EXECUCAO DIRETA
# ============================================================

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    resultado = estimar_preco()
    print("\n" + "=" * 55)
    print("RESULTADO AGENTE 5")
    print("=" * 55)
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
