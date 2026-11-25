"""
Testes da configuracao das IAs (services/ia.py). Sem rede.

    .venv/Scripts/python.exe -m tests.test_ia
"""
import os
import sys

sys.path.insert(0, ".")

from services import ia


def test_modelo_sem_variavel_usa_o_padrao():
    os.environ.pop("NVIDIA_MODELO_VISAO", None)
    os.environ["NVIDIA_MODELO_VISAO"] = ""
    assert ia.modelo("NVIDIA_MODELO_VISAO") == ia.PADROES_MODELOS["NVIDIA_MODELO_VISAO"]


def test_modelo_do_env_vale_mais_que_o_padrao():
    os.environ["GEMINI_MODELO"] = "  gemini-teste  "
    try:
        assert ia.modelo("GEMINI_MODELO") == "gemini-teste"
    finally:
        os.environ.pop("GEMINI_MODELO")


def test_todas_as_variaveis_de_modelo_tem_padrao():
    esperadas = {"GROQ_MODELO_TEXTO_GRANDE", "GROQ_MODELO_TEXTO_PEQUENO", "GROQ_MODELO_VISAO", "GEMINI_MODELO",
                 "NVIDIA_MODELO_TEXTO", "NVIDIA_MODELO_VISAO", "ZAI_MODELO_TEXTO", "ZAI_MODELO_VISAO"}
    assert set(ia.PADROES_MODELOS) == esperadas
    assert all(ia.PADROES_MODELOS.values())


def test_provedor_sem_chave_devolve_vazio_sem_chamar():
    os.environ["ZAI_API_KEY"] = ""
    assert ia.chamar_openai_compativel("zai", "glm-4.7-flash", [{"role": "user", "content": "oi"}], chave="") == ""


def test_pensar_desligado_nos_dois_provedores():
    assert ia.PROVEDORES_OPENAI["nvidia"]["sem_pensar"] == {"reasoning_effort": "none"}
    assert ia.PROVEDORES_OPENAI["zai"]["sem_pensar"] == {"thinking": {"type": "disabled"}}


def test_registro_grava_provedor_e_modelo():
    from services.registro_execucao import _modelos_ia
    m = _modelos_ia(
        {}, {"zona_homogenea": {"provider_visao": "nvidia", "modelo_visao": "nvidia/nemotron-x"}},
        {"imovel_alvo": {"analise_qualitativa": {"llm_usada": "nvidia/nvidia/nemotron-x"}}},
        {"scores": {"provider_llm": "NVIDIA", "modelo_llm": "nvidia/nemotron-y"}},
    )
    assert m["agente2_zona_visao"] == "nvidia/nvidia/nemotron-x"
    assert m["agente3"] == {"nvidia/nvidia/nemotron-x": 1}
    assert m["agente4"] == "NVIDIA/nvidia/nemotron-y"
    # Registro antigo, sem o modelo: so o provedor.
    assert _modelos_ia({}, {}, {}, {"scores": {"provider_llm": "Gemini"}})["agente4"] == "Gemini"


# --- Etapa 2: ordem, regra do 429, trava do Z.AI, fotos ----------------------

def _com_env(valores: dict, fn):
    antigos = {k: os.environ.get(k) for k in valores}
    os.environ.update(valores)
    try:
        return fn()
    finally:
        for k, v in antigos.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_ordens_padrao_iguais_ao_que_ja_existia():
    for t in ia.ORDENS:
        os.environ.pop(t, None)
    assert ia.ordem("ORDEM_COMPARAVEIS") == ["groq1", "groq2", "gemini", "nvidia", "zai"]
    assert ia.ordem("ORDEM_ZONA") == ["gemini", "groq1", "nvidia"]
    assert ia.ordem("ORDEM_FOTOS_ALVO") == ["gemini", "groq1", "nvidia"]
    assert ia.ordem("ORDEM_FOTOS_COMPARAVEIS") == ["groq1", "nvidia", "gemini"]
    assert ia.ordem("ORDEM_REGIAO") == ["gemini", "groq1", "nvidia", "zai"]


def test_ordem_do_env_groq_vira_as_duas_chaves_e_ignora_desconhecido():
    r = _com_env({"ORDEM_ZONA": " NVIDIA, groq ;chatgpt  gemini,nvidia"}, lambda: ia.ordem("ORDEM_ZONA"))
    assert r == ["nvidia", "groq1", "groq2", "gemini"], r


def test_ordem_vazia_ou_toda_invalida_volta_ao_padrao():
    r = _com_env({"ORDEM_REGIAO": "foo, bar"}, lambda: ia.ordem("ORDEM_REGIAO"))
    assert r == ia.ordem_padrao("ORDEM_REGIAO")


