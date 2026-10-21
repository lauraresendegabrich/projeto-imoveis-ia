"""
Checagem do proprio anuncio: provas mais fortes que a descricao (link do anuncio,
foto em comum, codigo da imobiliaria) e descricao sem o rodape da imobiliaria. Sem rede.

    .venv/Scripts/python.exe -m tests.test_provas_anuncio_alvo
"""
import logging
import sys

sys.path.insert(0, ".")
logging.disable(logging.CRITICAL)

import agents.comparables as ag2

LINK_VR = "https://www.vivareal.com.br/imovel/casa-8-quartos-praia-do-sonho-ens-brito-palhoca-360m2-venda-RS1200000-id-2903862416/"
FOTO_1 = "https://resizedimgs.vivareal.com/img/vr-listing/26503686aee82ce91049daff6f4cce0e/{description}.jpg?action=fit-in&dimension=870x707"
FOTO_1_ZAP = "https://resizedimgs.zapimoveis.com.br/img/vr-listing/26503686aee82ce91049daff6f4cce0e/casa.webp?dimension=614x297"
FOTO_2 = "https://resizedimgs.vivareal.com/img/vr-listing/ca1b70eddffe3688258c79699994399f/{description}.jpg"
RODAPE = "Agende sua visita!<br>Atendemos sábado, domingo e feriado.(Plantão de vendas)<br>Pagani Imóveis<br>CRECI 1234-J"

ALVO = {"rua": "", "numero": "", "bairro": "Praia do Sonho", "neighborhood": "Praia do Sonho", "cidade": "Palhoça",
        "estado": "SC", "tipo": "house", "propertyType": "Casas", "area": 360.0, "bedrooms": 8, "bathrooms": 6,
        "parkingSpaces": 2, "description": "Casa na praia", "descricao_gerada": True, "images": []}


def anuncio(**extra):
    base = {"portal": "vivareal", "listing_id": "2903862416", "url": LINK_VR, "propertyType": "Casas",
            "tipo": "casa", "price": 1200000.0, "area": 360.0, "bedrooms": 8, "bathrooms": 6,
            "parkingSpaces": 2, "neighborhood": "Praia do Sonho", "description": "", "images": []}
    base.update(extra)
    return base


# ---------------------------------------------------------------- (a) link
def test_a1_link_igual_confirma_mesmo_com_veto():
    # 5 quartos x 8: ha veto de atributo, mas o link prova que e o anuncio.
    eh, _, sinais, _ = ag2._eh_anuncio_do_alvo(dict(ALVO, link_anuncio=LINK_VR), anuncio(bedrooms=5))
    assert eh and sinais == ["link_do_anuncio(grupozap:2903862416)"], sinais


def test_a2_link_do_zap_reconhece_o_mesmo_id_do_vivareal():
    link_zap = "https://www.zapimoveis.com.br/imovel/venda-casa-8-quartos-palhoca-sc-360m2-id-2903862416/?source=x"
    eh, _, _, _ = ag2._eh_anuncio_do_alvo(dict(ALVO, link_anuncio=link_zap), anuncio(url="https://vr/x"))
    assert eh


def test_a3_link_diferente_nao_muda():
    outro = LINK_VR.replace("2903862416", "2811111111")
    sem_link = ag2._eh_anuncio_do_alvo(ALVO, anuncio())
    com_outro = ag2._eh_anuncio_do_alvo(dict(ALVO, link_anuncio=outro), anuncio())
    assert sem_link == com_outro, (sem_link, com_outro)
    assert not com_outro[0]


def test_a4_link_vale_contra_a_duplicata_absorvida():
    orig = ag2._geocodificar_alvo_identidade
    ag2._geocodificar_alvo_identidade = lambda alvo: None
    try:
        dup = anuncio()
        rep = anuncio(portal="imovelweb", listing_id="3047426520", url="https://www.imovelweb.com.br/x-3047426520.html")
        rep["duplicatas"] = [{"portal": "vivareal", "listing_id": "2903862416", "dados_identidade": dup}]
        n = ag2._marcar_anuncio_do_alvo(dict(ALVO, link_anuncio=LINK_VR), [rep])
    finally:
        ag2._geocodificar_alvo_identidade = orig
    assert n == 1 and rep.get("eh_anuncio_do_alvo")
    sinais = rep["checagem_alvo"]["sinais"]
    assert rep["checagem_alvo"]["resultado"] == "confirmado"
    assert "link_do_anuncio(grupozap:2903862416)" in sinais and any(s.startswith("via_duplicata") for s in sinais), sinais


# ---------------------------------------------------------------- (b) foto
def test_b1_casa_com_foto_em_comum_confirma():
    eh, _, sinais, _ = ag2._eh_anuncio_do_alvo(dict(ALVO, images=[FOTO_1_ZAP]), anuncio(images=[FOTO_2, FOTO_1]))
    assert eh and "foto_em_comum(26503686aee82ce91049daff6f4cce0e)" in sinais, sinais


def test_b2_casa_com_foto_em_comum_e_veto_so_suspeita():
    eh, suspeito, _, _ = ag2._eh_anuncio_do_alvo(dict(ALVO, images=[FOTO_1]), anuncio(images=[FOTO_1], bedrooms=4))
    assert not eh and suspeito


