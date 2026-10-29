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
    Apartamento/sala: as duas series sao iguais, entao usa uma so (cada
    comparavel entra uma vez). A planilha juntava F e G tambem para apartamento,
    o que contava cada um duas vezes; nao era intencional.

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
    "avaliacao_confiavel": bool — False quando nao houve amostra (terreno+construcao)
                           ou o valor final ficou <= 0
    "status_avaliacao": "ok" | "sem_amostra" | "valor_nao_estimado"
    "avaliacao_planilha": { valor_minimo, valor_medio, desconto, valor_liquidez }
    "liquidez_experimental": { score, classificacao, tempo_estimado, aviso }
    "auditoria": { todos os valores intermediarios + total_amostras +
                   comparaveis_terreno_maior_que_imovel }

ROBUSTEZ:
─────────
    - Terreno estimado > preco do anuncio: em vez de descartar a construcao (o que
      inflaria o valor final para so o terreno), usa preco/m2 total do comparavel.
    - Sem nenhuma amostra valida OU valor final <= 0: marca avaliacao_confiavel=False
      e status_avaliacao correspondente, em vez de devolver R$ 0 como sucesso.

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

from agents.execucao import ler_json_da_execucao


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

# ------------------------------------------------------------
# FAIXAS DE SANIDADE (anti-dado-corrompido)
# Anuncios com area errada (ex.: terreno cadastrado como 1-2 m2) ou preco em
# unidade errada geram m2 fisicamente impossiveis. Em amostras pequenas o
# TRIMMEAN nao consegue filtrar (precisa de 4+ valores), entao um unico outlier
# multiplica o valor final. Estas faixas descartam o que e claramente lixo antes
# de qualquer media. Sao largas de proposito: cobrem do interior barato ao bairro
# nobre, so cortam o impossivel.
# ------------------------------------------------------------
AREA_MINIMA_VALIDA = 10.0          # m2: abaixo disso e erro de cadastro
M2_TERRENO_MIN = 50.0              # R$/m2 de terreno plausivel (minimo)
M2_TERRENO_MAX = 30000.0          # R$/m2 de terreno plausivel (maximo)
M2_CONSTRUCAO_MIN = 500.0         # R$/m2 de construcao plausivel (minimo)
M2_CONSTRUCAO_MAX = 50000.0       # R$/m2 de construcao plausivel (maximo)
# Casa com menos de MIN_AMOSTRAS_CONFIAVEL terrenos: o terreno nao e separado (calculo
# pelo m2 das casas, como sem nenhum terreno). Decisao da usuaria, 17/10/2026: antes,
# com 1 a 4 terrenos o terreno era separado e a avaliacao dava amostra_insuficiente,
# enquanto com 0 terrenos calculava normalmente.
AVISO_TERRENO_NAO_SEPARADO = (
    "Só {n} {terrenos} à venda na região (mínimo de 5). O valor foi calculado pelo m² das "
    "casas parecidas, sem separar o terreno; se o lote do imóvel for bem maior ou menor "
    "que o das casas comparadas, o valor fica menos preciso."
)
# Sem nota de infraestrutura (Agente 4 nao localizou o endereco ou falhou): o tempo de
# venda usa a nota neutra 0,50 e os pesos de sempre (decisao da usuaria, 17/10/2026).
AVISO_SEM_INFRAESTRUTURA = (
    "Tempo estimado sem a infraestrutura do entorno (endereço não localizado no mapa): a "
    "infraestrutura foi considerada média. Confira o entorno do imóvel."
)
# Mesma situacao, mas o Agente 4 falhou por outro motivo (tempo esgotado, servico fora
# do ar, arquivo desta avaliacao ausente): o endereco pode estar localizado.
AVISO_FALHA_INFRAESTRUTURA = (
    "Tempo estimado sem a infraestrutura do entorno (a avaliação da infraestrutura falhou "
    "nesta rodada): a infraestrutura foi considerada média."
)
MIN_AMOSTRAS_CONFIAVEL = 5        # abaixo disso a estimativa e marcada baixa confianca (era 3 ate out/2026)

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
    # Terreno/lote — reconhece tambem as nomenclaturas do Athena (allotment_land,
    # residential_allotment_land, land, lot). Mantido em sincronia com _eh_terreno
    # do Agente 2, senao um terreno confirmado na zona "sumiria" aqui no calculo.
    tipo_tokens = tipo.replace("_", " ").replace("-", " ")
    if re.search(r"\b(terreno|terrenos|lote|lotes|land|lot|allotment)\b", tipo_tokens):
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


def _remover_cada_lado(n: int, proporcao: float = 0.5) -> int:
    """Quantos valores o TRIMMEAN corta em cada ponta (mesma regra do Excel)."""
    quantidade_remover = int(n * proporcao)
    # Arredonda para baixo ate multiplo de 2
    if quantidade_remover % 2 != 0:
        quantidade_remover -= 1
    # Se quantidade a remover >= n, reduz ate sobrar pelo menos 1 valor
    while quantidade_remover >= n:
        quantidade_remover -= 2
    if quantidade_remover < 0:
        quantidade_remover = 0
    return quantidade_remover // 2


def marcar_media_aparada(valores: List[float], proporcao: float = 0.5) -> List[bool]:
    """
    Para cada valor (na ordem da lista), True se ficou dentro da media aparada e False
    se foi cortado. Mesmo corte de calcular_media_aparada (ordena e tira as pontas);
    so para mostrar a conta de cada anuncio, nao muda o calculo.
    """
    n = len(valores)
    if n == 0:
        return []
    ordem = sorted(range(n), key=lambda i: valores[i])
    r = _remover_cada_lado(n, proporcao)
    mantidos = set(ordem[r:n - r])
    return [i in mantidos for i in range(n)]


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
    remover_cada_lado = _remover_cada_lado(n, proporcao)
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


