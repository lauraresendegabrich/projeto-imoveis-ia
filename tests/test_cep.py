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
