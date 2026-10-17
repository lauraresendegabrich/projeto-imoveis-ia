"""
Testes da busca por proximidade (Agente 1) e das protecoes (Agentes 2 e 5). Sem rede.

    .venv/Scripts/python.exe -m tests.test_busca_proximidade
"""
import sys

sys.path.insert(0, ".")

import agents.collector as ag1
import agents.comparables as ag2
from services.athena_client import AthenaClient

ALVO = (-23.2938, -51.1580)   # Londrina / Aritana (aprox.)


def _cliente():
    """AthenaClient sem boto3 nem rede: guarda o SQL em vez de executar."""
    c = object.__new__(AthenaClient)
    c.table, c.particionada, c.sql = "anuncios", False, None

    def executar(sql, timeout=30):
        c.sql = sql
        return []
    c.executar_query = executar
    return c


# ---------------------------------------------------------------- consulta
def test_consulta_com_coordenada_inclui_proximidade_e_ordena_por_distancia():
    c = _cliente()
    c.buscar_bairro_rua(cidade="Londrina", bairro="Aritana", rua="Rua Sargento José Beleti", estado="PR",
                        tipo="casa", limit=400, lat_alvo=ALVO[0], lon_alvo=ALVO[1], raio_proximidade_m=1500)
    sql = c.sql
    assert "TRY_CAST(latitude AS double) BETWEEN" in sql and "TRY_CAST(longitude AS double) BETWEEN" in sql
    assert "<= 1500" in sql and "AS distancia_alvo_m" in sql
    assert "CASE WHEN prioridade = 2 THEN distancia_alvo_m END ASC" in sql
    assert "estado = 'PR'" in sql and "tipo IN ('casa')" in sql


def test_consulta_sem_coordenada_nao_tem_proximidade():
    c = _cliente()
    c.buscar_bairro_rua(cidade="Londrina", bairro="Aritana", rua="", estado="PR", tipo="casa", limit=400)
    assert "BETWEEN" not in c.sql and "OR FALSE" in c.sql


def test_caixa_de_coordenadas_cobre_o_raio():
    cond, _ = AthenaClient.condicao_proximidade(ALVO[0], ALVO[1], 1500)
    # 1500 m ~ 0,0135 grau de latitude
    assert f"BETWEEN {ALVO[0] - 1500 / 111320:.7f} AND {ALVO[0] + 1500 / 111320:.7f}" in cond


def test_proximidade_so_com_localizacao_precisa():
    assert "bairro" in ag1.NIVEIS_GEO_PRECISOS and "rua" in ag1.NIVEIS_GEO_PRECISOS
    assert "cidade" not in ag1.NIVEIS_GEO_PRECISOS and None not in ag1.NIVEIS_GEO_PRECISOS


# ---------------------------------------------------------------- Agente 1
def test_marca_proximidade_e_descarta_alem_do_raio():
    perto = {"prioridade": 2, "latitude": ALVO[0] + 0.005, "longitude": ALVO[1]}     # ~555 m
    longe = {"prioridade": "2", "latitude": ALVO[0] + 0.02, "longitude": ALVO[1]}    # ~2,2 km
    local = {"prioridade": 1, "latitude": None, "longitude": None}
    r = ag1._marcar_proximidade([perto, longe, local], ALVO[0], ALVO[1], 1500)
    assert r == [perto, local]
    assert perto["origem_busca"] == "proximidade" and 540 < perto["distancia_alvo_m"] < 570
    assert "origem_busca" not in local


def test_ordem_rua_bairro_e_depois_os_mais_proximos():
    ims = [
        {"id": "longe", "neighborhood": "Vizinho", "origem_busca": "proximidade", "distancia_alvo_m": 1200},
        {"id": "bairro", "neighborhood": "Aritana"},
        {"id": "perto", "neighborhood": "Outro", "origem_busca": "proximidade", "distancia_alvo_m": 300},
        {"id": "rua", "neighborhood": "Aritana", "street": "Rua Sargento José Beleti, 10"},
    ]
    ordem = [i["id"] for i in ag1._ordenar_por_proximidade(ims, rua="Rua Sargento José Beleti", bairro="Aritana")]
    assert ordem == ["rua", "bairro", "perto", "longe"], ordem


