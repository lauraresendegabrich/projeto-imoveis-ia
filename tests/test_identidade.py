"""
Testes do teste de identidade (agents/identidade.py) e da marcacao do alvo no Ag2.
Sem rede: a geocodificacao do alvo e desligada.

    .venv/Scripts/python.exe -m tests.test_identidade
"""
import sys

sys.path.insert(0, ".")

import agents.comparables as comparables
from agents.identidade import deduplicar, mesmo_imovel

comparables._geocodificar = lambda endereco: (None, None)   # sem rede nos testes

DESC_APTO = (
    "Apartamento de 3 quartos com suite, sala ampla para dois ambientes, varanda, "
    "cozinha planejada, area de servico e duas vagas de garagem. Predio com elevador."
)
DESC_CASA = (
    "Casa com 3 quartos sendo uma suite, sala de estar, cozinha ampla, quintal com "
    "churrasqueira, garagem coberta para dois carros e area gourmet nos fundos."
)


def anuncio(**campos):
    base = {
        "portal": "vivareal", "source": "VivaReal", "tipo": "apartamento",
        "preco": 500000.0, "area_construida": 80.0, "quartos": 3, "vagas": 2, "suites": 1,
        "rua": "Rua Patagonia, 100", "bairro": "Sion", "descricao": DESC_APTO,
        "anunciante_nome": "Imobiliaria Alfa Ltda", "codigo_imovel_anunciante": "AP123",
        "listing_id": "1", "url": "https://exemplo/1",
    }
    base.update(campos)
    return base


def casa(**campos):
    base = anuncio(tipo="casa", area_construida=150.0, descricao=DESC_CASA, rua="Rua Lirica, 50",
                   bairro="Santa Monica", codigo_imovel_anunciante="CA9")
    base.update(campos)
    return base


# ---------------------------------------------------------------- entre anuncios
def test_mesmo_codigo_e_anunciante_em_portais_diferentes():
    a = anuncio()
    b = anuncio(portal="imovelweb", source="ImovelWeb", preco=650000.0, listing_id="9")
    assert mesmo_imovel(a, b) == (True, "mesmo_codigo_e_anunciante")


def test_mesmo_portal_mesmo_anunciante_codigos_diferentes_sao_imoveis_diferentes():
    a = anuncio()
    b = anuncio(codigo_imovel_anunciante="AP124", listing_id="2")
    assert mesmo_imovel(a, b) == (False, "veto_codigos_diferentes")


def test_apto_preco_identico_area_igual_outra_imobiliaria():
    a = anuncio(codigo_imovel_anunciante=None)
    b = anuncio(portal="chavesnamao", source="Chaves na Mão", anunciante_nome="Beta Imoveis",
                codigo_imovel_anunciante=None, preco=501000.0, area_construida=80.5, descricao="")
    igual, motivo = mesmo_imovel(a, b)
    assert igual and motivo.startswith("apto_preco_identico"), motivo


def test_apto_unidades_diferentes_mesmo_predio_vetadas_por_vagas():
    a = anuncio(codigo_imovel_anunciante=None)
    b = anuncio(codigo_imovel_anunciante=None, vagas=1, anunciante_nome="Beta", listing_id="2")
    assert mesmo_imovel(a, b) == (False, "veto_vagas")


def test_casa_geminada_mesmo_preco_sem_descricao_nao_e_fundida():
    # Casa exige preco + area + descricao: casas vizinhas da mesma construtora
    # tem preco e area iguais, mas sem descricao parecida nao ha prova. Num
    # condominio de casas o numero da rua e o mesmo para todas: nao serve de prova.
    a = casa(codigo_imovel_anunciante=None)
    b = casa(codigo_imovel_anunciante=None, portal="imovelweb", anunciante_nome="Beta",
             descricao="Casa nova em condominio fechado, acabamento de primeira, entrega imediata.")
    igual, motivo = mesmo_imovel(a, b)
    assert not igual and motivo.startswith("sem_prova"), motivo


