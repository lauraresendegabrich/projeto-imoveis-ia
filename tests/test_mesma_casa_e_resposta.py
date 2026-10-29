"""
Palhoca, 29/10/2026:
  - Mesma casa (rua, numero, area, quartos) anunciada por imobiliarias diferentes com
    precos diferentes: vira 1 anuncio com a mediana dos precos, e o alerta mostra o
    preco de cada imobiliaria (agents/identidade.py, services/alertas.py).
  - "Este anuncio e do seu imovel?": a resposta tira o anuncio do calculo do Agente 5,
    e a observacao continua na tela (app/paginas/avaliacao.py, app/resultado_tela.py).
Sem rede.

    .venv/Scripts/python.exe -m tests.test_mesma_casa_e_resposta
"""
import logging
import sys

sys.path.insert(0, ".")
logging.disable(logging.CRITICAL)

from streamlit.testing.v1 import AppTest

from agents.identidade import MOTIVO_MESMO_ENDERECO, agrupar_mesmo_endereco
from services.alertas import calcular_alertas
from services.textos_tela import anuncios_do_proprio_imovel, marcados_pela_usuaria


def jandaia(i, preco, anunciante, **extra):
    return {"url": f"https://x/jandaia-{i}", "tipo": "casa", "propertyType": "Casas", "price": preco,
            "area": 295, "bedrooms": 8, "street": "Rua Jandaia, 286", "neighborhood": "Praia do Sonho",
            "anunciante_nome": anunciante, "source": "Chaves na Mão", **extra}


# ---------------------------------------------------------------- mesma casa
def test_mesma_casa_com_precos_diferentes_vira_1_com_a_mediana():
    anuncios = [jandaia(1, 1_300_000, "Auxiliadora", description="x" * 80),
                jandaia(2, 1_600_000, "GFloripa"), jandaia(3, 1_400_000, "GS Corretores"),
                jandaia(4, 1_300_000, "Foxter", street="Rua Jandaia")]          # sem numero: fica
    unicos, descartados = agrupar_mesmo_endereco(anuncios)
    assert len(unicos) == 2 and len(descartados) == 2, (len(unicos), len(descartados))
    rep = next(u for u in unicos if u.get("precos_entre_imobiliarias"))
    assert rep["url"] == "https://x/jandaia-1" and rep["price"] == 1_400_000 and rep["preco_original"] == 1_300_000
    assert [p["preco"] for p in rep["precos_entre_imobiliarias"]] == [1_300_000, 1_600_000, 1_400_000]
    assert {d["motivo_duplicata"] for d in descartados} == {MOTIVO_MESMO_ENDERECO}
    assert len(rep["duplicatas"]) == 2 and rep["duplicatas"][0]["dados_identidade"]["price"] == 1_600_000


def test_nao_junta_apartamento_area_quartos_ou_numero_diferentes():
    for outro in (dict(area=320), dict(bedrooms=6), dict(street="Rua Jandaia, 290"),
                  dict(tipo="apartamento", propertyType="Apartamentos"),
                  dict(description="Casa 3 do condominio Jandaia")):
        base = jandaia(1, 1_300_000, "A")
        if "tipo" in outro:
            base.update(tipo="apartamento", propertyType="Apartamentos")
        unicos, descartados = agrupar_mesmo_endereco([base, jandaia(2, 1_600_000, "B", **outro)])
        assert len(unicos) == 2 and not descartados, outro


def test_mesmo_preco_nao_e_juntado_aqui():
    # Preco igual e do deduplicar (prova mais forte); aqui ficam separados.
    unicos, descartados = agrupar_mesmo_endereco([jandaia(1, 1_300_000, "A"), jandaia(2, 1_300_000, "B")])
    assert len(unicos) == 2 and not descartados


def test_alerta_mostra_o_preco_de_cada_imobiliaria():
    usado = {"url": "https://x/jandaia-1", "rua": "Rua Jandaia, 286", "preco": 1_400_000, "area": 295,
             "status_zona": "confirmado", "precos_entre_imobiliarias": [
                 {"anunciante": "Auxiliadora", "portal": "VivaReal", "preco": 1_300_000, "url": "https://x/1"},
                 {"anunciante": "GFloripa", "portal": "Chaves na Mão", "preco": 1_600_000, "url": "https://x/2"},
                 {"anunciante": "GS Corretores", "portal": "Chaves na Mão", "preco": 1_400_000, "url": "https://x/3"}]}
    alertas = calcular_alertas({"status_agente5": "ok"}, {"comparaveis_usados": {"construcao": [usado]}})
    alerta = next(a for a in alertas if a["codigo"] == "mesma_casa_precos_diferentes")
    assert alerta["mensagem"] == (
        "Mesma casa com preços diferentes: A casa da Rua Jandaia, 286 (295 m²) aparece em 3 anúncios de "
        "imobiliárias diferentes, com preços de R$ 1.300.000 a R$ 1.600.000. Contou como 1 imóvel, com o "
        "preço do meio (mediana): R$ 1.400.000."), alerta["mensagem"]
    assert [(d["motivo"], d["preco"]) for d in alerta["detalhe"]] == [
        ("Auxiliadora", 1_300_000), ("GFloripa", 1_600_000), ("GS Corretores", 1_400_000)]


