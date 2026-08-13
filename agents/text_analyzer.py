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
         a. Seleciona ate 8 fotos espacadas uniformemente
         b. Monta prompt com titulo, descricao, campos estruturados e fotos
         c. LLM multimodal analisa texto + fotos juntos e retorna JSON
         d. Python valida, normaliza vocabulario e calcula score deterministico
    4. Imovel alvo: analisado separadamente
    5. Salva em data/imoveis_analisados_ag3.json

CADEIA DE FALLBACK (LLMs):
    1. Gemini 2.5 Flash (GOOGLE_API_KEY) — multimodal, ate 8 fotos por chamada
    2. Groq qwen3.6-27b (GROQ_API_KEY) — multimodal, ate 5 fotos por chamada
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
    - google-generativeai (Gemini 2.5 Flash)
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
    Envia titulo, descricao e fotos para o Gemini 2.5 Flash (multimodal).
    Uma unica chamada com ate 8 fotos — o modelo analisa texto e imagens juntos.
    Retorna {} em caso de falha.
    Fallback: NVIDIA NIM (llama-3.2-11b-vision-instruct).
    """
    try:
        from google import genai
        from google.genai import types

        api_key = os.getenv("GOOGLE_API_KEY", "")
        if not api_key:
            # Fallback para NVIDIA NIM
            return _analisar_imovel_vision_nvidia(imovel)

        client = genai.Client(api_key=api_key)

        titulo    = imovel.get("title", "") or ""
        descricao = imovel.get("description", "") or imovel.get("descricao", "") or ""
        tipo      = imovel.get("propertyType", "") or ""
        area      = imovel.get("area", "")
        quartos   = imovel.get("bedrooms", "")
        banheiros = imovel.get("bathrooms", "")
        suites    = imovel.get("suites", "") or ""
        vagas     = imovel.get("parkingSpaces", "")
        preco     = imovel.get("priceFormatted", "") or imovel.get("price", "")
        bairro    = imovel.get("neighborhood", "") or imovel.get("bairro", "") or ""
        cidade    = imovel.get("city", "") or imovel.get("cidade", "") or ""
        images    = imovel.get("images", []) or []

        prompt_texto = f"""Você é um avaliador imobiliário especializado em análise qualitativa de imóveis a partir de fotografias, descrição do anúncio e dados estruturados.
Todas as imagens fornecidas pertencem ao MESMO imóvel.
Sua tarefa é interpretar somente características qualitativas do imóvel que possam ser observadas ou explicitamente informadas.
Você NÃO deve calcular preço, valor de mercado, score qualitativo ou classificação favorável/desfavorável. Essas etapas serão realizadas posteriormente pelo sistema por meio de regras determinísticas.

# OBJETIVO
Analise conjuntamente:
1. estado geral de conservação;
2. padrão aparente de acabamento;
3. diferenciais relevantes;
4. problemas ou aspectos negativos comprovados;
5. evidências que sustentam as classificações;
6. qualidade das imagens;
7. nível de confiança da análise.

# DADOS DO IMÓVEL
Título: {titulo[:200]}
Descrição:
{descricao[:500]}
Tipo: {tipo}
Área: {area} m²
Quartos: {quartos}
Banheiros: {banheiros}
Suítes: {suites}
Vagas: {vagas}
Preço anunciado: {preco}
Bairro: {bairro}
Cidade: {cidade}
Também são fornecidas até 8 imagens do imóvel.

# REGRA FUNDAMENTAL
Use SOMENTE informações:
* visualmente identificáveis nas imagens;
* explicitamente presentes na descrição;
* fornecidas nos campos estruturados.
NÃO invente informações.
NÃO complete informações com conhecimento externo.
NÃO presuma características comuns a imóveis semelhantes.
Quando não houver evidência suficiente, use "desconhecido".
Ausência de informação NÃO significa ausência da característica e NÃO deve ser tratada como ponto negativo.

# INDEPENDÊNCIA DO PREÇO
O preço anunciado NÃO deve influenciar:
* estado de conservação;
* padrão de acabamento;
* pontos positivos;
* pontos negativos;
* confiança da análise.
Nunca conclua que um imóvel é de alto padrão por ser caro.
Nunca conclua que um imóvel é simples por ser barato.
Analise exclusivamente suas características observáveis.

