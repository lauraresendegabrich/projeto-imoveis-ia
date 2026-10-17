"""
Testes do pedido de comparabilidade enviado a IA do Agente 2. Sem rede.

    .venv/Scripts/python.exe -m tests.test_prompt_ag2
"""
import sys

sys.path.insert(0, ".")

from agents.comparables import _montar_prompt_clustering

ALVO = {"propertyType": "Casas", "area": 116, "bedrooms": 2, "bathrooms": 1,
        "neighborhood": "Jardim Itajubá", "street": "Rua Tenente Joaquim Rabelo de Matos"}
CANDIDATO = {"propertyType": "Casas", "area": 100, "bedrooms": 3, "bathrooms": 1,
             "neighborhood": "Nancilândia", "street": "Rua das Flores, 10"}


def test_prompt_sem_bairro_e_rua():
    prompt = _montar_prompt_clustering(ALVO, [CANDIDATO])
    for termo in ("Bairro=", "Rua=", "Jardim Itajubá", "Nancilândia", "Rua das Flores"):
        assert termo not in prompt, termo


def test_prompt_diz_que_localizacao_nao_e_criterio():
    prompt = _montar_prompt_clustering(ALVO, [CANDIDATO])
    assert "A localizacao NAO e criterio aqui" in prompt
    assert "Julgue apenas tipo/uso, area, quartos e padrao" in prompt
    assert "contexto de localizacao sao prioritarios" not in prompt


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
    print(f"\n{len(testes) - falhas}/{len(testes)} testes passaram")
    sys.exit(1 if falhas else 0)