def carregar_dados_pipeline(
    id_execucao: Optional[str] = None, urls_do_alvo_pela_usuaria: Optional[List[str]] = None,
) -> Tuple[Dict, List[Dict], List[Dict], Dict, Dict]:
    """
    Le os JSONs dos agentes anteriores e retorna:
    - imovel_alvo (dict)
    - terrenos_zona (list) — terrenos confirmados na zona (ou anexados por fallback
      quando nenhum foi confirmado — ver Opcao B no Agente 2)
    - comparaveis_zona (list) — imoveis construidos na zona (inclui os de fallback)
    - dados_ag3 (dict) — resultado completo do agente 3
    - dados_ag4 (dict) — resultado completo do agente 4

    Com id_execucao, so aceita arquivos DESTA avaliacao (ver agents/execucao.py).
    Se a zona homogenea nao rodou nesta avaliacao, nao ha comparaveis (o status
    sai sem_amostra): antes, o arquivo da avaliacao anterior — de outro imovel —
    era usado no calculo. Sem id_execucao (testes/scripts antigos), le como antes.

    urls_do_alvo_pela_usuaria: anuncios que a pessoa disse, na tela, que sao do proprio
    imovel ("Este anuncio e do seu imovel?"). Saem do calculo como os confirmados pelo Ag2.
    """
    import logging
    logger_local = logging.getLogger(__name__)
    urls_pela_usuaria = set(urls_do_alvo_pela_usuaria or ())

    def _ler(caminho: str) -> Dict:
        if id_execucao:
            return ler_json_da_execucao(caminho, id_execucao) or {}
        return carregar_json(caminho)

    caminho_ag2 = os.path.join(DATA_DIR, "imoveis_comparaveis_ag2.json")

    # Zona homogenea (Ag. 2)
    zona = _ler(CAMINHO_ZONA)
    todos_comparaveis = zona.get("comparaveis_confirmados", [])

    # Fallback: zona desta avaliacao sem confirmados (ex.: alvo nao geocodificado)
    # usa o Cluster A do Ag. 2. Se a zona nem rodou nesta avaliacao, nao ha fallback.
    zona_desta_execucao = bool(zona) or not id_execucao
    if not todos_comparaveis and zona_desta_execucao:
        ag2 = _ler(caminho_ag2)
        if ag2:
            # Anuncios trazidos de fora da rua/bairro (proximidade) so valem com o
            # circulo da zona confirmando a distancia; no socorro nao ha circulo.
            todos_comparaveis = [
                dict(c, _sem_validacao_zona=True)
                for c in ag2.get("comparaveis", [])
                if c.get("cluster") == "A" and c.get("origem_busca") not in ("proximidade", "cidade")
            ]
            logger_local.info(f"Fallback zona: usando {len(todos_comparaveis)} comparaveis do Cluster A")
    elif not zona_desta_execucao:
        logger_local.warning(
            "[Ag5] Zona homogenea nao calculada nesta avaliacao: sem comparaveis (sem_amostra)"
        )

    # Separar terrenos dos construidos (sem duplicatas).
    # Deduplica por chave de negocio estavel: url -> id/listing_id -> composicao
    # de campos. Cobrir o caso sem url evita contar 2x um imovel que tenha vazado
    # duplicado da etapa anterior.
    terrenos_zona = []
    comparaveis_zona = []
    chaves_vistas = set()

    def _chave_dedup(im: Dict[str, Any]) -> str:
        for campo in ("url", "id", "listing_id"):
            val = im.get(campo)
            if val:
                return f"{campo}:{val}"
        # Sem identificador proprio: usa composicao de atributos como chave.
        return "comp:" + "|".join(str(im.get(c, "")) for c in (
            "propertyType", "price", "area", "bedrooms", "bathrooms", "street", "neighborhood"
        ))

    excluidos_anuncio_alvo = 0
    for imovel in todos_comparaveis:
        # O Ag2 marca o proprio anuncio do imovel-alvo (quando ele aparece entre os
        # coletados). Ele e excluido do CALCULO de preco para nao ancorar a estimativa
        # no preco pedido pelo usuario. Continua disponivel nos demais agentes/interface.
        if imovel.get("eh_anuncio_do_alvo") or (imovel.get("url") and imovel.get("url") in urls_pela_usuaria):
            excluidos_anuncio_alvo += 1
            continue

        chave = _chave_dedup(imovel)
        if chave in chaves_vistas:
            continue
        chaves_vistas.add(chave)

        # Le o tipo de AMBOS os campos (propertyType e tipo). Terrenos do Athena
        # podem trazer 'Terrenos' em propertyType e 'residential_allotment_land' em tipo,
        # ou vice-versa; checar os dois evita que o terreno "vaze" para construidos.
        tipo_bruto = imovel.get("propertyType") or imovel.get("tipo") or ""
        tipo_bruto_alt = imovel.get("tipo") or ""
        eh_terreno = (
            normalizar_tipo(tipo_bruto) in TIPOS_TERRENO
            or normalizar_tipo(tipo_bruto_alt) in TIPOS_TERRENO
        )
        if eh_terreno:
            terrenos_zona.append(imovel)
        else:
            comparaveis_zona.append(imovel)

    # LOG DE RASTREAMENTO (auditoria da separacao terreno x construcao).
    import logging as _log_ag5
    _lg = _log_ag5.getLogger(__name__)
    _lg.info("[Ag5][Separacao] === ENTRADA (comparaveis_confirmados da zona) ===")
    for _i, _im in enumerate(todos_comparaveis):
        _lg.info(
            f"[Ag5][Separacao] [{_i}] propertyType={_im.get('propertyType')!r} | tipo={_im.get('tipo')!r} "
            f"| normalizado={normalizar_tipo(_im.get('propertyType') or _im.get('tipo'))!r} "
            f"| classificacao_zona={_im.get('classificacao_zona')!r} "
            f"| preco={_im.get('price') or _im.get('preco')} | url={str(_im.get('url'))[:60]}"
        )
    _lg.info(f"[Ag5][Separacao] RESULTADO -> CONSTRUCOES={len(comparaveis_zona)} | TERRENOS={len(terrenos_zona)}")

    if excluidos_anuncio_alvo:
        _lg.info(
            f"[Ag5] {excluidos_anuncio_alvo} anuncio(s) do proprio alvo excluido(s) do "
            f"calculo de preco (marcados pelo Ag2 como eh_anuncio_do_alvo"
            + (f" ou pela usuaria na tela: {len(urls_pela_usuaria)}" if urls_pela_usuaria else "") + ")"
        )

    # Agente 3 (analise qualitativa) e Agente 4 (infraestrutura): se falharam nesta
    # avaliacao, o arquivo em disco e de outra; com id_execucao ele e ignorado.
    dados_ag3 = _ler(CAMINHO_AG3)
    dados_ag4 = _ler(CAMINHO_AG4)

    # Imovel alvo — pega do Ag. 3 (tem os dados completos)
    # Fallback: se Ag. 3 nao tem, pega do Ag. 2 (imoveis_comparaveis)
    imovel_alvo = dados_ag3.get("imovel_alvo", {})
    if not imovel_alvo:
        imovel_alvo = _ler(caminho_ag2).get("imovel_alvo", {})
    # Quantos anuncios do proprio imovel sairam do calculo: so para os textos (o
    # aviso de amostra explica a diferenca para a contagem da zona).
    imovel_alvo = {**imovel_alvo, "anuncios_do_alvo_excluidos": excluidos_anuncio_alvo}

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