def test_b3_apto_com_foto_em_comum_so_suspeita():
    alvo = dict(ALVO, tipo="apartment", propertyType="Apartamentos", bedrooms=2, bathrooms=1, area=60.0,
                images=[FOTO_1])
    apto = anuncio(propertyType="Apartamentos", tipo="apartamento", bedrooms=2, bathrooms=1, area=60.0,
                   price=400000.0, images=[FOTO_1])
    eh, suspeito, sinais, _ = ag2._eh_anuncio_do_alvo(alvo, apto)
    assert not eh and suspeito and any(s.startswith("foto_em_comum") for s in sinais), sinais


def test_b4_fotos_diferentes_nao_contam():
    eh, _, sinais, _ = ag2._eh_anuncio_do_alvo(dict(ALVO, images=[FOTO_2]), anuncio(images=[FOTO_1]))
    assert not eh and not any(s.startswith("foto_em_comum") for s in sinais)


def test_b5_codigo_da_foto_ignora_tamanho_e_parametros():
    assert ag2._codigos_fotos([FOTO_1]) == ag2._codigos_fotos([FOTO_1_ZAP]) == {"26503686aee82ce91049daff6f4cce0e"}
    iw = "https://imgbr.imovelwebcdn.com/avisos/2/30/22/01/09/86/720x532/7134732301.jpg?isFirstImage=true"
    assert ag2._codigos_fotos([iw]) == ag2._codigos_fotos([iw.replace("720x532", "360x266").split("?")[0]])


# ---------------------------------------------------------------- (c) codigo
DESC_A = "CÓDIGO DO IMÓVEL : CA0406<br>Casa ampla perto da praia."
DESC_B = "Cód. CA0406 - Casa com 8 quartos, piscina e espaço gourmet."


def test_c1_mesmo_codigo_da_imobiliaria_confirma():
    eh, _, sinais, _ = ag2._eh_anuncio_do_alvo(dict(ALVO, description=DESC_A, descricao_gerada=False),
                                               anuncio(description=DESC_B))
    assert eh and "codigo_imobiliaria(CA0406)" in sinais, sinais


def test_c2_codigos_diferentes_nao_confirmam():
    eh, _, sinais, _ = ag2._eh_anuncio_do_alvo(dict(ALVO, description=DESC_A, descricao_gerada=False),
                                               anuncio(description=DESC_B.replace("CA0406", "CA0407")))
    assert not eh and not any(s.startswith("codigo_imobiliaria") for s in sinais), sinais


def test_c3_codigo_com_veto_nao_confirma():
    eh, _, _, _ = ag2._eh_anuncio_do_alvo(dict(ALVO, description=DESC_A, descricao_gerada=False),
                                          anuncio(description=DESC_B, bedrooms=3))
    assert not eh


def test_c4_extrai_so_codigos_com_letras_e_numeros():
    assert ag2._codigos_imobiliaria("Ref.: AP1234 | Referência 998877 | cod. 12") == {"AP1234"}


# ---------------------------------------------------------------- (d) rodape
def test_d1_rodape_sai_antes_de_comparar():
    assert ag2._sem_rodape("Casa com piscina e quintal.<br>" + RODAPE) == "Casa com piscina e quintal."


def test_d2_mesma_imobiliaria_so_com_rodape_em_comum_nao_confirma():
    casa_1 = ("Casa térrea com 3 quartos, sala ampla, cozinha planejada, quintal com churrasqueira e garagem "
              "para dois carros, perto de escola e mercado.<br>" + RODAPE)
    casa_2 = ("Sobrado com 4 suítes, piscina aquecida, espaço gourmet integrado e vista para o mar na Pinheira, "
              "acabamento de alto padrão.<br>" + RODAPE)
    assert ag2._similaridade_descricao(casa_1, casa_2) < 0.5, ag2._similaridade_descricao(casa_1, casa_2)
    eh, _, _, _ = ag2._eh_anuncio_do_alvo(dict(ALVO, description=casa_1, descricao_gerada=False, price=1200000.0),
                                          anuncio(description=casa_2))
    assert not eh


# ---------------------------------------------------------------- vagas: None x 0
APTO_ALVO = dict(ALVO, tipo="apartment", propertyType="Apartamentos", bedrooms=2, bathrooms=1, area=60.0,
                 rua="Rua A", street="Rua A", numero="100", price=400000.0, descricao_gerada=True)


def apto_anuncio(vagas):
    return anuncio(propertyType="Apartamentos", tipo="apartamento", bedrooms=2, bathrooms=1, area=60.0,
                   price=400000.0, street="Rua A", numero="100", parkingSpaces=vagas)


def test_e1_vagas_vazias_no_formulario_nao_vetam():
    _, _, sinais, _ = ag2._eh_anuncio_do_alvo(dict(APTO_ALVO, parkingSpaces=None), apto_anuncio(1))
    assert "veto_vagas" not in sinais, sinais


def test_e2_zero_vagas_e_sem_vaga_e_veta_quem_tem_vaga():
    _, _, sinais, _ = ag2._eh_anuncio_do_alvo(dict(APTO_ALVO, parkingSpaces=0), apto_anuncio(1))
    assert "veto_vagas" in sinais, sinais
    _, _, sinais, _ = ag2._eh_anuncio_do_alvo(dict(APTO_ALVO, parkingSpaces=0), apto_anuncio(0))
    assert "veto_vagas" not in sinais, sinais


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
