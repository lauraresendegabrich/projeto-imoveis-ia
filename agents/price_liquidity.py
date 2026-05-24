"""
Agente 5 - Estimador de Preco e Liquidez
==========================================

RESPONSABILIDADE:
    Calcula o valor estimado do imovel alvo a partir do valor do metro
    quadrado da zona homogenea, separando terreno e construcao por padrao.
    Estima tambem o tempo de liquidez com base nos scores dos agentes 3 e 4.

ENTRADA:
    - data/zona_homogenea_ag2.json (comparaveis confirmados + terrenos)
    - data/imoveis_analisados_ag3.json (score qualitativo + padrao)
    - data/infra_avaliada_ag4.json (score infraestrutura)
    - imovel_alvo (dict com area, area_terreno, tipo, etc.)

SAIDA:
    - data/preco_liquidez_ag5.json

LOGICA:
    1. Calcula valor m2 do terreno na zona homogenea (terrenos comparaveis)
    2. Calcula valor m2 da construcao por padrao (baixo, medio, alto)
    3. Para o imovel alvo, escolhe o padrao construtivo (do Ag. 3)
    4. Valor minimo e medio do terreno
    5. Valor minimo e medio da construcao
    6. Soma terreno + construcao
    7. Valor de liquidez = valor medio * (1 - desconto)
    8. Estima tempo de liquidez usando scores dos agentes 3 e 4
"""

