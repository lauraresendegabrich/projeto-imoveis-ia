"""
Entrada completa do formulario e checagem do proprio anuncio no banco; preco no
formato brasileiro. Sem rede.

    .venv/Scripts/python.exe -m tests.test_entrada_usuario
"""
import logging
import sys

sys.path.insert(0, ".")
logging.disable(logging.CRITICAL)

import agents.comparables as ag2
from services.banco import COLUNAS_EXECUCOES, COLUNAS_JSON
from services.registro_execucao import montar_registro

DESC = ("CÓDIGO DO IMÓVEL : CA0406 LOCALIZAÇÃO: Localizado na Praia do sonho AMBIENTES: Casa com 8 "
        "quartos sendo 6 suítes, com varanda, espaço gourmet, ótima localização a 570m da praia.")
ALVO = {"rua": "Praia Do Sonho Ens Brito", "numero": "", "bairro": "Praia Do Sonho Ens Brito", "cidade": "Palhoça",
        "estado": "SC", "tipo": "house", "propertyType": "Casas", "area": 360.0, "bedrooms": 8, "bathrooms": 6,
        "parkingSpaces": 2, "price": 1200000.0, "description": DESC, "descricao_gerada": False,
        "neighborhood": "Praia Do Sonho Ens Brito"}


def anuncio(url, preco, area, desc=DESC):
    return {"url": url, "source": "VivaReal", "propertyType": "Casas", "tipo": "casa", "price": preco,
            "area": area, "bedrooms": 8, "bathrooms": 6, "parkingSpaces": 2, "neighborhood": "Praia do Sonho",
            "description": desc}


def test_checagem_fica_registrada_para_todos_os_anuncios():
    proprio = anuncio("https://vr/2903862416", 1200000.0, 360.0)
    outro = anuncio("https://vr/2", 800000.0, 200.0, desc="Casa simples perto do centro, dois quartos e quintal amplo para pets.")
    assert ag2._marcar_anuncio_do_alvo(dict(ALVO), [proprio, outro]) == 1
    assert proprio["checagem_alvo"]["resultado"] == "confirmado"
    assert any(s.startswith("casa_preco_area_descricao") for s in proprio["checagem_alvo"]["sinais"])
    assert outro["checagem_alvo"]["resultado"] == "nao" and "score" in outro["checagem_alvo"]


def _registro(coletados, entrada):
    return montar_registro(id_execucao="x", imovel_alvo={}, leilao_entrada={}, leilao={},
                           imoveis_coletados=coletados, resultado_ag2={}, zona_resultado={}, resultado_ag3={},
                           resultado_ag4={}, resultado_ag5={}, entrada_usuario=entrada)[0]


def test_banco_guarda_entrada_completa_e_checagem():
    proprio = anuncio("https://vr/2903862416", 1200000.0, 360.0)
    ag2._marcar_anuncio_do_alvo(dict(ALVO), [proprio])
    entrada = {"rua": "Praia Do Sonho Ens Brito", "preco_digitado": "1.200.000", "preco_lido": 1200000.0,
               "descricao": DESC, "descricao_caracteres": len(DESC), "quartos": 8, "banheiros": 6, "vagas": 2}
    e = _registro([proprio], entrada)
    assert e["entrada_usuario"]["preco_lido"] == 1200000.0 and e["entrada_usuario"]["descricao_caracteres"] == len(DESC)
    chec = e["checagem_anuncio_alvo"]
    assert chec["testados"] == 1 and chec["confirmados"] == 1
    assert chec["maiores_pontuacoes"][0]["link"] == "https://vr/2903862416"
    assert any("desc=" in s for s in chec["maiores_pontuacoes"][0]["sinais"])


def test_sem_checagem_fica_vazio():
    e = _registro([], None)
    assert e["entrada_usuario"] is None and e["checagem_anuncio_alvo"] is None


def test_colunas_e_migracao_003():
    sql = open("db/migracoes/003_entrada_usuario_e_checagem_do_alvo.sql", encoding="utf-8").read()
    schema = open("db/schema.sql", encoding="utf-8").read()
    for coluna in ("entrada_usuario", "checagem_anuncio_alvo"):
        assert f"ADD COLUMN IF NOT EXISTS {coluna}" in sql and coluna in schema
        assert coluna in COLUNAS_EXECUCOES and coluna in COLUNAS_JSON


def test_preco_invalido_aparece_como_erro_na_tela():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file("app/interface.py", default_timeout=60).run()
    preco = next(w for w in at.sidebar.text_input if w.label.startswith("Preço"))
    assert preco.placeholder == "Ex.: 1.200.000"
    preco.input("1.2.3")
    at.sidebar.button[0].click().run()
    erros = [w.value for w in at.warning if "Preço inválido" in w.value]
    assert erros and "1.200.000 ou 1.200.000,00" in erros[0], erros


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
