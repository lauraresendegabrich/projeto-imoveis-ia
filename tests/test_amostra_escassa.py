"""
Correcoes da reavaliacao dos "Sem estimativa" (29/10/2026):
  - Agente 1: com o alvo localizado, o Apify raspa tambem a pagina da cidade (so
    VivaReal); os anuncios de fora da rua/bairro ficam com origem_busca="cidade" e
    so entram pela zona. A cidade lida da URL do anuncio reconhece cidade de varias
    palavras (Rio Largo, Cruzeiro do Sul). "Rua X, SN" e a mesma rua.
  - Agente 2: zona estendida no mesmo bairro ate 2,5 km quando faltam confirmados;
    coordenada do portal a mais de 50 km e descartada; areas absurdas fora da media.
  - IA: tolerancia de quartos e banheiros maior em casa grande; amenidade nao informada no alvo
    nao rebaixa.
Sem rede.

    .venv/Scripts/python.exe -m tests.test_amostra_escassa
"""
import logging
import sys

sys.path.insert(0, ".")
logging.disable(logging.CRITICAL)

from agents import comparables
from agents.collector import (
    _aplicar_escopo, _chave_rua, _cidade_incompativel, _mesma_rua, _montar_urls_listagem, _normalizar_ocrad,
    _separar_bairro_cidade,
)
from agents.comparables import (
    _calcular_estatisticas_areas, _classificar_imovel_na_zona, _completar_mesmo_bairro,
    _montar_prompt_clustering, _tolerancia_comodos,
)
from services.leilao import contar_status_zona, texto_aviso_zona

ALVO_LAT, ALVO_LON = -9.518847, -35.7775149


# ---------------------------------------------------------------- Agente 1
def test_pagina_da_cidade_so_com_o_alvo_localizado():
    sem = [u for u, _ in _montar_urls_listagem("house", "Jardim Paulista", "Paraíso do Tocantins", "TO")]
    com = [u for u, _ in _montar_urls_listagem("house", "Jardim Paulista", "Paraíso do Tocantins", "TO",
                                               incluir_cidade=True)]
    cidade = [u for u in com if u not in sem]
    assert len(sem) == 4 and cidade == [
        "https://www.vivareal.com.br/venda/tocantins/paraiso-do-tocantins/casa_residencial/",
        "https://www.vivareal.com.br/venda/tocantins/paraiso-do-tocantins/lote-terreno_residencial/",
    ], cidade


def test_escopo_mantem_o_resto_da_cidade_para_a_zona_decidir():
    no_bairro = {"id": 1, "neighborhood": "Jardim Paulista", "city": "Paraíso do Tocantins", "origem_busca": "cidade"}
    outro_bairro = {"id": 2, "neighborhood": "Centro", "city": "Paraíso do Tocantins", "origem_busca": "cidade"}
    outra_cidade = {"id": 3, "neighborhood": "Plano Diretor Sul", "city": "Palmas", "origem_busca": "cidade"}
    mantidos, escopo = _aplicar_escopo([no_bairro, outro_bairro, outra_cidade], rua="", bairro="Jardim Paulista",
                                       cidade="Paraíso do Tocantins")
    assert [m["id"] for m in mantidos] == [1, 2] and escopo == "rua+bairro+proximidade", (mantidos, escopo)
    assert "origem_busca" not in no_bairro and outro_bairro["origem_busca"] == "cidade"


