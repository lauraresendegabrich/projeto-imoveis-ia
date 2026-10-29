"""
Testes da TomTom como ultima tentativa de geocodificacao (agents/comparables.py).
Sem rede: Nominatim, Google e TomTom simulados.

    .venv/Scripts/python.exe -m tests.test_tomtom
"""
import os
import sys
import time

sys.path.insert(0, ".")

import requests

import agents.comparables as ag2

END = "Rua Nossa Senhora da Conceição, JARDIM ITAJUBA, Itaboraí, RJ, Brasil"


class _Resposta:
    def __init__(self, dados, status=200):
        self.status_code, self._dados = status, dados

    def json(self):
        return self._dados


def _rodar(func, tomtom=None, status=200, nominatim=None, chave="teste", google=None):
    """Roda func com Nominatim/Google vazios (ou `nominatim`) e a TomTom respondendo `tomtom`."""
    chamadas = {"tomtom": 0}

    def get(url, params=None, **_):
        if "nominatim" in url:
            return _Resposta(nominatim or [])
        if "googleapis" in url:
            return _Resposta(google or {"results": []})
        chamadas["tomtom"] += 1
        return _Resposta(tomtom if tomtom is not None else {"results": []}, status)

    originais = (requests.get, time.sleep, os.environ.get("TOMTOM_API_KEY"), os.environ.get("GOOGLE_MAPS_KEY"))
    requests.get, time.sleep = get, (lambda *_: None)
    os.environ["GOOGLE_MAPS_KEY"] = "teste"
    if chave:
        os.environ["TOMTOM_API_KEY"] = chave
    else:
        os.environ.pop("TOMTOM_API_KEY", None)
    ag2.reiniciar_contagem_tomtom()
    try:
        return func(), chamadas["tomtom"]
    finally:
        requests.get, time.sleep = originais[0], originais[1]
        for nome, valor in (("TOMTOM_API_KEY", originais[2]), ("GOOGLE_MAPS_KEY", originais[3])):
            if valor is None:
                os.environ.pop(nome, None)
            else:
                os.environ[nome] = valor


def tomtom(tipo, entidade=None, municipio="Itaboraí", lat=-22.70, lon=-42.80):
    item = {"type": tipo, "position": {"lat": lat, "lon": lon}, "address": {"municipality": municipio}}
    if entidade:
        item["entityType"] = entidade
    return {"results": [item]}


def detalhado():
    return ag2._geocodificar_detalhado(END, cidade_esperada="Itaboraí")


def test_aceita_nivel_rua():
    (r, n) = _rodar(detalhado, tomtom("Point Address"))
    assert r == (-22.70, -42.80, "rua_numero") and n == 1, r
    (r, _) = _rodar(detalhado, tomtom("Street"))
    assert r[2] == "rua", r


def test_aceita_nivel_bairro():
    (r, _) = _rodar(detalhado, tomtom("Geography", "MunicipalitySubdivision"))
    assert r == (-22.70, -42.80, "bairro"), r


def test_recusa_nivel_cidade():
    for entidade in ("Municipality", "CountrySubdivision"):
        (r, _) = _rodar(detalhado, tomtom("Geography", entidade))
        assert r == (None, None, None), (entidade, r)


def test_recusa_outra_cidade():
    (r, _) = _rodar(detalhado, tomtom("Street", municipio="Niterói"))
    assert r == (None, None, None), r


def test_sem_chave_pula_sem_erro():
    (r, n) = _rodar(detalhado, tomtom("Point Address"), chave=None)
    assert r == (None, None, None) and n == 0


def test_erro_429_segue_como_hoje():
    (r, n) = _rodar(detalhado, {"error": "too many requests"}, status=429)
    assert r == (None, None, None) and n == 1


def test_so_chama_a_tomtom_se_nominatim_e_google_falharem():
    aceito = [{"lat": "-22.71", "lon": "-42.81", "addresstype": "road", "type": "residential"}]
    (r, n) = _rodar(detalhado, tomtom("Point Address"), nominatim=aceito)
    assert r == (-22.71, -42.81, "rua") and n == 0, (r, n)


def test_limite_por_avaliacao():
    def rodar_alem_do_limite():
        for _ in range(ag2.LIMITE_TOMTOM_POR_AVALIACAO + 5):
            ag2._geocodificar_tomtom(END, "Itaboraí")
        return ag2.contagem_tomtom()
    (contagem, n) = _rodar(rodar_alem_do_limite, tomtom("Point Address"))
    assert n == ag2.LIMITE_TOMTOM_POR_AVALIACAO and contagem["chamadas"] == ag2.LIMITE_TOMTOM_POR_AVALIACAO
    # Depois do limite, nenhuma chamada nova: o anuncio fica sem localizacao (zona nao verificada).
    (r, n) = _rodar(lambda: (ag2._TOMTOM.update(chamadas=ag2.LIMITE_TOMTOM_POR_AVALIACAO), detalhado())[1],
                    tomtom("Point Address"))
    assert r == (None, None, None) and n == 0


def test_fallback_completo_grava_o_nivel_da_tomtom_e_conta_no_banco():
    def rodar():
        r = ag2._geocodificar_com_fallback(endereco_principal=END, rua="Rua Nossa Senhora da Conceição",
                                           bairro="JARDIM ITAJUBA", cidade="Itaboraí", estado="RJ")
        from services.registro_execucao import montar_registro
        e, _ = montar_registro(id_execucao="x", imovel_alvo={}, leilao_entrada={}, leilao={},
                               imoveis_coletados=[], resultado_ag2={}, zona_resultado={}, resultado_ag3={},
                               resultado_ag4={}, resultado_ag5={})
        return r, e["fontes"]
    ((r, fontes), _) = _rodar(rodar, tomtom("Street"))
    assert r[:3] == (-22.70, -42.80, "rua"), r
    assert fontes["tomtom_localizacoes"] == 1 and fontes["tomtom_chamadas"] == 1, fontes



