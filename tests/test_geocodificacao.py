"""
Testes da geocodificacao precisa (agents/comparables.py). Sem rede: respostas do
Nominatim e do Google simuladas.

    .venv/Scripts/python.exe -m tests.test_geocodificacao
"""
import os
import sys

sys.path.insert(0, ".")

import requests

import agents.comparables as ag2

CENTRO_ITABORAI = (-22.7472462, -42.8584458)


class _Resposta:
    def __init__(self, dados):
        self.status_code = 200
        self._dados = dados

    def json(self):
        return self._dados


def _simular(nominatim, google):
    """nominatim/google: dict endereco -> resposta (lista do Nominatim / dict do Google)."""
    def get(url, params=None, **_):
        consulta = (params or {}).get("q") or (params or {}).get("address")
        if "nominatim" in url:
            return _Resposta(nominatim.get(consulta, []))
        return _Resposta(google.get(consulta, {"results": []}))
    return get


def _com(nominatim, google, func):
    original, chave = requests.get, os.environ.get("GOOGLE_MAPS_KEY")
    requests.get = _simular(nominatim, google)
    os.environ["GOOGLE_MAPS_KEY"] = "teste"
    import time
    sleep_original = time.sleep
    time.sleep = lambda *_: None
    try:
        return func()
    finally:
        requests.get = original
        time.sleep = sleep_original
        if chave is None:
            os.environ.pop("GOOGLE_MAPS_KEY", None)
        else:
            os.environ["GOOGLE_MAPS_KEY"] = chave


def nominatim(lat, lon, addresstype, tipo=None):
    return [{"lat": str(lat), "lon": str(lon), "addresstype": addresstype, "type": tipo or addresstype}]


def google(lat, lon, types, location_type="ROOFTOP", partial=False):
    item = {"types": types, "geometry": {"location": {"lat": lat, "lng": lon}, "location_type": location_type}}
    if partial:
        item["partial_match"] = True
    return {"results": [item]}


def test_resultado_de_cidade_recusado_nos_dois():
    end = "Rua Inexistente, Itaboraí, RJ"
    r = _com({end: nominatim(*CENTRO_ITABORAI, "city")},
             {end: google(*CENTRO_ITABORAI, ["locality", "political"], "APPROXIMATE")},
             lambda: ag2._geocodificar(end))
    assert r == (None, None), r


def test_google_aproximado_com_partial_match_recusado():
    end = "Rua X, Itaboraí, RJ"
    r = _com({}, {end: google(-22.74, -42.85, ["route"], "APPROXIMATE", partial=True)},
             lambda: ag2._geocodificar(end))
    assert r == (None, None), r


def test_resultado_de_rua_aceito():
    end = "Rua Tenente Joaquim Rabelo de Matos, Itaboraí, RJ"
    r = _com({end: nominatim(-22.7601, -42.8702, "road", "residential")}, {}, lambda: ag2._geocodificar(end))
    assert r == (-22.7601, -42.8702), r


def test_nominatim_cidade_recusado_google_rua_aceito():
    end = "Rua Y, 10, Itaboraí, RJ"
    r = _com({end: nominatim(*CENTRO_ITABORAI, "town")},
             {end: google(-22.75, -42.87, ["street_address"], "ROOFTOP")},
             lambda: ag2._geocodificar(end))
    assert r == (-22.75, -42.87), r


def test_fallback_segue_para_o_bairro_quando_a_rua_vira_cidade():
    # Endereco completo e rua caem no centro da cidade (recusados); o bairro e aceito.
    bairro = "JARDIM ITAJUBA, Itaboraí, RJ, Brasil"
    r = _com({bairro: nominatim(-22.7701, -42.8801, "suburb")}, {},
             lambda: ag2._geocodificar_com_fallback(
                 endereco_principal="Rua Z, JARDIM ITAJUBA, Itaboraí, RJ", rua="Rua Z",
                 bairro="JARDIM ITAJUBA", cidade="Itaboraí", estado="RJ"))
    assert r[:3] == (-22.7701, -42.8801, "bairro"), r


def test_alvo_sem_precisao_de_rua_ou_bairro_fica_sem_localizacao():
    r = _com({}, {}, lambda: ag2._geocodificar_com_fallback(
        endereco_principal="Rua Z, Bairro W, Itaboraí, RJ", rua="Rua Z", bairro="Bairro W",
        cidade="Itaboraí", estado="RJ"))
    assert r == (None, None, None, None), r


def test_centros_da_cidade_dos_dois_servicos():
    # Nominatim e Google dao centros diferentes (Itaborai: ~2,7 km); os dois contam.
    end = "Itaboraí, RJ, Brasil"
    r = _com({end: nominatim(-22.7558, -42.8830, "city")}, {end: google(*CENTRO_ITABORAI, ["locality"])},
             lambda: ag2._centros_da_cidade("Itaboraí", "RJ"))
    assert r == [(-22.7558, -42.8830), CENTRO_ITABORAI], r


# ---------------------------------------------------------------- anuncios
ALVO = (-22.7601, -42.8702)


def _classificar(im, repetidas=None):
    return ag2._classificar_imovel_na_zona(
        im, ALVO[0], ALVO[1], 3000, "Itaboraí", "RJ",
        centros_cidade=[(-22.7558, -42.8830), CENTRO_ITABORAI], coords_repetidas=repetidas or set())


def test_anuncio_no_centro_da_cidade_vira_nao_verificado():
    im = {"lat": -22.747246, "lon": -42.858446, "neighborhood": "Centro (Sambaetiba)"}
    assert _classificar(im) == "zona_nao_verificada"
    assert "centro da cidade" in im["motivo_zona_nao_verificada"]


def test_anuncio_longe_do_centro_dentro_do_raio_fica_na_zona():
    im = {"lat": -22.7605, "lon": -42.8705, "neighborhood": "Jardim Itajubá"}
    assert _classificar(im) == "na_zona"


def test_coordenada_repetida_em_varios_bairros():
    ims = [{"lat": -22.7752, "lon": -42.86, "neighborhood": b} for b in ("Areal", "Caluge", "Centro")]
    repetidas = ag2._coordenadas_repetidas(ims)
    assert (-22.7752, -42.86) in repetidas
    assert _classificar(dict(ims[0]), repetidas=repetidas) == "zona_nao_verificada"


def test_coordenada_repetida_no_mesmo_bairro_nao_e_suspeita():
    # Varias unidades do mesmo condominio dividem a coordenada: nao e generica.
    ims = [{"lat": -22.7752, "lon": -42.86, "neighborhood": "Areal"} for _ in range(4)]
    assert ag2._coordenadas_repetidas(ims) == set()


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