def calcular_valores_m2_terreno(terrenos: List[Dict[str, Any]], coletar_usados: bool = False):
    """
    Calcula o valor do m2 dos terrenos da zona homogenea.
    valor_m2_terreno = preco / area
    Se topografia = "Aclive/Declive acentuado", aplica fator 0.80 (desconto 20%).

    Se coletar_usados=True, retorna (valores, terrenos_usados) — a lista dos
    terrenos que efetivamente entraram no calculo (para exibir na interface).
    """
    valores = []
    usados = []
    descartados = 0
    for terreno in terrenos:
        preco = extrair_preco(terreno)
        area = extrair_area(terreno)

        # Area minima valida: abaixo disso e erro de cadastro (ex.: terreno "1 m2"),
        # que geraria um m2 gigante. Nesses casos, so aproveita pricePerSqm se vier
        # explicito e plausivel.
        if not preco or not area or area < AREA_MINIMA_VALIDA:
            val_direto = converter_numero(terreno.get("pricePerSqm"))
            if val_direto and M2_TERRENO_MIN <= val_direto <= M2_TERRENO_MAX:
                valores.append(val_direto)
                usados.append(terreno)
            else:
                descartados += 1
            continue

        valor_m2 = preco / area

        # Fator topografia: Aclive/Declive acentuado = 0.80
        topografia = (terreno.get("topografia") or terreno.get("topography") or "").strip().lower()
        if "acentuado" in topografia:
            valor_m2 *= 0.80

        # Filtro de sanidade: descarta m2 fisicamente impossivel (dado corrompido).
        if valor_m2 < M2_TERRENO_MIN or valor_m2 > M2_TERRENO_MAX:
            descartados += 1
            continue

        valores.append(valor_m2)
        usados.append(terreno)

    if descartados:
        import logging
        logging.getLogger(__name__).info(
            f"[Ag5][Sanidade] {descartados} terreno(s) descartado(s) por m2 fora da "
            f"faixa R$ {M2_TERRENO_MIN:.0f}-{M2_TERRENO_MAX:.0f} ou area < {AREA_MINIMA_VALIDA:.0f}m2"
        )

    if coletar_usados:
        return valores, usados, descartados
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
    excluidos_anuncio_alvo = int(imovel_alvo.get("anuncios_do_alvo_excluidos") or 0)

    def _cheira_leilao(im: Dict[str, Any]) -> bool:
        """Heuristica leve de auditoria: o texto do imovel tem cara de leilao?"""
        termos = (
            "leilao", "leilão", "leiloes", "leilões", "leiloeiro", "judicial",
            "arremat", "licitac", "licitaç", "venda direta", "retomad",
            "alienacao fiduciaria", "alienação fiduciária", "hasta publica",
            "wiser", "sodre santoro", "zukerman", "mega leiloes",
        )
        texto = " ".join([
            str(im.get("title") or im.get("titulo") or ""),
            str(im.get("description") or im.get("descricao") or ""),
            str(im.get("source") or im.get("source_site") or ""),
        ]).lower()
        return any(t in texto for t in termos)

    def _resumo_imovel(im: Dict[str, Any]) -> Dict[str, Any]:
        """Resumo enxuto de um comparavel para exibir na interface (com link + auditoria)."""
        return {
            "url": im.get("url") or "",
            "rua": im.get("street") or im.get("rua") or "",
            "bairro": im.get("neighborhood") or im.get("bairro") or "",
            "preco": extrair_preco(im),
            "area": extrair_area(im),
            "area_terreno": extrair_area_terreno_imovel(im),
            "quartos": im.get("bedrooms") or im.get("quartos"),
            "tipo": im.get("propertyType") or im.get("tipo") or "",
            # Sinais de auditoria: eh_anuncio_do_alvo=True e excluido do calculo;
            # possivel_anuncio_do_alvo=True PERMANECE no calculo (so alerta).
            "eh_anuncio_do_alvo": bool(im.get("eh_anuncio_do_alvo")),
            "possivel_anuncio_do_alvo": bool(im.get("possivel_anuncio_do_alvo")),
            # Suspeito com o perfil quase todo igual (Ag2): tambem continua no calculo.
            "provavel_anuncio_do_alvo": bool(im.get("provavel_anuncio_do_alvo")),
            "suspeita_leilao": _cheira_leilao(im),
            # De onde veio o comparavel (nao muda o calculo; usado no aviso da
            # avaliacao de leilao e na auditoria):
            #   confirmado    = dentro do raio da zona homogenea
            #   mesmo_bairro  = fora da zona, no mesmo bairro ate 2,5 km (amostra escassa)
            #   fallback      = zona_nao_verificada anexado por amostra escassa
            #   sem_validacao = Cluster A do Ag2 usado sem zona (alvo nao geocodificado)
            "status_zona": (
                "mesmo_bairro" if im.get("incluido_por_mesmo_bairro")
                else "fallback" if im.get("incluido_por_fallback_zona")
                else "sem_validacao" if im.get("_sem_validacao_zona")
                else "confirmado"
            ),
            "portal": im.get("source") or im.get("portal") or "",
            # Mesmo imovel com areas diferentes entre portais (Ag1): area de cada
            # portal; o calculo ja usa a area escolhida (menor, para casa/apto).
            "areas_entre_portais": im.get("areas_entre_portais"),
            # Mesma casa (rua, numero, area, quartos) anunciada por imobiliarias diferentes
            # com precos diferentes (Ag1): conta como 1, com a mediana dos precos.
            "precos_entre_imobiliarias": im.get("precos_entre_imobiliarias"),
            "preco_original": im.get("preco_original"),
            # Grupo de anuncios iguais de imobiliarias diferentes (Ag1): conta como 1.
            "provavel_lancamento": im.get("provavel_lancamento"),
            "area_original": im.get("area_original"),
        }

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

    valores_m2_terreno, usados_terreno, terrenos_descartados_sanidade = calcular_valores_m2_terreno(
        terrenos_zona, coletar_usados=True
    )

    if valores_m2_terreno:
        menor_m2_terreno = min(valores_m2_terreno)
        medio_m2_terreno = calcular_estatistica(valores_m2_terreno, metodo=metodo_media)
    else:
        menor_m2_terreno = 0.0
        medio_m2_terreno = 0.0
        if not eh_condominial and area_terreno_alvo > 0:
            if terrenos_descartados_sanidade > 0:
                # Transparencia: havia terreno na zona, mas com preco/area gerando um
                # valor de m2 fora do plausivel (ex.: regiao muito barata ou dado
                # inconsistente do anuncio). Foi descartado para nao distorcer o calculo.
                avisos.append(
                    (f"{terrenos_descartados_sanidade} terreno estava na zona, mas foi descartado"
                     if terrenos_descartados_sanidade == 1 else
                     f"{terrenos_descartados_sanidade} terrenos estavam na zona, mas foram descartados")
                    + f" por ter preço/área que resulta em valor de m² fora da faixa plausível "
                    f"(R$ {M2_TERRENO_MIN:.0f} a R$ {M2_TERRENO_MAX:,.0f}/m²). ".replace(",", ".")
                    + "Pode ser região muito barata ou dado inconsistente do anúncio."
                )
            else:
                avisos.append(
                    "Não foram encontrados terrenos comparáveis para calcular o valor do m² do terreno."
                )

    # ========================================================
    # 2. DECISAO: SEPARAR TERRENO OU NAO
    # Regra da planilha:
    # - Se condominial (apto/sala): terreno = 0
    # - Se casa/sobrado com area_terreno e 5+ terrenos na zona: separa
    # - Se casa com 1 a 4 terrenos: nao separa (m2 total), terrenos fora do calculo
    # - Se casa sem area_terreno ou sem terrenos: usa m2 total (nao separa)
    # ========================================================

    aviso_terreno = None
    # Motivo para os terrenos da zona que nao entram no calculo quando o terreno nao e
    # separado (None quando separa ou quando o alvo e um terreno, que usa os terrenos).
    motivo_terreno_fora = None
    if eh_terreno:
        separar_terreno = False
    elif eh_condominial:
        separar_terreno = False
        motivo_terreno_fora = "apartamento/sala: o terreno não entra no cálculo"
    elif area_terreno_alvo > 0 and len(valores_m2_terreno) >= MIN_AMOSTRAS_CONFIAVEL:
        separar_terreno = True
    else:
        separar_terreno = False
        if area_terreno_alvo <= 0:
            motivo_terreno_fora = "terreno do imóvel não informado: o valor foi calculado pelo m² das casas"
        if area_terreno_alvo > 0 and valores_m2_terreno:
            # Poucos terrenos: nao entram no calculo (ficam como descartados).
            n_terrenos_poucos = len(valores_m2_terreno)
            aviso_terreno = AVISO_TERRENO_NAO_SEPARADO.format(
                n=n_terrenos_poucos, terrenos="terreno" if n_terrenos_poucos == 1 else "terrenos"
            )
            import logging as _log_t
            _log_t.getLogger(__name__).info(
                f"[Ag5] terreno nao separado: {n_terrenos_poucos} terrenos "
                f"(< {MIN_AMOSTRAS_CONFIAVEL}); calculo pelo m2 das casas"
            )

    if not separar_terreno and not eh_terreno:
        usados_terreno = []

    # ========================================================
    # 3. DUAS SERIES DE M2 DA CONSTRUCAO (fiel a planilha)
    # Serie 1: desconta terreno usando m2_terreno_MINIMO
    # Serie 2: desconta terreno usando m2_terreno_MEDIO
    # Para apto/sala: preco/area direto (sem desconto terreno)
    # ========================================================

    valores_m2_construcao_min_terreno = []
    valores_m2_construcao_med_terreno = []
    comparaveis_terreno_maior = 0  # comparaveis onde o terreno estimado > preco do anuncio
    construcao_descartados = 0     # m2 de construcao fora da faixa de sanidade
    # [resumo do imovel, quantos valores de m2 dele passaram na sanidade]. Separa os
    # que entraram de fato no m2 de construcao dos descartados (auditoria/banco).
    registros_construcao = []
    descartados_construcao = []    # na zona, mas sem preco/area validos ou com m2 implausivel

    # De qual imovel (indice em registros_construcao) veio cada valor das duas series:
    # para mostrar a conta de cada anuncio (funil), sem mudar o calculo.
    donos_min_terreno, donos_med_terreno = [], []

    def _add_sanidade(lista, valor):
        """Adiciona so se o m2 de construcao for fisicamente plausivel."""
        nonlocal construcao_descartados
        if M2_CONSTRUCAO_MIN <= valor <= M2_CONSTRUCAO_MAX:
            lista.append(valor)
            donos = donos_min_terreno if lista is valores_m2_construcao_min_terreno else donos_med_terreno
            donos.append(len(registros_construcao) - 1)
            if registros_construcao:
                registros_construcao[-1][1] += 1
            return True
        construcao_descartados += 1
        return False

    for imovel in comparaveis_zona:
        tipo_comp = normalizar_tipo(imovel.get("propertyType", ""))
        if tipo_comp in TIPOS_TERRENO:
            continue

        preco_comp = extrair_preco(imovel)
        area_construida_comp = extrair_area(imovel)
        # Area minima valida: descarta anuncio com area corrompida (ex.: "1 m2").
        if not preco_comp or not area_construida_comp or area_construida_comp < AREA_MINIMA_VALIDA:
            descartados_construcao.append({
                **_resumo_imovel(imovel),
                "motivo_descarte": f"sem preço ou área construída válida (área menor que {AREA_MINIMA_VALIDA:.0f} m²)",
            })
            continue

        # Registra o imovel (uma vez); conta como usado se algum m2 dele entrar.
        registros_construcao.append([_resumo_imovel(imovel), 0])

        # Apartamento/Sala: preco/area direto (terreno = 0)
        if tipo_comp in TIPOS_CONDOMINIAIS:
            m2_valor = preco_comp / area_construida_comp
            _add_sanidade(valores_m2_construcao_min_terreno, m2_valor)
            _add_sanidade(valores_m2_construcao_med_terreno, m2_valor)
            continue

        # Casa/Loja/Galpao: desconta terreno
        if separar_terreno:
            area_terreno_comp = extrair_area_terreno_imovel(imovel)
            if not area_terreno_comp or area_terreno_comp <= 0:
                # Sem area terreno: usa preco/area como fallback
                m2_valor = preco_comp / area_construida_comp
                _add_sanidade(valores_m2_construcao_min_terreno, m2_valor)
                _add_sanidade(valores_m2_construcao_med_terreno, m2_valor)
                continue

            # Serie MIN/TERRENO
            valor_terreno_est_min = menor_m2_terreno * area_terreno_comp
            valor_constr_min = preco_comp - valor_terreno_est_min

            # Serie MED/TERRENO
            valor_terreno_est_med = medio_m2_terreno * area_terreno_comp
            valor_constr_med = preco_comp - valor_terreno_est_med

            # Quando o terreno estimado vale MAIS que o proprio anuncio, a construcao
            # descontada fica <= 0. Antes esses valores eram simplesmente descartados;
            # se isso acontecesse com todos os comparaveis, a serie de construcao ficava
            # vazia e o valor final virava so o terreno (superestimado). Agora, quando
            # ambas as series dariam <= 0 para este imovel, usamos preco/area total como
            # fallback para nao perder a amostra e nao inflar o valor.
            if valor_constr_min > 0:
                _add_sanidade(valores_m2_construcao_min_terreno, valor_constr_min / area_construida_comp)
            if valor_constr_med > 0:
                _add_sanidade(valores_m2_construcao_med_terreno, valor_constr_med / area_construida_comp)

            if valor_constr_min <= 0 and valor_constr_med <= 0:
                comparaveis_terreno_maior += 1
                m2_valor = preco_comp / area_construida_comp
                _add_sanidade(valores_m2_construcao_min_terreno, m2_valor)
                _add_sanidade(valores_m2_construcao_med_terreno, m2_valor)
        else:
            # Nao separa terreno: preco/area direto
            m2_valor = preco_comp / area_construida_comp
            _add_sanidade(valores_m2_construcao_min_terreno, m2_valor)
            _add_sanidade(valores_m2_construcao_med_terreno, m2_valor)

    usados_construcao = [resumo for resumo, aceitos in registros_construcao if aceitos > 0]
    descartados_construcao += [
        {**resumo, "motivo_descarte": (
            f"R$/m² da construção fora da faixa plausível (R$ {M2_CONSTRUCAO_MIN:,.0f} a "
            f"R$ {M2_CONSTRUCAO_MAX:,.0f})".replace(",", ".")
        )}
        for resumo, aceitos in registros_construcao if aceitos == 0
    ]
    # Motivo de cada terreno fora do calculo (auditoria e funil da tela).
    if aviso_terreno:
        motivo_terreno = (
            f"terreno não separado: só {len(valores_m2_terreno)} "
            f"{'terreno válido' if len(valores_m2_terreno) == 1 else 'terrenos válidos'} (mínimo de "
            f"{MIN_AMOSTRAS_CONFIAVEL}); o valor foi calculado pelo m² das casas"
        )
    elif motivo_terreno_fora:
        motivo_terreno = motivo_terreno_fora
    else:
        motivo_terreno = (
            f"preço ou área inválidos, ou R$/m² fora da faixa plausível (R$ {M2_TERRENO_MIN:.0f} a "
            f"R$ {M2_TERRENO_MAX:,.0f})".replace(",", ".")
        )
    descartados_terreno = [
        {**_resumo_imovel(t), "motivo_descarte": motivo_terreno}
        for t in terrenos_zona if not any(t is u for u in usados_terreno)
    ]

    if construcao_descartados:
        import logging as _log_c
        _log_c.getLogger(__name__).info(
            f"[Ag5][Sanidade] {construcao_descartados} valor(es) de m2 de construcao "
            f"descartado(s) por estar fora da faixa R$ {M2_CONSTRUCAO_MIN:.0f}-{M2_CONSTRUCAO_MAX:.0f}"
        )

    # Combina as duas series para MIN e MEDIA (planilha: MEDIA.INTERNA($F$38:$G$57)).
    # Apartamento/sala: as duas series sao iguais (preco/area, sem terreno), e juntar
    # contaria cada comparavel duas vezes. Com 3, 6, 7, 10, 11... comparaveis o corte
    # do TRIMMEAN separava as duas copias de um mesmo anuncio e mudava o valor (ex.:
    # BH/Floresta, 6 aptos: R$ 5.691,69 x R$ 5.721,10/m2). Nao era intencional na
    # planilha (confirmado em 17/10/2026): para condominial usa uma serie so.
    if eh_condominial:
        todos_valores_construcao = list(valores_m2_construcao_min_terreno)
        donos_construcao = list(donos_min_terreno)
    else:
        todos_valores_construcao = valores_m2_construcao_min_terreno + valores_m2_construcao_med_terreno
        donos_construcao = donos_min_terreno + donos_med_terreno

    # Conta de cada anuncio (funil e auditoria): seus R$/m2 e se cada um ficou dentro
    # da media aparada ou foi cortado. Nao muda o calculo.
    for valor, dono, ficou in zip(
        todos_valores_construcao, donos_construcao, marcar_media_aparada(todos_valores_construcao)
    ):
        if 0 <= dono < len(registros_construcao):
            registros_construcao[dono][0].setdefault("conta_m2", []).append(
                {"valor_m2": round(valor, 2), "na_media": ficou}
            )

    if todos_valores_construcao:
        menor_m2_construcao = min(todos_valores_construcao)
        medio_m2_construcao = calcular_estatistica(todos_valores_construcao, metodo=metodo_media)
    else:
        menor_m2_construcao = 0.0
        medio_m2_construcao = 0.0
        if not eh_terreno and area_construida_alvo > 0:
            avisos.append(
                "Não foram encontrados imóveis comparáveis para calcular o valor do m² da construção."
            )

    if comparaveis_terreno_maior > 0:
        avisos.append(
            ("1 comparável tinha o terreno estimado valendo mais que o próprio anúncio; para ele"
             if comparaveis_terreno_maior == 1 else
             f"{comparaveis_terreno_maior} comparáveis tinham o terreno estimado valendo mais que o "
             f"próprio anúncio; para esses")
            + " foi usado o preço/m² total (evita superestimar o valor da construção). "
            "Reveja se o m² de terreno da zona está coerente."
        )

    # ========================================================
    # 4. CALCULO DO TERRENO
    # ========================================================

    if eh_terreno:
        # Alvo e terreno puro: o valor e so o terreno (m2 da zona * area do lote).
        # A decisao de "separar" nao se aplica; o terreno E o proprio imovel.
        if valores_m2_terreno and area_terreno_alvo > 0:
            valor_terreno_minimo = menor_m2_terreno * area_terreno_alvo
            valor_terreno_medio = medio_m2_terreno * area_terreno_alvo
            terreno_aplicado = True
        else:
            valor_terreno_minimo = 0.0
            valor_terreno_medio = 0.0
            terreno_aplicado = False
            if not valores_m2_terreno:
                avisos.append(
                    "O imóvel é um terreno, mas não há terrenos comparáveis na zona para "
                    "estimar o valor do m²."
                )
            elif area_terreno_alvo <= 0:
                avisos.append("Área do terreno do imóvel não informada.")
    elif separar_terreno:
        valor_terreno_minimo = menor_m2_terreno * area_terreno_alvo
        valor_terreno_medio = medio_m2_terreno * area_terreno_alvo
        terreno_aplicado = True
    else:
        valor_terreno_minimo = 0.0
        valor_terreno_medio = 0.0
        terreno_aplicado = False
        if not eh_condominial and not eh_terreno and area_terreno_alvo <= 0:
            avisos.append(
                "Área do terreno do imóvel não informada. "
                "O cálculo usou só o m² total dos comparáveis (preço ÷ área construída)."
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
    # 6b. CONFIABILIDADE DA AVALIACAO
    # Sem amostra de terreno E de construcao, ou valor final <= 0, o resultado
    # nao e confiavel. Antes isso saia como R$ 0,00 com status de sucesso, o que
    # enganava a interface. Agora sinalizamos explicitamente.
    # ========================================================

    total_amostras = len(valores_m2_terreno) + len(todos_valores_construcao)
    # Numero de comparaveis DISTINTOS por serie (a serie min tem 1 valor por
    # comparavel; a lista combinada dobra, entao usamos a serie unica para contar).
    n_construcao = len(valores_m2_construcao_min_terreno)
    n_terreno = len(valores_m2_terreno)
    avaliacao_confiavel = True
    status_avaliacao = "ok"

    if total_amostras == 0:
        avaliacao_confiavel = False
        status_avaliacao = "sem_amostra"
        avisos.append(
            "Nenhum comparável válido (terreno ou construção) foi encontrado na zona. "
            "Não foi possível estimar o valor do imóvel."
        )
    elif valor_medio_imovel <= 0:
        avaliacao_confiavel = False
        status_avaliacao = "valor_nao_estimado"
        avisos.append(
            "O cálculo resultou em valor zero ou negativo. A avaliação não é confiável "
            "(verifique a área do imóvel e os comparáveis da zona)."
        )
    else:
        # Amostra pequena: o valor sai, mas nao e estatisticamente solido. Com poucos
        # comparaveis o TRIMMEAN nao filtra outliers e um unico anuncio domina a media.
        motivos_baixa = []
        if not eh_terreno and n_construcao < MIN_AMOSTRAS_CONFIAVEL:
            motivos_baixa.append(
                ("apenas 1 comparável de construção" if n_construcao == 1 else
                 f"apenas {n_construcao} comparáveis de construção")
                # Explica a diferenca para a contagem da zona (texto apenas).
                + (" (o anúncio do próprio imóvel saiu do cálculo)" if excluidos_anuncio_alvo == 1 else
                   f" ({excluidos_anuncio_alvo} anúncios do próprio imóvel saíram do cálculo)"
                   if excluidos_anuncio_alvo > 1 else "")
            )
        if separar_terreno and n_terreno < MIN_AMOSTRAS_CONFIAVEL:
            motivos_baixa.append(f"apenas {n_terreno} {'terreno comparável' if n_terreno == 1 else 'terrenos comparáveis'}")
        if eh_terreno and n_terreno < MIN_AMOSTRAS_CONFIAVEL:
            motivos_baixa.append(f"apenas {n_terreno} {'terreno comparável' if n_terreno == 1 else 'terrenos comparáveis'}")
        if motivos_baixa:
            avaliacao_confiavel = False
            status_avaliacao = "amostra_insuficiente"
            avisos.append(
                "Amostra insuficiente para uma estimativa confiável ("
                + "; ".join(motivos_baixa)
                + f"; mínimo desejado: {MIN_AMOSTRAS_CONFIAVEL}). "
                "O valor calculado é uma referência fraca, baseada em poucos anúncios."
            )

    # ========================================================
    # 7. LIQUIDEZ EXPERIMENTAL (nao faz parte da planilha)
    # Heuristica multiagente para discussao metodologica.
    # NAO modifica valor_minimo, valor_medio nem valor_liquidez.
    # ========================================================

    score_liquidez = calcular_score_liquidez(score_agente3, score_agente4, desconto_liquidez)
    classificacao_liquidez, tempo_estimado = classificar_tempo_liquidez(score_liquidez)
    aviso_infraestrutura = None
    if score_agente4 is None:
        nao_localizado = (dados_ag4 or {}).get("status") == "endereco_nao_localizado"
        aviso_infraestrutura = AVISO_SEM_INFRAESTRUTURA if nao_localizado else AVISO_FALHA_INFRAESTRUTURA
        import logging as _log_i
        _log_i.getLogger(__name__).warning(
            f"[Ag5] liquidez sem nota de infraestrutura: usado neutro 0,50 | "
            f"score={score_liquidez:.3f} | tempo={tempo_estimado} | "
            f"motivo={'endereco_nao_localizado' if nao_localizado else 'falha_agente4'}"
        )

    # ========================================================
    # 8. RESULTADO FINAL
    # ========================================================

    resultado = {
        "agente": "Agente 5 - Estimador de Preco e Liquidez",
        "metodo": "Valor m2 da zona homogenea (terreno + construcao por padrao)",
        "avaliacao_confiavel": avaliacao_confiavel,
        "status_avaliacao": status_avaliacao,
        "anuncios_do_alvo_excluidos": excluidos_anuncio_alvo,
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
            # Sem nota do Agente 4: infraestrutura neutra (0,50) e este aviso.
            "aviso_infraestrutura": aviso_infraestrutura,
        },
        "comparaveis_usados": {
            "construcao": usados_construcao,
            # Terrenos usados, na mesma ordem de valores_m2_terreno: com a conta de cada um.
            "terreno": [
                {**_resumo_imovel(t), "conta_m2": [{"valor_m2": round(v, 2), "na_media": ficou}],
                 # Para refazer o R$/m2 do terreno (verificacoes): fator de topografia
                 # e preco/m2 do anuncio quando a area e invalida.
                 "topografia": t.get("topografia") or t.get("topography"),
                 "preco_m2_anuncio": t.get("pricePerSqm")}
                for t, v, ficou in zip(usados_terreno, valores_m2_terreno, marcar_media_aparada(valores_m2_terreno))
            ] if len(usados_terreno) == len(valores_m2_terreno) else [_resumo_imovel(t) for t in usados_terreno],
        },
        # Na zona, mas fora do calculo (area < minima, sem preco/area ou m2 fora da
        # faixa de sanidade). Para auditoria e para o registro no banco.
        "comparaveis_descartados": {
            "construcao": descartados_construcao,
            "terreno": descartados_terreno,
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
            "total_amostras": total_amostras,
            "comparaveis_terreno_maior_que_imovel": comparaveis_terreno_maior,
            "terrenos_descartados_sanidade": terrenos_descartados_sanidade,
            "construcao_descartados_sanidade": construcao_descartados,
        },
        "avisos": avisos,
        # Casa com 1 a 4 terrenos: calculo sem separar o terreno (None quando nao se aplica).
        "aviso_terreno": aviso_terreno,
        # Sem nota de infraestrutura: tempo de venda com infraestrutura neutra (0,50).
        "aviso_infraestrutura": aviso_infraestrutura,
        "justificativa": (
            f"O valor do imóvel foi estimado a partir do m² da zona homogênea. "
            f"Terreno: {len(valores_m2_terreno)} amostras, m² de referência R$ {medio_m2_terreno:.2f}. "
            f"Construção: {len(todos_valores_construcao)} amostras"
            f"{'' if eh_condominial else ' (2 séries combinadas)'}, "
            f"m² de referência R$ {medio_m2_construcao:.2f}. "
            f"Valor médio estimado: R$ {valor_medio_imovel:,.2f}. "
            f"Valor de liquidez (desconto de 10%): R$ {valor_liquidez:,.2f}."
        ),
    }

    return resultado