def test_fotos_por_provedor():
    for k in ia.PADROES_FOTOS:
        os.environ.pop(k, None)
    assert [ia.fotos(p) for p in ("qwen", "gemini", "groq", "groq2", "nvidia", "zai")] == [4, 4, 2, 2, 1, 1]
    assert _com_env({"FOTOS_NVIDIA": "3"}, lambda: ia.fotos("nvidia")) == 3
    assert _com_env({"FOTOS_GROQ": "abc"}, lambda: ia.fotos("groq")) == 2
    assert _com_env({"FOTOS_GEMINI": "0"}, lambda: ia.fotos("gemini")) == 1


GROQ_TPM = ("Error code: 429 - {'error': {'message': 'Rate limit reached for model `openai/gpt-oss-120b` "
            "on tokens per minute (TPM): Limit 8000, Used 7000, Requested 2000. Please try again in 7.5s.', "
            "'type': 'tokens', 'code': 'rate_limit_exceeded'}}")
GROQ_TPD = ("Error code: 429 - {'error': {'message': 'Rate limit reached for model `openai/gpt-oss-120b` "
            "on tokens per day (TPD): Limit 200000, Used 199000. Please try again in 12m3.2s.'}}")
GROQ_TPM_LONGO = GROQ_TPM.replace("7.5s", "1m2.5s")
GEMINI_MIN = ("429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'details': [{'violations': [{'quotaId': "
              "'GenerateRequestsPerMinutePerProjectPerModel-FreeTier'}]}, {'retryDelay': '23s'}]}}")
GEMINI_DIA = GEMINI_MIN.replace("PerMinute", "PerDay").replace("23s", "3s")
ZAI_1305 = "Error code: 429 - {'error': {'code': '1305', 'message': 'O servico esta sobrecarregado'}}"


def test_classificacao_do_429():
    assert ia.analisar_limite(Exception(GROQ_TPM)) == ("minuto", 7.5)
    assert ia.analisar_limite(Exception(GROQ_TPM_LONGO)) == ("minuto", 62.5)
    assert ia.analisar_limite(Exception(GROQ_TPD))[0] == "dia"
    assert ia.analisar_limite(Exception(GEMINI_MIN)) == ("minuto", 23.0)
    assert ia.analisar_limite(Exception(GEMINI_DIA))[0] == "dia"
    assert ia.analisar_limite(Exception(ZAI_1305)) == ("minuto", None)
    assert ia.analisar_limite(Exception("Error code: 500 - internal")) == (None, None)
    assert ia.analisar_limite(TimeoutError("Request timed out")) == (None, None)


class _Falha:
    """chamar() que falha com as mensagens dadas e depois responde 'ok'."""
    def __init__(self, *erros):
        self.erros = list(erros)
        self.chamadas = 0

    def __call__(self):
        self.chamadas += 1
        if self.erros:
            raise Exception(self.erros.pop(0))
        return "ok"


def _sem_dormir(fn):
    esperas = []
    original = ia.time.sleep
    ia.time.sleep = esperas.append
    try:
        return fn(), esperas
    finally:
        ia.time.sleep = original


def _resultado(chamar):
    try:
        return ia.com_regra_429(chamar, "teste")
    except Exception as e:
        return f"erro: {str(e)[:20]}"


def test_429_por_minuto_espera_e_tenta_uma_vez():
    f = _Falha(GROQ_TPM)
    r, esperas = _sem_dormir(lambda: _resultado(f))
    assert r == "ok" and f.chamadas == 2 and esperas == [8.5], (r, esperas)
    f = _Falha(ZAI_1305)                       # sem tempo informado: 10 s
    r, esperas = _sem_dormir(lambda: _resultado(f))
    assert r == "ok" and esperas == [ia.ESPERA_PADRAO_429_S]


def test_429_repetido_nao_tenta_terceira_vez():
    f = _Falha(GROQ_TPM, GROQ_TPM)
    r, esperas = _sem_dormir(lambda: _resultado(f))
    assert r.startswith("erro") and f.chamadas == 2 and len(esperas) == 1


def test_429_do_dia_ou_espera_longa_vai_direto_para_a_proxima():
    for msg in (GROQ_TPD, GEMINI_DIA, GROQ_TPM_LONGO, "Request timed out.", "Error code: 401 - invalid key"):
        f = _Falha(msg)
        r, esperas = _sem_dormir(lambda: _resultado(f))
        assert r.startswith("erro") and f.chamadas == 1 and esperas == [], (msg[:40], esperas)


def test_trava_do_zai_ocupada_desiste():
    original = ia.ZAI_ESPERA_TRAVA_S
    ia.ZAI_ESPERA_TRAVA_S = 0.05
    ia._trava_zai.acquire()
    try:
        ia.chamar_openai_compativel("zai", "glm-4.7-flash", [{"role": "user", "content": "oi"}], chave="x")
        assert False, "deveria desistir"
    except TimeoutError:
        pass
    finally:
        ia._trava_zai.release()
        ia.ZAI_ESPERA_TRAVA_S = original


