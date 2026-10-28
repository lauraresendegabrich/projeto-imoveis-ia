"""
Correcoes da auditoria de 28/10/2026 (casa de 35,88 m² em Alvorada do Sul/PR, "Sem
estimativa"):
  - Agente 2: com 5+ terrenos coletados, a area do terreno nao elimina casas (o Agente
    5 separa o terreno); a IA e avisada de que o lote e descontado.
  - Agente 1: o mesmo lote com o mesmo codigo e o nome da imobiliaria escrito diferente
    entre portais e repetido.
  - Tela: o motivo do "Sem estimativa" diz quando todas as casas tem area diferente.
Sem rede.

    .venv/Scripts/python.exe -m tests.test_auditoria_alvorada
"""
import logging
import shutil
import sys
from pathlib import Path

sys.path.insert(0, ".")
logging.disable(logging.CRITICAL)

from agents import comparables
from agents.comparables import (
    MIN_TERRENOS_TERRENO_NAO_ELIMINA, _montar_prompt_clustering, _pre_classificar, identificar_comparaveis,
)
from agents.identidade import deduplicar, mesmo_anunciante, mesmo_imovel
from services.textos_tela import motivo_areas_diferentes, motivo_sem_valor

ALVO = {"tipo": "house", "propertyType": "Casas", "area": 100.0, "area_terreno": 200.0, "bedrooms": 2,
        "bathrooms": 1, "cidade": "Palhoça", "estado": "SC", "description": "Casa"}


def casa(i, area=100.0, terreno=600.0):
    return {"listing_id": f"c{i}", "url": f"https://x/c{i}", "propertyType": "Casas", "tipo": "casa",
            "area": area, "area_terreno": terreno, "bedrooms": 2, "bathrooms": 1, "price": 400000.0 + i}


def terreno(i):
    return {"listing_id": f"t{i}", "url": f"https://x/t{i}", "propertyType": "Terrenos", "tipo": "terreno",
            "area": 400.0, "price": 120000.0 + i}


def _rodar(coletados):
    run_id = "teste_auditoria_alvorada"
    try:
        return identificar_comparaveis(dict(ALVO), imoveis_coletados=coletados, usar_llm=False, run_id=run_id)
    finally:
        shutil.rmtree(Path(comparables.DATA_DIR) / f"run_{run_id}", ignore_errors=True)


# ---------------------------------------------------------------- Agente 2
def test_terreno_diferente_so_elimina_quando_o_agente5_nao_separa_o_terreno():
    cand = casa(1, terreno=600.0)   # lote 3x maior, area construida igual
    elimina = _pre_classificar(ALVO, cand, terreno_elimina=True)
    nao_elimina = _pre_classificar(ALVO, cand, terreno_elimina=False)
    assert not elimina["elegivel_llm"] and "area de terreno difere" in elimina["motivos_incompatibilidade"][0]
    assert nao_elimina["elegivel_llm"] and nao_elimina["area_terreno"]["diferenca_percentual"] == 200.0
    assert nao_elimina["area_terreno"]["elimina"] is False
    # Area construida diferente continua eliminando.
    assert not _pre_classificar(ALVO, casa(2, area=300.0), terreno_elimina=False)["elegivel_llm"]


def test_com_5_terrenos_coletados_a_casa_de_lote_maior_passa():
    casas = [casa(i) for i in range(10)]
    com = _rodar(casas + [terreno(i) for i in range(MIN_TERRENOS_TERRENO_NAO_ELIMINA)])
    pre = com["resumo"]["pre_classificacao"]
    assert pre["elegiveis_apos_pre_classificacao"] == 10 and pre["terreno_elimina"] is False, pre
    sem = _rodar([casa(i) for i in range(10)] + [terreno(i) for i in range(MIN_TERRENOS_TERRENO_NAO_ELIMINA - 1)])
    pre = sem["resumo"]["pre_classificacao"]
    assert pre["elegiveis_apos_pre_classificacao"] == 0 and pre["terreno_elimina"] is True, pre


