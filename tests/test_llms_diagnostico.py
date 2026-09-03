"""
Diagnostico de saude das LLMs do Agente 2.
==========================================

Testa CADA provider de LLM individualmente, tanto para TEXTO (clustering) quanto
para VISAO (zona homogenea), e mostra um relatorio claro de quem esta respondendo
corretamente. Use sempre que suspeitar que um modelo foi descontinuado ou trocado.

Cada teste valida a resposta com o MESMO validador usado em producao:
  - texto  -> _validar_classificacao_llm (IDs 1..N, cluster A/B, score 0..100)
  - visao  -> _validar_zona_llm (8 campos obrigatorios preenchidos)

COMO RODAR:
    .venv/Scripts/python.exe tests/test_llms_diagnostico.py

Providers sem chave configurada aparecem como PULADO (nao e erro).
"""
import sys
import os
import io
import base64

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Forca UTF-8 no console do Windows para nao quebrar em acentos/emojis.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from dotenv import load_dotenv
load_dotenv(override=True)

from agents import comparables as m


# ---------------------------------------------------------------------------
# Insumos de teste
# ---------------------------------------------------------------------------

_ALVO = {
    "propertyType": "Apartamentos", "area": 70, "bedrooms": 2, "bathrooms": 2,
    "parkingSpaces": 1, "city": "Campinas", "neighborhood": "Cambui", "street": "Rua X",
}
_CANDIDATOS = [
    {"propertyType": "Apartamentos", "area": 72, "bedrooms": 2, "bathrooms": 2, "parkingSpaces": 1},
    {"propertyType": "Apartamentos", "area": 150, "bedrooms": 4, "bathrooms": 4, "parkingSpaces": 3},
]
_PROMPT_TEXTO = m._montar_prompt_clustering(_ALVO, _CANDIDATOS)

_PROMPT_VISAO = (
    "Analise a imagem de satelite centrada no imovel alvo (marcador vermelho). "
    "Defina uma zona homogenea usando somente elementos visiveis. "
    "RESPONDA SOMENTE JSON com os campos: padrao_construtivo, homogeneidade_visual, "
    "densidade_urbana, transicao_visual, raio_sugerido_metros (inteiro), justificativa_raio, "
    "descricao_zona_homogenea, confianca."
)