# ---------------------------------------------------------------- Google parcial x bairro
def google_rua(bairro=None, parcial=True, lat=-22.84, lon=-42.80):
    componentes = [{"long_name": "Rua Nossa Senhora da Conceição", "types": ["route"]},
                   {"long_name": "Itaboraí", "types": ["administrative_area_level_2", "political"]}]
    if bairro:
        componentes.insert(1, {"long_name": bairro, "types": ["sublocality_level_1", "sublocality", "political"]})
    item = {"types": ["route"], "address_components": componentes,
            "geometry": {"location": {"lat": lat, "lng": lon}, "location_type": "GEOMETRIC_CENTER"}}
    if parcial:
        item["partial_match"] = True
    return {"results": [item]}


def detalhado_com_bairro():
    return ag2._geocodificar_detalhado(END, cidade_esperada="Itaboraí", bairro_esperado="JARDIM ITAJUBA")


def test_google_parcial_com_bairro_diferente_cai_na_tomtom():
    # Itaborai: o Google achou a rua homonima em Pachecos; a TomTom acertou.
    (r, n) = _rodar(detalhado_com_bairro, tomtom("Cross Street", lat=-22.7018, lon=-42.8767),
                    google=google_rua("Pachecos"))
    assert r == (-22.7018, -42.8767, "rua") and n == 1, (r, n)


def test_google_parcial_com_o_mesmo_bairro_e_aceito():
    (r, n) = _rodar(detalhado_com_bairro, tomtom("Point Address"), google=google_rua("Jardim Itajubá"))
    assert r == (-22.84, -42.80, "rua") and n == 0, (r, n)          # sem acento/maiusculas


def test_google_parcial_sem_bairro_e_recusado():
    (r, n) = _rodar(detalhado_com_bairro, {"results": []}, google=google_rua(None))
    assert r == (None, None, None) and n == 1, (r, n)


def test_google_sem_partial_match_aceito_como_hoje():
    (r, n) = _rodar(detalhado_com_bairro, tomtom("Point Address"), google=google_rua("Pachecos", parcial=False))
    assert r == (-22.84, -42.80, "rua") and n == 0, (r, n)


# ---------------------------------------------------------------- Palhoca, 29/10/2026
END_P = "Avenida Caravelas, 364, Praia Do Sonho, Palhoça, SC, Brasil"


def test_tomtom_com_outra_rua_e_recusada():
    # Pesquisada a Avenida Caravelas; a TomTom devolveu a Estrada Geral, a 2,1 km.
    resp = tomtom("Street", municipio="Palhoça")
    resp["results"][0]["address"]["streetName"] = "Estrada Geral Praia do Sonho"
    (r, n) = _rodar(lambda: ag2._geocodificar_detalhado(END_P, cidade_esperada="Palhoça",
                                                        rua_esperada="Avenida Caravelas"), resp)
    assert r == (None, None, None) and n == 1, r
    # A mesma rua (com ou sem prefixo) e aceita; Cross Street basta uma das duas.
    resp["results"][0]["address"]["streetName"] = "Av. Caravelas"
    (r, _) = _rodar(lambda: ag2._geocodificar_detalhado(END_P, cidade_esperada="Palhoça",
                                                        rua_esperada="Avenida Caravelas"), resp)
    assert r[2] == "rua", r
    # Abreviacao: Rio Largo, a CAIXA escreve "DR EMILIO MAIA" e a TomTom "Doutor Emilio de Maia".
    resp["results"][0]["address"]["streetName"] = "Rua Doutor Emílio de Maia"
    (r, _) = _rodar(lambda: ag2._geocodificar_detalhado(END_P, cidade_esperada="Palhoça",
                                                        rua_esperada="RUA DR EMILIO MAIA"), resp)
    assert r[2] == "rua", r
    cross = tomtom("Cross Street", municipio="Palhoça")
    cross["results"][0]["address"]["streetName"] = "Rua Ijui & Avenida Caravelas"
    (r, _) = _rodar(lambda: ag2._geocodificar_detalhado(END_P, cidade_esperada="Palhoça",
                                                        rua_esperada="Avenida Caravelas"), cross)
    assert r[2] == "rua", r


def test_google_com_bairro_entre_parenteses_e_aceito():
    g = google_rua("Praia do Sonho (Ens Brito)")
    (r, n) = _rodar(lambda: ag2._geocodificar_detalhado(END_P, cidade_esperada="Palhoça",
                                                        bairro_esperado="Praia Do Sonho"), tomtom("Street"), google=g)
    assert r == (-22.84, -42.80, "rua") and n == 0, (r, n)


def test_nominatim_highway_residential_e_rua():
    via = [{"lat": "-27.8343", "lon": "-48.5919", "class": "highway", "type": "residential",
            "addresstype": "residential"}]
    (r, n) = _rodar(lambda: ag2._geocodificar_detalhado(END_P), tomtom("Street"), nominatim=via)
    assert r == (-27.8343, -48.5919, "rua") and n == 0, r
    loteamento = [{"lat": "-27.83", "lon": "-48.59", "class": "landuse", "type": "residential",
                   "addresstype": "residential"}]
    (r, _) = _rodar(lambda: ag2._geocodificar_detalhado(END_P), tomtom("Street"), nominatim=loteamento)
    assert r[2] == "bairro", r


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
