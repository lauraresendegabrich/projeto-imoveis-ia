"""
Tela de resultado: tela limpa ao avaliar de novo, contagem da zona com o anuncio do
proprio imovel, motivo exato quando nao ha valor. Simulador do Streamlit. Sem rede.

    .venv/Scripts/python.exe -m tests.test_tela_resultado
"""
import logging
import sys

sys.path.insert(0, ".")
logging.disable(logging.CRITICAL)

from streamlit.testing.v1 import AppTest

from agents.price_liquidity import executar_agente5
from services.textos_tela import motivo_sem_valor, texto_comparaveis_na_zona
from tests.test_tela_amostra_concentrada import _laudo


def casa(i, **extra):
    return {"url": f"https://x/{i}", "propertyType": "Casas", "price": 500_000 + i * 10_000, "area": 100 + i,
            "street": f"Rua {i}", "neighborhood": "Centro", "cluster": "A", **extra}


def usado(c):
    return {"url": c["url"], "preco": c["price"], "area": c["area"], "rua": c["street"], "bairro": "Centro",
            "status_zona": "confirmado"}


ALVO_NA_ZONA = casa(0, eh_anuncio_do_alvo=True)
NA_ZONA = [ALVO_NA_ZONA] + [casa(i) for i in range(1, 5)]


def resultado_sem_valor(**extra_zona):
    ag5 = {"status_avaliacao": "amostra_insuficiente", "avaliacao_confiavel": False,
           "comparaveis_usados": {"construcao": [usado(c) for c in NA_ZONA[1:]], "terreno": []},
           "avaliacao_planilha": {"valor_medio_imovel": 480000, "valor_liquidez": 432000},
           "liquidez_experimental": {"tempo_estimado": "90 a 150 dias"},
           "avisos": ["Amostra insuficiente para uma estimativa confiável (apenas 4 comparáveis de construção)."]}
    zona = {"comparaveis_confirmados": NA_ZONA, "raio_final_m": 1500, "raio_ia_m": 600,
            "ampliacao_raio": {"ampliado": True, "limite_m": 1500}, **extra_zona}
    return {"status": "completo", "preco_estimado": ag5, "resumo": {"cluster_a": 5},
            "comparaveis": NA_ZONA, "terrenos": [], "zona_homogenea": zona,
            "registro": {"execucao": {"alertas": []}, "comparaveis": []}}


def _tela(resultado, alvo=None):
    at = AppTest.from_file("app/interface.py", default_timeout=60)
    at.session_state["resultado"] = resultado
    at.session_state["imovel_alvo_dados"] = alvo or {"area": 104, "tipo": "house"}
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


# ---------------------------------------------------------------- (a) tela limpa
def test_a_ao_avaliar_de_novo_o_resultado_anterior_sai_da_tela():
    at = _tela(resultado_sem_valor())
    assert "📊 Resultado da Avaliação" in [s.value for s in at.subheader]
    # Avaliar de novo (com o formulario incompleto, para a avaliacao parar logo).
    next(b for b in at.button if "Avaliar" in b.label).click().run()
    assert "📊 Resultado da Avaliação" not in [s.value for s in at.subheader]
    assert "resultado" not in at.session_state
    assert any("Rua é obrigatória" in w.value for w in at.warning)


# ---------------------------------------------------------------- (c) contagem
def test_c_contagem_da_zona_explica_o_anuncio_do_proprio_imovel():
    assert texto_comparaveis_na_zona(5, 1) == "5 comparáveis na zona (1 é o anúncio do próprio imóvel e saiu do cálculo)"
    assert texto_comparaveis_na_zona(1, 0) == "1 comparável na zona"
    at = _tela(resultado_sem_valor())
    linhas = " ".join(m.value for m in at.markdown)
    assert "Todos os **5** comparáveis estão na zona homogênea (raio de 1500 m) (1 é o anúncio do próprio imóvel" in linhas


def test_c_aviso_do_agente5_diz_que_o_anuncio_saiu():
    comps = [{"propertyType": "casa", "price": 500_000 + i * 10_000, "area": 100 + i} for i in range(4)]
    r = executar_agente5({"propertyType": "casa", "area": 104, "anuncios_do_alvo_excluidos": 1}, [], comps, {}, {})
    assert r["status_avaliacao"] == "amostra_insuficiente" and r["anuncios_do_alvo_excluidos"] == 1
    aviso = next(a for a in r["avisos"] if a.startswith("Amostra insuficiente"))
    assert "apenas 4 comparáveis de construção (o anúncio do próprio imóvel saiu do cálculo)" in aviso, aviso