def test_casa_mesma_rua_e_numero_dispensa_descricao():
    # Mesma casa em 2 portais, cada um com seu texto: rua+numero+preco+area bastam.
    a = casa(codigo_imovel_anunciante=None, rua="Rua Manoel Cesario Franca, 168", area_construida=179.0)
    b = casa(codigo_imovel_anunciante=None, portal="imovelweb", anunciante_nome="Beta",
             rua="R. Manoel Cesario Franca, nº 168", area_construida=181.0,
             descricao="Otima casa, venha conhecer, aceita financiamento bancario e FGTS, agende sua visita.")
    igual, motivo = mesmo_imovel(a, b)
    assert igual and motivo.startswith("casa_preco_area_rua_numero"), motivo


def test_casas_vizinhas_numeros_diferentes_nao_sao_fundidas():
    a = casa(codigo_imovel_anunciante=None, rua="Rua Lirica, 50")
    b = casa(codigo_imovel_anunciante=None, portal="imovelweb", anunciante_nome="Beta",
             rua="Rua Lirica, 52", descricao="Casa nova de construtora, entrega imediata, financiamento.")
    igual, motivo = mesmo_imovel(a, b)
    assert not igual and motivo.startswith("sem_prova"), motivo


def test_casa_em_condominio_num_portal_e_casa_no_outro_ainda_e_comparada():
    a = casa(codigo_imovel_anunciante=None, property_sub_type="CONDOMINIUM")
    b = casa(codigo_imovel_anunciante=None, portal="imovelweb", anunciante_nome="Beta",
             property_sub_type="Casas")
    igual, motivo = mesmo_imovel(a, b)
    assert igual and motivo.startswith("casa_preco_area_descricao"), motivo


def test_bairros_diferentes_vetam():
    a = anuncio(codigo_imovel_anunciante=None)
    b = anuncio(codigo_imovel_anunciante=None, anunciante_nome="Beta", bairro="Savassi",
                rua="Rua Pernambuco, 10")
    assert mesmo_imovel(a, b) == (False, "veto_local")


def test_terreno_nunca_e_fundido():
    a = anuncio(tipo="terreno", codigo_imovel_anunciante=None)
    b = anuncio(tipo="terreno", codigo_imovel_anunciante=None, portal="imovelweb")
    assert mesmo_imovel(a, b) == (False, "tipo_sem_regra_calibrada")


def test_mesmo_codigo_com_nome_da_imobiliaria_escrito_diferente():
    # Casos reais de Sao Jose do Rio Preto: cada portal escreve a imobiliaria de um jeito.
    a = casa(anunciante_nome="Habicarmo Imoveis", codigo_imovel_anunciante="CA1807",
             rua="Rua Marcelino Bertoni, 646")
    b = casa(portal="chavesnamao", source="Chaves na Mão", anunciante_nome="Habicarmo",
             codigo_imovel_anunciante="CA1807", rua="Rua Projetada, 646", listing_id="2")
    assert mesmo_imovel(a, b) == (True, "mesmo_codigo_e_anunciante")


def test_terreno_mesmo_codigo_e_anunciante_e_fundido():
    a = anuncio(tipo="terreno", preco=11200.0, area_construida=200.0, portal="chavesnamao",
                anunciante_nome="Sumares Negocios Imobiliarios", codigo_imovel_anunciante="TE00704")
    b = anuncio(tipo="terreno", preco=11200.0, area_construida=200.0, portal="imovelweb",
                anunciante_nome="Sumares Imoveis", codigo_imovel_anunciante="TE00704", listing_id="2")
    assert mesmo_imovel(a, b) == (True, "mesmo_codigo_e_anunciante")
    unicos, descartados = deduplicar([a, b])
    assert len(unicos) == 1 and len(descartados) == 1


