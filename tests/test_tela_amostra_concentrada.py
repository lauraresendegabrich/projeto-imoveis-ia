"""
Tela: aviso de amostra concentrada (area e/ou preco) com os anuncios iguais num
expander. Usa o simulador do Streamlit com um resultado pronto. Sem rede.

    .venv/Scripts/python.exe -m tests.test_tela_amostra_concentrada
"""
import logging
import sys

sys.path.insert(0, ".")
logging.disable(logging.CRITICAL)

from streamlit.testing.v1 import AppTest

from services.alertas import calcular_alertas


def comp(preco, area, rua):
    return {"preco": preco, "area": area, "rua": rua, "bairro": "Barra Funda", "portal": "VivaReal",
            "url": f"https://x/{rua}", "status_zona": "confirmado"}


DIVERSOS = [comp(400_000 + i * 20_000, 100 + i * 7, f"Rua B, {i}") for i in range(6)]
CASOS = {
    "area": [comp(550_000 + i * 10_000, 142, f"Rua A, {i}") for i in range(4)] + DIVERSOS,
    "preco": [comp(300_000, 60 + i, f"Rua A, {i}") for i in range(4)] + DIVERSOS,
    "os_dois": [comp(550_000, 142, f"Rua A, {i}") for i in range(4)] + DIVERSOS,
    "nenhum": DIVERSOS,
}


def _tela(caso):
    usados = {"construcao": CASOS[caso], "terreno": []}
    ag5 = {"status_avaliacao": "ok", "avaliacao_confiavel": True, "comparaveis_usados": usados,
           "avaliacao_planilha": {"valor_medio_imovel": 500000, "valor_liquidez": 450000},
           "liquidez_experimental": {"tempo_estimado": "90 a 150 dias"}}
    alertas = calcular_alertas({"status_agente5": "ok", "qtd_comparaveis_construcao": 10}, ag5)
    at = AppTest.from_file("app/interface.py", default_timeout=60)
    at.session_state["resultado"] = {"status": "completo", "preco_estimado": ag5, "resumo": {},
                                     "comparaveis": [], "terrenos": [],
                                     "registro": {"execucao": {"alertas": alertas}, "comparaveis": []}}
    at.session_state["imovel_alvo_dados"] = {"area": 80, "tipo": "apartment"}
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    avisos = [w.value for w in at.warning if "Amostra concentrada:" in w.value]
    expanders = [e.label for e in at.expander if e.label.startswith("Ver os ")]
    return avisos, expanders, at


def test_alerta_de_area():
    avisos, expanders, at = _tela("area")
    assert len(avisos) == 1 and "têm exatamente a mesma área: 142 m²" in avisos[0], avisos
    assert "Confira os anúncios abaixo." in avisos[0]
    assert expanders == ["Ver os 4 anúncios iguais"], expanders
    tabela = [m.value for m in at.markdown if "Rua A, 0, Barra Funda" in m.value]
    assert tabela and "[ver](https://x/Rua A, 0)" in tabela[0] and "VivaReal" in tabela[0], tabela


def test_alerta_de_preco():
    avisos, expanders, _ = _tela("preco")
    assert len(avisos) == 1 and "o mesmo preço: R\$ 300.000" in avisos[0], avisos
    assert expanders == ["Ver os 4 anúncios iguais"]


def test_os_dois_juntos():
    avisos, expanders, _ = _tela("os_dois")
    assert len(avisos) == 2 and "a mesma área" in avisos[0] and "o mesmo preço" in avisos[1], avisos
    assert expanders == ["Ver os 4 anúncios iguais", "Ver os 4 anúncios iguais"]


def test_nenhum_nao_mostra_nada():
    avisos, expanders, _ = _tela("nenhum")
    assert avisos == [] and expanders == []



def _laudo(at):
    """Conteudo do laudo TXT gerado pelo botao de download (armazenado em memoria)."""
    import gc
    from streamlit.runtime.memory_media_file_storage import MemoryMediaFileStorage
    url = at.get("download_button")[0].proto.url
    for obj in gc.get_objects():
        if isinstance(obj, MemoryMediaFileStorage):
            for f in obj._files_by_id.values():
                texto = f.content.decode("utf-8", "ignore")
                if "LAUDO DE AVALIAÇÃO" in texto and url.split("/")[-1].split(".")[0] in str(obj._files_by_id):
                    return texto
    return ""


def test_laudo_aponta_para_a_tela_e_o_excel():
    _, _, at = _tela("area")
    laudo = _laudo(at)
    linha = [l for l in laudo.splitlines() if "Amostra concentrada:" in l]
    assert linha and linha[0].endswith("Confira os anúncios na tela ou no Excel."), linha
    assert "Confira os anúncios abaixo." not in laudo

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
