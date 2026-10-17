"""
Testes do fallback da zona homogenea (Agente 2) com o minimo de 5. Sem rede: imagem
de satelite, IA de visao e classificacao por distancia sao simuladas.

    .venv/Scripts/python.exe -m tests.test_fallback_zona
"""
import sys

sys.path.insert(0, ".")

import agents.comparables as ag2
from tests._pasta_temporaria import data_dir_temporario


def _simular(monkey):
    originais = {n: getattr(ag2, n) for n in monkey}
    for nome, func in monkey.items():
        setattr(ag2, nome, func)
    return originais


def _restaurar(originais):
    for nome, func in originais.items():
        setattr(ag2, nome, func)


def _rodar(casas, terrenos):
    """Cada anuncio traz em 'zona' a classificacao simulada (na_zona / zona_nao_verificada)."""
    originais = _simular({
        "_obter_imagem_satelite": lambda *a, **k: b"png",
        "_analisar_zona_homogenea": lambda *a, **k: {"raio_metros": 500, "raio_sugerido_metros": 500},
        "_classificar_imovel_na_zona": lambda im, *a, **k: im["zona"],
    })
    try:
        with data_dir_temporario():
            return ag2.analisar_zona_homogenea(
                "Rua X, 1", casas, cidade="Cidade", estado="SP",
                lat_alvo_precomp=-20.0, lon_alvo_precomp=-49.0, terrenos=terrenos, id_execucao="teste",
            )
    finally:
        _restaurar(originais)


def anuncio(i, zona, tipo="casa"):
    return {"id": f"{tipo}{i}", "propertyType": tipo, "price": 500000 + i, "area": 150, "zona": zona}


def test_casas_com_4_confirmadas_recebem_fallback():
    casas = [anuncio(i, "na_zona") for i in range(4)] + [anuncio(9, "zona_nao_verificada")]
    r = _rodar(casas, [])
    construcao = [c for c in r["comparaveis_confirmados"] if c["propertyType"] == "casa"]
    assert len(construcao) == 5 and r["resumo_zona"]["fallback_zona_acionado"], r["resumo_zona"]


def test_casas_com_5_confirmadas_nao_recebem_fallback():
    casas = [anuncio(i, "na_zona") for i in range(5)] + [anuncio(9, "zona_nao_verificada")]
    r = _rodar(casas, [])
    assert len(r["comparaveis_confirmados"]) == 5 and not r["resumo_zona"]["fallback_zona_acionado"]


def test_terrenos_com_2_confirmados_somam_os_nao_verificados():
    casas = [anuncio(i, "na_zona") for i in range(5)]
    terrenos = [anuncio(i, "na_zona", "terreno") for i in range(2)] + [
        anuncio(i, "zona_nao_verificada", "terreno") for i in range(10, 13)]
    r = _rodar(casas, terrenos)
    assert len(r["terrenos"]) == 5, len(r["terrenos"])
    assert sum(1 for t in r["terrenos"] if t.get("incluido_por_fallback_zona")) == 3


def test_terrenos_com_5_confirmados_nao_recebem_fallback():
    casas = [anuncio(i, "na_zona") for i in range(5)]
    terrenos = [anuncio(i, "na_zona", "terreno") for i in range(5)] + [anuncio(9, "zona_nao_verificada", "terreno")]
    r = _rodar(casas, terrenos)
    assert len(r["terrenos"]) == 5 and not any(t.get("incluido_por_fallback_zona") for t in r["terrenos"])


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