def test_imobiliarias_diferentes_com_mesmo_codigo_nao_sao_fundidas():
    a = casa(anunciante_nome="Habicarmo Imoveis", codigo_imovel_anunciante="CA10")
    b = casa(portal="imovelweb", anunciante_nome="Villaggio Imoveis", codigo_imovel_anunciante="CA10",
             preco=900000.0, listing_id="2")
    assert mesmo_imovel(a, b)[0] is False



# ---------------------------------------------------------------- area entre portais
def _par(area_a, area_b, tipo="casa", extra_a=None):
    """Mesmo imovel em 2 portais (mesmo codigo e anunciante), areas diferentes.
    O primeiro tem mais campos (fica como representante)."""
    a = casa(tipo=tipo, preco=590000.0, area_construida=area_a, codigo_imovel_anunciante="CA77",
             anunciante_nome="Imobiliaria Paes", portal="vivareal", source="VivaReal",
             listing_id="1", url="https://vr/1", vagas=2, **(extra_a or {}))
    b = casa(tipo=tipo, preco=590000.0, area_construida=area_b, codigo_imovel_anunciante="CA77",
             anunciante_nome="Imobiliaria Paes Imoveis", portal="chavesnamao", source="Chaves na Mão",
             listing_id="2", url="https://cnm/2", vagas=None, suites=None)
    unicos, descartados = deduplicar([a, b])
    assert len(unicos) == 1 and len(descartados) == 1
    return unicos[0]


def test_area_divergente_usa_a_menor_quando_o_mais_completo_tem_a_maior():
    # Curitiba R$ 590.000: 80 m2 num portal e 110 m2 (area do terreno) no outro.
    rep = _par(110.0, 80.0)
    assert rep["area"] == 80.0 and rep["area_construida"] == 80.0, rep.get("area")
    assert rep["area_original"] == 110.0
    assert sorted(a["area"] for a in rep["areas_entre_portais"]) == [80.0, 110.0]


def test_area_divergente_ja_com_a_menor_so_marca():
    rep = _par(80.0, 110.0)
    assert rep["area_construida"] == 80.0 and "area_original" not in rep
    assert len(rep["areas_entre_portais"]) == 2


def test_area_ate_5_por_cento_nao_muda_nada():
    rep = _par(104.0, 100.0)
    assert rep["area_construida"] == 104.0 and "areas_entre_portais" not in rep


def test_terreno_com_area_divergente_mantem_e_marca():
    rep = _par(720.0, 600.0, tipo="terreno")
    assert rep["area_construida"] == 720.0 and "area_original" not in rep
    assert len(rep["areas_entre_portais"]) == 2

# ---------------------------------------------------------------- deduplicar
def test_deduplicar_guarda_descartado_completo_e_motivo():
    a = anuncio(listing_id="1", url="https://vr/1")
    b = anuncio(portal="imovelweb", source="ImovelWeb", listing_id="9", url="https://iw/9", fotos_urls=None)
    c = anuncio(codigo_imovel_anunciante=None, preco=900000.0, area_construida=120.0, listing_id="3")
    unicos, descartados = deduplicar([a, b, c])
    assert len(unicos) == 2 and len(descartados) == 1
    rep = next(u for u in unicos if u.get("duplicatas"))
    assert rep["duplicatas"][0]["motivo"] == "mesmo_codigo_e_anunciante"
    assert set(rep["fontes_origem"]) == {"VivaReal", "ImovelWeb"}
    d = descartados[0]
    assert d["duplicata_de"]["url"] == rep["url"] and d["motivo_duplicata"] == "mesmo_codigo_e_anunciante"
    assert d["descricao"] == DESC_APTO   # registro completo


def test_deduplicar_compara_milhares_vizinhos():
    # R$ 450.400 e R$ 450.600 (0,04%) caem em milhares diferentes
    a = anuncio(codigo_imovel_anunciante=None, preco=450400.0)
    b = anuncio(codigo_imovel_anunciante=None, preco=450600.0, portal="imovelweb",
                anunciante_nome="Beta", listing_id="2")
    unicos, descartados = deduplicar([a, b])
    assert len(unicos) == 1 and len(descartados) == 1


