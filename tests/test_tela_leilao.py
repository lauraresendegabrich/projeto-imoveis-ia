"""
Tela do leilao (passo 3): campos por modalidade fora/dentro do st.form, leitura da
pagina da CAIXA preenchendo o formulario, cartao do leilao no topo e cronometro.
Simulador do Streamlit. Sem rede.

    .venv/Scripts/python.exe -m tests.test_tela_leilao
"""
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, ".")
logging.disable(logging.CRITICAL)

from streamlit.testing.v1 import AppTest

from app.cronometro import html_cronometro, rotulo_prazo
from services.caixa_pagina import texto_da_pagina
from services.leilao import agora_brasilia, avaliar_imovel_leilao, ler_formulario_leilao, linhas_laudo
from tests.test_tela_amostra_concentrada import _laudo
from tests.test_tela_resultado import resultado_sem_valor

PAGINAS = Path(__file__).parent / "paginas_caixa"


def _app():
    return AppTest.from_file("app/interface.py", default_timeout=60).run()


def _rotulos(at):
    return [w.label for w in at.sidebar.text_input]


def _colar_pagina(at, nome):
    texto = texto_da_pagina((PAGINAS / f"{nome}.html").read_text(encoding="utf-8"))
    at.sidebar.text_area(key="caixa_texto").input(texto)
    next(b for b in at.sidebar.button if b.label == "Ler dados").click().run()
    assert not at.exception, [e.value for e in at.exception]
    return at


# ---------------------------------------------------------------- campos por modalidade
def test_sem_modalidade_nao_ha_campos_de_leilao():
    rotulos = _rotulos(_app())
    assert not any("Valor mínimo" in r or "Edital" in r for r in rotulos), rotulos


def test_leilao_sfi_tem_1o_e_2o_leilao_e_edital():
    at = _app()
    at.sidebar.selectbox(key="f_modalidade").select("Leilão SFI").run()
    rotulos = _rotulos(at)
    for esperado in ("Valor mínimo do 1º leilão (R$)", "Data e hora do 1º leilão", "Valor mínimo do 2º leilão (R$)",
                     "Data e hora do 2º leilão", "Edital", "Número do item", "Leiloeiro(a)", "Matrícula"):
        assert esperado in rotulos, (esperado, rotulos)
    assert "Valor mínimo de venda (R$)" not in rotulos


def test_compra_direta_so_valor_minimo_sem_data():
    at = _app()
    at.sidebar.selectbox(key="f_modalidade").select("Compra Direta").run()
    rotulos = _rotulos(at)
    assert "Valor mínimo de venda (R$)" in rotulos
    assert not any(r.startswith("Data") for r in rotulos) and "Edital" not in rotulos, rotulos
    assert any("sem data de encerramento" in c.value for c in at.sidebar.caption)


def test_venda_online_tem_encerramento_sem_edital():
    at = _app()
    at.sidebar.selectbox(key="f_modalidade").select("Venda Online").run()
    rotulos = _rotulos(at)
    assert "Data e hora do encerramento" in rotulos and "Edital" not in rotulos


def test_data_invalida_aparece_como_erro():
    at = _app()
    at.sidebar.selectbox(key="f_modalidade").select("Leilão SFI").run()
    at.sidebar.text_input(key="f_data_1_leilao").input("30/13/2026")
    next(b for b in at.sidebar.button if "Avaliar" in b.label).click().run()
    assert any("Data do 1º leilão inválida" in w.value for w in at.warning), [w.value for w in at.warning]


# ---------------------------------------------------------------- pagina da CAIXA
def test_ler_pagina_sfi_preenche_o_formulario():
    at = _colar_pagina(_app(), "leilao_sfi")
    ss = at.session_state
    assert (ss["f_rua"], ss["f_numero"], ss["f_bairro"], ss["f_cidade"], ss["f_uf"]) == (
        "AVENIDA JOSE LEITE", "911", "CAJI", "LAURO DE FREITAS", "BA")
    assert (ss["f_tipo"], ss["f_area"], ss["f_quartos"], ss["f_vagas"]) == ("Apartamento", "54,68", 2, 1)
    assert ss["f_modalidade"] == "Leilão SFI"
    assert (ss["f_valor_minimo_1"], ss["f_data_1_leilao"]) == ("224.000,00", "30/11/2026 10:00")
    assert (ss["f_valor_minimo_2"], ss["f_data_2_leilao"]) == ("296.523,50", "04/12/2026 10:00")
    assert ss["f_edital"] == "0052/0226 - CPA/RE" and ss["f_leiloeiro"] == "JONAS GABRIEL ANTUNES MOREIRA"
    # Os campos do SFI aparecem no formulario ja preenchidos (editaveis).
    assert at.sidebar.text_input(key="f_valor_minimo_2").value == "296.523,50"
    assert any(s.value.startswith("Dados lidos da CAIXA — confira antes de avaliar") for s in at.sidebar.success)
    assert any("Área total, Área do terreno" in w.value for w in at.sidebar.warning)
    # O CEP da pagina nao sobrescreve o endereco lido da CAIXA.
    assert ss["f_cep"] == "42700-000" and ss["_cep_aplicado"] == "42700000"


