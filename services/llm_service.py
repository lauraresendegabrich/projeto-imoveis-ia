"""
Servico LLM - Configuracao do modelo de linguagem
===================================================

NOTA: Este servico e usado pelos agentes que precisam de UMA unica LLM
(text_analyzer, infra_evaluator, etc.). O collector.py tem seu proprio
sistema de LLM com round-robin entre multiplas contas Groq — ver
_get_llms() e _extrair_com_llm() em agents/collector.py.

─────────────────────────────────────────────────────────────────
O QUE E O GROQ:
─────────────────────────────────────────────────────────────────
  Groq e uma API que roda modelos de IA open-source (como o LLaMA
  da Meta) em servidores com chips especializados (LPU — Language
  Processing Unit). Nao e um modelo proprio — e uma infraestrutura
  que executa modelos existentes com alta velocidade.
  Funciona via chamada HTTP para api.groq.com.

─────────────────────────────────────────────────────────────────
MODELO USADO: llama-3.1-8b-instant
─────────────────────────────────────────────────────────────────
  - Criado pela Meta (open-source, familia LLaMA)
  - 8 bilhoes de parametros
  - Suficiente para extrair campos estruturados de texto
  - Mais rapido que modelos maiores (70B) no free tier do Groq

─────────────────────────────────────────────────────────────────
PLANO: 100% gratis, sem cartao de credito
─────────────────────────────────────────────────────────────────
  - 14.400 requests/dia
  - 30 requests/minuto
  - 6.000 tokens/minuto (principal gargalo)
  - Obtenha em: https://console.groq.com

─────────────────────────────────────────────────────────────────
POR QUE NAO USAR MODELO LOCAL (Ollama):
─────────────────────────────────────────────────────────────────
  Groq:   ~0.5s/resposta (servidor com chip especializado)
  Ollama: ~54s/resposta  (roda na CPU da maquina)
  Com 50 anuncios: Groq = 25s, Ollama = 45 minutos.
  Ollama e fallback final — so usado se Groq estiver indisponivel.

─────────────────────────────────────────────────────────────────
ORDEM DE PRIORIDADE:
─────────────────────────────────────────────────────────────────
  1. Groq  (GROQ_API_KEY)   — rapido, 14.400 req/dia
  2. Gemini (GOOGLE_API_KEY) — limite de tokens alto, mas pode travar
  3. Ollama local            — sem limite, mas lento (~54s/resposta)
"""

import os
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

GROQ_API_KEY   = os.getenv("GROQ_API_KEY", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

# Modelo Groq: llama-3.1-8b-instant (Meta LLaMA, 8B params)
# Rapido (~0.5s), 14.400 req/dia no free tier
MODELOS_GROQ = [
    "llama-3.1-8b-instant",   # preferido — mais rapido
    "llama3-8b-8192",         # alternativo
    "gemma2-9b-it",           # alternativo Google via Groq
]

# Modelos Gemini (fallback — pode travar em alguns ambientes)
MODELOS_GEMINI = [
    "gemini-2.0-flash-lite",  # 1.500 req/dia
    "gemini-2.0-flash",       # 50 req/dia
]

MODEL_OLLAMA = "llama3.2"


def get_llm():
    """
    Retorna UMA unica LLM para uso geral (text_analyzer, etc.).
    Para o collector.py, ver _get_llms() que suporta round-robin.

    Ordem: Groq -> Gemini -> Ollama local.
    """
    # 1. Groq — rapido, modelo llama-3.1-8b-instant
    if GROQ_API_KEY:
        try:
            from langchain_groq import ChatGroq
            llm = ChatGroq(
                model=MODELOS_GROQ[0],
                api_key=GROQ_API_KEY,
                temperature=0,
            )
            logger.debug(f"LLM: Groq ({MODELOS_GROQ[0]})")
            return llm
        except Exception as e:
            logger.warning(f"Groq indisponivel: {e}")

    # 2. Gemini — fallback (pode travar em alguns ambientes)
    if GOOGLE_API_KEY:
        from langchain_google_genai import ChatGoogleGenerativeAI
        for modelo in MODELOS_GEMINI:
            try:
                llm = ChatGoogleGenerativeAI(
                    model=modelo,
                    google_api_key=GOOGLE_API_KEY,
                    temperature=0,
                    convert_system_message_to_human=True,
                    request_timeout=15,
                )
                logger.debug(f"LLM: Gemini ({modelo})")
                return llm
            except Exception as e:
                logger.warning(f"Gemini {modelo} indisponivel: {e}")

    # 3. Ollama local — fallback final (~54s/resposta, sem limite)
    from langchain_ollama import OllamaLLM
    logger.info("LLM: Ollama local (llama3.2) — configure GROQ_API_KEY para mais velocidade")
    return OllamaLLM(model=MODEL_OLLAMA)
