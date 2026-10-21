"""
Agente 1: o que a coleta registra para as verificacoes automaticas (id_execucao e
horario em cada anuncio). Athena e Apify simulados, data/ numa pasta temporaria.
Sem rede.

    .venv/Scripts/python.exe -m tests.test_coleta_registro
"""
import contextlib
import logging
import sys
import tempfile

sys.path.insert(0, ".")
logging.disable(logging.CRITICAL)

import agents.collector as ag1
import services.athena_client as athena_client
from services.verificacoes import verificar_execucao


def linha(i, **extra):
    """Linha da tabela anuncios do Athena."""
    return {"portal": "vivareal", "listing_id": str(1000 + i), "url": f"https://www.vivareal.com.br/imovel/x-id-{1000 + i}/",
            "tipo": "casa", "preco": 500000 + i * 1000, "area_construida": 100 + i, "quartos": 3,
            "cidade": "Curitiba", "estado": "PR", "bairro": "Centro", "rua": f"Rua {i}",
            "fotos_urls": f"https://img/{i}.jpg", **extra}


class AthenaFalso:
    """Devolve as linhas pedidas; `falhar` = subtipos (nomes no Athena) que levantam erro."""
    linhas, falhar = [], set()

    def __init__(self):
        pass

    def _resposta(self, tipo):
        if set(tipo) & AthenaFalso.falhar:
            raise RuntimeError(f"Athena falhou em {tipo[0]}")
        return [dict(l) for l in AthenaFalso.linhas if l["tipo"] in tipo]

    def buscar_bairro_rua(self, tipo, **_):
        return self._resposta(tipo)

    def buscar_cidade(self, tipo, **_):
        return self._resposta(tipo)


@contextlib.contextmanager
def ambiente(linhas, falhar=(), apify=None):
    originais = (athena_client.AthenaClient, ag1._coletar_ocrad, ag1.DATA_DIR)
    AthenaFalso.linhas, AthenaFalso.falhar = linhas, set(falhar)
    athena_client.AthenaClient = AthenaFalso
    ag1._coletar_ocrad = apify or (lambda *a, **k: [])
    with tempfile.TemporaryDirectory() as pasta:
        ag1.DATA_DIR = pasta
        try:
            yield
        finally:
            athena_client.AthenaClient, ag1._coletar_ocrad, ag1.DATA_DIR = originais


def coletar(linhas, **kw):
    with ambiente(linhas, **{k: kw.pop(k) for k in ("falhar", "apify") if k in kw}):
        return ag1.coletar_imoveis("Curitiba, PR", "house", bairro="Centro", **kw)


def resultado_da_coleta(coletados, id_execucao="exec-1"):
    """Resultado minimo para as verificacoes do Agente 1."""
    return {"id_execucao": id_execucao, "imovel_alvo": {"cidade": "Curitiba", "estado": "PR"},
            "comparaveis": [c for c in coletados if c.get("propertyType") != "Terrenos"],
            "terrenos": [c for c in coletados if c.get("propertyType") == "Terrenos"],
            "duplicatas_descartadas": [{"Anúncio descartado": d.get("url")}
                                       for c in coletados for d in c.get("duplicatas") or []],
            "resumo_coleta": (coletados[0].get("resumo_coleta") if coletados else None)}


def _v(resultado, inicio):
    return next(v for v in verificar_execucao(resultado) if v["verificacao"].startswith(inicio))


# ---------------------------------------------------------------- id e horario
def test_cada_anuncio_tem_o_id_e_o_horario_desta_execucao():
    coletados = coletar([linha(i) for i in range(12)], id_execucao="exec-1")
    assert len(coletados) == 12
    assert {c["id_execucao"] for c in coletados} == {"exec-1"}
    assert all(c.get("coletado_em") for c in coletados)
    v = _v(resultado_da_coleta(coletados), "Os dados são desta execução")
    assert v["ok"] is True and "12 de 12 com o id desta execução" in v["encontrado"], v


def test_dados_de_outra_rodada_falham():
    coletados = coletar([linha(i) for i in range(12)], id_execucao="rodada-anterior")
    v = _v(resultado_da_coleta(coletados, id_execucao="exec-1"), "Os dados são desta execução")
    assert v["ok"] is False and "0 de 12" in v["encontrado"] and "rodada-anterior" in v["encontrado"], v


# ---------------------------------------------------------------- fontes
def test_athena_respondeu_e_apify_nao_foi_preciso():
    coletados = coletar([linha(i) for i in range(12)], id_execucao="exec-1")
    fontes = coletados[0]["resumo_coleta"]["fontes"]
    assert fontes["athena"]["respondeu"] and fontes["athena"]["consultas_ok"] == 2 and not fontes["athena"]["falhas"]
    assert fontes["apify"]["consultada"] is False and "não consultado" in fontes["apify"]["motivo"]
    v = _v(resultado_da_coleta(coletados), "Cada fonte consultada respondeu")
    assert v["ok"] is True and v["encontrado"].startswith("Athena: respondeu (12 anúncios) | Apify: não consultado"), v


