"""
Agente 3 - Analisador Qualitativo de Descricao e Imagens (vocabulario controlado)
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
    ALVO: Gemini (ate 2 tentativas em 429 curto) -> Groq -> NVIDIA
    COMPARAVEIS: Groq -> NVIDIA -> Gemini (ultimo fallback, sem retry)
    Gemini: ate 4 fotos + JSON
    Groq qwen3.6-27b: ate 2 fotos + JSON Object Mode
    NVIDIA NIM llama-3.2-11b-vision: 1 foto + JSON solicitado no prompt

SAIDA ESTRUTURADA:
    - Gemini: response_mime_type=application/json; validacao final em Python
    - Groq/Qwen: response_format={"type": "json_object"}; validacao final em Python
    - NVIDIA NIM: JSON solicitado no prompt, sem JSON Schema rigido; validacao tolerante em Python

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
    - pontos_positivos (vocabulario controlado; pode alterar score)
    - pontos_negativos (vocabulario controlado; pode alterar score)
    - caracteristicas_unidade (vocabulario controlado; informativo)
    - caracteristicas_condominio (vocabulario controlado; informativo)
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
import unicodedata
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

# =============================================================================
# VOCABULARIOS CONTROLADOS
# =============================================================================
# Somente pontos positivos/negativos controlados podem alterar o score.
# Caracteristicas da unidade e do condominio sao informativas.
PONTOS_POSITIVOS_CONTROLADOS = [
    "acabamento diferenciado",
    "cozinha planejada",
    "armários planejados",
    "varanda gourmet",
    "vista livre",
    "boa iluminação natural",
    "integração de ambientes",
    "área externa privativa",
    "churrasqueira privativa",
    "piscina privativa",
]

PONTOS_NEGATIVOS_CONTROLADOS = [
    "documentação irregular",
    "infiltração/umidade",
    "precisa reforma",
    "pintura deteriorada",
    "acabamento desgastado",
    "danos visíveis",
]

CARACTERISTICAS_UNIDADE_CONTROLADAS = [
    "varanda",
    "suíte",
    "vaga de garagem",
    "closet",
    "ar-condicionado",
    "bancada em granito",
    "banheira",
    "quarto de despejo",
    "copa",
    "lavabo",
]

CARACTERISTICAS_CONDOMINIO_CONTROLADAS = [
    "interfone",
    "portão eletrônico",
    "câmeras de segurança",
    "alarme",
    "portaria",
    "elevador",
    "piscina do condomínio",
    "academia",
    "salão de festas",
    "playground",
]

# =============================================================================
# SCHEMA UNICO DA RESPOSTA DO AGENTE 3
# =============================================================================
#
# O mesmo contrato logico e usado nos tres provedores.
# O schema abaixo documenta o contrato esperado. A validacao final e feita
# em Python para nao perder informacao util por pequenas variacoes textuais.
# Groq/Qwen usa JSON Object Mode. Gemini usa application/json. NVIDIA recebe
# o formato esperado no prompt, sem JSON Schema rigido na API.
#
SCHEMA_AGENTE3 = {
    "type": "object",
    "properties": {
        "estado_conservacao": {
            "type": "string",
            "enum": [
                "novo",
                "reformado",
                "bom",
                "regular",
                "precisa_reforma",
                "desconhecido",
            ],
        },
        "padrao_acabamento": {
            "type": "string",
            "enum": [
                "alto_padrao",
                "medio",
                "simples",
                "desconhecido",
            ],
        },
        "pontos_positivos": {
            "type": "array",
            "items": {"type": "string", "enum": PONTOS_POSITIVOS_CONTROLADOS},
        },
        "pontos_negativos": {
            "type": "array",
            "items": {"type": "string", "enum": PONTOS_NEGATIVOS_CONTROLADOS},
        },
        "caracteristicas_unidade": {
            "type": "array",
            "items": {"type": "string", "enum": CARACTERISTICAS_UNIDADE_CONTROLADAS},
        },
        "caracteristicas_condominio": {
            "type": "array",
            "items": {"type": "string", "enum": CARACTERISTICAS_CONDOMINIO_CONTROLADAS},
        },
        "limitacoes_analise": {
            "type": "array",
            "items": {"type": "string"},
        },
        "qualidade_imagens": {
            "type": "string",
            "enum": ["boa", "razoavel", "ruim"],
        },
        "confianca_extracao": {
            "type": "string",
            "enum": ["baixa", "media", "alta"],
        },
        "evidencias": {
            "type": "object",
            "properties": {
                "conservacao": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "acabamento": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["conservacao", "acabamento"],
        },
        "observacoes": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": [
        "estado_conservacao",
        "padrao_acabamento",
        "pontos_positivos",
        "pontos_negativos",
        "caracteristicas_unidade",
        "caracteristicas_condominio",
        "limitacoes_analise",
        "qualidade_imagens",
        "confianca_extracao",
        "evidencias",
        "observacoes",
    ],
}


def _parse_json_obj(texto: str) -> dict:
    """
    Converte a resposta do provedor em dict.

    Com structured output/JSON mode a resposta normalmente ja e JSON puro.
    O pequeno fallback de limpeza existe apenas para compatibilidade com
    respostas antigas ou provedores que eventualmente envolvam o JSON em
    bloco Markdown.
    """
    if not texto:
        return {}

    texto = str(texto).strip()
    if "</think>" in texto:
        texto = texto.split("</think>", 1)[1].strip()

    texto = re.sub(r"^```json\s*", "", texto, flags=re.IGNORECASE)
    texto = re.sub(r"^```\s*", "", texto)
    texto = re.sub(r"\s*```$", "", texto).strip()

    try:
        obj = json.loads(texto)
        return obj if isinstance(obj, dict) else {}
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", texto)
        if not m:
            return {}
        try:
            obj = json.loads(m.group(0))
            return obj if isinstance(obj, dict) else {}
        except json.JSONDecodeError:
            return {}


def _deduplicar_lista(valores) -> list:
    """Remove duplicatas textuais preservando a ordem."""
    if not isinstance(valores, list):
        return []

    vistos = set()
    saida = []
    for valor in valores:
        item = str(valor).strip()
        if not item:
            continue
        chave = item.casefold()
        if chave in vistos:
            continue
        vistos.add(chave)
        saida.append(item)
    return saida


def _chave_vocabulario(valor) -> str:
    """
    Normaliza texto para comparacao de vocabulario sem perder o valor original.
    Remove acentos e trata '_'/'-' como espaco.
    """
    texto = str(valor or "").strip().casefold()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    texto = re.sub(r"[_\-]+", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


# Variacoes equivalentes que podem ser devolvidas pelos modelos.
# Apenas equivalencias seguras viram itens pontuaveis. Termos mais livres
# continuam preservados em observacoes e NAO alteram o score.
_ALIASES_NEGATIVOS = {
    "documentacao irregular": "documentação irregular",
    "infiltracao": "infiltração/umidade",
    "infiltracao/umidade": "infiltração/umidade",
    "infiltracao e umidade": "infiltração/umidade",
    "precisa de reforma": "precisa reforma",
    "necessita reforma": "precisa reforma",
    "necessita de reforma": "precisa reforma",
    "pintura deteriorada": "pintura deteriorada",
    "pintura descascada": "pintura deteriorada",
    "acabamento desgastado": "acabamento desgastado",
    "acabamentos desgastados": "acabamento desgastado",
    "danos visiveis": "danos visíveis",
    "dano visivel": "danos visíveis",
}

_ALIASES_POSITIVOS = {
    "armarios planejados": "armários planejados",
    "boa iluminacao natural": "boa iluminação natural",
    "integracao de ambientes": "integração de ambientes",
    "area externa privativa": "área externa privativa",
}

_ALIASES_UNIDADE = {
    "suite": "suíte",
    "vaga garagem": "vaga de garagem",
    "vaga": "vaga de garagem",
    "ar condicionado": "ar-condicionado",
}

_ALIASES_CONDOMINIO = {
    "portao eletronico": "portão eletrônico",
    "cameras de seguranca": "câmeras de segurança",
    "piscina condominio": "piscina do condomínio",
    "salao de festas": "salão de festas",
}


def _filtrar_controlados_com_extras(
    valores,
    permitidos: list,
    aliases: Optional[dict] = None,
) -> tuple[list, list]:
    """
    Separa itens pontuaveis/controlados de textos livres.

    - Itens equivalentes ao vocabulario sao convertidos para a forma canonica.
    - Itens fora do vocabulario NAO sao apagados: voltam em `extras` para
      serem preservados em observacoes, sem afetar o score.
    """
    mapa = {_chave_vocabulario(item): item for item in permitidos}
    for alias, canonico in (aliases or {}).items():
        mapa[_chave_vocabulario(alias)] = canonico

    controlados = []
    extras = []
    vistos_controlados = set()
    vistos_extras = set()

    for valor in _deduplicar_lista(valores):
        chave = _chave_vocabulario(valor)
        canonico = mapa.get(chave)

        if canonico is not None:
            chave_canonica = _chave_vocabulario(canonico)
            if chave_canonica not in vistos_controlados:
                vistos_controlados.add(chave_canonica)
                controlados.append(canonico)
            continue

        if chave and chave not in vistos_extras:
            vistos_extras.add(chave)
            extras.append(valor)

    return controlados, extras


def _filtrar_controlados(valores, permitidos: list) -> list:
    """Compatibilidade: retorna apenas a parte controlada."""
    controlados, _ = _filtrar_controlados_com_extras(valores, permitidos)
    return controlados


def _validar_saida_llm(dados: dict) -> dict:
    """
    Normaliza a resposta dos provedores sem destruir informacao util.

    Estado/padrao aceitam variacoes textuais conhecidas.
    Somente vocabulario controlado altera o score.
    Qualquer item livre devolvido em positivos/negativos/caracteristicas e
    preservado em `observacoes` em vez de ser descartado.
    """
    if not isinstance(dados, dict):
        return {}

    estado = _normalizar_conservacao(
        dados.get("estado_conservacao", "desconhecido")
    )
    padrao = _normalizar_acabamento(
        dados.get("padrao_acabamento", "desconhecido")
    )

    qualidade = _chave_vocabulario(
        dados.get("qualidade_imagens", "razoavel")
    )
    if qualidade not in {"boa", "razoavel", "ruim"}:
        qualidade = "razoavel"

    confianca = _chave_vocabulario(
        dados.get("confianca_extracao", "baixa")
    )
    if confianca not in {"baixa", "media", "alta"}:
        confianca = "baixa"

    evidencias = dados.get("evidencias")
    if not isinstance(evidencias, dict):
        evidencias = {}

    positivos, positivos_livres = _filtrar_controlados_com_extras(
        dados.get("pontos_positivos", []),
        PONTOS_POSITIVOS_CONTROLADOS,
        _ALIASES_POSITIVOS,
    )
    negativos, negativos_livres = _filtrar_controlados_com_extras(
        dados.get("pontos_negativos", []),
        PONTOS_NEGATIVOS_CONTROLADOS,
        _ALIASES_NEGATIVOS,
    )
    unidade, unidade_livre = _filtrar_controlados_com_extras(
        dados.get("caracteristicas_unidade", []),
        CARACTERISTICAS_UNIDADE_CONTROLADAS,
        _ALIASES_UNIDADE,
    )
    condominio, condominio_livre = _filtrar_controlados_com_extras(
        dados.get("caracteristicas_condominio", []),
        CARACTERISTICAS_CONDOMINIO_CONTROLADAS,
        _ALIASES_CONDOMINIO,
    )

    observacoes_originais = dados.get("observacoes", [])
    if not isinstance(observacoes_originais, list):
        observacoes_originais = [observacoes_originais] if observacoes_originais else []

    observacoes = _deduplicar_lista(
        observacoes_originais
        + positivos_livres
        + negativos_livres
        + unidade_livre
        + condominio_livre
    )

    return {
        "estado_conservacao": estado,
        "padrao_acabamento": padrao,
        "pontos_positivos": positivos,
        "pontos_negativos": negativos,
        "caracteristicas_unidade": unidade,
        "caracteristicas_condominio": condominio,
        "limitacoes_analise": _deduplicar_lista(dados.get("limitacoes_analise", [])),
        "qualidade_imagens": qualidade,
        "confianca_extracao": confianca,
        "evidencias": {
            "conservacao": _deduplicar_lista(evidencias.get("conservacao", [])),
            "acabamento": _deduplicar_lista(evidencias.get("acabamento", [])),
        },
        "observacoes": observacoes,
    }


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
    """
    Prompt usado por Groq/NVIDIA.

    Importante:
    - uma única foto NÃO torna automaticamente a análise inconclusiva;
    - descrição, amenities e dados estruturados também são evidências;
    - "desconhecido" só deve ser usado quando o conjunto das evidências
      realmente não permitir uma classificação razoável.
    """
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

    return f"""Voce e um avaliador imobiliario especializado em analise qualitativa de imoveis.