def test_cidade_e_bairro_pela_url_do_anuncio():
    vr = "https://www.vivareal.com.br/imovel/"
    assert _separar_bairro_cidade(vr + "lote-terreno-tabuleiro-do-pinto-bairros-rio-largo-179m2-venda-id-1/") == \
        ("tabuleiro do pinto", "rio largo")
    # Sem "-bairros-": a cidade do alvo (antes "rio-largo" virava "Largo" e saia como outra cidade).
    assert _separar_bairro_cidade(vr + "lote-terreno-rio-largo-161m2-venda-id-2/", "RIO LARGO") == (None, "rio largo")
    assert _separar_bairro_cidade(vr + "casa-3-quartos-cruzeiro-do-sul-com-garagem-131m2-venda-id-3/",
                                  "CRUZEIRO DO SUL") == (None, "cruzeiro do sul")
    assert _separar_bairro_cidade(vr + "apartamento-2-quartos-vila-olimpia-sao-paulo-com-garagem-id-5/") == \
        ("vila olimpia", "sao paulo")
    assert _separar_bairro_cidade(vr + "casa-3-quartos-centro-londrina-com-garagem-id-6/", "Maringá") == \
        ("centro", "londrina")
    im = _normalizar_ocrad({"url": vr + "casa-3-quartos-cruzeiro-do-sul-com-garagem-131m2-venda-RS350000-id-3/",
                            "price": "R$ 350.000", "location": "Av.Vitoria Régia"}, cidade_alvo="CRUZEIRO DO SUL")
    assert im["city"] == "Cruzeiro Do Sul" and not _cidade_incompativel(im, "CRUZEIRO DO SUL"), im["city"]


def test_rua_sem_numero():
    assert _chave_rua("Rua Tenente Joaquim Rabelo de Matos, SN") == "tenente joaquim rabelo de matos"
    assert _chave_rua("Rua das Flores S/N") == "das flores"
    assert _mesma_rua("Rua Tenente Joaquim Rabelo de Matos, SN", "Rua Tenente Joaquim Rabelo de Matos")
    assert _chave_rua("Rua Sns") == "sns"


# ---------------------------------------------------------------- Agente 2: zona
def _anuncio(dist, bairro="Cidade Universitária", nivel="coordenadas_athena"):
    return {"url": f"https://x/{dist}-{bairro}", "distancia_metros": dist, "geocodificacao_nivel": nivel,
            "neighborhood": bairro, "classificacao_zona": "fora_zona"}


def test_mesmo_bairro_completa_ate_2500_m():
    confirmados = [_anuncio(900)] * 4
    fora = [_anuncio(1800), _anuncio(2400), _anuncio(2600), _anuncio(1700, bairro="Tabuleiro"),
            _anuncio(1600, nivel="bairro")]
    # Faltava 1: o raio cresce x1,5 (2250 m) e para quando chega a 5.
    entram, resto, raio = _completar_mesmo_bairro(confirmados, fora, 1500, "CIDADE UNIVERSITARIA")
    assert [e["distancia_metros"] for e in entram] == [1800] and raio == 2250, (entram, raio)
    assert entram[0]["incluido_por_mesmo_bairro"] and entram[0]["incluido_por_fallback_zona"]
    assert len(resto) == 4
    # Faltavam 2: vai ate o limite (2500 m); 2600 m, outro bairro e centro do bairro ficam fora.
    fora = [_anuncio(1800), _anuncio(2400), _anuncio(2600), _anuncio(1700, bairro="Tabuleiro"),
            _anuncio(1600, nivel="bairro")]
    entram, resto, raio = _completar_mesmo_bairro(confirmados[:3], fora, 1500, "CIDADE UNIVERSITARIA")
    assert [e["distancia_metros"] for e in entram] == [1800, 2400] and raio == 2500, (entram, raio)
    assert {r["distancia_metros"] for r in resto} == {2600, 1700, 1600}


def test_mesmo_bairro_nao_age_com_5_confirmados_ou_sem_bairro():
    fora = [_anuncio(1800)]
    assert _completar_mesmo_bairro([_anuncio(100)] * 5, fora, 1500, "Cidade Universitária")[0] == []
    assert _completar_mesmo_bairro([], fora, 1500, "")[0] == []
    assert "incluido_por_mesmo_bairro" not in fora[0]


