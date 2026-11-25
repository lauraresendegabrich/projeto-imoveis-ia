"""
Avaliacao pelo terminal — o MESMO fluxo da tela
================================================

COMO RODAR (da raiz do projeto):
    .venv/Scripts/python.exe -m app.main            # nao grava no banco
    .venv/Scripts/python.exe -m app.main --gravar   # grava no banco, como a tela

Preencha IMOVEL e, se for leilao, LEILAO abaixo, com os mesmos campos do formulario
da pagina "Avaliacao de imovel". O imovel e montado pela mesma funcao da tela
(services/pipeline.montar_imovel_alvo) e avaliado pelo mesmo fluxo
(services/pipeline.executar_avaliacao): tela e terminal dao o mesmo resultado.
"""
import logging
import sys

from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# =============================================================================
# IMOVEL — campos do formulario (tipo: "Casa" ou "Apartamento")
# =============================================================================

IMOVEL = {
    "rua": "Rua Chirito Mascarado",
    "numero": "116",
    "bairro": "Jardim Interlagos",
    "cidade": "Arapongas",
    "estado": "PR",
    "tipo": "Casa",
    "area": 69.97,
    "area_terreno": 128.17,
    "quartos": 2,
    "banheiros": 1,
    "vagas": 1,
    "descricao": "",
    "fotos": [],              # links diretos das fotos, ate 8
    "link_anuncio": "",       # anuncio do proprio imovel num portal, se houver
    "em_condominio": False,
    "preco": 0.0,             # preco anunciado (opcional)
}

# Leilao: textos como no formulario (None = nao e leilao). Campos por modalidade em
# services/leilao.campos_da_modalidade.
LEILAO = {
    "banco": "CAIXA",
    "modalidade": "Leilão SFI",
    "textos": {
        "valor_minimo_1": "157000,00", "data_1_leilao": "24/11/2026 10:00",
        "valor_minimo_2": "144.637,65", "data_2_leilao": "30/11/2026 10:00",
        "numero_imovel": "8444412088380",
    },
}


def main(gravar: bool = False) -> dict:
    from services.leilao import ler_formulario_leilao
    from services.pipeline import ObservadorLog, executar_avaliacao, montar_imovel_alvo

    dados_leilao = None
    if LEILAO:
        dados_leilao, erros = ler_formulario_leilao(LEILAO["textos"], LEILAO["banco"], LEILAO["modalidade"])
        if erros:
            raise SystemExit("Campos do leilao invalidos: " + "; ".join(erros))

    imovel_alvo = montar_imovel_alvo(**IMOVEL)
    saida = executar_avaliacao(
        imovel_alvo, dados_leilao=dados_leilao, obs=ObservadorLog(), gravar=gravar,
        entrada_usuario={**IMOVEL, "origem": "terminal (app/main.py)"},
        tela_resultado={k: IMOVEL[k] for k in ("rua", "numero", "bairro", "cidade", "estado", "tipo",
                                               "quartos", "banheiros", "vagas")},
    )
    resultado = saida["resultado"] or {}
    pe = resultado.get("preco_estimado") or {}
    ap = pe.get("avaliacao_planilha") or {}
    usados = pe.get("comparaveis_usados") or {}
    leilao = resultado.get("leilao") or {}

    print("\n" + "=" * 60)
    print("RESULTADO (mesmo fluxo da tela)")
    print("=" * 60)
    print(f"Parada:          {saida['parada'] or 'nenhuma (avaliacao completa)'}")
    print(f"Valor medio:     {ap.get('valor_medio_imovel')}")
    print(f"Liquidez:        {ap.get('valor_liquidez')}")
    print(f"Status Ag5:      {pe.get('status_avaliacao')} | confiavel: {pe.get('avaliacao_confiavel')}")
    print(f"Usados:          {len(usados.get('construcao') or [])} construidos, {len(usados.get('terreno') or [])} terrenos")
    if leilao:
        print(f"Leilao:          {leilao.get('decisao')} | ROI {leilao.get('roi')} | etapa {leilao.get('etapa')}")
    print(f"Falhas:          {resultado.get('falhas') or 'nenhuma'}")
    print(f"Gravado no banco: {'sim' if gravar else 'nao'}")
    return saida


if __name__ == "__main__":
    main(gravar="--gravar" in sys.argv)