Foram fornecidas exatamente {qtd_fotos} imagem(ns) nesta chamada.

Analise o CONJUNTO das evidencias:
- imagens;
- titulo;
- descricao;
- dados estruturados;
- amenities informadas no anuncio.

DADOS DO IMOVEL
Titulo: {titulo[:200]}
Descricao:
{descricao[:MAX_DESC_CHARS]}

Tipo: {tipo}
Area: {area} m2
Area do terreno: {area_terreno} m2
Quartos: {quartos}
Banheiros: {banheiros}
Suites: {suites}
Vagas: {vagas}
Amenities: {amenities_txt}

REGRA CENTRAL
Uma quantidade pequena de fotos NAO significa automaticamente que
estado_conservacao ou padrao_acabamento devam ser "desconhecido".

Mesmo com 1 foto, use a descricao e os demais dados como evidencias.
Use "desconhecido" SOMENTE quando o conjunto de texto + imagens + dados
for realmente insuficiente, contraditorio ou nao trouxer qualquer evidencia
util para aquela classificacao.

ESTADO DE CONSERVACAO
Escolha exatamente uma opcao:
- "novo": evidencia clara de imovel novo, recem-construido, recem-entregue
  ou nunca habitado.
- "reformado": evidencia clara de reforma/modernizacao relevante.
- "bom": imovel aparentemente bem conservado, funcional, sem sinais
  relevantes de deterioracao ou necessidade evidente de intervencao.
  Acabamentos antigos podem estar em bom estado.