# ---------------------------------------------------------------- zona
def test_anuncio_do_proprio_imovel_nao_conta_para_o_minimo_da_zona():
    from agents.comparables import _ampliar_raio, _completar_mesmo_bairro

    def anuncio(dist, **extra):
        return {"url": f"https://x/{dist}", "distancia_metros": dist, "geocodificacao_nivel": "coordenadas_athena",
                "neighborhood": "Praia do Sonho", **extra}
    # Palhoca: 5 na zona de 450 m, mas 1 e o suspeito: o raio amplia para 675 m.
    confirmados = [anuncio(100, possivel_anuncio_do_alvo=True), anuncio(92), anuncio(310), anuncio(409),
                   anuncio(80, eh_anuncio_do_alvo=True)]
    fora = [anuncio(606), anuncio(610), anuncio(900)]
    conf, resto, raio = _ampliar_raio(confirmados, fora, 450)
    assert raio == 675 and len(conf) == 7 and [r["distancia_metros"] for r in resto] == [900], (raio, len(conf))
    # Sem suspeito, 5 bastam (como antes).
    conf, _, raio = _ampliar_raio([anuncio(d) for d in (1, 2, 3, 4, 5)], [anuncio(606)], 450)
    assert raio == 450 and len(conf) == 5
    # Zona no mesmo bairro tambem nao conta o suspeito.
    entram, _, _ = _completar_mesmo_bairro([anuncio(d) for d in (1, 2, 3, 4)] + [anuncio(5, possivel_anuncio_do_alvo=True)],
                                           [anuncio(1800)], 1500, "Praia do Sonho")
    assert [e["distancia_metros"] for e in entram] == [1800]


# ---------------------------------------------------------------- Agente 5
def test_agente5_tira_do_calculo_o_anuncio_marcado():
    import agents.price_liquidity as ag5
    casas = [{"url": f"https://x/{i}", "propertyType": "Casas", "price": 500_000 + i, "area": 100,
              "classificacao_zona": "na_zona"} for i in range(6)]
    original = ag5.ler_json_da_execucao
    ag5.ler_json_da_execucao = lambda caminho, _id: (
        {"comparaveis_confirmados": casas, "id_execucao": "e1"} if caminho == ag5.CAMINHO_ZONA else {})
    try:
        _, _, construidos, _, _ = ag5.carregar_dados_pipeline("e1", ["https://x/2"])
        assert [c["url"] for c in construidos] == [f"https://x/{i}" for i in (0, 1, 3, 4, 5)]
        _, _, construidos, _, _ = ag5.carregar_dados_pipeline("e1")
        assert len(construidos) == 6
    finally:
        ag5.ler_json_da_execucao = original


# ---------------------------------------------------------------- tela
ALVO = {"area": 360, "bedrooms": 8, "bathrooms": 6, "parkingSpaces": 2, "neighborhood": "Praia do Sonho",
        "tipo": "house"}
SUSPEITO = {"url": "https://x/360", "propertyType": "Casas", "price": 1_200_000, "area": 360, "bedrooms": 8,
            "bathrooms": 6, "parkingSpaces": 2, "neighborhood": "Praia do Sonho", "possivel_anuncio_do_alvo": True}
OUTRAS = [{"url": f"https://x/{i}", "propertyType": "Casas", "price": 600_000 + i * 50_000, "area": 300}
          for i in range(5)]


def _ag5(sem_suspeito):
    usados = [] if sem_suspeito else [{"url": SUSPEITO["url"], "preco": 1_200_000, "area": 360,
                                        "possivel_anuncio_do_alvo": True, "status_zona": "confirmado"}]
    usados += [{"url": c["url"], "preco": c["price"], "area": 300, "status_zona": "confirmado"} for c in OUTRAS]
    return {"status_avaliacao": "ok", "avaliacao_confiavel": True, "zona_calculada_nesta_avaliacao": True,
            "comparaveis_usados": {"construcao": usados, "terreno": []},
            "avaliacao_planilha": {"valor_medio_imovel": 900_000 if sem_suspeito else 1_000_000,
                                   "valor_liquidez": 810_000},
            "liquidez_experimental": {"tempo_estimado": "90 a 150 dias"},
            "anuncios_do_alvo_pela_usuaria": [SUSPEITO["url"]] if sem_suspeito else []}


