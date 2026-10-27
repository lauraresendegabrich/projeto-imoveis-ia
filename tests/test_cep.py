"""
Testes da busca de CEP (services/cep.py). Sem rede: os servicos sao simulados.

    .venv/Scripts/python.exe -m tests.test_cep
"""
import sys

sys.path.insert(0, ".")

import services.cep as cep

CURITIBA = {"rua": "Rua Raul de Oliveira", "bairro": "Cajuru", "cidade": "Curitiba", "estado": "PR"}


def _com_servicos(*funcoes):
    cep.SERVICOS_CEP = [(f"s{i}", f) for i, f in enumerate(funcoes)]


def _falha(_cep):
    raise TimeoutError("sem resposta")


def test_limpar_cep():
    assert cep.limpar_cep("82950-190") == "82950190"
    assert cep.limpar_cep(" 82.950-190 ") == "82950190"
    for invalido in ("", None, "8295019", "829501900", "abc"):
        assert cep.limpar_cep(invalido) is None, invalido


def test_viacep_bloqueado_usa_o_proximo():
    _com_servicos(_falha, lambda c: CURITIBA)
    assert cep.buscar_cep("82950190") == (CURITIBA, "ok")


def test_todos_fora_do_ar():
    _com_servicos(_falha, _falha, _falha)
    assert cep.buscar_cep("82950190") == (None, "indisponivel")


def test_cep_inexistente():
    _com_servicos(lambda c: None, _falha, lambda c: None)
    assert cep.buscar_cep("00000000") == (None, "nao_encontrado")



def test_texto_do_endereco_sem_partes_vazias():
    from services.cep import texto_endereco_cep
    assert texto_endereco_cep({"rua": "Rua X", "bairro": "Centro", "cidade": "Curitiba", "estado": "PR"}) == (
        "Rua X, Centro, Curitiba/PR")
    # CEP geral da cidade (69980-000, Cruzeiro do Sul): antes saia ", , Cruzeiro do Sul/AC".
    assert texto_endereco_cep({"rua": "", "bairro": "", "cidade": "Cruzeiro do Sul", "estado": "AC"}) == (
        "Cruzeiro do Sul/AC (CEP geral da cidade, sem rua e bairro)")
    assert texto_endereco_cep({"rua": "", "bairro": "Centro", "cidade": "Rio Branco", "estado": "AC"}) == (
        "Centro, Rio Branco/AC")


def test_tela_com_cep_geral_nao_mostra_virgulas_soltas():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file("app/interface.py", default_timeout=60)
    # CEP ja consultado (cache da sessao): o teste nao usa a rede.
    at.session_state["_cache_cep"] = {"69980000": {"rua": "", "bairro": "", "cidade": "Cruzeiro do Sul",
                                                   "estado": "AC"}}
    at.run()
    at.sidebar.text_input(key="f_cep").input("69980-000").run()
    textos = [s.value for s in at.sidebar.success]
    assert "Cruzeiro do Sul/AC (CEP geral da cidade, sem rua e bairro)" in textos, textos
    assert at.session_state["f_cidade"] == "Cruzeiro do Sul" and at.session_state["f_rua"] == ""

if __name__ == "__main__":
    originais = list(cep.SERVICOS_CEP)
    testes = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    falhas = 0
    for nome, fn in testes:
        try:
            fn()
            print(f"OK    {nome}")
        except AssertionError as e:
            falhas += 1
            print(f"FALHA {nome}: {e}")
        finally:
            cep.SERVICOS_CEP = list(originais)
    print(f"\n{len(testes) - falhas}/{len(testes)} testes passaram")
    sys.exit(1 if falhas else 0)