- "regular": existem sinais concretos de desgaste, manutencao pendente,
  pintura deteriorada, pequenos danos ou acabamento visivelmente desgastado.
- "precisa_reforma": existem evidencias claras de deterioracao significativa,
  danos relevantes, infiltracao/umidade importante ou necessidade de reforma.
- "desconhecido": somente quando o conjunto das evidencias nao permite
  classificar de modo razoavel.

PADRAO DE ACABAMENTO
Escolha exatamente uma opcao:
- "alto_padrao": evidencia consistente de materiais/acabamentos superiores.
- "medio": acabamentos intermediarios, adequados e de boa apresentacao.
- "simples": acabamentos basicos e funcionais.
- "desconhecido": somente quando nao ha evidencia suficiente para diferenciar
  simples, medio ou alto_padrao.

REGRAS IMPORTANTES
1. Nao invente informacoes e nao complete frases truncadas.
2. Nao confunda conservacao com padrao de acabamento.
3. Acabamento antigo, madeira aparente, piso antigo ou estilo simples
   NAO significam automaticamente estado regular ou necessidade de reforma.
4. So use pontos_negativos quando houver problema objetivo.
5. Poucas fotos, ambientes nao fotografados, imagens repetidas ou descricao
   incompleta sao limitacoes_analise, nunca defeitos do imovel.
6. Limitacoes da analise NAO reduzem diretamente o score.
7. Nao use preco, preco/m2, bairro, cidade, rua, IPTU ou condominio para
   inferir conservacao ou padrao.
8. Amenities do condominio nao provam acabamento interno da unidade.
9. Se houver apenas 1 foto, evite afirmar "alto_padrao" APENAS pela foto.
   Entretanto, se descricao + amenities + imagem trouxerem evidencias
   suficientes, classifique normalmente como simples, medio, bom, reformado etc.
10. Nao escolha "desconhecido" apenas por cautela. Escolha-o somente quando
    realmente faltarem evidencias.

VOCABULARIO CONTROLADO
pontos_positivos deve conter somente:
{'; '.join(PONTOS_POSITIVOS_CONTROLADOS)}

pontos_negativos deve conter somente:
{'; '.join(PONTOS_NEGATIVOS_CONTROLADOS)}

caracteristicas_unidade deve conter somente:
{'; '.join(CARACTERISTICAS_UNIDADE_CONTROLADAS)}

caracteristicas_condominio deve conter somente:
{'; '.join(CARACTERISTICAS_CONDOMINIO_CONTROLADAS)}

