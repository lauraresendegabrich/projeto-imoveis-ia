# -*- coding: utf-8 -*-
"""
Teste do Agente 1 - Coletor de Dados

Executa a coleta via Apify (ocrad) para o imovel alvo
e exibe um resumo dos resultados no terminal.

COMO RODAR:
    .venv/Scripts/python.exe -m tests.test_coleta

PRE-REQUISITOS:
    - APIFY_TOKEN_2 no .env (ou APIFY_TOKEN)

ARQUIVOS GERADOS:
    data/imoveis_brutos_ocrad.json -> brutos do ocrad
    data/imoveis_coletados.json    -> resultado final
"""

import sys
import os
from collections import Counter

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agents.collector import coletar_imoveis

# =============================================================================
# IMOVEL ALVO - altere aqui para testar outros imoveis depois colocar as características principais
# =============================================================================

IMOVEL_ALVO = {
    "descricao":   "Casa",
    "rua":         "Rua Franklin Maximo Pereira",
    "numero":      "188",
    "bairro":      "Centro",
    "cidade":      "Itajai",
    "estado":      "SC",
    "localizacao": "Itajai, SC",
    "tipo":        "house",   # "house" -> Casas + Terrenos
                              # "apartment" -> so Apartamentos
}

# =============================================================================
# EXECUCAO
# =============================================================================

if __name__ == "__main__":
    print("\n" + "=" * 55)
    print("TESTE - AGENTE 1: COLETOR DE DADOS")
    print("=" * 55)
    print(f"Imovel alvo : {IMOVEL_ALVO['rua']}, {IMOVEL_ALVO['numero']}")
    print(f"Bairro      : {IMOVEL_ALVO['bairro']}")
    print(f"Cidade/UF   : {IMOVEL_ALVO['cidade']}/{IMOVEL_ALVO['estado']}")
    print(f"Tipo        : {IMOVEL_ALVO['tipo']}")
    print("-" * 55)

    comparaveis = coletar_imoveis(
        localizacao=IMOVEL_ALVO["localizacao"],
        tipo_imovel=IMOVEL_ALVO["tipo"],
        bairro=IMOVEL_ALVO["bairro"],
        rua=IMOVEL_ALVO["rua"],
    )

    print("\n" + "=" * 55)
    print(f"RESULTADO: {len(comparaveis)} comparaveis encontrados")
    print("=" * 55)

    if not comparaveis:
        print("Nenhum imovel encontrado.")
        print("Verifique APIFY_TOKEN_2 no .env")
        sys.exit(0)

    portais  = Counter(i.get("source", "?") for i in comparaveis)
    tipos    = Counter(i.get("propertyType", "?") for i in comparaveis)
    bairros  = Counter(i.get("neighborhood", "?") for i in comparaveis)
    com_rua  = sum(1 for i in comparaveis if i.get("street"))
    com_data = sum(1 for i in comparaveis if i.get("publishedAt"))

    print(f"Portais  : {dict(portais)}")
    print(f"Tipos    : {dict(tipos)}")
    print(f"Bairros  : {dict(bairros)}")
    print(f"Com rua  : {com_rua}/{len(comparaveis)}")
    print(f"Com data : {com_data}/{len(comparaveis)}")

    print("\n--- Exemplo: primeiro imovel ---")
    for k, v in comparaveis[0].items():
        if k not in ("images", "raw_markdown"):
            print(f"  {k}: {v}")

    print(f"\nArquivos salvos:")
    print(f"  data/imoveis_brutos_ocrad.json -> brutos ocrad")
    print(f"  data/imoveis_coletados.json    -> {len(comparaveis)} comparaveis")