def test_deduplicar_nao_junta_unidades_do_mesmo_anunciante_via_outro_portal():
    # Lancamento: o anuncio do VivaReal bate com 2 unidades do ImovelWeb (mesmo
    # preco/area), mas as 2 sao do mesmo anunciante com codigos diferentes =
    # unidades diferentes. So uma pode ficar no grupo.
    rep = anuncio(codigo_imovel_anunciante=None, anunciante_nome="Construtora X")
    u1 = anuncio(portal="imovelweb", source="ImovelWeb", anunciante_nome="Inova",
                 codigo_imovel_anunciante="U101", listing_id="a", url="https://iw/a", descricao="")
    u2 = anuncio(portal="imovelweb", source="ImovelWeb", anunciante_nome="Inova",
                 codigo_imovel_anunciante="U102", listing_id="b", url="https://iw/b", descricao="")
    unicos, descartados = deduplicar([rep, u1, u2])
    assert len(descartados) == 1 and len(unicos) == 2


# ---------------------------------------------------------------- alvo (Ag2)
def alvo_apto(**campos):
    base = {
        "tipo": "apartment", "propertyType": "Apartamentos", "rua": "Rua Patagonia", "numero": "100",
        "bairro": "Sion", "cidade": "Belo Horizonte", "estado": "MG", "area": 80.0,
        "bedrooms": 3, "bathrooms": 2, "parkingSpaces": 2,
        "description": "Apartamento com 80m², 3 quartos", "descricao_gerada": True,
    }
    base.update(campos)
    return base


def alvo_casa(**campos):
    base = alvo_apto(tipo="house", propertyType="Casas", rua="Rua Lirica", numero="50",
                     bairro="Santa Monica", area=150.0)
    base.update(campos)
    return base


def test_alvo_apto_com_preco_identico_confirma():
    eh, poss, sinais, _ = comparables._eh_anuncio_do_alvo(alvo_apto(price=500000), anuncio())
    assert eh and not poss, sinais


def test_alvo_sem_preco_apto_rua_numero_sem_unidade_nao_confirma():
    eh, poss, sinais, _ = comparables._eh_anuncio_do_alvo(alvo_apto(), anuncio())
    assert not eh and "mesma_rua_e_numero" in sinais, sinais


def test_alvo_sem_preco_casa_rua_numero_confirma():
    eh, _, sinais, _ = comparables._eh_anuncio_do_alvo(alvo_casa(), casa())
    assert eh and "mesma_rua_e_numero" in sinais, sinais


def test_alvo_casa_preco_identico_sem_descricao_real_fica_suspeito():
    # Descricao gerada pela interface nao prova nada: casa com preco e area
    # iguais mas sem rua+numero vira so suspeita.
    eh, poss, sinais, _ = comparables._eh_anuncio_do_alvo(
        alvo_casa(price=500000, numero="", rua=""), casa())
    assert not eh and poss, sinais



def test_alvo_bairro_escrito_diferente_gera_alerta_e_continua_no_calculo():
    # Palhoca (20/10/2026): o formulario tinha "Praia Do Sonho Ens Brito" e o portal
    # "Praia do Sonho". Sem descricao e sem rua+numero, nao confirma; mas o perfil bate
    # (mesmo preco, area e comodos) e agora vira "possivel anuncio do proprio imovel".
    alvo = alvo_casa(rua="", numero="", bairro="Praia Do Sonho Ens Brito", area=360.0, bedrooms=8,
                     bathrooms=6, parkingSpaces=2, price=1200000)
    comp = casa(rua="", bairro="Praia do Sonho", area_construida=360.0, quartos=8, banheiros=6, vagas=2,
                preco=1200000.0, descricao="Casa com 8 quartos sendo 6 suites, piscina e area gourmet perto da praia.")
    eh, poss, sinais, _ = comparables._eh_anuncio_do_alvo(alvo, comp)
    assert not eh and poss and "mesmo_bairro" in sinais, sinais