Se uma informacao relevante nao estiver nesses vocabularios, NAO a descarte:
coloque-a em observacoes como texto livre. Isso vale especialmente para um
ponto de atencao objetivo que nao tenha equivalente exato em pontos_negativos.
Itens em observacoes sao informativos e NAO alteram o score.
Nao duplique itens entre listas.

FORMATO OBRIGATORIO DA RESPOSTA
Use exatamente estas chaves:
{{
  "estado_conservacao": "novo|reformado|bom|regular|precisa_reforma|desconhecido",
  "padrao_acabamento": "alto_padrao|medio|simples|desconhecido",
  "pontos_positivos": [],
  "pontos_negativos": [],
  "caracteristicas_unidade": [],
  "caracteristicas_condominio": [],
  "limitacoes_analise": [],
  "qualidade_imagens": "boa|razoavel|ruim",
  "confianca_extracao": "baixa|media|alta",
  "evidencias": {{
    "conservacao": [],
    "acabamento": []
  }},
  "observacoes": []
}}

Os textos com "|" acima indicam alternativas permitidas: escolha apenas UMA delas.
Responda SOMENTE com um objeto JSON valido, sem Markdown e sem texto fora do JSON.
"""

# =============================================================================
# NORMALIZACAO DE VOCABULARIO
# =============================================================================

_NORM_CONSERVACAO = {
    "novo": "novo", "lancamento": "novo", "lançamento": "novo",
    "nunca habitado": "novo", "reformado": "reformado",
    "recém reformado": "reformado", "recem reformado": "reformado",
    "bom": "bom", "excelente": "bom", "ótimo": "bom", "otimo": "bom",
    "impecável": "bom", "impecavel": "bom", "pronto para morar": "bom",
    "bom estado": "bom", "bom estado de conservação": "bom",
    "bom estado de conservacao": "bom", "bem conservado": "bom",
    "bem conservada": "bom",
    "regular": "regular", "estado regular": "regular",
    "precisa_reforma": "precisa_reforma",
    "precisa de reforma": "precisa_reforma", "necessita reforma": "precisa_reforma",
    "necessita de reforma": "precisa_reforma",
    "desconhecido": "desconhecido", "indefinido": "desconhecido",
}

_NORM_ACABAMENTO = {
    "alto_padrao": "alto_padrao", "alto padrao": "alto_padrao",
    "alto padrão": "alto_padrao", "alto": "alto_padrao",
    "luxo": "alto_padrao", "premium": "alto_padrao",
    "padrao alto": "alto_padrao", "padrão alto": "alto_padrao",
    "medio": "medio", "médio": "medio", "bom": "medio",
    "padrao medio": "medio", "padrão médio": "medio",
    "acabamento medio": "medio", "acabamento médio": "medio",
    "simples": "simples", "padrao simples": "simples", "padrão simples": "simples",
    "acabamento simples": "simples", "desconhecido": "desconhecido",
    "indefinido": "desconhecido",
}


def _buscar_normalizado(valor, mapa: dict, padrao: str = "desconhecido") -> str:
    """Busca por chave literal e, se necessario, por forma sem acento/underscore."""
    bruto = str(valor or "").strip().casefold()
    if bruto in mapa:
        return mapa[bruto]

    chave = _chave_vocabulario(bruto)
    mapa_flex = {_chave_vocabulario(k): v for k, v in mapa.items()}
    return mapa_flex.get(chave, padrao)


def _normalizar_conservacao(v: str) -> str:
    return _buscar_normalizado(v, _NORM_CONSERVACAO)


def _normalizar_acabamento(v: str) -> str:
    return _buscar_normalizado(v, _NORM_ACABAMENTO)


# =============================================================================
# PROVIDER STATE (circuit breaker por execucao)
# =============================================================================

_provider_state = {
    "gemini": {"available": True, "reason": None, "chamadas": 0, "sucessos": 0, "erros_429": 0, "puladas": 0},
    "groq": {"available": True, "reason": None, "last_request": 0.0, "chamadas": 0, "sucessos": 0, "erros_429": 0},
    "nvidia": {"available": True, "reason": None, "chamadas": 0, "sucessos": 0, "erros": 0},
}

GROQ_INTERVALO_PREVENTIVO = 8.0  # segundos entre chamadas ao Groq Vision

# Gemini é priorizado para o imóvel alvo.
# Faz no máximo 2 tentativas no alvo quando o 429 pedir uma espera curta.
GEMINI_MAX_TENTATIVAS_ALVO = 2
GEMINI_RETRY_CURTO_MAX_SEGUNDOS = 15.0
GEMINI_RETRY_PADRAO_SEGUNDOS = 5.0


def _reset_provider_state():
    """Reseta o estado dos provedores (chamado no inicio de cada execucao)."""
    _provider_state["gemini"] = {"available": True, "reason": None, "chamadas": 0, "sucessos": 0, "erros_429": 0, "puladas": 0}
    _provider_state["groq"] = {"available": True, "reason": None, "last_request": 0.0, "chamadas": 0, "sucessos": 0, "erros_429": 0}
    _provider_state["nvidia"] = {"available": True, "reason": None, "chamadas": 0, "sucessos": 0, "erros": 0}


# =============================================================================
# CHAMADA AO LLM VISION (texto + fotos juntos)
# =============================================================================

def _resultado_conclusivo(resultado: dict) -> bool:
    """
    Considera conclusiva uma resposta que trouxe informacao qualitativa util.
    JSON valido com estado/padrao desconhecidos e confianca baixa nao encerra
    prematuramente a cadeia de fallback.
    """
    if not isinstance(resultado, dict) or not resultado:
        return False

    estado = _normalizar_conservacao(
        resultado.get("estado_conservacao", "desconhecido")
    )
    padrao = _normalizar_acabamento(
        resultado.get("padrao_acabamento", "desconhecido")
    )
    confianca = _chave_vocabulario(
        resultado.get("confianca_extracao", "baixa")
    )

    if estado != "desconhecido" or padrao != "desconhecido":
        return True
    if resultado.get("pontos_positivos") or resultado.get("pontos_negativos"):
        return True
    if confianca in {"media", "alta"}:
        return True
    return False


def _riqueza_resultado(resultado: dict) -> int:
    """Pontua apenas para escolher o melhor fallback inconclusivo."""
    if not isinstance(resultado, dict) or not resultado:
        return -1

    score = 0
    if _normalizar_conservacao(resultado.get("estado_conservacao")) != "desconhecido":
        score += 5
    if _normalizar_acabamento(resultado.get("padrao_acabamento")) != "desconhecido":
        score += 4

    score += min(len(resultado.get("pontos_positivos") or []), 3)
    score += min(len(resultado.get("pontos_negativos") or []), 3)
    score += min(len(resultado.get("observacoes") or []), 2)
    evidencias = resultado.get("evidencias") or {}
    if isinstance(evidencias, dict):
        score += min(len(evidencias.get("conservacao") or []), 2)
        score += min(len(evidencias.get("acabamento") or []), 2)
    return score


def _melhor_resultado(*resultados: dict) -> dict:
    validos = [r for r in resultados if isinstance(r, dict) and r]
    return max(validos, key=_riqueza_resultado) if validos else {}


def _analisar_imovel_vision(imovel: dict, is_alvo: bool = False) -> dict:
    """
    Roteamento centralizado dos provedores.

    ALVO:
        Gemini -> Groq -> NVIDIA

    COMPARAVEIS:
        Groq -> NVIDIA -> Gemini

    Resposta "desconhecido/desconhecido" com confianca baixa nao encerra
    prematuramente o fluxo: o proximo provedor ainda e tentado.
    """
    if is_alvo:
        logger.info("[Ag3][Roteamento][Alvo] prioridade: Gemini -> Groq -> NVIDIA")

        gemini = _tentar_gemini(
            imovel,
            permitir_retry_429=True,
            max_tentativas=GEMINI_MAX_TENTATIVAS_ALVO,
        )
        if _resultado_conclusivo(gemini):
            return gemini
        if gemini:
            logger.info("[Ag3][Roteamento][Alvo] Gemini respondeu, mas foi inconclusivo")

        logger.info("[Ag3][Roteamento][Alvo] tentando Groq")
        groq = _tentar_groq(imovel)
        if _resultado_conclusivo(groq):
            return groq
        if groq:
            logger.info("[Ag3][Roteamento][Alvo] Groq respondeu, mas foi inconclusivo")

        logger.info("[Ag3][Roteamento][Alvo] tentando NVIDIA")
        nvidia = _analisar_imovel_vision_nvidia(imovel)
        if nvidia:
            return nvidia

        return _melhor_resultado(gemini, groq)

    logger.info("[Ag3][Roteamento][Comparavel] prioridade: Groq -> NVIDIA -> Gemini")

    groq = _tentar_groq(imovel)
    if _resultado_conclusivo(groq):
        return groq

    if groq:
        logger.info("[Ag3][Roteamento][Comparavel] Groq inconclusivo -> tentando NVIDIA")
    else:
        logger.info("[Ag3][Roteamento][Comparavel] Groq falhou/indisponivel -> tentando NVIDIA")

    nvidia = _analisar_imovel_vision_nvidia(imovel)
    if _resultado_conclusivo(nvidia):
        return nvidia

    if nvidia:
        logger.info("[Ag3][Roteamento][Comparavel] NVIDIA inconclusiva -> Gemini ultimo fallback")
    else:
        logger.info("[Ag3][Roteamento][Comparavel] NVIDIA falhou -> Gemini ultimo fallback")

    gemini = _tentar_gemini(
        imovel,
        permitir_retry_429=False,
        max_tentativas=1,
    )
    if _resultado_conclusivo(gemini):
        return gemini

    return _melhor_resultado(gemini, nvidia, groq)


def _extrair_retry_after_segundos(erro: str):
    """
    Tenta extrair um tempo de retry de mensagens de erro 429.
    Aceita formatos comuns como '3.27s', 'retryDelay: 5s' etc.
    """
    if not erro:
        return None

    padroes = [
        r"retry[_\s-]*after[^\d]*(\d+(?:\.\d+)?)\s*s",
        r"retrydelay[^\d]*(\d+(?:\.\d+)?)\s*s",
        r"(\d+(?:\.\d+)?)\s*s",
    ]

    texto = str(erro).lower()
    for padrao in padroes:
        m = re.search(padrao, texto)
        if m:
            try:
                return float(m.group(1))
            except (TypeError, ValueError):
                pass
    return None


def _tentar_gemini(
    imovel: dict,
    permitir_retry_429: bool = False,
    max_tentativas: int = 1,
) -> dict:
    """
    Chama Gemini com JSON Schema.

    Para o imovel alvo:
      - max_tentativas=2;
      - se houver 429 com retry curto (<= 15s), espera e tenta mais 1 vez;
      - se o retry indicado for longo, nao prende a execucao: retorna {} e
        o roteador segue para Groq/NVIDIA.

    Para comparaveis:
      - Gemini e apenas ultimo fallback;
      - faz uma unica tentativa;
      - nao espera 429.

    Esta funcao NAO chama outro provedor por dentro. O roteamento fica
    centralizado em _analisar_imovel_vision().
    """
    try:
        from google import genai
        from google.genai import types
    except Exception as e:
        logger.error(f"[Ag3][Gemini] erro ao importar SDK: {e}")
        return {}

    api_key = os.getenv("GOOGLE_API_KEY_2", "") or os.getenv("GOOGLE_API_KEY", "")
    if not api_key:
        logger.warning("[Ag3][Gemini] chave nao configurada")
        return {}

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
Todas as imagens pertencem ao MESMO imovel. Foram fornecidas exatamente {qtd_fotos} imagem(ns).
Voce NAO calcula preco, valor de mercado, score ou classificacao favoravel/desfavoravel; o Python faz isso depois.

DADOS DO IMOVEL
Titulo: {titulo[:200]}
Descricao:
{descricao[:MAX_DESC_CHARS]}
Tipo: {tipo}
Area: {area} m2 | Area do terreno: {area_terreno} m2 | Quartos: {quartos} | Banheiros: {banheiros} | Suites: {suites} | Vagas: {vagas}
Amenities: {amenities_txt}

REGRAS FUNDAMENTAIS
1. Use SOMENTE informacoes visiveis nas imagens, explicitamente presentes na descricao ou nos campos estruturados.
2. Nao invente, nao complete frases truncadas e nao presuma caracteristicas comuns.
3. Use "desconhecido" SOMENTE quando o conjunto de texto + imagens + dados estruturados realmente nao permitir uma classificacao razoavel.
4. Uma quantidade pequena de fotos NAO torna automaticamente a analise inconclusiva: considere tambem descricao, amenities e dados estruturados.
5. Ausencia de informacao NAO e defeito do imovel.
6. Poucas fotos, ambientes nao fotografados, imagens repetidas/concentradas e descricao incompleta pertencem apenas a limitacoes_analise.
7. Acabamento antigo, madeira aparente, piso/revestimento antigo ou estilo simples nao sao negativos por si so.
8. Estado de conservacao e padrao de acabamento sao independentes.
9. Nao use preco, preco/m2, bairro, cidade, rua, IPTU ou condominio para inferir conservacao ou padrao.
10. Amenities do condominio nao provam acabamento interno.
11. Considere as imagens em conjunto e nao generalize um problema localizado.
12. Se houver somente 1 foto, NAO classifique alto_padrao apenas pela imagem. Porem, uma unica foto nao obriga estado ou padrao a serem desconhecidos: use descricao, amenities e dados estruturados quando trouxerem evidencias suficientes.
13. pontos_positivos e pontos_negativos sao VOCABULARIOS CONTROLADOS. Nao escreva frases livres nesses campos.
14. caracteristicas_unidade e caracteristicas_condominio sao informativas e NAO alteram o score.
15. Se algo relevante nao estiver no vocabulario permitido, registre em observacoes.
16. Nao duplique informacoes entre listas.
17. Se identificar uma informacao relevante que nao tenha equivalente exato
    nos vocabularios controlados, preserve-a em observacoes. Nunca descarte
    um achado relevante apenas por nao estar no vocabulario pontuavel.
18. observacoes aceita texto livre e NAO altera o score.

POSITIVOS PERMITIDOS
{'; '.join(PONTOS_POSITIVOS_CONTROLADOS)}

NEGATIVOS PERMITIDOS
{'; '.join(PONTOS_NEGATIVOS_CONTROLADOS)}

CARACTERISTICAS DA UNIDADE
{'; '.join(CARACTERISTICAS_UNIDADE_CONTROLADAS)}

CARACTERISTICAS DO CONDOMINIO
{'; '.join(CARACTERISTICAS_CONDOMINIO_CONTROLADAS)}

CATEGORIAS
estado_conservacao: novo | reformado | bom | regular | precisa_reforma | desconhecido
padrao_acabamento: alto_padrao | medio | simples | desconhecido
qualidade_imagens: boa | razoavel | ruim
confianca_extracao: baixa | media | alta

FORMATO OBRIGATORIO DA RESPOSTA
Use exatamente estas chaves:
{{
  "estado_conservacao": "novo|reformado|bom|regular|precisa_reforma|desconhecido",
  "padrao_acabamento": "alto_padrao|medio|simples|desconhecido",
  "pontos_positivos": [],
  "pontos_negativos": [],
  "caracteristicas_unidade": [],
  "caracteristicas_condominio": [],
  "limitacoes_analise": [],
  "qualidade_imagens": "boa|razoavel|ruim",
  "confianca_extracao": "baixa|media|alta",
  "evidencias": {{
    "conservacao": [],
    "acabamento": []
  }},
  "observacoes": []
}}

Os textos com "|" acima indicam alternativas permitidas: escolha apenas UMA delas.
Responda SOMENTE com um objeto JSON valido, sem Markdown e sem texto fora do JSON.
"""

    parts = [types.Part.from_text(text=prompt_texto)]
    for url in fotos_selecionadas:
        try:
            parts.append(types.Part.from_uri(file_uri=url, mime_type="image/webp"))
        except Exception:
            pass

    max_tentativas = max(1, int(max_tentativas))

    for tentativa in range(1, max_tentativas + 1):
        _provider_state["gemini"]["chamadas"] += 1

        logger.info(
            f"[Ag3][Gemini] tentativa={tentativa}/{max_tentativas} | "
            f"fotos={qtd_fotos} | desc_chars={min(len(descricao), MAX_DESC_CHARS)}"
        )

        try:
            response = client.models.generate_content(
                model="gemini-3.5-flash-lite",
                contents=[types.Content(role="user", parts=parts)],
                config=types.GenerateContentConfig(
                    temperature=0,
                    response_mime_type="application/json",
                ),
            )

            texto_resp = response.text or ""
            resultado = _validar_saida_llm(_parse_json_obj(texto_resp))
            if not resultado:
                logger.warning(
                    "[Ag3][Gemini] resposta estruturada vazia/invalida"
                )
                return {}

            resultado["fotos_analisadas"] = qtd_fotos
            resultado["llm_usada"] = "gemini-3.5-flash-lite"
            _provider_state["gemini"]["sucessos"] += 1
            _provider_state["gemini"]["available"] = True
            _provider_state["gemini"]["reason"] = None
            return resultado

        except Exception as e:
            err_str = str(e)
            err_lower = err_str.lower()

            # Retry de erro interno 500 somente uma vez, sem exceder o limite
            # total de tentativas definido para esta chamada.
            if "500" in err_lower and tentativa < max_tentativas:
                logger.warning("[Ag3][Gemini] erro 500 -> retry em 3s")
                time.sleep(3)
                continue

            eh_429 = (
                "429" in err_lower
                or "resource_exhausted" in err_lower
                or "quota" in err_lower
            )

            if eh_429:
                _provider_state["gemini"]["erros_429"] += 1
                retry_after = _extrair_retry_after_segundos(err_str)

                if retry_after is not None:
                    logger.warning(
                        f"[Ag3][Gemini] 429 | retry_after={retry_after:.2f}s"
                    )
                else:
                    logger.warning("[Ag3][Gemini] 429 | retry_after=nao_informado")

                pode_repetir = (
                    permitir_retry_429
                    and tentativa < max_tentativas
                    and (
                        retry_after is None
                        or retry_after <= GEMINI_RETRY_CURTO_MAX_SEGUNDOS
                    )
                )

                if pode_repetir:
                    espera = (
                        retry_after + 1.0
                        if retry_after is not None
                        else GEMINI_RETRY_PADRAO_SEGUNDOS
                    )
                    logger.info(
                        f"[Ag3][Gemini] aguardando {espera:.1f}s antes da "
                        f"tentativa {tentativa + 1}/{max_tentativas}"
                    )
                    time.sleep(espera)
                    continue

                # Nao mata o Gemini pela execucao inteira. Apenas registra
                # que esta chamada nao conseguiu prosseguir.
                _provider_state["gemini"]["available"] = True
                if retry_after is not None and retry_after > GEMINI_RETRY_CURTO_MAX_SEGUNDOS:
                    _provider_state["gemini"]["reason"] = (
                        f"429_retry_longo_{retry_after:.1f}s"
                    )
                else:
                    _provider_state["gemini"]["reason"] = "429_sem_retry"

                return {}

            logger.error(f"[Ag3][Gemini] falhou: {e}")
            return {}

    return {}

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
    """
    Chamada Groq pura: ate 2 fotos + JSON Object Mode.
    Nao chama NVIDIA internamente. O fallback fica centralizado no roteador.
    """
    try:
        from groq import Groq

        api_key = os.getenv("GROQ_API_KEY", "")
        if not api_key:
            logger.warning("[Ag3][Groq] chave nao configurada")
            return {}

        client = Groq(api_key=api_key, max_retries=0)
        images = imovel.get("images", []) or []
        fotos_selecionadas = _selecionar_fotos(images, MAX_FOTOS_GROQ)
        prompt_texto = _prompt_compacto(imovel, len(fotos_selecionadas))

        content = [{"type": "text", "text": prompt_texto}]
        for url in fotos_selecionadas:
            content.append({"type": "image_url", "image_url": {"url": url}})

        def _executar(client_obj):
            return client_obj.chat.completions.create(
                model="qwen/qwen3.6-27b",
                messages=[{"role": "user", "content": content}],
                temperature=0,
                max_completion_tokens=1400,
                reasoning_effort="none",
                response_format={"type": "json_object"},
            )

        response = _executar(client)
        texto_resp = response.choices[0].message.content or ""
        resultado = _validar_saida_llm(_parse_json_obj(texto_resp))
        if not resultado:
            logger.warning("[Ag3][Groq] JSON Object Mode retornou objeto inutilizavel")
            return {}

        resultado["fotos_analisadas"] = len(fotos_selecionadas)
        resultado["llm_usada"] = "groq-qwen3.6-27b"
        return resultado

    except Exception as e:
        err_str = str(e)
        if "429" in err_str:
            _provider_state["groq"]["erros_429"] += 1
            retry_after = _extrair_retry_after_segundos(err_str)
            logger.warning(
                "[Ag3][Groq] 429 | retry_after="
                + (f"{retry_after:.2f}s" if retry_after is not None else "nao_informado")
            )

            if retry_after is not None and retry_after <= 15:
                wait = retry_after + 1
                _provider_state["groq"].setdefault("tempo_espera_total", 0.0)
                _provider_state["groq"]["tempo_espera_total"] += wait
                logger.info(f"[Ag3][Groq] aguardando {wait:.1f}s (retry_after curto)")
                time.sleep(wait)
                try:
                    client2 = Groq(api_key=api_key, max_retries=0)
                    response2 = _executar(client2)
                    texto_resp2 = response2.choices[0].message.content or ""
                    resultado2 = _validar_saida_llm(_parse_json_obj(texto_resp2))
                    if resultado2:
                        resultado2["fotos_analisadas"] = len(fotos_selecionadas)
                        resultado2["llm_usada"] = "groq-qwen3.6-27b"
                        return resultado2
                except Exception as retry_error:
                    logger.warning(f"[Ag3][Groq] retry falhou: {retry_error}")

            logger.info("[Ag3][Groq] 429 nao resolvido — devolvendo controle ao roteador")
            return {}

        logger.error(f"[Ag3][Groq] falhou: {e}")
        return {}