# ---------------------------------------------------------------- (d) motivo exato
def test_d_motivo_exato_e_o_que_fazer():
    sem = motivo_sem_valor(resultado_sem_valor(), {"tipo": "house", "area": 104})
    assert sem["motivo"].startswith("Faltou 1 casa para o mínimo de 5: só 4 casas parecidas"), sem
    assert "O anúncio do próprio imóvel saiu do cálculo." in sem["motivo"]
    assert "O raio já foi ampliado até 1.500 m (o máximo)." in sem["fazer"]
    assert any(f.startswith("Informe a área do terreno") for f in sem["fazer"])
    # Apartamento, sem ampliacao: so o motivo.
    r = resultado_sem_valor(ampliacao_raio={})
    r["comparaveis"] = r["zona_homogenea"]["comparaveis_confirmados"] = NA_ZONA[1:]
    r["preco_estimado"]["comparaveis_usados"]["construcao"] = r["preco_estimado"]["comparaveis_usados"]["construcao"][:3]
    sem = motivo_sem_valor(r, {"tipo": "apartment"})
    assert sem == {"motivo": "Faltaram 2 apartamentos para o mínimo de 5: só 3 apartamentos parecidos perto "
                             "do imóvel entraram no cálculo.", "fazer": []}, sem


def test_d_tela_e_laudo_mostram_o_motivo():
    at = _tela(resultado_sem_valor())
    avisos = [w.value for w in at.warning if "Não foi possível estimar um valor confiável" in w.value]
    assert avisos and "Faltou 1 casa para o mínimo de 5" in avisos[0], avisos
    textos = " ".join(w.value for w in at.warning)
    assert "verifique a área informada" not in textos.lower()
    assert any("O raio já foi ampliado até 1.500 m" in c.value for c in at.caption)
    laudo = _laudo(at)
    assert "Faltou 1 casa para o mínimo de 5" in laudo and "- O raio já foi ampliado até 1.500 m (o máximo)." in laudo


# ---------------------------------------------------------------- (e) proprio anuncio no topo
def _indice(at, tipo, texto):
    """Posicao do primeiro elemento do tipo com o texto, na ordem da tela."""
    elementos = list(_percorrer(at.main))
    return next(i for i, el in enumerate(elementos) if el.type == tipo and texto in str(getattr(el, "value", "")))


def _percorrer(no):
    for filho in getattr(no, "children", {}).values():
        yield filho
        yield from _percorrer(filho)


def test_e_anuncio_excluido_aparece_logo_abaixo_do_valor():
    at = _tela(resultado_sem_valor())
    infos = [i.value for i in at.info if "Encontramos o anúncio do próprio imóvel" in i.value]
    assert infos and "saiu do cálculo" in infos[0] and "[Ver o anúncio](https://x/0)" in infos[0], infos
    # Logo abaixo dos cartoes de valor e antes de "Como chegamos neste valor".
    pos_aviso = _indice(at, "info", "Encontramos o anúncio do próprio imóvel")
    assert _indice(at, "metric", "") < pos_aviso < _indice(at, "subheader", "Como chegamos")
    assert "encontramos o anúncio do próprio imóvel e ele saiu do cálculo (https://x/0)" in _laudo(at)


def test_e_suspeito_continua_no_calculo():
    r = resultado_sem_valor()
    r["comparaveis"] = r["zona_homogenea"]["comparaveis_confirmados"] = NA_ZONA[1:]
    r["preco_estimado"]["comparaveis_usados"]["construcao"][0]["possivel_anuncio_do_alvo"] = True
    at = _tela(r)
    avisos = [w.value for w in at.warning if "Possível anúncio do próprio imóvel" in w.value]
    assert avisos and "continua no cálculo" in avisos[0] and "(https://x/1)" in avisos[0], avisos
    assert not [i for i in at.info if "Encontramos o anúncio" in i.value]