def _imagem_teste() -> tuple[bytes, str]:
    """Gera uma imagem de satelite sintetica (grade + marcador vermelho)."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (256, 256), (120, 140, 120))
    d = ImageDraw.Draw(img)
    for x in range(0, 256, 32):
        d.line([(x, 0), (x, 256)], fill=(90, 100, 90))
        d.line([(0, x), (256, x)], fill=(90, 100, 90))
    d.ellipse([120, 120, 136, 136], fill=(220, 30, 30))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    dados = buf.getvalue()
    return dados, base64.b64encode(dados).decode("utf-8")


# ---------------------------------------------------------------------------
# Runners
# ---------------------------------------------------------------------------

_RESULTADOS = []  # (categoria, nome, status, detalhe)


def _registrar(categoria, nome, status, detalhe=""):
    _RESULTADOS.append((categoria, nome, status, detalhe))
    icone = {"OK": "[OK]  ", "FALHA": "[FALHA]", "PULADO": "[--]  ", "VAZIO": "[VAZIO]"}.get(status, status)
    print(f"  {icone} {nome}" + (f"  ->  {detalhe}" if detalhe else ""))


def _testar_texto(nome, chamar):
    try:
        resp = chamar() or ""
    except Exception as e:
        _registrar("texto", nome, "FALHA", f"{type(e).__name__}: {str(e)[:90]}")
        return
    if not resp:
        _registrar("texto", nome, "VAZIO", "sem resposta / erro tratado")
        return
    val = m._validar_classificacao_llm(resp, len(_CANDIDATOS))
    if val:
        cls = [(c["id"], c["cluster"], c["score_similaridade"]) for c in val["classificacao"]]
        _registrar("texto", nome, "OK", f"JSON valido {cls}")
    else:
        _registrar("texto", nome, "FALHA", f"JSON invalido/incompleto: {resp[:70].strip()!r}")


def _testar_visao(nome, chamar):
    try:
        resultado = chamar()
    except Exception as e:
        _registrar("visao", nome, "FALHA", f"{type(e).__name__}: {str(e)[:90]}")
        return
    if resultado:
        _registrar("visao", nome, "OK",
                   f"raio={resultado.get('raio_sugerido_metros')} conf={resultado.get('confianca')}")
    else:
        _registrar("visao", nome, "FALHA", "None (rejeitado pela validacao rigorosa ou erro)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    groq_key = os.getenv("GROQ_API_KEY", "")
    groq_key2 = os.getenv("GROQ_API_KEY_2", "")
    google_key = os.getenv("GOOGLE_API_KEY_2", "") or os.getenv("GOOGLE_API_KEY", "")
    google_key_visao = os.getenv("GOOGLE_API_KEY", "") or google_key
    nvidia_key = os.getenv("NVIDIA_API_KEY", "")
    qwen_url = m._obter_secret("QWEN_API_URL")

    print("=" * 64)
    print("DIAGNOSTICO DE LLMs — AGENTE 2 (texto/clustering + visao/zona)")
    print("=" * 64)
    print(f"Chaves: GROQ={'sim' if groq_key else 'nao'} | GROQ_2={'sim' if groq_key2 else 'nao'} | "
          f"GOOGLE={'sim' if google_key else 'nao'} | NVIDIA={'sim' if nvidia_key else 'nao'} | "
          f"QWEN_COLAB={'sim' if qwen_url else 'nao'}")

    # ===== TEXTO / CLUSTERING =====
    print("\n--- TEXTO / CLUSTERING (cadeia de fallback) ---")
    if qwen_url:
        _testar_texto("1. Qwen3-VL-8B (Colab)",
                      lambda: m._chamar_qwen_colab(_PROMPT_TEXTO, max_new_tokens=1600))
    else:
        _registrar("texto", "1. Qwen3-VL-8B (Colab)", "PULADO", "QWEN_API_URL nao configurada")

    if groq_key:
        _testar_texto("2. Groq openai/gpt-oss-120b (KEY)",
                      lambda: m._chamar_groq(_PROMPT_TEXTO, groq_key, model="openai/gpt-oss-120b"))
    else:
        _registrar("texto", "2. Groq gpt-oss-120b (KEY)", "PULADO", "GROQ_API_KEY nao configurada")

    if groq_key2:
        _testar_texto("3. Groq openai/gpt-oss-120b (KEY_2)",
                      lambda: m._chamar_groq(_PROMPT_TEXTO, groq_key2, model="openai/gpt-oss-120b"))
    else:
        _registrar("texto", "3. Groq gpt-oss-120b (KEY_2)", "PULADO", "GROQ_API_KEY_2 nao configurada")

    if google_key:
        _testar_texto("4. Gemini gemini-3.5-flash-lite",
                      lambda: m._chamar_gemini(_PROMPT_TEXTO, google_key))
    else:
        _registrar("texto", "4. Gemini 3.5-flash-lite", "PULADO", "GOOGLE_API_KEY nao configurada")

    if nvidia_key:
        _testar_texto("5. NVIDIA openai/gpt-oss-20b",
                      lambda: m._chamar_nvidia(_PROMPT_TEXTO, nvidia_key))
    else:
        _registrar("texto", "5. NVIDIA gpt-oss-20b", "PULADO", "NVIDIA_API_KEY nao configurada")

    # ===== VISAO / ZONA =====
    print("\n--- VISAO / ZONA HOMOGENEA (cadeia de fallback) ---")
    img_bytes, img_b64 = _imagem_teste()

    if qwen_url:
        _testar_visao("1. Qwen3-VL-8B (Colab)",
                      lambda: m._validar_zona_llm(
                          m._chamar_qwen_colab(prompt=_PROMPT_VISAO, imagem_bytes=img_bytes, max_new_tokens=1024) or ""))
    else:
        _registrar("visao", "1. Qwen3-VL-8B (Colab)", "PULADO", "QWEN_API_URL nao configurada")

    if google_key_visao:
        _testar_visao("2. Gemini gemini-3.5-flash-lite (visao)",
                      lambda: m._chamar_gemini_visao(_PROMPT_VISAO, img_bytes, google_key_visao))
    else:
        _registrar("visao", "2. Gemini 3.5-flash-lite (visao)", "PULADO", "GOOGLE_API_KEY nao configurada")

    if groq_key:
        _testar_visao("3. Groq qwen/qwen3.8-27b (visao)",
                      lambda: m._chamar_groq_visao(_PROMPT_VISAO, img_b64, "image/jpeg", groq_key))
    else:
        _registrar("visao", "3. Groq qwen3.8-27b (visao)", "PULADO", "GROQ_API_KEY nao configurada")

    if nvidia_key:
        _testar_visao("4. NVIDIA meta/llama-3.2-11b-vision-instruct",
                      lambda: m._chamar_nvidia_visao(_PROMPT_VISAO, img_b64, "image/jpeg", nvidia_key))
    else:
        _registrar("visao", "4. NVIDIA llama-3.2-11b-vision", "PULADO", "NVIDIA_API_KEY nao configurada")

    # ===== RELATORIO =====
    print("\n" + "=" * 64)
    print("RESUMO")
    print("=" * 64)
    ok = sum(1 for _, _, s, _ in _RESULTADOS if s == "OK")
    falha = sum(1 for _, _, s, _ in _RESULTADOS if s in ("FALHA", "VAZIO"))
    pulado = sum(1 for _, _, s, _ in _RESULTADOS if s == "PULADO")
    testados = ok + falha
    print(f"OK: {ok}/{testados} testados | Falhas: {falha} | Pulados (sem chave): {pulado}")

    texto_ok = [n for c, n, s, _ in _RESULTADOS if c == "texto" and s == "OK"]
    visao_ok = [n for c, n, s, _ in _RESULTADOS if c == "visao" and s == "OK"]
    print(f"\nTexto funcionando: {len(texto_ok)} provider(s)")
    print(f"Visao funcionando: {len(visao_ok)} provider(s)")

    if not texto_ok:
        print("\n[ALERTA] Nenhum provider de TEXTO respondeu — o clustering cairia no fallback Python.")
    if not visao_ok:
        print("\n[ALERTA] Nenhum provider de VISAO respondeu — a zona cairia no raio fallback (500m).")

    # Exit code: falha real (nao pulado) derruba, para uso em CI se desejado.
    return 1 if (falha > 0 and testados > 0 and ok == 0) else 0


if __name__ == "__main__":
    sys.exit(main())