def test_prompt_avisa_a_ia_que_o_terreno_e_descontado():
    assert "TAMANHO\n   DO TERRENO NAO e motivo para rejeitar" in _montar_prompt_clustering(ALVO, [casa(1)], terreno_corrigido=True)
    sem = _montar_prompt_clustering(ALVO, [casa(1)])
    assert "Banheiros, vagas, terreno e caracteristicas estruturais" in sem and "DO TERRENO NAO" not in sem


# ---------------------------------------------------------------- Agente 1
def _lote(portal, source, anunciante, listing_id):
    return {"portal": portal, "source": source, "tipo": "terreno", "propertyType": "Terrenos",
            "preco": 280000.0, "area_construida": 870.0, "rua": "Avenida Augusto Alves, 923",
            "anunciante_nome": anunciante, "codigo_imovel_anunciante": "TE287993",
            "listing_id": listing_id, "url": f"https://x/{listing_id}"}


def test_mesmo_lote_com_o_nome_da_imobiliaria_escrito_diferente_e_repetido():
    a = _lote("chavesnamao", "Chaves na Mão", "IMOBILIÁRIA HOPE LTDA", "1")
    b = _lote("vivareal", "VivaReal", "Hope Administracao De Bens E Imoveis Ltda", "2")
    assert mesmo_imovel(a, b) == (True, "mesmo_codigo_e_anunciante")
    unicos, descartados = deduplicar([a, b])
    assert len(unicos) == 1 and len(descartados) == 1
    # Outra imobiliaria com o mesmo codigo nao e prova.
    c = _lote("vivareal", "VivaReal", "Imobiliaria Alfa", "3")
    assert mesmo_imovel(a, c)[0] is False


def test_mesmo_anunciante():
    assert mesmo_anunciante("hope", "hope administracao bens")
    assert mesmo_anunciante("alfa", "alfa")
    assert not mesmo_anunciante("hope", "alfa") and not mesmo_anunciante("", "hope")
    assert not mesmo_anunciante("hope prime", "hope administracao")


# ---------------------------------------------------------------- tela
def _resultado_areas(areas, motivo_extra=None):
    comparaveis = []
    for i, a in enumerate(areas):
        dif = abs(a - 35.88) / 35.88 * 100
        pre = {"area_construida": {"alvo": 35.88, "candidato": a, "diferenca_percentual": round(dif, 2),
                                   "limite_percentual": 45}}
        if motivo_extra and i == 0:
            pre["area_construida"]["diferenca_percentual"] = 10.0   # area ok: saiu por outra coisa
        comparaveis.append({"status_julgamento": "REPROVADO_PRE_CLASSIFICACAO", "pre_classificacao": pre})
    return {"preco_estimado": {"status_avaliacao": "amostra_insuficiente", "comparaveis_usados": {}},
            "resumo": {"cluster_a": 0, "pre_classificacao": {"total_construidos": len(areas),
                                                              "regra_area_percentual": 45,
                                                              "referencia_alvo": {"area_construida": 35.88}}},
            "comparaveis": comparaveis + [{"status_julgamento": "SEPARADO_TIPO"}], "zona_homogenea": {}}


def test_motivo_diz_que_todas_as_casas_tem_area_diferente():
    r = _resultado_areas([100.0, 153.0, 1000.0])
    sem = motivo_sem_valor(r, {"tipo": "house", "area_terreno": 204})
    assert sem["motivo"] == ("Nenhuma das 3 casas à venda na região tem área parecida: elas têm de 100 a 1.000 m², "
                             "e o imóvel tem 35,88 m² (o cálculo aceita de 20 a 52 m², até 45% de diferença)."), sem
    assert "Confira a área construída informada." in sem["fazer"]
    assert motivo_areas_diferentes(_resultado_areas([150.0]), "casa", "casas").startswith(
        "A única casa à venda na região tem 150 m²")


def test_motivo_antigo_quando_alguma_saiu_por_outro_motivo():
    r = _resultado_areas([40.0, 153.0], motivo_extra=True)
    assert motivo_areas_diferentes(r, "casa", "casas") is None
    assert motivo_sem_valor(r, {"tipo": "house"})["motivo"].startswith("Faltaram 5 casas para o mínimo de 5")


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
