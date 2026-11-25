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

  ORDEM_*        ordem das IAs de cada tarefa (ver ORDENS abaixo)
  FOTOS_*        quantas fotos vao em cada chamada do Agente 3, por provedor

Regra de repeticao, igual em todas as IAs e tarefas (com_regra_429):
  - limite por MINUTO (429) pedindo espera de ate 30 s: espera e tenta mais UMA vez;
  - falha do servidor (500/502/503): espera 3 s e tenta mais UMA vez;
  - limite por DIA (ou espera maior que 30 s), tempo esgotado e outros erros:
    passa direto para a proxima IA.
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time

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


# Ordem das IAs por tarefa: (padrao, nomes aceitos). Nomes:
#   groq   = as duas chaves do Groq (GROQ_API_KEY e depois GROQ_API_KEY_2)
#   groq1 / groq2 = so uma delas
#   gemini, nvidia, zai, qwen (Colab; desligado hoje, so entra se escrito na lista)
# Os padroes repetem a ordem que ja existia; o Z.AI entra so no fim das de texto
# (a visao dele, glm-4.6v-flash, vivia sobrecarregada em 24/11/2026: fica fora).
_TEXTO = {"groq", "groq1", "groq2", "gemini", "nvidia", "zai", "qwen"}
ORDENS = {
    "ORDEM_COMPARAVEIS": ("groq,gemini,nvidia,zai", _TEXTO),             # Agente 2, classificacao
    "ORDEM_ZONA": ("gemini,groq1,nvidia", _TEXTO),                       # Agente 2, satelite
    "ORDEM_FOTOS_ALVO": ("gemini,groq1,nvidia", _TEXTO),                 # Agente 3, imovel avaliado
    "ORDEM_FOTOS_COMPARAVEIS": ("groq1,nvidia,gemini", _TEXTO),          # Agente 3, comparaveis
    "ORDEM_REGIAO": ("gemini,groq1,nvidia,zai", _TEXTO),                 # Agente 4
}

# Fotos por chamada no Agente 3 (cada provedor aguenta um tanto).
PADROES_FOTOS = {"FOTOS_QWEN": 4, "FOTOS_GEMINI": 4, "FOTOS_GROQ": 2, "FOTOS_NVIDIA": 1, "FOTOS_ZAI": 1}

ESPERA_MAX_429_S = 30.0       # acima disso, nao espera: vai para a proxima IA
ESPERA_PADRAO_429_S = 10.0    # limite por minuto sem tempo informado
ESPERA_FALHA_SERVIDOR_S = 3.0  # erro 500/502/503: espera e tenta 1x
ZAI_ESPERA_TRAVA_S = 90.0    # o Z.AI gratis atende uma chamada por vez

_trava_zai = threading.Lock()


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


def ordem(tarefa: str) -> list[str]:
    """
    Lista das IAs da `tarefa` (ex.: "ORDEM_ZONA"), na ordem do .env ou do padrao.
    "groq" vira ["groq1", "groq2"]. Nome desconhecido e repetido sao ignorados
    (com aviso no log); lista vazia volta ao padrao.
    """
    padrao, aceitos = ORDENS[tarefa]
    texto = obter_config(tarefa, padrao)
    lista: list[str] = []
    for nome in re.split(r"[,;\s]+", texto.lower()):
        if not nome:
            continue
        if nome not in aceitos:
            logger.warning(f"[IA] {tarefa}: '{nome}' nao e uma IA conhecida ({', '.join(sorted(aceitos))}); ignorado")
            continue
        for item in (["groq1", "groq2"] if nome == "groq" else [nome]):
            if item not in lista:
                lista.append(item)
    if not lista:
        logger.warning(f"[IA] {tarefa} vazia ou invalida; usando o padrao: {padrao}")
        return ordem_padrao(tarefa)
    return lista


def ordem_padrao(tarefa: str) -> list[str]:
    lista: list[str] = []
    for nome in ORDENS[tarefa][0].split(","):
        lista += ["groq1", "groq2"] if nome == "groq" else [nome]
    return lista


def chave_groq(nome: str) -> str:
    """'groq1' -> GROQ_API_KEY, 'groq2' -> GROQ_API_KEY_2."""
    return obter_config("GROQ_API_KEY_2" if nome == "groq2" else "GROQ_API_KEY")


def chave_gemini() -> str:
    return obter_config("GOOGLE_API_KEY_2") or obter_config("GOOGLE_API_KEY")


def fotos(provedor: str) -> int:
    """Fotos por chamada do Agente 3 para o provedor ('gemini', 'groq', ...); minimo 1."""
    nome = f"FOTOS_{provedor.upper().rstrip('12')}"
    padrao = PADROES_FOTOS.get(nome, 1)
    try:
        return max(1, int(obter_config(nome, str(padrao))))
    except ValueError:
        logger.warning(f"[IA] {nome} nao e numero; usando {padrao}")
        return padrao


# -----------------------------------------------------------------------------
# Erro 429 (limite de uso)
# -----------------------------------------------------------------------------

_MARCAS_DIA = ("per day", "perday", "per_day", "daily", "(rpd)", "(tpd)",
               "insufficient balance")


def analisar_limite(erro: Exception) -> tuple[str | None, float | None]:
    """
    ('minuto', segundos), ('dia', None) ou (None, None) se nao for erro de limite.
    `segundos` e a espera pedida pelo provedor (None se ele nao disse).
    """
    texto = str(erro)
    baixo = texto.lower()
    codigo = getattr(erro, "status_code", None) or getattr(erro, "code", None)
    eh_limite = (
        codigo == 429
        or "429" in baixo
        or "rate limit" in baixo
        or "rate_limit" in baixo
        or "resource_exhausted" in baixo
        or "too many requests" in baixo
        or re.search(r"code['\"]?\s*:\s*['\"]?130[25]\b", baixo)   # Z.AI: concorrencia / sobrecarga
    )
    if not eh_limite:
        return None, None
    if any(m in baixo for m in _MARCAS_DIA) or re.search(r"code['\"]?\s*:\s*['\"]?1113\b", baixo):
        return "dia", None
    return "minuto", _segundos_de_espera(erro, baixo)


