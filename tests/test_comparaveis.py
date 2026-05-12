# -*- coding: utf-8 -*-
"""
Teste do Agente 2 - Identificador de Comparaveis

Usa os dados coletados pelo Agente 1 e identifica quais imoveis
sao realmente comparaveis ao imovel alvo.

COMO RODAR:
    .venv/Scripts/python.exe -m tests.test_comparaveis

PRE-REQUISITOS:
    - data/imoveis_completos.json (gerado pelo Agente 1)
    - GROQ_API_KEY no .env (para clustering via LLM)

ARQUIVOS GERADOS:
    data/imoveis_comparaveis.json -> resultado com ranking e clusters
"""

import sys
import os

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agents.comparables import identificar_comparaveis, analisar_zona_homogenea

# =============================================================================
# IMOVEL ALVO - mesmo do teste do Agente 1
# =============================================================================

IMOVEL_ALVO = {
    "descricao": "Casa",
    "rua": "Rua Franklin Maximo Pereira",
    "numero": "188",
    "bairro": "Centro",
    "cidade": "Itajai",
    "estado": "SC",
    # Caracteristicas do imovel alvo (preencher com dados reais)
    "propertyType": "Casas",
    "area": 170,
    "bedrooms": 3,
    "bathrooms": 4,
    "parkingSpaces": 2,
    "pricePerSqm": 8205.88,  # R$ 1.395.000 / 170m²
    "price": 1395000,
    "priceFormatted": "R$ 1.395.000",
    "neighborhood": "Centro",
    "street": "Rua Franklin Máximo Pereira",
    "description": "Casa com 170m², 3 quartos, 4 banheiros, 2 vagas, Centro de Itajaí",
}

# =============================================================================
# EXECUCAO
# =============================================================================

if __name__ == "__main__":
    print("\n" + "=" * 55)
    print("TESTE - AGENTE 2: IDENTIFICADOR DE COMPARAVEIS")
    print("=" * 55)
    print(f"Imovel alvo : {IMOVEL_ALVO['rua']}, {IMOVEL_ALVO['numero']}")
    print(f"Tipo        : {IMOVEL_ALVO['propertyType']}")
    print(f"Area        : {IMOVEL_ALVO['area']} m²")
    print(f"Quartos     : {IMOVEL_ALVO['bedrooms']}")
    print(f"Preco/m²    : R$ {IMOVEL_ALVO['pricePerSqm']:.2f}")
    print("-" * 55)

    resultado = identificar_comparaveis(
        imovel_alvo=IMOVEL_ALVO,
        usar_llm=True,
    )

    comparaveis = resultado.get("comparaveis", [])
    resumo = resultado.get("resumo", {})

    print("\n" + "=" * 55)
    print(f"RESULTADO: {resumo.get('cluster_a', 0)} similares | {resumo.get('cluster_b', 0)} nao similares")
    print("=" * 55)

    # Mostra Cluster A (similares)
    cluster_a = [c for c in comparaveis if c.get("cluster") == "A"]
    if cluster_a:
        print(f"\n--- CLUSTER A: {len(cluster_a)} imoveis SIMILARES ---")
        for c in cluster_a[:10]:
            print(f"  #{c.get('ranking_llm', '?')} | score={c.get('score_similaridade', 0):.2f} | "
                  f"{c.get('area', '?')}m² | {c.get('bedrooms', '?')}q | "
                  f"{c.get('priceFormatted', '?')} | {c.get('street') or c.get('neighborhood', '?')}")
            if c.get("justificativa"):
                print(f"       {c['justificativa']}")

    # Mostra Cluster B (nao similares)
    cluster_b = [c for c in comparaveis if c.get("cluster") != "A"]
    if cluster_b:
        print(f"\n--- CLUSTER B: {len(cluster_b)} imoveis NAO SIMILARES ---")
        for c in cluster_b[:5]:
            print(f"  score={c.get('score_similaridade', 0):.2f} | "
                  f"{c.get('area', '?')}m² | {c.get('bedrooms', '?')}q | "
                  f"{c.get('propertyType', '?')} | {c.get('priceFormatted', '?')}")
            if c.get("justificativa"):
                print(f"       {c['justificativa']}")

    print(f"\nArquivo salvo: data/imoveis_comparaveis.json")
    print(f"Metodo: {resumo.get('metodo', '?')}")

    # ── ZONA HOMOGENEA (opcional — requer GOOGLE_MAPS_KEY) ────────
    import os
    if os.getenv("GOOGLE_MAPS_KEY"):
        print("\n" + "=" * 55)
        print("ZONA HOMOGENEA: Google Maps + Groq Vision")
        print("=" * 55)

        endereco = f"{IMOVEL_ALVO['rua']}, {IMOVEL_ALVO['numero']}, {IMOVEL_ALVO['bairro']}, {IMOVEL_ALVO['cidade']}, {IMOVEL_ALVO['estado']}"

        # Usa o resultado do clustering (que ja tem cluster, ranking, score)
        zona_resultado = analisar_zona_homogenea(
            endereco_alvo=endereco,
            imoveis=comparaveis,
            cidade=IMOVEL_ALVO["cidade"],
            estado=IMOVEL_ALVO["estado"],
        )

        zona = zona_resultado.get("zona_homogenea", {})
        confirmados = zona_resultado.get("comparaveis_confirmados", [])
        fora_zona = zona_resultado.get("fora_zona", [])

        print(f"\nAnalise visual da regiao:")
        print(f"  Tipo: {zona.get('tipo_regiao', '?')}")
        print(f"  Uso: {zona.get('uso_predominante', '?')}")
        print(f"  Padrao: {zona.get('padrao_construtivo', '?')}")
        print(f"  Densidade: {zona.get('densidade_urbana', '?')}")
        print(f"  Homogeneidade: {zona.get('homogeneidade_visual', '?')}")
        print(f"  Raio sugerido: {zona.get('raio_sugerido_metros', '?')}m")
        print(f"  Confianca: {zona.get('confianca', '?')}")
        if zona.get("descricao_zona_homogenea"):
            print(f"  Descricao: {zona['descricao_zona_homogenea']}")
        if zona.get("justificativa_raio"):
            print(f"  Justificativa raio: {zona['justificativa_raio']}")
        if zona.get("limitacoes"):
            print(f"  Limitacoes: {zona['limitacoes']}")

        print(f"\n  NA ZONA HOMOGENEA: {len(confirmados)}")
        for c in confirmados[:10]:
            dist = c.get("distancia_metros")
            rua = c.get("street") or c.get("neighborhood", "?")
            dist_str = f"{dist}m" if dist is not None else "mesmo bairro"
            print(f"    {dist_str:>12} | {rua}")

        print(f"\n  FORA DA ZONA: {len(fora_zona)}")
        for c in fora_zona[:5]:
            dist = c.get("distancia_metros", "?")
            rua = c.get("street") or c.get("neighborhood", "?")
            print(f"    {dist}m | {rua}")

        print(f"\n  Imagem: {zona_resultado.get('imagem_satelite', '?')}")
    else:
        print("\n(GOOGLE_MAPS_KEY nao configurada — zona homogenea pulada)")
