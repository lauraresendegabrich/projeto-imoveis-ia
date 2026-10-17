"""
Testes do calculo do Agente 5 (agents/price_liquidity.py) com exemplos reais:
a planilha do professor, um apartamento de BH e uma casa de Curitiba. Sem rede.

    .venv/Scripts/python.exe -m tests.test_calculo_ag5
"""
import sys

sys.path.insert(0, ".")

from agents.price_liquidity import executar_agente5


def apto(preco, area):
    return {"propertyType": "apartamento", "price": preco, "area": area}


def casa(preco, area, area_terreno):
    return {"propertyType": "casa", "price": preco, "area": area, "area_terreno": area_terreno}


def terreno(preco, area):
    return {"propertyType": "terreno", "price": preco, "area": area}


def calcular(alvo, comparaveis, terrenos=()):
    return executar_agente5(alvo, list(terrenos), comparaveis, {}, {})


def valor_medio(r):
    return r["avaliacao_planilha"]["valor_medio_imovel"]


def test_planilha_do_professor_5_aptos():
    # Ficha da Construcao, linhas 38-42; area do imovel avaliado (E7) = 250 m2.
    # Com 5 aptos, contar uma ou duas vezes da o mesmo resultado (C64 e C65).
    comps = [apto(350000, 242), apto(430000, 232), apto(680000, 169), apto(400000, 300), apto(520000, 140)]
    r = calcular({"propertyType": "apartamento", "area": 250}, comps)
    assert valor_medio(r) == 584501.25, valor_medio(r)
    assert r["avaliacao_planilha"]["valor_minimo_imovel"] == 333333.33
    assert r["avaliacao_planilha"]["valor_liquidez"] == 526051.12


def test_bh_floresta_6_aptos_cada_um_conta_uma_vez():
    # Antes (lista dobrada): R$ 5.691,69/m2 -> R$ 620.394,07. Agora: R$ 5.721,10/m2.
    comps = [apto(300000, 93), apto(499900, 120), apto(630000, 110),
             apto(648000, 117), apto(650000, 77), apto(790000, 106)]
    r = calcular({"propertyType": "apartamento", "area": 109}, comps)
    assert r["calculo_construcao"]["valor_m2_referencia"] == 5721.1, r["calculo_construcao"]
    assert valor_medio(r) == 623599.84, valor_medio(r)
    assert r["valor_m2_zona_homogenea"]["construcao"]["combinados"]["quantidade_total"] == 6
    assert r["status_avaliacao"] == "ok"


def test_casa_curitiba_continua_com_as_duas_series():
    # Casa: as duas series sao diferentes e continuam juntas (valor igual ao do banco).
    comps = [casa(690000, 146, 105), casa(699900, 126, 126), casa(799000, 136, 136), casa(899000, 173, 173)]
    terrenos = [terreno(515000, 540), terreno(789000, 600), terreno(836000, 418), terreno(1950000, 1824)]
    r = calcular({"propertyType": "casa", "area": 171.19, "area_terreno": 146.76}, comps, terrenos)
    assert r["calculo_construcao"]["valor_m2_referencia"] == 4311.69, r["calculo_construcao"]
    assert valor_medio(r) == 913061.64, valor_medio(r)
    assert r["valor_m2_zona_homogenea"]["construcao"]["combinados"]["quantidade_total"] == 8


def test_minimo_de_5_comparaveis():
    alvo = {"propertyType": "apartamento", "area": 100}
    quatro = [apto(500000 + i * 10000, 100) for i in range(4)]
    assert calcular(alvo, quatro)["status_avaliacao"] == "amostra_insuficiente"
    assert calcular(alvo, quatro + [apto(450000, 100)])["status_avaliacao"] == "ok"


CASAS_5 = [casa(600000 + i * 50000, 150, 200) for i in range(5)]
ALVO_CASA = {"propertyType": "casa", "area": 150, "area_terreno": 200}


def test_casa_sem_nenhum_terreno_usa_preco_m2_total():
    r = calcular(ALVO_CASA, CASAS_5, [])
    assert r["status_avaliacao"] == "ok", r["status_avaliacao"]
    assert r["calculo_terreno"]["aplicado"] is False


def test_casa_com_1_a_4_terrenos_fica_sem_estimativa():
    for n in (1, 4):
        terrenos = [terreno(200000 + i * 10000, 250) for i in range(n)]
        r = calcular(ALVO_CASA, CASAS_5, terrenos)
        assert r["status_avaliacao"] == "amostra_insuficiente", (n, r["status_avaliacao"])


def test_casa_com_5_terrenos_separa_terreno():
    terrenos = [terreno(200000 + i * 10000, 250) for i in range(5)]
    r = calcular(ALVO_CASA, CASAS_5, terrenos)
    assert r["status_avaliacao"] == "ok" and r["calculo_terreno"]["aplicado"] is True, r["status_avaliacao"]


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
