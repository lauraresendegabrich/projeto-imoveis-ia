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
    assert "saiu do c" in aviso and "do proprio imovel" in aviso.replace("ó", "o").replace("í", "i"), aviso


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
