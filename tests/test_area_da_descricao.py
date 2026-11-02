"""
Casa com o terreno no campo de area e a area construida escrita na descricao (Campo
Largo, 02/11/2026: sobrado "455 m2" que tinha 180 m2 construidos). O Agente 1 troca so
com tres confirmacoes. Sem rede.

    .venv/Scripts/python.exe -m tests.test_area_da_descricao
"""
import logging
import sys

sys.path.insert(0, ".")
logging.disable(logging.CRITICAL)

from agents.collector import _area_construida_na_descricao, _corrigir_area_pela_descricao
from services.alertas import calcular_alertas


def casa(area, descricao, **extra):
    return {"tipo": "casa", "propertyType": "Casas", "price": 710_000, "area": area, "description": descricao, **extra}


def test_sobrado_de_campo_largo():
    im = casa(455.0, "Sobrado com 455,00 m² de área de terreno e 180,00 m² de área construída, 4 quartos.",
              area_terreno="455.0", pricePerSqm=1560.44)
    assert _corrigir_area_pela_descricao(im)
    assert (im["area"], im["area_original"], im["area_corrigida_pela_descricao"]) == (180.0, 455.0, 180.0)
    assert im["pricePerSqm"] == round(710_000 / 180, 2)


def test_frases_reais_do_banco():
    exemplos = [
        (667, "Terreno de 666,15 m²;<br>Área construída de 288,39 m²", {}, 288.39),
        (412, "- 412m² Área de terreno. - 357m² Área construída. - 4 Dormitórios", {}, 357),
        (300, "➥ Metragem do terreno 12x25. ➥ Área construída de 75m² ➥ Forro de pvc", {}, 75),
        (1000, "Casa ampla em terreno de 1.000m², com uma área construída de 347m²", {}, 347),
    ]
    for area, texto, extra, esperado in exemplos:
        im = casa(area, texto, **extra)
        assert _corrigir_area_pela_descricao(im) and im["area"] == esperado, (texto, im.get("area"))


def test_nao_troca_sem_as_tres_confirmacoes():
    # Sem area construida escrita.
    assert not _corrigir_area_pela_descricao(casa(455, "Sobrado com terreno de 455 m², 4 quartos."))
    # O campo nao e o terreno (nem igual ao campo de terreno, nem citado como terreno/medidas).
    assert not _corrigir_area_pela_descricao(casa(250, "Casa com 180 m² de área construída, terreno de 400 m²."))
    # A area escrita e maior (o erro comum e o terreno no lugar da construcao).
    assert not _corrigir_area_pela_descricao(casa(120, "Terreno de 120 m². Área construída de 200 m²."))
    # Duas areas construidas diferentes no texto: ambiguo.
    assert _area_construida_na_descricao("Área construída de 180 m². Edícula com 40 m² de área construída.") is None
    # Apartamento: nao se aplica.
    apto = casa(455, "455 m² de área total e 180 m² de área construída", tipo="apartamento",
                propertyType="Apartamentos")
    assert not _corrigir_area_pela_descricao(apto)


def test_alerta_na_tela():
    usado = {"url": "https://x/1", "rua": "Rua A", "preco": 710_000, "area": 180, "status_zona": "confirmado",
             "area_original": 455.0, "area_corrigida_pela_descricao": 180.0}
    alertas = calcular_alertas({"status_agente5": "ok"}, {"comparaveis_usados": {"construcao": [usado]}})
    alerta = next(a for a in alertas if a["codigo"] == "area_da_descricao")
    assert alerta["mensagem"].startswith("Área tirada da descrição: em 1 casa usada no cálculo")
    assert alerta["detalhe"][0]["motivo"] == "campo de área 455 m² (terreno); descrição: 180 m² construídos"


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