def test_ler_outra_pagina_nao_mistura_dados_do_imovel_anterior():
    at = _colar_pagina(_app(), "leilao_sfi")
    _colar_pagina(at, "compra_direta")
    ss = at.session_state
    assert ss["f_modalidade"] == "Compra Direta" and ss["f_valor_minimo"] == "5.074.300,00"
    assert ss["f_numero"] == "" and ss["f_quartos"] == 0 and ss["f_edital"] == ""   # nada do SFI ficou
    assert ss["f_tipo"] == "Casa"   # Gleba nao e avaliada: o tipo volta ao inicial, com aviso
    assert any("Gleba" in w.value for w in at.sidebar.warning)


def test_pagina_errada_mostra_erro_e_nao_preenche():
    at = _app()
    at.sidebar.text_area(key="caixa_texto").input("Radware Bot Manager CAPTCHA")
    next(b for b in at.sidebar.button if b.label == "Ler dados").click().run()
    assert any("Não parece a página de um imóvel da CAIXA" in e.value for e in at.sidebar.error)
    assert at.session_state["f_rua"] == ""


# ---------------------------------------------------------------- cartao do leilao
AG5_OK = {"status_avaliacao": "ok", "avaliacao_confiavel": True, "avaliacao_planilha": {"valor_liquidez": 450000},
          "comparaveis_usados": {"construcao": [], "terreno": []}}
SFI = {"modalidade": "Leilão SFI", "data_1_leilao": datetime(2026, 11, 30, 10), "valor_minimo_1": 224000.00,
       "data_2_leilao": datetime(2026, 12, 4, 10), "valor_minimo_2": 296523.50, "gravame": True,
       "edital": "0052/0226 - CPA/RE", "numero_item": "25", "numero_imovel": "855552271653-1"}


def _cartao(leilao):
    r = resultado_sem_valor()
    r["leilao"] = leilao
    at = AppTest.from_file("app/interface.py", default_timeout=60)
    at.session_state["resultado"] = r
    at.session_state["imovel_alvo_dados"] = {"area": 104, "tipo": "house"}
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def test_cartao_sfi_no_2o_leilao():
    at = _cartao(avaliar_imovel_leilao(AG5_OK, SFI, agora=datetime(2026, 12, 1, 9)))
    markdown = [m.value for m in at.markdown]
    assert "**CAIXA · Leilão SFI · 2º leilão**" in markdown
    assert any("gravame/penhora" in e.value for e in at.error)
    captions = [c.value for c in at.caption]
    assert any(c.startswith("No 1º leilão (mínimo R\\$ 224.000), o ROI seria") for c in captions), captions
    assert any("Comissão do leiloeiro: 5%" in c for c in captions)
    assert any("antigo dono pode recomprar" in c for c in captions)
    assert any("Edital: 0052/0226 - CPA/RE" in c for c in captions)
    assert any(m.label == "Valor mínimo (2º leilão)" for m in at.metric)
    assert at.get("iframe"), "cronometro"


def test_cartao_vem_antes_do_valor_estimado():
    at = _cartao(avaliar_imovel_leilao(AG5_OK, SFI, agora=datetime(2026, 12, 1, 9)))
    textos = [getattr(e, "value", "") for e in at.main]
    assert textos.index("#### 🔨 Avaliação de leilão") < next(
        i for i, t in enumerate(textos) if isinstance(t, str) and "Como chegamos" in t)


def test_cartao_compra_direta_sem_cronometro_e_corretagem_da_caixa():
    leilao = avaliar_imovel_leilao(AG5_OK, {"modalidade": "Compra Direta", "valor_minimo": 200000})
    at = _cartao(leilao)
    assert "**CAIXA · Compra Direta**" in [m.value for m in at.markdown]
    assert not at.get("iframe")
    assert any(c.value == "Corretagem por conta da CAIXA." for c in at.caption)


