"""
Testes da calculadora de simulacao (app/calculadora.py) e dos parametros opcionais da
conta (services/leilao.py). Sem rede.

    .venv/Scripts/python.exe -m tests.test_calculadora
"""
import sys

sys.path.insert(0, ".")

from streamlit.testing.v1 import AppTest

from app.calculadora import _INICIAIS, parametros_detalhados, sugestao_da_avaliacao
from services.leilao import (
    CUSTOS_ANTES_DA_VENDA, conta_investimento, lance_para_roi, venda_para_empatar,
)


def perto(a, b, tol=0.01):
    return abs(a - b) <= tol


def test_padroes_dao_a_conta_do_professor():
    # Campina da Barra, 2o leilao: R$ 207 mil e liquidez de 90% de R$ 494.203.
    padrao = conta_investimento(207000, 444783.05)
    explicito = conta_investimento(207000, 444783.05, custos_pct=0.33, corretagem_pct=0.05, ir_pct=0.15,
                                   custos_fixos=0)
    assert padrao == explicito
    assert round(padrao["roi"] * 100, 1) == 44.2


def test_custos_em_reais_somam_aos_percentuais():
    c = conta_investimento(200000, 400000, custos_pct=0.10, custos_fixos=30000)
    assert perto(c["custos_antes_da_venda"], 200000 * 1.10 + 30000)


def test_lance_para_roi_com_custos_em_reais_desfaz_a_conta():
    p = {"custos_pct": 0.095, "corretagem_pct": 0.05, "ir_pct": 0.15, "custos_fixos": 40000}
    lance = lance_para_roi(400000, 0.30, **p)
    assert perto(conta_investimento(lance, 400000, **p)["roi"], 0.30, 1e-9)
    # Custos em R$ maiores que o permitido: nenhum lance da o ROI.
    assert lance_para_roi(100000, 0.30, custos_fixos=500000) == 0.0


def test_venda_para_empatar_da_roi_zero():
    for p in ({}, {"custos_pct": 0.095, "custos_fixos": 25000}, {"corretagem_pct": 0.06, "ir_pct": 0.20}):
        venda = venda_para_empatar(207000, **p)
        assert perto(conta_investimento(207000, venda, **p)["roi"], 0.0, 1e-9), p


def test_detalhado_padrao_soma_33():
    pct = {k: _INICIAIS[k] / 100 for k in ("calc_comissao", "calc_itbi", "calc_registro", "calc_reserva")}
    custos_pct, fixos = parametros_detalhados(pct, {"a": 0.0, "b": 0.0})
    assert perto(custos_pct, CUSTOS_ANTES_DA_VENDA, 1e-9) and fixos == 0


def test_sugestao_so_com_estimativa_confiavel():
    leilao = {"lance_maximo": 150000, "liquidez": 400000, "valor_minimo": 207000, "etapa": 2,
              "modalidade": "Leilão SFI"}
    s = sugestao_da_avaliacao(leilao, "abc")
    assert s["arrematacao"] == 207000 and s["venda"] == 400000 and s["id"] == "abc:2"
    assert sugestao_da_avaliacao(dict(leilao, lance_maximo=None), "abc") is None   # Sem estimativa
    assert sugestao_da_avaliacao(None, "abc") is None


def _pagina():
    import streamlit as st
    from app.calculadora import mostrar_calculadora, pedir_simulacao
    if st.session_state.get("teste_sugestao"):
        pedir_simulacao(st.session_state["teste_sugestao"])
    mostrar_calculadora()


def test_tela_preenchida_mostra_o_mesmo_roi():
    at = AppTest.from_function(_pagina, default_timeout=30)
    at.session_state["teste_sugestao"] = {"id": "x", "arrematacao": 207000, "venda": 444783.05,
                                          "modalidade": "Leilão SFI", "rotulo": "teste"}
    at.run()
    assert not at.exception
    assert at.number_input(key="calc_arrematacao").value == 207000
    assert any(m.value == "44,25%" for m in at.metric), [m.value for m in at.metric]
    # Mudar a venda muda o ROI; a sugestao nao volta a sobrescrever.
    at.number_input(key="calc_venda").set_value(288000).run()
    assert at.number_input(key="calc_venda").value == 288000
    assert not any(m.value == "44,25%" for m in at.metric)


def test_tela_detalhada_sem_leiloeiro_mantem_33():
    at = AppTest.from_function(_pagina, default_timeout=30)
    at.session_state["teste_sugestao"] = {"id": "y", "arrematacao": 100000, "venda": 300000,
                                          "modalidade": "Venda Online", "rotulo": "teste"}
    at.run()
    roi_simples = [m.value for m in at.metric]
    at.radio(key="calc_modo").set_value("Detalhado").run()
    assert not at.exception
    assert at.number_input(key="calc_comissao").value == 0.0
    assert [m.value for m in at.metric] == roi_simples   # padroes do detalhado = 33%
    at.number_input(key="calc_reforma").set_value(20000).run()
    assert [m.value for m in at.metric] != roi_simples


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
