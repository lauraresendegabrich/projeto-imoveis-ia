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