def test_agente3_segue_a_ordem_e_para_no_primeiro_conclusivo():
    from agents import text_analyzer as ta
    chamados = []
    respostas = {"gemini": {}, "groq1": {"estado_conservacao": "bom", "padrao_acabamento": "medio",
                                         "confianca_extracao": "media"}}
    original = ta._tentar_provedor
    ta._tentar_provedor = lambda nome, imovel, is_alvo=False: (chamados.append(nome), respostas.get(nome, {}))[1]
    try:
        r = _com_env({"ORDEM_FOTOS_ALVO": "gemini,groq1,nvidia"},
                     lambda: ta._analisar_imovel_vision({"images": []}, is_alvo=True))
        assert chamados == ["gemini", "groq1"] and r["estado_conservacao"] == "bom", chamados
        chamados.clear()
        _com_env({"ORDEM_FOTOS_COMPARAVEIS": "nvidia,gemini"},
                 lambda: ta._analisar_imovel_vision({"images": []}, is_alvo=False))
        assert chamados == ["nvidia", "gemini"], chamados
    finally:
        ta._tentar_provedor = original


NVIDIA_503 = "Error code: 503 - {'error': {'message': 'content safety screening is temporarily unavailable'}}"
GEMINI_500 = "500 INTERNAL. {'error': {'code': 500, 'message': 'An internal error has occurred.'}}"


def test_falha_do_servidor_espera_3s_e_tenta_uma_vez():
    assert ia.eh_falha_do_servidor(Exception(NVIDIA_503)) and ia.eh_falha_do_servidor(Exception(GEMINI_500))
    assert ia.eh_falha_do_servidor(Exception("Error code: 502 - Bad Gateway"))
    assert not ia.eh_falha_do_servidor(Exception(GROQ_TPM))                      # 429
    assert not ia.eh_falha_do_servidor(Exception("Limit 500, Used 499"))           # 500 no meio do texto
    for msg in (NVIDIA_503, GEMINI_500):
        f = _Falha(msg)
        r, esperas = _sem_dormir(lambda: _resultado(f))
        assert r == "ok" and f.chamadas == 2 and esperas == [ia.ESPERA_FALHA_SERVIDOR_S], (msg[:20], esperas)
    f = _Falha(NVIDIA_503, NVIDIA_503)                     # falhou de novo: proxima IA, sem 3a tentativa
    r, esperas = _sem_dormir(lambda: _resultado(f))
    assert r.startswith("erro") and f.chamadas == 2


def test_gemini_do_agente3_repete_erro_500_no_alvo_e_nos_comparaveis():
    import types as tipos
    from agents import text_analyzer as ta
    from google import genai

    resposta_ok = tipos.SimpleNamespace(text='{"estado_conservacao": "bom", "padrao_acabamento": "medio"}')
    chamadas, erros = [], [GEMINI_500]

    class Modelos:
        def generate_content(self, **kw):
            chamadas.append(1)
            if erros:
                raise Exception(erros.pop(0))
            return resposta_ok

    original = genai.Client
    genai.Client = lambda api_key=None: tipos.SimpleNamespace(models=Modelos())
    try:
        (r, esperas) = _sem_dormir(lambda: _com_env({"GOOGLE_API_KEY": "x"},
                                                      lambda: ta._tentar_gemini({"images": []})))
        assert r and len(chamadas) == 2 and esperas == [3.0], (chamadas, esperas)
    finally:
        genai.Client = original


def test_agente2_monta_as_tentativas_na_ordem_e_pula_sem_chave():
    from agents import comparables as c
    env = {"ORDEM_COMPARAVEIS": "zai,groq,gemini", "ZAI_API_KEY": "z", "GROQ_API_KEY": "g1",
           "GROQ_API_KEY_2": "", "GOOGLE_API_KEY": "", "GOOGLE_API_KEY_2": ""}
    t = _com_env(env, lambda: c._tentativas_clustering("prompt"))
    assert [(p, conta) for p, _, conta, _ in t] == [("zai", "ZAI_API_KEY"), ("groq", "GROQ_API_KEY")], t


if __name__ == "__main__":
    testes = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    falhas = 0
    for nome, fn in testes:
        try:
            fn()
            print(f"OK    {nome}")
        except AssertionError as e:
            falhas += 1
            print(f"FALHA {nome}: {e}")
        except Exception as e:
            falhas += 1
            print(f"ERRO  {nome}: {type(e).__name__}: {e}")
    print(f"\n{len(testes) - falhas}/{len(testes)} testes passaram")
    sys.exit(1 if falhas else 0)