def test_escopo_mantem_locais_e_proximos():
    ims = [{"neighborhood": "Aritana", "city": "Londrina"},
           {"neighborhood": "Vizinho", "city": "Londrina", "origem_busca": "proximidade"},
           {"neighborhood": "Longe", "city": "Londrina"}]
    r, escopo = ag1._aplicar_escopo(ims, rua="", bairro="Aritana", cidade="Londrina")
    assert escopo == "rua+bairro+proximidade" and len(r) == 2, (escopo, len(r))
    r, escopo = ag1._aplicar_escopo(ims[1:], rua="", bairro="Aritana", cidade="Londrina")
    assert escopo == "proximidade" and len(r) == 1


# ---------------------------------------------------------------- protecoes
def _classificar(im, centros=None):
    return ag2._classificar_imovel_na_zona(im, ALVO[0], ALVO[1], 450, "Londrina", "PR", centros_cidade=centros or [])


def test_proximo_dentro_do_circulo_entra():
    assert _classificar({"origem_busca": "proximidade", "lat": ALVO[0] + 0.002, "lon": ALVO[1]}) == "na_zona"


def test_proximo_com_coordenada_generica_fica_fora():
    centro = (ALVO[0] + 0.001, ALVO[1])
    im = {"origem_busca": "proximidade", "lat": centro[0], "lon": centro[1], "neighborhood": "Centro"}
    assert _classificar(im, centros=[centro]) == "fora_zona"
    assert _classificar({"lat": centro[0], "lon": centro[1]}, centros=[centro]) == "zona_nao_verificada"


def test_proximo_sem_posicao_fica_fora():
    original = ag2._geocodificar_com_fallback
    ag2._geocodificar_com_fallback = lambda **k: (None, None, None, None)
    try:
        assert _classificar({"origem_busca": "proximidade"}) == "fora_zona"
        assert _classificar({}) == "zona_nao_verificada"
    finally:
        ag2._geocodificar_com_fallback = original


def test_socorro_do_agente5_ignora_os_proximos():
    import tests.test_zona_execucao as tz
    comps = tz._comparaveis(7)
    for c in comps:
        c["origem_busca"] = "proximidade"
    zona = {"id_execucao": tz.ID, "comparaveis_confirmados": [], "resumo_zona": {"raio_usado_metros": 450}}
    r = tz._rodar(zona=zona, ag2={"id_execucao": tz.ID, "comparaveis": comps})
    assert r["comparaveis_usados"]["construcao"] == [] and r["status_avaliacao"] == "sem_amostra", r["status_avaliacao"]


def test_fallback_da_zona_nao_puxa_os_proximos():
    casas = [{"id": i, "url": f"https://x/{i}", "propertyType": "Casas", "price": 1 + i, "area": 100, "cluster": "A"}
             for i in range(3)]
    casas[0]["zona"], casas[1]["zona"], casas[2]["zona"] = "na_zona", "zona_nao_verificada", "zona_nao_verificada"
    casas[2]["origem_busca"] = "proximidade"
    originais = (ag2._obter_imagem_satelite, ag2._analisar_zona_homogenea, ag2._classificar_imovel_na_zona,
                 ag2._centros_da_cidade)
    ag2._obter_imagem_satelite = lambda *a, **k: b"png"
    ag2._analisar_zona_homogenea = lambda *a, **k: {"raio_metros": 450, "raio_sugerido_metros": 450}
    ag2._centros_da_cidade = lambda *a, **k: []
    # Simula a regra real: proximo sem posicao confirmada -> fora_zona.
    ag2._classificar_imovel_na_zona = lambda im, *a, **k: (
        "fora_zona" if ag2._so_entra_com_circulo(im) and im["zona"] != "na_zona" else im["zona"])
    try:
        z = ag2.analisar_zona_homogenea("x", casas, cidade="Londrina", estado="PR", lat_alvo_precomp=ALVO[0],
                                        lon_alvo_precomp=ALVO[1], terrenos=[], id_execucao="teste")
    finally:
        (ag2._obter_imagem_satelite, ag2._analisar_zona_homogenea, ag2._classificar_imovel_na_zona,
         ag2._centros_da_cidade) = originais
    assert {c["id"] for c in z["comparaveis_confirmados"]} == {0, 1}


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