# ANÁLISE DAS MÚLTIPLAS IMAGENS
Considere TODAS as imagens como diferentes perspectivas ou ambientes do mesmo imóvel.
NÃO determine o estado geral com base em uma única fotografia.
Antes de produzir a resposta final:
1. observe as imagens individualmente;
2. identifique os ambientes que podem ser reconhecidos;
3. procure características que se repetem em várias imagens;
4. diferencie situações isoladas de situações predominantes;
5. consolide as evidências para representar o imóvel como um todo.
Uma cozinha moderna NÃO significa automaticamente que todo o imóvel foi reformado.
Um banheiro antigo NÃO significa automaticamente que todo o imóvel está em estado regular.
Uma pequena mancha isolada NÃO significa automaticamente que existe infiltração generalizada.

# CONFLITOS ENTRE IMAGENS
Se diferentes ambientes apresentarem estados distintos:
* considere a quantidade de ambientes afetados;
* considere a intensidade das diferenças;
* considere se a característica é localizada ou generalizada;
* escolha a classificação que melhor represente o conjunto do imóvel.
Se não for possível determinar qual situação predomina:
→ reduza a confiança.

# 1. ESTADO DE CONSERVAÇÃO
Escolha EXATAMENTE UMA opção:
"novo" — evidência clara de imóvel novo, recém-construído, recém-entregue ou nunca habitado. Apenas possuir acabamento moderno NÃO é suficiente.
"reformado" — evidências claras de reforma ou modernização relevante em parte significativa do imóvel. NÃO classifique como reformado porque apenas um ambiente parece novo.
"bom" — bem conservado, sem deterioração relevante, funcional, sem necessidade evidente de intervenção significativa. Pode possuir acabamentos antigos e ainda estar em bom estado.
"regular" — sinais perceptíveis de desgaste, acabamento envelhecido, manutenção pendente, pintura desgastada, pequenos danos. Problemas perceptíveis mas sem necessidade de reforma ampla.
"precisa_reforma" — evidências claras de deterioração significativa, danos relevantes, sinais fortes de umidade/infiltração, revestimentos bastante danificados, vários ambientes deteriorados. NÃO utilize por questões meramente estéticas ou acabamento antigo.
"desconhecido" — poucas imagens, imagens ruins, ambientes internos não aparecem, evidências insuficientes.

# 2. PADRÃO DE ACABAMENTO
Escolha EXATAMENTE UMA opção:
"alto_padrao" — evidência consistente de materiais, acabamentos ou soluções visualmente superiores. NÃO utilize por localização, preço, tamanho ou número de quartos.
"medio" — acabamentos intermediários, boa apresentação, materiais aparentemente adequados.
"simples" — acabamentos básicos, materiais aparentemente simples, soluções funcionais. "Simples" NÃO significa "mal conservado".
"desconhecido" — imagens ou informações insuficientes para avaliar.
REGRA ESSENCIAL: estado de conservação e padrão de acabamento são conceitos independentes.

# 3. PONTOS POSITIVOS
Inclua somente características claramente visíveis, explicitamente mencionadas na descrição ou presentes nos dados estruturados.
Se {vagas} > 0: inclua "vagas de garagem".
Se {suites} > 0 ou houver suíte explicitamente informada: inclua "suite".
Evite duplicidades e expressões subjetivas.

# 4. PONTOS NEGATIVOS
Inclua SOMENTE problemas com evidência concreta. Use expressões padronizadas quando possível:
"documentacao_irregular" — somente quando explicitamente informado no texto, NUNCA infira pelas imagens.
"infiltracao_umidade" — sinais visuais consistentes, manchas características ou informação textual explícita.
"precisa_reforma" — evidências de necessidade relevante de reforma.
"pintura_deteriorada" — desgaste visível de pintura.
"acabamento_desgastado" — revestimentos ou materiais visivelmente desgastados.
"danos_visiveis" — danos concretos observáveis.
A ausência de piscina, varanda, suíte, garagem, churrasqueira, móveis planejados NÃO é ponto negativo.