def _segundos_de_espera(erro: Exception, baixo: str) -> float | None:
    resposta = getattr(erro, "response", None)
    try:
        cabecalho = resposta.headers.get("retry-after") if resposta is not None else None
        if cabecalho:
            return float(cabecalho)
    except (AttributeError, TypeError, ValueError):
        pass
    # Groq: "try again in 1m2.5s" / "in 7.5s" / "in 450ms"; Gemini: "retryDelay': '23s'"
    m = re.search(r"try again in (?:(\d+)h)?(?:(\d+)m(?!s))?(?:(\d+(?:\.\d+)?)s)?(?:(\d+(?:\.\d+)?)ms)?", baixo)
    if m and any(m.groups()):
        h, mi, s, ms = m.groups()
        return int(h or 0) * 3600 + int(mi or 0) * 60 + float(s or 0) + float(ms or 0) / 1000
    m = re.search(r"retry[_\s-]*(?:delay|after)['\"]?\s*[:=]?\s*['\"]?(\d+(?:\.\d+)?)\s*s", baixo)
    if m:
        return float(m.group(1))
    return None


def eh_falha_do_servidor(erro: Exception) -> bool:
    """Erro 500, 502 ou 503: falha passageira do servidor do provedor."""
    codigo = getattr(erro, "status_code", None) or getattr(erro, "code", None)
    if codigo in (500, 502, 503):
        return True
    # Groq/NVIDIA/Z.AI: "Error code: 503 - {...}"; Gemini: "500 INTERNAL. {...}"
    return bool(re.match(r"\s*(?:error code:\s*)?(500|502|503)\b", str(erro).lower()))


def com_regra_429(chamar, rotulo: str = "IA"):
    """
    Executa `chamar()`. Tenta mais UMA vez quando:
      - limite por minuto pedindo ate 30 s: espera o tempo pedido;
      - falha do servidor (500/502/503): espera ESPERA_FALHA_SERVIDOR_S.
    Limite por dia (ou espera maior), tempo esgotado e qualquer outro erro sobem
    como excecao, para o chamador passar para a proxima IA.
    """
    try:
        return chamar()
    except Exception as erro:
        if eh_falha_do_servidor(erro):
            logger.info(f"[IA] {rotulo}: falha do servidor ({str(erro)[:60]}); "
                        f"esperando {ESPERA_FALHA_SERVIDOR_S:.0f}s e tentando de novo (1x)")
            time.sleep(ESPERA_FALHA_SERVIDOR_S)
            return chamar()
        tipo, segundos = analisar_limite(erro)
        if tipo != "minuto":
            if tipo == "dia":
                logger.warning(f"[IA] {rotulo}: limite do DIA; proxima IA")
            raise
        espera = ESPERA_PADRAO_429_S if segundos is None else segundos + 1.0
        if espera > ESPERA_MAX_429_S:
            logger.warning(f"[IA] {rotulo}: limite por minuto pede {espera:.0f}s (> {ESPERA_MAX_429_S:.0f}s); proxima IA")
            raise
        logger.info(f"[IA] {rotulo}: limite por minuto; esperando {espera:.1f}s e tentando de novo (1x)")
        time.sleep(espera)
        return chamar()


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

    def _criar():
        return client.chat.completions.create(
            model=nome_modelo,
            messages=mensagens,
            max_tokens=max_tokens,
            temperature=temperature,
            extra_body=dict(cfg["sem_pensar"]),
            **extra,
        )

    if provedor == "zai":
        # O plano gratis do Z.AI atende uma chamada por vez (erro 1302 se vierem
        # duas juntas, e os Agentes 3 e 4 rodam ao mesmo tempo).
        if not _trava_zai.acquire(timeout=ZAI_ESPERA_TRAVA_S):
            raise TimeoutError(f"Z.AI ocupada ha mais de {ZAI_ESPERA_TRAVA_S:.0f}s")
        try:
            resposta = _criar()
        finally:
            _trava_zai.release()
    else:
        resposta = _criar()
    return (resposta.choices[0].message.content or "").strip()


def provedor_de(nome: str) -> str:
    """'groq1'/'groq2' -> 'groq'; os outros ficam iguais."""
    return "groq" if nome.startswith("groq") else nome


def modelo_texto(provedor: str, grande: bool = True) -> str:
    """Modelo de texto do provedor ('groq1' tambem vale)."""
    p = provedor_de(provedor)
    if p == "groq":
        return modelo("GROQ_MODELO_TEXTO_GRANDE" if grande else "GROQ_MODELO_TEXTO_PEQUENO")
    return {"gemini": modelo("GEMINI_MODELO"), "nvidia": modelo("NVIDIA_MODELO_TEXTO"),
            "zai": modelo("ZAI_MODELO_TEXTO"), "qwen": "Qwen3-VL-8B"}[p]


def modelo_visao(provedor: str) -> str:
    p = provedor_de(provedor)
    return {"groq": modelo("GROQ_MODELO_VISAO"), "gemini": modelo("GEMINI_MODELO"),
            "nvidia": modelo("NVIDIA_MODELO_VISAO"), "zai": modelo("ZAI_MODELO_VISAO"),
            "qwen": "Qwen3-VL-8B"}[p]