def _analisar_imovel_vision_nvidia(imovel: dict) -> dict:
    """
    NVIDIA NIM: 1 foto, JSON solicitado no prompt e normalizacao tolerante.

    Mantem o comportamento que funcionava melhor anteriormente:
    nao usa JSON Schema rigido na API. A resposta e parseada e validada
    em Python, preservando observacoes livres.
    """
    _provider_state["nvidia"]["chamadas"] += 1

    try:
        from openai import OpenAI

        api_key = os.getenv("NVIDIA_API_KEY", "")
        if not api_key:
            logger.warning("[Ag3][NVIDIA] NVIDIA_API_KEY nao configurada")
            return {}

        client = OpenAI(
            base_url="https://integrate.api.nvidia.com/v1",
            api_key=api_key,
        )

        images = imovel.get("images", []) or []
        fotos_selecionadas = _selecionar_fotos(images, MAX_FOTOS_NVIDIA)
        prompt_texto = _prompt_compacto(imovel, len(fotos_selecionadas))

        prompt_texto += """
IMPORTANTE PARA A RESPOSTA NVIDIA:
- Retorne APENAS um objeto JSON valido.
- Use exatamente as chaves solicitadas no prompt.
- Se houver evidencia razoavel no conjunto foto + descricao + dados,
  classifique estado e padrao; nao escolha "desconhecido" apenas por haver
  uma unica foto.
- Se observar algo relevante fora dos vocabularios controlados, preserve
  essa informacao em observacoes. Nao a descarte.
"""

        content = [{"type": "text", "text": prompt_texto}]
        if fotos_selecionadas:
            content.append(
                {"type": "image_url", "image_url": {"url": fotos_selecionadas[0]}}
            )

        response = client.chat.completions.create(
            model="meta/llama-3.2-11b-vision-instruct",
            messages=[{"role": "user", "content": content}],
            max_tokens=1000,
            temperature=0,
        )

        texto_resp = response.choices[0].message.content or ""
        logger.info(f"[Ag3][NVIDIA] resposta bruta ({len(texto_resp)} chars): {texto_resp[:500]}")
        bruto = _parse_json_obj(texto_resp)
        if not bruto:
            logger.warning(f"[Ag3][NVIDIA] nao retornou JSON utilizavel | resposta completa: {texto_resp[:1000]}")
            _provider_state["nvidia"]["erros"] += 1
            return {}

        resultado_nim = _validar_saida_llm(bruto)
        if not resultado_nim:
            logger.warning("[Ag3][NVIDIA] resposta JSON nao passou na validacao")
            _provider_state["nvidia"]["erros"] += 1
            return {}

        resultado_nim["fotos_analisadas"] = len(fotos_selecionadas)
        resultado_nim["llm_usada"] = "nvidia-llama-3.2-11b-vision"
        _provider_state["nvidia"]["sucessos"] += 1

        logger.info(
            "[Ag3][NVIDIA] resposta | "
            f"estado={resultado_nim.get('estado_conservacao')} | "
            f"padrao={resultado_nim.get('padrao_acabamento')} | "
            f"confianca={resultado_nim.get('confianca_extracao')} | "
            f"observacoes={len(resultado_nim.get('observacoes') or [])}"
        )
        return resultado_nim

    except Exception as e:
        _provider_state["nvidia"]["erros"] += 1
        logger.error(f"[Ag3][NVIDIA] erro ao chamar NIM: {e}")
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
        "armários planejados": 0.03,
        "varanda gourmet": 0.04,
        "vista livre": 0.03,
        "boa iluminação natural": 0.02,
        "integração de ambientes": 0.02,
        "área externa privativa": 0.04,
        "churrasqueira privativa": 0.02,
        "piscina privativa": 0.04,
    }
    LIMITE_BONUS_POSITIVOS = 0.15

    # ============================================================
    # 5. PENALIZAÇÕES
    # ============================================================
    pesos_negativos_map = {
        "documentação irregular": -0.20,
        "infiltração/umidade": -0.15,
        "precisa reforma": -0.25,
        "danos visíveis": -0.10,
        "pintura deteriorada": -0.06,
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
                and negativo_normalizado == "precisa reforma"):
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
            "caracteristicas_unidade": [], "caracteristicas_condominio": [],
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
    dados = _analisar_imovel_vision(imovel, is_alvo=is_alvo)

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
            "caracteristicas_unidade": [],
            "caracteristicas_condominio": [],
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
    caracteristicas_unidade = dados.get("caracteristicas_unidade", [])
    caracteristicas_condominio = dados.get("caracteristicas_condominio", [])
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
    if not isinstance(caracteristicas_unidade, list): caracteristicas_unidade = []
    if not isinstance(caracteristicas_condominio, list): caracteristicas_condominio = []
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
    if caracteristicas_unidade:
        partes_just.append(f"{len(caracteristicas_unidade)} caracteristicas da unidade registradas")
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
        "caracteristicas_unidade": caracteristicas_unidade,
        "caracteristicas_condominio": caracteristicas_condominio,
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
                    f"estado={analise['estado_conservacao']} | padrao={analise['padrao_acabamento']} | "
                    f"confianca={analise.get('confianca_extracao', 'baixa')} | "
                    f"score={analise['scores']['score_qualitativo']}")
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
    nv = _provider_state["nvidia"]
    logger.info(f"[Ag3][Resumo LLM] Gemini chamadas={g['chamadas']} | sucessos={g['sucessos']} | 429={g['erros_429']} | puladas={g['puladas']}")
    logger.info(f"[Ag3][Resumo LLM] Groq chamadas={gr['chamadas']} | sucessos={gr['sucessos']} | 429={gr['erros_429']} | tempo_espera_quota={tempo_espera:.0f}s")
    logger.info(f"[Ag3][Resumo LLM] NVIDIA chamadas={nv['chamadas']} | sucessos={nv['sucessos']} | erros={nv['erros']}")

    return saida