# 5. QUALIDADE DAS IMAGENS
"boa" — claras, variadas, mostram vários ambientes relevantes.
"razoavel" — utilizáveis, mas poucos ambientes, repetição ou enquadramentos limitados.
"ruim" — desfocadas, muito pequenas, escuras, repetitivas, predominantemente externas, insuficientes.

# 6. CONFIANÇA DA EXTRAÇÃO
"alta" — várias imagens claras, diferentes ambientes, evidências consistentes.
"media" — análise possível, algumas ambiguidades, parte do imóvel não é mostrada.
"baixa" — poucas evidências, imagens ruins, poucos ambientes, conflitos importantes.
NÃO aumente a confiança apenas porque a descrição usa palavras como "luxuoso", "impecável", "excelente". Textos comerciais são evidência mais fraca quando incompatíveis com as imagens.

# 7. EVIDÊNCIAS
Forneça até 3 observações objetivas para conservação e até 3 para acabamento, baseadas apenas no que é visível ou explicitamente informado.

# 8. OBSERVAÇÕES
Informações importantes que não alteram necessariamente a classificação geral. Máximo de 4 observações.

# VERIFICAÇÃO FINAL OBRIGATÓRIA
Antes de responder, confira internamente:
1. Analisei todas as imagens em conjunto?
2. Minha classificação representa o imóvel como um todo?
3. Estou confundindo conservação com padrão?
4. Alguma característica foi inventada?
5. Algum ponto negativo representa apenas ausência de um diferencial?
6. O preço influenciou indevidamente minha avaliação?
7. Os pontos positivos possuem evidência?
8. Os pontos negativos possuem evidência?
9. Minhas evidências sustentam as classificações?
10. Minha confiança está compatível com a quantidade e qualidade das imagens?
11. Usei apenas os valores permitidos nos campos categóricos?
12. Meu JSON é válido?