def test_coordenada_do_portal_em_outro_estado_e_descartada():
    original = comparables._geocodificar_com_fallback
    comparables._geocodificar_com_fallback = lambda **_: (None, None, None, None)
    try:
        im = {"lat": -23.5, "lon": -46.6, "neighborhood": "Cidade Universitária", "url": "https://x/1"}
        classe = _classificar_imovel_na_zona(im, ALVO_LAT, ALVO_LON, 1500, "Maceió", "AL")
        assert classe == "zona_nao_verificada" and im["coordenada_portal_descartada"] == {"lat": -23.5, "lon": -46.6}
        perto = {"lat": ALVO_LAT + 0.005, "lon": ALVO_LON, "url": "https://x/2"}
        assert _classificar_imovel_na_zona(perto, ALVO_LAT, ALVO_LON, 1500, "Maceió", "AL") == "na_zona"
    finally:
        comparables._geocodificar_com_fallback = original


def test_area_absurda_fora_da_media():
    casas = [{"area": 250}, {"area": 350}, {"area": 2_790_041}]
    est = _calcular_estatisticas_areas(casas, {"propertyType": "Apartamentos"})
    assert est["media_area_construida"] == 300.0 and est["amostras_area_construida"] == 2, est


def test_aviso_de_leilao_com_mesmo_bairro():
    ag5 = {"comparaveis_usados": {"construcao": [{"status_zona": "confirmado"}] * 4 + [{"status_zona": "mesmo_bairro"}] * 3}}
    contagem = contar_status_zona(ag5)
    assert contagem["mesmo_bairro"] == 3 and contagem["total"] == 7
    assert texto_aviso_zona(contagem) == (
        "Só 4 dos 7 comparáveis foram confirmados perto do imóvel (dentro da zona homogênea). 3 estão no "
        "mesmo bairro, um pouco mais longe (até 2,5 km), e entraram para completar o mínimo de 5. "
        "Confira esses anúncios antes de decidir.")


# ---------------------------------------------------------------- IA
CASA = {"propertyType": "Casas", "area": 340, "bedrooms": 5, "bathrooms": 4}


def test_tolerancia_de_quartos():
    assert [_tolerancia_comodos(q) for q in (None, 2, 4, 5, 6, 7, 8)] == [1, 1, 1, 2, 2, 3, 3]
    grande = _montar_prompt_clustering({"propertyType": "Casas", "area": 360, "bedrooms": 8}, [CASA])
    assert "ATE 3 QUARTOS (candidato com 5 a 11)" in grande
    pequena = _montar_prompt_clustering({"propertyType": "Casas", "area": 55, "bedrooms": 2}, [CASA])
    assert "ATE 1 QUARTO" in pequena and "casa grande" not in pequena


def test_tolerancia_de_banheiros():
    # Palhoca: alvo com 6 banheiros, casas parecidas com 4.
    grande = _montar_prompt_clustering({"propertyType": "Casas", "area": 360, "bedrooms": 8, "bathrooms": 6}, [CASA])
    assert "ATE 2 BANHEIROS (candidato com\n   4 a 8)" in grande, grande
    assert "quartos e banheiros dentro da tolerancia" in grande
    pequena = _montar_prompt_clustering({"propertyType": "Casas", "area": 55, "bedrooms": 2, "bathrooms": 1}, [CASA])
    assert "BANHEIROS" not in pequena


def test_amenidade_nao_informada_no_alvo_nao_rebaixa():
    caixa = {"propertyType": "Casas", "area": 55, "bedrooms": 2,
             "description": "2 Quartos, Varanda/sacada, Área de Serviço, Wc, Sala, Cozinha"}
    prompt = _montar_prompt_clustering(caixa, [CASA])
    assert "o alvo NAO informa a ausencia de nenhuma amenidade" in prompt
    assert "CONJUNTO EXPRESSIVO" not in prompt


def test_prompt_pede_para_nao_citar_o_terreno():
    assert "Nao cite o terreno na justificativa." in _montar_prompt_clustering(CASA, [CASA], terreno_corrigido=True)


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