import json
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
    Media aparada (TRIMMEAN): remove proporcao/2 de cada extremo.
    Se poucos dados, usa mediana.
    """
    valores = sorted([v for v in valores if v and v > 0])
    if not valores:
        raise ValueError("Lista de valores vazia.")
    if len(valores) < 4:
        return median(valores)
    quantidade_remover = int(len(valores) * proporcao)
    if quantidade_remover % 2 != 0:
        quantidade_remover -= 1
    remover_cada_lado = quantidade_remover // 2
    valores_filtrados = valores[remover_cada_lado: len(valores) - remover_cada_lado]
    if not valores_filtrados:
        return median(valores)
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
    """Carrega um arquivo JSON."""
    with open(caminho, "r", encoding="utf-8") as f:
        return json.load(f)


def salvar_json(dados: Any, caminho: str) -> None:
    """Salva dados em JSON."""
    Path(caminho).parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=2)


def carregar_dados_pipeline() -> Tuple[Dict, List[Dict], List[Dict], Dict, Dict]:
    """
    Le os JSONs dos agentes anteriores e retorna:
    - imovel_alvo (dict)
    - terrenos_zona (list) — terrenos com classificacao_zona='na_zona'
    - comparaveis_zona (list) — imoveis construidos na zona
    - dados_ag3 (dict) — resultado completo do agente 3
    - dados_ag4 (dict) — resultado completo do agente 4
    """
    # Zona homogenea (Ag. 2)
    zona = carregar_json(CAMINHO_ZONA)
    todos_comparaveis = zona.get("comparaveis_confirmados", [])

    # Separar terrenos dos construidos (sem duplicatas por id)
    terrenos_zona = []
    comparaveis_zona = []
    ids_vistos = set()

    for imovel in todos_comparaveis:
        imovel_id = imovel.get("id", "")
        if imovel_id in ids_vistos:
            continue
        ids_vistos.add(imovel_id)

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
    imovel_alvo = dados_ag3.get("imovel_alvo", {})

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
    """
    valores = []
    for terreno in terrenos:
        # Tenta pricePerSqm direto
        val_direto = converter_numero(terreno.get("pricePerSqm"))
        if val_direto and val_direto > 0:
            valores.append(val_direto)
            continue

        preco = extrair_preco(terreno)
        area = extrair_area(terreno)
        if preco and area and area > 0:
            valores.append(preco / area)

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
    metodo_media: str = "mediana",
    desconto_liquidez: float = 0.10
) -> Dict[str, Any]:
    """
    Agente 5 - Estimador de Preco e Liquidez.

    1. Calcula valor m2 do terreno na zona homogenea
    2. Calcula valor m2 da construcao por padrao
    3. Para o imovel alvo, escolhe o padrao construtivo
    4. Calcula valor minimo e medio
    5. Calcula liquidez com desconto de 10%
    6. Estima tempo de liquidez
    """
    avisos = []

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
    # 3. VALOR M2 DA CONSTRUCAO POR PADRAO
    # Se separar_terreno=True: so usa comparaveis com area_terreno
    # e desconta o terreno antes de calcular m2 construcao.
    # Se separar_terreno=False: usa preco/area direto.
    # ========================================================

    grupos_construcao = agrupar_m2_construcao_por_padrao(
        comparaveis=comparaveis_zona,
        valor_m2_terreno_zona=medio_m2_terreno,
        dados_ag3=dados_ag3,
        separar_terreno=separar_terreno
    )

    valores_padrao_alvo = grupos_construcao.get(padrao_alvo, [])

    if valores_padrao_alvo:
        menor_m2_construcao = min(valores_padrao_alvo)
        medio_m2_construcao = calcular_estatistica(valores_padrao_alvo, metodo=metodo_media)
    else:
        # Fallback: usa todos os padroes
        todos_valores = (
            grupos_construcao["baixo"] +
            grupos_construcao["medio"] +
            grupos_construcao["alto"]
        )
        if todos_valores:
            menor_m2_construcao = min(todos_valores)
            medio_m2_construcao = calcular_estatistica(todos_valores, metodo=metodo_media)
            avisos.append(
                f"Nao havia amostras suficientes para o padrao '{padrao_alvo}'. "
                "Foi usada a base geral de construcao da zona homogenea."
            )
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
    # 7. TEMPO DE LIQUIDEZ
    # ========================================================

    score_liquidez = calcular_score_liquidez(
        score_agente3=score_agente3,
        score_agente4=score_agente4,
        desconto_liquidez=desconto_liquidez
    )

    classificacao_liquidez, tempo_estimado = classificar_tempo_liquidez(score_liquidez)

    # ========================================================
    # 8. RESULTADO FINAL
    # ========================================================

    resultado = {
        "agente": "Agente 5 - Estimador de Preco e Liquidez",
        "metodo": "Valor m2 da zona homogenea (terreno + construcao por padrao)",
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
            "construcao_por_padrao": {
                "baixo": {
                    "quantidade_amostras": len(grupos_construcao["baixo"]),
                    "valores_m2": [round(v, 2) for v in grupos_construcao["baixo"]],
                },
                "medio": {
                    "quantidade_amostras": len(grupos_construcao["medio"]),
                    "valores_m2": [round(v, 2) for v in grupos_construcao["medio"]],
                },
                "alto": {
                    "quantidade_amostras": len(grupos_construcao["alto"]),
                    "valores_m2": [round(v, 2) for v in grupos_construcao["alto"]],
                },
                "padrao_usado": padrao_alvo,
                "menor_valor_m2_usado": round(menor_m2_construcao, 2),
                "valor_m2_referencia_usado": round(medio_m2_construcao, 2),
                "metodo": metodo_media,
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
            "formula": "valor_m2_construcao_padrao * area_construida",
            "padrao_usado": padrao_alvo,
            "valor_m2_menor": round(menor_m2_construcao, 2),
            "valor_m2_referencia": round(medio_m2_construcao, 2),
            "area_construida_m2": area_construida_alvo,
            "valor_construcao_minimo": round(valor_construcao_minimo, 2),
            "valor_construcao_medio": round(valor_construcao_medio, 2),
        },
        "avaliacao": {
            "valor_minimo_imovel": round(valor_minimo_imovel, 2),
            "valor_medio_imovel": round(valor_medio_imovel, 2),
            "desconto_liquidez_percentual": round(desconto_liquidez * 100, 1),
            "valor_liquidez": round(valor_liquidez, 2),
            "valor_liquidez_arredondado": arredondar_mil(valor_liquidez),
        },
        "liquidez": {
            "score_liquidez": round(score_liquidez, 3),
            "classificacao": classificacao_liquidez,
            "tempo_estimado": tempo_estimado,
            "tempo_liquidez_regional_ag4": dados_ag4.get("resumo_scores", {}).get("tempo_liquidez_regional")
                or dados_ag4.get("analise_llm", {}).get("tempo_liquidez_regional"),
            "composicao_score": {
                "score_qualitativo_ag3": score_agente3,
                "peso_qualitativo": 0.35,
                "score_infraestrutura_ag4": score_agente4,
                "peso_infraestrutura": 0.40,
                "fator_preco": round(1 - desconto_liquidez, 2),
                "peso_preco": 0.25,
            },
        },
        "avisos": avisos,
        "justificativa": (
            f"O valor do imovel foi estimado a partir do m2 da zona homogenea. "
            f"Terreno: {len(valores_m2_terreno)} amostras, m2 referencia R$ {medio_m2_terreno:.2f}. "
            f"Construcao (padrao {padrao_alvo}): {len(valores_padrao_alvo)} amostras, "
            f"m2 referencia R$ {medio_m2_construcao:.2f}. "
            f"Valor medio estimado: R$ {valor_medio_imovel:,.2f}. "
            f"Valor de liquidez (desconto {desconto_liquidez*100:.0f}%): R$ {valor_liquidez:,.2f}. "
            f"Tempo estimado de venda: {tempo_estimado} ({classificacao_liquidez})."
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
        f"  Imovel alvo: {imovel_alvo.get('propertyType', '?')} "
        f"- {imovel_alvo.get('area', '?')}m2 "
        f"- {imovel_alvo.get('neighborhood', '?')}"
    )
    logger.info(f"  Terrenos na zona: {len(terrenos_zona)}")
    logger.info(f"  Comparaveis na zona: {len(comparaveis_zona)}")

    resultado = executar_agente5(
        imovel_alvo=imovel_alvo,
        terrenos_zona=terrenos_zona,
        comparaveis_zona=comparaveis_zona,
        dados_ag3=dados_ag3,
        dados_ag4=dados_ag4,
        metodo_media="mediana",
        desconto_liquidez=0.10,
    )

    salvar_json(resultado, CAMINHO_SAIDA)
    logger.info(f"Agente 5: resultado salvo em {CAMINHO_SAIDA}")
    logger.info(
        f"  Valor medio: R$ {resultado['avaliacao']['valor_medio_imovel']:,.2f}"
    )
    logger.info(
        f"  Valor liquidez: R$ {resultado['avaliacao']['valor_liquidez']:,.2f}"
    )
    logger.info(
        f"  Tempo estimado: {resultado['liquidez']['tempo_estimado']}"
    )

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