# FORMATO DE RESPOSTA
Responda SOMENTE com um objeto JSON válido.
Não utilize Markdown.
Não escreva texto antes ou depois do JSON.
Não crie campos além dos especificados.
{{
  "estado_conservacao": "novo | reformado | bom | regular | precisa_reforma | desconhecido",
  "padrao_acabamento": "alto_padrao | medio | simples | desconhecido",
  "pontos_positivos": [],
  "pontos_negativos": [],
  "qualidade_imagens": "boa | razoavel | ruim",
  "confianca_extracao": "baixa | media | alta",
  "evidencias": {{
    "conservacao": [],
    "acabamento": []
  }},
  "observacoes": []
}}"""

        # Seleciona ate 8 fotos espaçadas uniformemente
        if len(images) <= 8:
            fotos_selecionadas = images
        else:
            step = len(images) / 8
            indices = [int(i * step) for i in range(8)]
            fotos_selecionadas = [images[i] for i in indices]

        # Monta conteudo: texto + fotos (Gemini aceita multiplas imagens por chamada)
        parts = [types.Part.from_text(text=prompt_texto)]
        for url in fotos_selecionadas:
            try:
                parts.append(types.Part.from_uri(file_uri=url, mime_type="image/webp"))
            except Exception:
                pass

        # Retry: tenta ate 2x se Gemini der 500
        texto_resp = ""
        for tentativa in range(2):
            try:
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=[types.Content(role="user", parts=parts)],
                    config=types.GenerateContentConfig(temperature=0),
                )
                texto_resp = response.text or ""
                break
            except Exception as e:
                if "500" in str(e) and tentativa == 0:
                    logger.warning(f"Gemini 500 — retry em 3s...")
                    time.sleep(3)
                    continue
                raise
        m = re.search(r"\{[\s\S]+\}", texto_resp)
        if not m:
            logger.warning("Gemini nao retornou JSON valido")
            return {}

        resultado = json.loads(m.group(0))
        resultado["fotos_analisadas"] = len(fotos_selecionadas)
        resultado["llm_usada"] = "gemini-2.5-flash"
        return resultado

    except Exception as e:
        logger.error(f"Gemini falhou: {e} — tentando Groq qwen3.6-27b")
        return _analisar_imovel_vision_groq(imovel)


def _analisar_imovel_vision_groq(imovel: dict) -> dict:
    """
    Fallback 1: Groq qwen3.6-27b (multimodal, ate 5 fotos por request).
    Envia texto + ate 5 fotos via URL numa unica chamada.
    """
    try:
        from groq import Groq

        api_key = os.getenv("GROQ_API_KEY", "")
        if not api_key:
            return _analisar_imovel_vision_nvidia(imovel)

        client = Groq(api_key=api_key)

        titulo    = imovel.get("title", "") or ""
        descricao = imovel.get("description", "") or imovel.get("descricao", "") or ""
        tipo      = imovel.get("propertyType", "") or ""
        area      = imovel.get("area", "")
        quartos   = imovel.get("bedrooms", "")
        banheiros = imovel.get("bathrooms", "")
        suites    = imovel.get("suites", "") or ""
        vagas     = imovel.get("parkingSpaces", "")
        preco     = imovel.get("priceFormatted", "") or imovel.get("price", "")
        bairro    = imovel.get("neighborhood", "") or imovel.get("bairro", "") or ""
        cidade    = imovel.get("city", "") or imovel.get("cidade", "") or ""
        images    = imovel.get("images", []) or []

        # Groq aceita max 3 imagens por request (qwen3.6-27b)
        if len(images) <= 3:
            fotos_selecionadas = images
        else:
            step = len(images) / 3
            indices = [int(i * step) for i in range(3)]
            fotos_selecionadas = [images[i] for i in indices]

        prompt_texto = (
            f"Voce e um avaliador imobiliario. Analise este imovel com base no texto e fotos.\n"
            f"Titulo: {titulo[:200]}\nDescricao: {descricao[:400]}\n"
            f"Tipo: {tipo} | Area: {area}m2 | Quartos: {quartos} | Banheiros: {banheiros} | "
            f"Suites: {suites} | Vagas: {vagas} | Preco: {preco} | Bairro: {bairro} | Cidade: {cidade}\n\n"
            f"Retorne SOMENTE JSON valido:\n"
            f'{{"estado_conservacao": "novo|reformado|bom|regular|precisa_reforma|desconhecido",'
            f'"padrao_acabamento": "alto_padrao|medio|simples|desconhecido",'
            f'"pontos_positivos": [],'
            f'"pontos_negativos": [],'
            f'"qualidade_imagens": "boa|razoavel|ruim",'
            f'"confianca_extracao": "baixa|media|alta",'
            f'"evidencias": {{"conservacao": [], "acabamento": []}},'
            f'"observacoes": []}}'
        )

        # Monta content com texto + fotos como URLs
        content = [{"type": "text", "text": prompt_texto}]
        for url in fotos_selecionadas:
            content.append({"type": "image_url", "image_url": {"url": url}})

        response = client.chat.completions.create(
            model="qwen/qwen3.6-27b",
            messages=[{"role": "user", "content": content}],
            temperature=0,
            max_completion_tokens=1024,
        )

        texto_resp = response.choices[0].message.content or ""
        m = re.search(r"\{[\s\S]+\}", texto_resp)
        if not m:
            logger.warning("Groq qwen3.6-27b nao retornou JSON valido — tentando NVIDIA NIM")
            return _analisar_imovel_vision_nvidia(imovel)

        resultado = json.loads(m.group(0))
        resultado["fotos_analisadas"] = len(fotos_selecionadas)
        resultado["llm_usada"] = "groq-qwen3.6-27b"
        return resultado

    except Exception as e:
        logger.error(f"Groq qwen3.6-27b falhou: {e} — tentando NVIDIA NIM")
        return _analisar_imovel_vision_nvidia(imovel)


def _analisar_imovel_vision_nvidia(imovel: dict) -> dict:
    """
    Fallback: NVIDIA NIM (meta/llama-3.2-11b-vision-instruct).
    Envia 1 foto principal + 7 extras (1 por vez).
    """
    try:
        from openai import OpenAI

        api_key = os.getenv("NVIDIA_API_KEY", "")
        if not api_key:
            logger.warning("NVIDIA_API_KEY nao configurada")
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

        # Seleciona ate 8 fotos espaçadas
        if len(images) <= 8:
            fotos_selecionadas = images
        else:
            step = len(images) / 8
            indices = [int(i * step) for i in range(8)]
            fotos_selecionadas = [images[i] for i in indices]

        # Chamada principal: texto + 1 foto (a do meio)
        content = [{"type": "text", "text": prompt_texto}]
        if fotos_selecionadas:
            foto_principal = fotos_selecionadas[len(fotos_selecionadas) // 2]
            content.append({"type": "image_url", "image_url": {"url": foto_principal}})

        response = client.chat.completions.create(
            model="meta/llama-3.2-11b-vision-instruct",
            messages=[{"role": "user", "content": content}],
            max_tokens=512,
            temperature=0,
        )

        texto_resp = response.choices[0].message.content or ""

        # Chamadas extras com mais fotos (1 foto por vez)
        if len(fotos_selecionadas) > 1:
            import time as time_mod
            extras = [f for i, f in enumerate(fotos_selecionadas) if i != len(fotos_selecionadas) // 2]
            for foto in extras[:7]:
                time_mod.sleep(1)
                try:
                    r2 = client.chat.completions.create(
                        model="meta/llama-3.2-11b-vision-instruct",
                        messages=[{"role": "user", "content": [
                            {"type": "text", "text": "Em uma frase: estado de conservacao (novo/bom/regular/precisa_reforma) e diferenciais visiveis."},
                            {"type": "image_url", "image_url": {"url": foto}}
                        ]}],
                        max_tokens=80,
                        temperature=0,
                    )
                    texto_resp += f"\n[Foto extra: {r2.choices[0].message.content}]"
                except Exception:
                    pass

        m = re.search(r"\{[\s\S]+\}", texto_resp)
        if not m:
            logger.warning("NVIDIA NIM nao retornou JSON valido")
            return {}

        resultado_nim = json.loads(m.group(0))
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
        # Problema não previsto na tabela: penalização genérica
        if peso is None:
            peso = -0.05

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
    qualidade_imagens = str(dados.get("qualidade_imagens", "razoavel")).lower().strip()
    if qualidade_imagens not in ("boa", "razoavel", "ruim"):
        qualidade_imagens = "razoavel"
    evidencias = dados.get("evidencias", {})
    if not isinstance(evidencias, dict):
        evidencias = {}

    if not isinstance(pontos_pos, list): pontos_pos = []
    if not isinstance(pontos_neg, list): pontos_neg = []
    if not isinstance(observacoes, list): observacoes = []

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
        "qualidade_imagens":     qualidade_imagens,
        "confianca_extracao":    confianca,
        "evidencias":            evidencias,
        "fotos_analisadas":      min(len(images), 8),
        "total_fotos_disponiveis": len(images),
        "llm_usada":             dados.get("llm_usada", "fallback"),
        "observacoes":           observacoes,
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
    analise_alvo = _analisar_imovel(imovel_alvo)
    imovel_alvo["analise_qualitativa"] = analise_alvo
    logger.info(f"  Alvo: estado={analise_alvo['estado_conservacao']} | "
                f"padrao={analise_alvo['padrao_acabamento']} | "
                f"score={analise_alvo['scores']['score_qualitativo']} | "
                f"class={analise_alvo['classificacao_qualitativa']} | "
                f"fotos={analise_alvo['fotos_analisadas']}")
    time.sleep(2.0)  # 2s entre chamadas

    # Limita a 20 comparaveis (os melhores por ranking_llm)
    MAX_COMPARAVEIS_AG3 = 20
    if len(comparaveis) > MAX_COMPARAVEIS_AG3:
        # Ordena por ranking_llm (menor = melhor) e pega os top 20
        comparaveis.sort(key=lambda x: x.get("ranking_llm") or 999)
        logger.info(f"Limitando de {len(comparaveis)} para {MAX_COMPARAVEIS_AG3} comparaveis (top ranking)")
        comparaveis = comparaveis[:MAX_COMPARAVEIS_AG3]

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
        llm_usada = analise.get("llm_usada", "fallback")
        logger.info(f"    -> {t1-t0:.1f}s | estado={analise['estado_conservacao']} | score={analise['scores']['score_qualitativo']} | llm={llm_usada}")
        if analise["status"] == "ok":
            com_ok += 1
        else:
            com_insuficiente += 1
        time.sleep(2.0)  # 2s entre chamadas — Gemini 2.5 Flash

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