def test_falha_de_um_subtipo_do_athena_fica_registrada():
    coletados = coletar([linha(i) for i in range(12)], falhar={"terreno"}, id_execucao="exec-1")
    falhas = coletados[0]["resumo_coleta"]["fontes"]["athena"]["falhas"]
    assert falhas == ["terreno: Athena falhou em terreno"], falhas
    v = _v(resultado_da_coleta(coletados), "Cada fonte consultada respondeu")
    assert v["ok"] is True and "falhas registradas: terreno: Athena falhou em terreno" in v["encontrado"], v


def test_falha_do_apify_fica_registrada_sem_o_token():
    def apify_quebrado(*a, **k):
        raise RuntimeError("500 Server Error for url https://api.apify.com/v2/acts/x/runs?token=segredo123")
    original = ag1.APIFY_TOKEN
    ag1.APIFY_TOKEN = "segredo123"
    try:
        coletados = coletar([linha(i) for i in range(5)], apify=apify_quebrado, id_execucao="exec-1")
    finally:
        ag1.APIFY_TOKEN = original
    apify = coletados[0]["resumo_coleta"]["fontes"]["apify"]
    assert apify["consultada"] and apify["respondeu"] is False and "menos de 10" in apify["motivo"], apify
    assert "token=***" in apify["erro"] and "segredo123" not in apify["erro"], apify
    v = _v(resultado_da_coleta(coletados), "Cada fonte consultada respondeu")
    assert v["ok"] is True and "Apify: falhou, registrado" in v["encontrado"], v


def test_erro_interno_do_apify_volta_na_situacao():
    import requests
    original_post, original_token = ag1.requests.post, ag1.APIFY_TOKEN

    def post_quebrado(url, **_):
        raise requests.ConnectionError(f"falhou {url}")
    ag1.requests.post, ag1.APIFY_TOKEN = post_quebrado, "segredo123"
    situacao = {}
    try:   # a funcao real (sem ambiente(), que troca o Apify por um falso); falha antes de gravar
        assert ag1._coletar_ocrad("Curitiba, PR", "house", "Centro", situacao=situacao) == []
    finally:
        ag1.requests.post, ag1.APIFY_TOKEN = original_post, original_token
    assert situacao["erro"].startswith("erro ao iniciar: falhou") and "segredo123" not in situacao["erro"], situacao


def test_fonte_sem_resposta_e_sem_falha_registrada_falha():
    r = resultado_da_coleta([])
    r["resumo_coleta"] = {"fontes": {"athena": {"consultada": True, "respondeu": False, "falhas": []}}}
    v = _v(r, "Cada fonte consultada respondeu")
    assert v["ok"] is False and "nenhuma falha foi registrada" in v["encontrado"], v


# ---------------------------------------------------------------- contagens
def repetido(i, portal, lid):
    """O mesmo imovel (mesmo codigo da imobiliaria) anunciado em outro portal."""
    return linha(i, portal=portal, listing_id=lid, url=f"https://{portal}/{lid}", rua="Rua 0",
                 codigo_imovel_anunciante="CA0406", anunciante_nome="Pagani Imoveis", preco=777000, area_construida=150)


def test_encontrados_igual_a_mantidos_mais_repetidos():
    coletados = coletar([repetido(0, "vivareal", "9001"), repetido(0, "chavesnamao", "9002")]
                        + [linha(i) for i in range(1, 12)], id_execucao="exec-1")
    c = coletados[0]["resumo_coleta"]["contagem"]
    assert (c["antes_dos_repetidos"], c["unicos"], c["repetidos_juntados"], c["mantidos"], c["repetidos"]) == \
        (13, 12, 1, 12, 1), c
    v = _v(resultado_da_coleta(coletados), "encontrados = mantidos + repetidos")
    assert v["ok"] is True and v["encontrado"].startswith("encontrados 13 = 12 únicos + 1 repetidos"), v


def test_cortados_pelo_limite_entram_na_conta():
    coletados = coletar([linha(i) for i in range(205)], id_execucao="exec-1")
    c = coletados[0]["resumo_coleta"]["contagem"]
    assert c["cortados_pelo_limite"] == 5 and c["mantidos"] == 200, c
    assert _v(resultado_da_coleta(coletados), "encontrados = mantidos + repetidos")["ok"] is True


def test_conta_que_nao_fecha_falha():
    coletados = coletar([repetido(0, "vivareal", "9001"), repetido(0, "chavesnamao", "9002")]
                        + [linha(i) for i in range(1, 12)], id_execucao="exec-1")
    r = resultado_da_coleta(coletados)
    r["duplicatas_descartadas"] = []                   # o repetido sumiu do resultado
    v = _v(r, "encontrados = mantidos + repetidos")
    assert v["ok"] is False and "no resultado: 12 anúncios e 0 repetidos" in v["encontrado"], v
    r = resultado_da_coleta(coletados)
    r["resumo_coleta"] = {"contagem": dict(coletados[0]["resumo_coleta"]["contagem"], antes_dos_repetidos=20)}
    assert _v(r, "encontrados = mantidos + repetidos")["ok"] is False


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