def test_alvo_bairros_diferentes_nao_gera_alerta():
    alvo = alvo_casa(rua="", numero="", bairro="Pinheira", area=360.0, bedrooms=8, bathrooms=6,
                     parkingSpaces=2, price=1200000)
    comp = casa(rua="", bairro="Praia do Sonho", area_construida=360.0, quartos=8, banheiros=6, vagas=2,
                preco=1200000.0)
    eh, poss, sinais, _ = comparables._eh_anuncio_do_alvo(alvo, comp)
    assert not eh and not poss and "mesmo_bairro" not in sinais, sinais

def test_alvo_vagas_nao_informadas_nao_veta():
    # Vagas vazias no formulario (None) = nao informado. Desde 20/10/2026, 0 = sem vaga
    # e veta o anuncio com 2 vagas (tests/test_provas_anuncio_alvo.py).
    eh, _, sinais, _ = comparables._eh_anuncio_do_alvo(alvo_apto(price=500000, parkingSpaces=None), anuncio())
    assert eh, sinais
    eh, _, sinais, _ = comparables._eh_anuncio_do_alvo(alvo_apto(price=500000, parkingSpaces=0), anuncio())
    assert not eh and "veto_vagas" in sinais, sinais


def test_alvo_quartos_diferentes_sem_outro_sinal_nao_marca():
    eh, poss, sinais, _ = comparables._eh_anuncio_do_alvo(
        alvo_apto(price=900000, bedrooms=2, rua="", numero=""), anuncio(rua=""))
    assert not eh and not poss and "veto_quartos" in sinais, sinais


def test_alvo_veto_de_vagas_com_preco_identico_fica_suspeito():
    # Caso real (Sion): mesmo texto, preco e area do alvo, mas o anuncio diz 1 vaga
    # em vez de 3 (erro de digitacao). O veto impede confirmar, mas marca suspeito.
    eh, poss, sinais, _ = comparables._eh_anuncio_do_alvo(
        alvo_apto(price=500000, parkingSpaces=3), anuncio(vagas=1, rua="Rua Patagonia, 400"))
    assert not eh and poss and "veto_vagas" in sinais, sinais


def test_alvo_casa_coordenadas_iguais_e_area_confirmam():
    alvo = alvo_casa(lat_identidade=-19.9400, lon_identidade=-43.9300, rua="", numero="")
    comp = casa(lat=-19.94005, lon=-43.93004, rua="")
    eh, _, sinais, _ = comparables._eh_anuncio_do_alvo(alvo, comp)
    assert eh and "coordenadas_iguais" in sinais, sinais


def test_alvo_coordenada_da_interface_sem_numero_nao_confirma():
    # Caso real (casa no Santa Monica): a interface preenche lat/lon do alvo mesmo
    # sem numero (ponto qualquer da rua). Isso nao pode confirmar identidade.
    alvo = alvo_casa(lat=-19.9400, lon=-43.9300, numero="", price=900000)
    comp = casa(lat=-19.94005, lon=-43.93004)
    comparables._marcar_anuncio_do_alvo(alvo, [comp])
    assert "lat_identidade" not in alvo
    assert not comp.get("eh_anuncio_do_alvo"), comp.get("match_alvo_sinais")


def test_alvo_apto_coordenadas_iguais_so_suspeito():
    # No apto a coordenada e a do predio: vale para todas as unidades.
    alvo = alvo_apto(lat_identidade=-19.9400, lon_identidade=-43.9300, rua="", numero="")
    comp = anuncio(lat=-19.94005, lon=-43.93004, rua="", bairro="")
    eh, poss, sinais, _ = comparables._eh_anuncio_do_alvo(alvo, comp)
    assert not eh and poss and "coordenadas_iguais" in sinais, sinais


