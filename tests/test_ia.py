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