# ============================================================
# FUNCAO DE ENTRADA (chamada pelo pipeline)
# ============================================================

def estimar_preco(
    imovel_alvo_extra: Dict[str, Any] = None, id_execucao: Optional[str] = None,
    urls_do_alvo_pela_usuaria: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Funcao principal do Agente 5.
    Le os JSONs dos agentes anteriores, calcula e salva o resultado.

    Parametros
    ----------
    imovel_alvo_extra : dict (opcional)
        Campos adicionais do imovel alvo (ex: area_terreno vindo do main.py/graph.py).
        Faz merge NAO destrutivo: so preenche chaves ausentes ou None no imovel alvo
        carregado do disco — nunca sobrescreve um valor ja existente.
    id_execucao : str (opcional)
        Identificador desta avaliacao. Com ele, so sao usados arquivos gravados por
        esta avaliacao; sem a zona homogenea desta avaliacao, o status e sem_amostra.
    urls_do_alvo_pela_usuaria : list (opcional)
        Anuncios que a pessoa marcou na tela como do proprio imovel: saem do calculo.
    """
    import logging
    logger = logging.getLogger(__name__)

    logger.info("Agente 5: carregando dados dos agentes anteriores...")

    imovel_alvo, terrenos_zona, comparaveis_zona, dados_ag3, dados_ag4 = (
        carregar_dados_pipeline(id_execucao, urls_do_alvo_pela_usuaria)
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

    # Interface usa este campo para nao dizer "poucos anuncios na regiao" quando o
    # motivo do sem_amostra e a zona nao ter rodado nesta avaliacao.
    resultado["zona_calculada_nesta_avaliacao"] = not (
        id_execucao and ler_json_da_execucao(CAMINHO_ZONA, id_execucao) is None
    )
    if not resultado["zona_calculada_nesta_avaliacao"]:
        resultado.setdefault("avisos", []).insert(
            0,
            "A zona homogenea nao foi calculada nesta avaliacao (ex.: sem chave do Google "
            "Maps ou erro na validacao geografica); por seguranca, o valor nao foi estimado.",
        )
    resultado["id_execucao"] = id_execucao
    resultado["anuncios_do_alvo_pela_usuaria"] = list(urls_do_alvo_pela_usuaria or [])

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

    # Situacao da zona dos comparaveis usados. Os "zona nao verificada" (fallback) e os
    # do socorro (sem_validacao) contam para o minimo (decisao do professor, 17/10/2026).
    usados = resultado.get("comparaveis_usados") or {}
    status = [c.get("status_zona") or "confirmado"
              for lista in (usados.get("construcao") or [], usados.get("terreno") or []) for c in lista]
    n_conf, n_fb, n_sv = status.count("confirmado"), status.count("fallback"), status.count("sem_validacao")
    n_mb = status.count("mesmo_bairro")
    n_fb += n_mb
    escopo_busca = (imovel_alvo_extra or {}).get("escopo_busca")
    linha_zona = (
        f"[Ag5][Zona] usados no calculo: {n_conf} confirmados | {n_mb} mesmo bairro ate 2,5 km | "
        f"{n_fb - n_mb} zona_nao_verificada "
        f"(contam para o minimo de {MIN_AMOSTRAS_CONFIAVEL}) | {n_sv} sem_validacao (socorro) | "
        f"escopo_busca={escopo_busca}"
    )
    if n_fb or n_sv or escopo_busca == "cidade":
        logger.warning(linha_zona)
    else:
        logger.info(linha_zona)

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