# ---------------------------------------------------------------- (f) referencia sem valor
def test_f_sem_valor_mostra_os_comparaveis_validos_como_referencia():
    at = _tela(resultado_sem_valor())
    assert any("Não é uma estimativa" in c.value for c in at.caption)
    tabela = [m.value for m in at.markdown if "R\\$/m²" in m.value and "[ver](https://x/1)" in m.value]
    assert tabela and "R\\$ 5.050" in tabela[0] and "101 m²" in tabela[0], tabela   # 510.000 / 101


def test_f_com_valor_nao_mostra_a_referencia():
    r = resultado_sem_valor()
    r["preco_estimado"].update(status_avaliacao="ok", avaliacao_confiavel=True)
    at = _tela(r)
    assert not any("Não é uma estimativa" in c.value for c in at.caption)


# ---------------------------------------------------------------- (g) acentos no Agente 5
def test_g_avisos_do_agente5_com_acento():
    casas = [{"propertyType": "casa", "price": 500_000 + i * 10_000, "area": 100 + i} for i in range(5)]
    r = executar_agente5({"propertyType": "casa", "area": 104}, [], casas, {}, {})
    assert ("Área do terreno do imóvel não informada. O cálculo usou só o m² total dos comparáveis "
            "(preço ÷ área construída).") in r["avisos"], r["avisos"]
    r = executar_agente5({"propertyType": "casa", "area": 104}, [], casas[:1], {}, {})
    aviso = next(a for a in r["avisos"] if a.startswith("Amostra insuficiente"))
    assert aviso == ("Amostra insuficiente para uma estimativa confiável (apenas 1 comparável de construção; "
                     "mínimo desejado: 5). O valor calculado é uma referência fraca, baseada em poucos anúncios."), aviso
    assert "desconto de 10%)" in r["justificativa"] and "%%" not in r["justificativa"]


# ---------------------------------------------------------------- (h) plural
def test_h_um_comparavel_no_singular():
    r = resultado_sem_valor()
    r["comparaveis"] = r["zona_homogenea"]["comparaveis_confirmados"] = NA_ZONA[1:2]
    r["resumo"] = {"cluster_a": 1, "total_coletados": 1}
    at = _tela(r)
    textos = " ".join(m.value for m in at.markdown)
    assert "O único comparável está na zona homogênea" in textos and "Todos os 1" not in textos
    assert "Dos 1 imóveis" not in textos and "Dos 1 imóvel encontrado:" in textos
    assert "(is)" not in textos


# ---------------------------------------------------------------- (j) formulario
def test_j_formulario_vagas_vazias_uf_e_aviso_do_terreno():
    at = AppTest.from_file("app/interface.py", default_timeout=60).run()
    vagas = next(n for n in at.number_input if n.label == "Vagas")
    assert vagas.value is None
    assert any(s.label == "UF" for s in at.selectbox)
    assert any("sem a área do terreno, o cálculo usa só o m² total das casas" in c.value for c in at.sidebar.caption)


# ---------------------------------------------------------------- (k) imobiliaria
def test_k_sem_imobiliaria_mais_proxima():
    r = resultado_sem_valor()
    r["infraestrutura"] = {"scores": {"score_final": 0.7, "classificacao_infraestrutura": "boa"},
                           "imobiliaria_proxima": {"encontrada": True, "nome": "Imob X", "telefone": "1"}}
    at = _tela(r)
    textos = " ".join(m.value for m in at.markdown)
    assert "Imobiliária mais próxima" not in textos and "Imob X" not in textos
    assert "Imob X" not in _laudo(at)


# ---------------------------------------------------------------- sem dispersao Area x Preco
def test_sem_grafico_de_dispersao_area_x_preco():
    r = resultado_sem_valor()
    r["preco_estimado"].update(status_avaliacao="ok", avaliacao_confiavel=True)
    r["analise_qualitativa"] = {
        "resumo": {"total_analisados": 4, "score_qualitativo_medio": 0.6},
        "imovel_alvo": {"analise_qualitativa": {"scores": {"score_qualitativo": 0.5}}},
        "comparaveis": [dict(c, analise_qualitativa={"scores": {"score_qualitativo": 0.6}}) for c in NA_ZONA],
    }
    at = _tela(r)
    assert any("| Preço" in m.value and "[ver](https://x/1)" in m.value for m in at.markdown)  # a tabela continua
    assert not at.get("plotly_chart"), "o gráfico de dispersão ainda aparece"


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
