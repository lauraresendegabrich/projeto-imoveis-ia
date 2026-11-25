"""
Configuracao das IAs usadas pelos agentes
=========================================

Um so lugar para:
  - os nomes dos modelos (lidos do .env ou dos Secrets do Streamlit Cloud; sem a
    variavel, vale o padrao daqui);
  - a chamada aos provedores no padrao OpenAI (NVIDIA e Z.AI), com o "pensar"
    desligado: os modelos novos gastam os tokens pensando e devolvem resposta vazia.

Variaveis (todas opcionais):
  GROQ_MODELO_TEXTO_GRANDE  comparaveis (Agente 2)
  GROQ_MODELO_TEXTO_PEQUENO regiao (Agente 4)
  GROQ_MODELO_VISAO         zona no satelite (Agente 2) e fotos (Agente 3)
  GEMINI_MODELO             todas as tarefas
  NVIDIA_MODELO_TEXTO / NVIDIA_MODELO_VISAO
  ZAI_MODELO_TEXTO / ZAI_MODELO_VISAO
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

PADROES_MODELOS = {
    "GROQ_MODELO_TEXTO_GRANDE": "openai/gpt-oss-120b",
    "GROQ_MODELO_TEXTO_PEQUENO": "openai/gpt-oss-20b",
    "GROQ_MODELO_VISAO": "qwen/qwen3.8-27b",
    "GEMINI_MODELO": "gemini-3.5-flash-lite",
    # NVIDIA: llama-3.2-11b-vision e gpt-oss-20b foram desativados em nov/2026 (erro 410).
    "NVIDIA_MODELO_TEXTO": "nvidia/nemotron-3.5-lightning-30b-a3b",
    "NVIDIA_MODELO_VISAO": "nvidia/nemotron-3.5-super-vl-120b-a12b",
    "ZAI_MODELO_TEXTO": "glm-4.7-flash",
    "ZAI_MODELO_VISAO": "glm-4.6v-flash",
}

# Provedores no padrao OpenAI: endereco, variavel da chave e o parametro que desliga
# o "pensar" (conferido em 24/11/2026: sem ele, 2 de 5 respostas vieram vazias).
PROVEDORES_OPENAI = {
    "nvidia": {
        "base_url": "https://integrate.api.nvidia.com/v1",
        "chave": "NVIDIA_API_KEY",
        "sem_pensar": {"reasoning_effort": "none"},
    },
    "zai": {
        "base_url": "https://api.z.ai/api/paas/v4",
        "chave": "ZAI_API_KEY",
        "sem_pensar": {"thinking": {"type": "disabled"}},
    },
}


def obter_config(nome: str, padrao: str = "") -> str:
    """Valor do .env (ambiente) ou, no Streamlit Cloud, dos Secrets; senao `padrao`."""
    valor = os.getenv(nome, "").strip()
    if valor:
        return valor
    try:
        import streamlit as st
        if nome in st.secrets:
            return str(st.secrets[nome]).strip() or padrao
    except Exception:
        pass
    return padrao


def modelo(nome: str) -> str:
    """Nome do modelo da variavel `nome` (ex.: "GEMINI_MODELO")."""
    return obter_config(nome, PADROES_MODELOS[nome])


def chamar_openai_compativel(
    provedor: str,
    nome_modelo: str,
    mensagens: list[dict],
    *,
    max_tokens: int = 1500,
    temperature: float = 0.0,
    timeout_s: float = 60.0,
    json_object: bool = False,
    chave: str | None = None,
) -> str:
    """
    Chama um provedor no padrao OpenAI (PROVEDORES_OPENAI) e devolve o texto da
    resposta. Sem chave devolve "" (o chamador segue para o proximo). Erros sobem
    como excecao, para o chamador decidir (registrar e seguir).
    """
    cfg = PROVEDORES_OPENAI[provedor]
    chave = chave if chave is not None else obter_config(cfg["chave"])
    if not chave:
        logger.warning(f"[IA] {provedor}: {cfg['chave']} nao configurada; pulando")
        return ""

    import httpx
    from openai import OpenAI

    client = OpenAI(
        base_url=cfg["base_url"],
        api_key=chave,
        timeout=httpx.Timeout(timeout_s, connect=10.0),
        max_retries=0,
    )
    extra = {"response_format": {"type": "json_object"}} if json_object else {}
    resposta = client.chat.completions.create(
        model=nome_modelo,
        messages=mensagens,
        max_tokens=max_tokens,
        temperature=temperature,
        extra_body=dict(cfg["sem_pensar"]),
        **extra,
    )
    return (resposta.choices[0].message.content or "").strip()