def test_alvo_testado_contra_duplicatas_absorvidas():
    # O representante nao bate com o alvo (outro preco), mas o anuncio absorvido bate.
    rep = anuncio(preco=520000.0, rua="", codigo_imovel_anunciante=None)
    rep["duplicatas"] = [{"portal": "imovelweb", "listing_id": "9",
                          "dados_identidade": anuncio(portal="imovelweb", rua="")}]
    comparables._marcar_anuncio_do_alvo(alvo_apto(price=500000, rua="", numero=""), [rep])
    assert rep.get("eh_anuncio_do_alvo") is True
    assert any(s.startswith("via_duplicata(imovelweb:9)") for s in rep["match_alvo_sinais"])


# ---------------------------------------------------------------- condominio e area diferente (21/10/2026)
def test_pode_ser_condominio_so_com_indicio_real():
    from agents.identidade import _pode_ser_condominio as cond
    nao = ["Casa 3 dormitórios à venda", "Casa à venda no Jardim", "Sem condomínio, IPTU baixo",
           "Não paga condomínio", "Isento de condomínio", "Livre de condomínio",
           "Valores de condomínio e IPTU podem sofrer alterações", "jcjpv-888-casa-601361091-16",
           "Casa E Terreno À Venda", "Fora de condomínio", "Não é condomínio", "Casa A Venda"]
    sim = ["Casa 3 do condomínio Jardim", "Casa 03 em vila", "casa nº 3", "Casa A, com quintal",
           "Casa em condomínio fechado", "Condomínio R$ 300", "Bloco B", "Lote 3", "Casa B do condomínio"]
    assert [t for t in nao if cond({"descricao": t})] == []
    assert [t for t in sim if not cond({"descricao": t})] == []
    assert cond({"descricao": "", "property_sub_type": "Casa / Sobrado em Condomínio"})


def _peixoto(**campos):
    """Av. Joao Peixoto Viegas, 888 (Sao Paulo, 21/10/2026): o mesmo imovel, cada
    imobiliaria com o proprio texto; uns portais com 135 m2, outros com 203 m2."""
    base = {"rua": "Avenida João Peixoto Viegas, 888", "bairro": "Jardim Consórcio", "preco": 830000.0,
            "codigo_imovel_anunciante": None}
    return casa(**{**base, **campos})


def test_casa_mesmo_endereco_e_preco_com_area_diferente_e_o_mesmo_imovel():
    a = _peixoto(area_construida=135.0, descricao="Casa 3 dormitórios à venda. Valores de condomínio e IPTU "
                 "podem sofrer alterações.", anunciante_nome="Remax", listing_id="1")
    b = _peixoto(area_construida=203.0, descricao="Sobrado reformado, sem condomínio.", portal="chavesnamao",
                 source="Chaves na Mão", anunciante_nome="B&G", listing_id="2", url="https://cnm/2")
    junta, motivo = mesmo_imovel(a, b)
    assert junta and motivo.startswith("casa_preco_rua_numero_area_diferente(area_dif=0.335"), motivo
    unicos, descartados = deduplicar([a, b])
    assert len(unicos) == 1 and len(descartados) == 1
    rep = unicos[0]
    from agents.identidade import area
    assert area(rep) == 135.0 and {x["area"] for x in rep["areas_entre_portais"]} == {135.0, 203.0}, rep


def test_area_diferente_ainda_veta_sem_o_endereco_completo_ou_com_condominio():
    a = _peixoto(area_construida=135.0)
    # Preco diferente: nao junta (preco identico e obrigatorio).
    assert mesmo_imovel(a, _peixoto(area_construida=203.0, preco=860000.0, listing_id="2"))[1] == "preco_diferente"
    # Outro numero: o veto de area continua.
    assert mesmo_imovel(a, _peixoto(area_construida=203.0, rua="Avenida João Peixoto Viegas, 800",
                                    listing_id="2"))[1] == "veto_area"
    # Pode ser condominio (varias casas no mesmo numero): o veto de area continua.
    assert mesmo_imovel(a, _peixoto(area_construida=203.0, descricao="Casa em condomínio fechado",
                                    listing_id="2"))[1] == "veto_area"
    # Quartos diferentes continuam vetando.
    assert mesmo_imovel(a, _peixoto(area_construida=203.0, quartos=4, listing_id="2"))[1] == "veto_quartos"