def test_laudo_traz_modalidade_prazo_e_gravame():
    leilao = avaliar_imovel_leilao(AG5_OK, SFI, agora=datetime(2026, 12, 1, 9))
    laudo = _laudo(_cartao(leilao))
    for trecho in ("CAIXA · Leilão SFI · 2º leilão", "Encerra em 3 dias e 1 h (04/12/2026 10:00)",
                   "Atenção: Imóvel com gravame/penhora", "o ROI seria", "Comissão do leiloeiro",
                   "Número do imóvel: 855552271653-1", "Edital: 0052/0226 - CPA/RE", "Item: 25"):
        assert trecho in laudo, trecho


def test_linhas_laudo_compra_direta():
    linhas = linhas_laudo(avaliar_imovel_leilao(AG5_OK, {"modalidade": "Compra Direta", "valor_minimo": 200000}),
                          lambda v: f"R$ {v:,.0f}")
    assert "CAIXA · Compra Direta" in linhas and "Corretagem por conta da CAIXA." in linhas
    assert not any(l.startswith("Encerra") for l in linhas)


# ---------------------------------------------------------------- leitura do formulario
def test_formulario_sfi_ignora_campos_de_outras_modalidades():
    textos = {"valor_minimo": "999.999,00", "valor_minimo_1": "224.000,00", "data_1_leilao": "30/11/2026 - 10h00",
              "valor_minimo_2": "296.523,50", "data_2_leilao": "04/12/2026", "data_encerramento": "01/01/2027",
              "edital": " 0052/0226 ", "gravame": False, "gravame_texto": ""}
    dados, erros = ler_formulario_leilao(textos, "CAIXA", "Leilão SFI")
    assert erros == []
    assert "valor_minimo" not in dados and "data_encerramento" not in dados
    assert dados["valor_minimo_2"] == 296523.50 and dados["data_1_leilao"] == datetime(2026, 11, 30, 10)
    assert str(dados["data_2_leilao"]) == "2026-12-04"   # so a data: vale ate o fim do dia
    assert dados["edital"] == "0052/0226" and dados["gravame"] is False


def test_formulario_compra_direta_e_gravame_pelo_texto():
    dados, erros = ler_formulario_leilao({"valor_minimo": "200.000", "data_1_leilao": "x", "edital": "E",
                                          "gravame_texto": "Imóvel com penhora"}, "CAIXA", "Compra Direta")
    assert erros == [] and dados["valor_minimo"] == 200000 and "edital" not in dados
    assert dados["gravame"] is True


def test_formulario_erros_e_sem_modalidade():
    dados, erros = ler_formulario_leilao({"valor_minimo": "abc", "data_encerramento": "amanhã"}, "CAIXA", "Venda Online")
    assert len(erros) == 2 and erros[0].startswith('Valor mínimo de venda inválido: "abc"')
    assert ler_formulario_leilao({"valor_minimo": "100"}, "CAIXA", "") == (None, [])


# ---------------------------------------------------------------- cronometro
def test_cronometro_conta_no_navegador_ate_a_data():
    html = html_cronometro(datetime(2026, 11, 30, 10), "1º leilão", agora=datetime(2026, 11, 1))
    assert 'new Date("2026-11-30T10:00:00-03:00")' in html   # horario de Brasilia
    assert "setInterval" in html and "1º leilão em 30/11/2026 10:00" in html
    assert "Encerrado em 30/11/2026 10:00" in html             # troca ao chegar a zero


def test_cronometro_encerrado_e_texto_fixo():
    html = html_cronometro(datetime(2026, 10, 26, 18), "Encerramento da venda", agora=datetime(2026, 10, 27))
    assert "Encerrado em 26/10/2026 18:00" in html and "<script" not in html


def test_rotulo_do_cronometro():
    assert rotulo_prazo({"etapa": 2, "modalidade": "Leilão SFI"}) == "2º leilão"
    assert rotulo_prazo({"modalidade": "Licitação Aberta"}) == "Licitação"
    assert rotulo_prazo({"modalidade": "Venda Online"}) == "Encerramento da venda"


def test_agora_e_horario_de_brasilia():
    esperado = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=3)
    assert abs((agora_brasilia() - esperado).total_seconds()) < 5


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