def _contexto():
    comparaveis = [dict(SUSPEITO)] + [dict(c) for c in OUTRAS]
    return {"id_execucao": "e1", "imovel_alvo": ALVO, "imoveis_coletados": [], "escopo_busca": "rua",
            "resumo": {"cluster_a": 6}, "duplicatas_descartadas": [], "dados_leilao": None,
            "alvo_sem_localizacao": False, "comparaveis": comparaveis, "terrenos": [],
            "zona_resultado": {"comparaveis_confirmados": comparaveis}, "resultado_ag2": {},
            "resultado_ag3": {}, "resultado_ag4": {}, "falhas": [], "localizacao_alvo": "rua",
            "entrada_usuario": {}, "tela_resultado": {},
            "tempos": {"total": 1, "agente1": 1, "agente2": 1, "zona": 1, "agentes3e4": 1}}


def test_pergunta_na_tela_tira_o_anuncio_e_a_observacao_fica():
    import agents.price_liquidity as ag5
    import services.banco as banco
    chamadas = []
    originais = (ag5.estimar_preco, banco.gravar_em_segundo_plano)

    def estimar(imovel_alvo_extra=None, id_execucao=None, urls_do_alvo_pela_usuaria=None):
        chamadas.append((id_execucao, list(urls_do_alvo_pela_usuaria or [])))
        return _ag5(bool(urls_do_alvo_pela_usuaria))

    ag5.estimar_preco, banco.gravar_em_segundo_plano = estimar, (lambda *a, **k: None)
    try:
        ctx = _contexto()
        at = AppTest.from_file("app/interface.py", default_timeout=60)
        at.session_state["contexto_avaliacao"] = ctx
        at.session_state["imovel_alvo_dados"] = ALVO
        at.session_state["resultado"] = {
            "status": "completo", "id_execucao": "e1", "preco_estimado": _ag5(False), "resumo": {"cluster_a": 6},
            "comparaveis": ctx["comparaveis"], "terrenos": [], "zona_homogenea": ctx["zona_resultado"],
            "imovel_alvo": ALVO, "registro": {"execucao": {"alertas": []}, "comparaveis": []}}
        at.run()
        assert not at.exception, [e.value for e in at.exception]
        textos = " ".join(w.value for w in at.warning)
        assert "Possível anúncio do próprio imóvel" in textos and "Este anúncio é do seu imóvel?" in textos
        botao = next(b for b in at.button if b.label.startswith("Sim, este anúncio é do meu imóvel"))
        botao.click().run()
        assert not at.exception, [e.value for e in at.exception]
        assert chamadas == [("e1", ["https://x/360"])], chamadas
        novo = at.session_state["resultado"]
        assert novo["preco_estimado"]["anuncios_do_alvo_pela_usuaria"] == ["https://x/360"]
        assert novo["registro"]["execucao"]["entrada_usuario"]["refeita_de"] == "e1"
        assert novo["registro"]["execucao"]["id_execucao"] != "e1"
        infos = " ".join(i.value for i in at.info)
        assert "Você indicou que este anúncio é do seu imóvel, e ele saiu do cálculo." in infos, infos
        assert "mesma área (360 m²)" in infos
        assert not any("Possível anúncio do próprio imóvel" in w.value for w in at.warning)
        # A tabela marca o anuncio como "seu anuncio"; voltar atras devolve ao calculo.
        assert ctx["comparaveis"][0]["eh_anuncio_do_alvo"] and ctx["comparaveis"][0]["anuncio_do_alvo_pela_usuaria"]
        next(b for b in at.button if b.label.startswith("Não é do meu imóvel")).click().run()
        assert chamadas[-1] == ("e1", []), chamadas
        assert not ctx["comparaveis"][0]["eh_anuncio_do_alvo"]
        assert any("Possível anúncio do próprio imóvel" in w.value for w in at.warning)
    finally:
        ag5.estimar_preco, banco.gravar_em_segundo_plano = originais


def test_textos_separam_o_marcado_pela_usuaria():
    comp = dict(SUSPEITO, eh_anuncio_do_alvo=True, anuncio_do_alvo_pela_usuaria=True)
    resultado = {"comparaveis": [comp], "terrenos": [], "preco_estimado": _ag5(True)}
    assert anuncios_do_proprio_imovel(resultado)[0] == []
    marcados = marcados_pela_usuaria(resultado, ALVO)
    assert marcados[0]["url"] == "https://x/360" and "mesmos quartos, banheiros e vagas" in marcados[0]["motivo"]


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