def _iw(listing_id, codigo, anunciante="Rankim 11", **campos):
    """Anuncio do ImovelWeb da Av. Joao Peixoto Viegas sem numero na rua (o 888 so no link)."""
    base = {"portal": "imovelweb", "source": "ImovelWeb", "rua": "Avenida João Peixoto Viegas",
            "url": f"https://www.imovelweb.com.br/propriedades/jcjpv-888-casa-601361091-16-{listing_id}.html",
            "listing_id": listing_id, "codigo_imovel_anunciante": codigo, "anunciante_nome": anunciante,
            "area_construida": 135.0, "descricao": f"Casa {listing_id}"}
    return _peixoto(**{**base, **campos})


def test_numero_lido_do_link_do_imovelweb():
    from agents.identidade import numero
    assert numero(_iw("3044295820", None)) == "888"
    # So quando as letras terminam com as iniciais da rua do anuncio.
    assert numero(_iw("1", None, rua="Rua Pedro Rendon")) is None
    assert numero(_iw("1", None, url="https://www.imovelweb.com.br/propriedades/"
                                    "casa-a-venda-jardim-marajoara-3-quartos-140-m2-3046689017.html")) is None
    # Com o numero do link, junta com o anuncio do VivaReal do mesmo endereco.
    vr = _peixoto(area_construida=135.0, rua="Avenida João Peixoto Viegas, 888", anunciante_nome="Remax",
                  descricao="Outro texto", listing_id="9")
    junta, motivo = mesmo_imovel(_iw("3044295820", None), vr)
    assert junta and motivo.startswith("casa_preco_area_rua_numero"), motivo


def test_codigo_gerado_pelo_portal_nao_veta():
    from agents.identidade import codigo_do_portal
    assert codigo_do_portal("MI-1787983209690-7YMHCD") and codigo_do_portal("TIA-A6PG-MI-1784297184312-YS53J2")
    assert not codigo_do_portal("IMCX1787702269080SP") and not codigo_do_portal("CA13241")
    # Rankim no ImovelWeb: mesmo anunciante, codigos "MI-..." diferentes -> sao o mesmo imovel.
    a = _iw("3044295820", "MI-1787983209690-7YMHCD")
    b = _iw("3047479773", "MI-1791266469792-YKGPVQ")
    junta, motivo = mesmo_imovel(a, b)
    assert junta and motivo.startswith("casa_preco_area_rua_numero"), motivo
    assert len(deduplicar([a, b])[0]) == 1
    # Codigos da imobiliaria diferentes continuam vetando (outra unidade).
    assert mesmo_imovel(_iw("1", "CA0101"), _iw("2", "CA0102")) == (False, "veto_codigos_diferentes")
    assert len(deduplicar([_iw("1", "CA0101"), _iw("2", "CA0102")])[0]) == 2


def test_anunciante_com_letras_soltas_e_e_comercial():
    from agents.identidade import _anunciante_base
    assert {_anunciante_base({"anunciante_nome": n}) for n in ("B E G Imoveis", "B&G IMÓVEIS", "BG Imóveis")} == {"bg"}
    assert _anunciante_base({"anunciante_nome": "Silva e Souza Imóveis"}) == "silva souza"
    a = _peixoto(area_construida=203.0, codigo_imovel_anunciante="CA13241", anunciante_nome="B E G Imoveis",
                 listing_id="2907797125")
    b = _peixoto(area_construida=203.0, codigo_imovel_anunciante="CA13241", anunciante_nome="B&G IMÓVEIS",
                 portal="chavesnamao", source="Chaves na Mão", listing_id="46066008", descricao="Outro texto")
    assert mesmo_imovel(a, b) == (True, "mesmo_codigo_e_anunciante")


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
