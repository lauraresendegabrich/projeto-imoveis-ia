"""
Testes dos alertas automaticos (services/alertas.py). Sem rede.

    .venv/Scripts/python.exe -m tests.test_alertas
"""
import sys

sys.path.insert(0, ".")

from services.alertas import calcular_alertas


def execucao(**campos):
    base = {
        "status_agente5": "ok", "qtd_comparaveis_construcao": 10, "qtd_terrenos": 0,
        "usados_por_fallback": 0, "valor_mercado": 1_000_000.0, "valor_avaliacao": None,
        "sobra": 100_000.0, "valor_minimo": 500_000.0,
    }
    base.update(campos)
    return base


def ag5(m2=(5000, 5200, 4800, 5100), terreno_aplicado=False, usados=None):
    return {
        "auditoria": {"m2_construcao_min_terreno": list(m2)},
        "calculo_terreno": {"aplicado": terreno_aplicado},
        "comparaveis_usados": usados or {"construcao": [], "terreno": []},
    }


def codigos(alertas):
    return [a["codigo"] for a in alertas]


def test_avaliacao_tranquila_sem_alertas():
    assert calcular_alertas(execucao(), ag5()) == []


def test_poucos_comparaveis():
    assert codigos(calcular_alertas(execucao(qtd_comparaveis_construcao=3), ag5())) == ["poucos_comparaveis"]
    assert calcular_alertas(execucao(qtd_comparaveis_construcao=5), ag5()) == []


def test_poucos_comparaveis_so_com_estimativa():
    # Com menos de 3 o status ja e amostra_insuficiente; nao repete o aviso.
    e = execucao(status_agente5="amostra_insuficiente", qtd_comparaveis_construcao=1, sobra=None)
    assert calcular_alertas(e, ag5()) == []


def test_poucos_terrenos_so_quando_separa_terreno():
    e = execucao(qtd_terrenos=2)
    assert calcular_alertas(e, ag5(terreno_aplicado=False)) == []
    assert codigos(calcular_alertas(e, ag5(terreno_aplicado=True))) == ["poucos_terrenos"]


def test_fora_da_zona():
    a = calcular_alertas(execucao(usados_por_fallback=2), ag5())
    assert codigos(a) == ["fora_da_zona"] and a[0]["valor"] == 2


def test_precos_espalhados():
    a = calcular_alertas(execucao(), ag5(m2=(2000, 9000, 3000, 10000)))
    assert codigos(a) == ["precos_espalhados"] and a[0]["valor"] > 0.4


def test_diferente_da_avaliacao_caixa():
    assert codigos(calcular_alertas(execucao(valor_avaliacao=600_000.0), ag5())) == ["diferente_avaliacao_caixa"]
    assert calcular_alertas(execucao(valor_avaliacao=900_000.0), ag5()) == []


def test_decisao_apertada_sobra_e_falta():
    assert codigos(calcular_alertas(execucao(sobra=10_000.0), ag5())) == ["decisao_apertada"]
    a = calcular_alertas(execucao(sobra=-10_000.0), ag5())
    assert codigos(a) == ["decisao_apertada"] and "Falta" in a[0]["mensagem"]


def test_sem_leilao_nao_avalia_decisao():
    assert calcular_alertas(execucao(sobra=None, valor_minimo=None), ag5()) == []


def test_possivel_alvo_no_calculo():
    usados = {"construcao": [{"possivel_anuncio_do_alvo": True}, {}], "terreno": []}
    assert codigos(calcular_alertas(execucao(), ag5(usados=usados))) == ["possivel_alvo_no_calculo"]


def test_falha_de_agente():
    assert codigos(calcular_alertas(execucao(), ag5(), falhas=["agente3: Timeout"])) == ["falha_de_agente"]


def test_varios_alertas_juntos():
    e = execucao(qtd_comparaveis_construcao=3, usados_por_fallback=1, sobra=5_000.0)
    assert codigos(calcular_alertas(e, ag5())) == ["poucos_comparaveis", "fora_da_zona", "decisao_apertada"]


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
