# -*- coding: utf-8 -*-
"""
Teste do Agente 3 - Analisador Textual

COMO RODAR:
    .venv/Scripts/python.exe -m tests.test_text_analyzer

PRE-REQUISITOS:
    - data/zona_homogenea_ag2.json (gerado pelo Agente 2)
    - data/imoveis_comparaveis_ag2.json (gerado pelo Agente 2)
    - GROQ_API_KEY no .env

ARQUIVOS GERADOS:
    data/imoveis_analisados_ag3.json
"""

import sys
import os

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agents.text_analyzer import analisar_comparaveis

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("TESTE - AGENTE 3: ANALISADOR TEXTUAL")
    print("=" * 60)

    resultado = analisar_comparaveis()

    if not resultado:
        print("Erro: nao foi possivel carregar os dados.")
        print("Verifique se data/zona_homogenea_ag2.json existe.")
        sys.exit(1)

    comparaveis = resultado.get("comparaveis", [])
    imovel_alvo = resultado.get("imovel_alvo", {})
    resumo      = resultado.get("resumo", {})

    def _print_analise(analise: dict):
        print(f"    Estado conservacao:  {analise.get('estado_conservacao','?')}")
        print(f"    Padrao acabamento:   {analise.get('padrao_acabamento','?')}")
        print(f"    Confianca extracao:  {analise.get('confianca_extracao','?')}")
        scores = analise.get("scores", {})
        print(f"    Score qualitativo:   {scores.get('score_qualitativo','?')}")
        print(f"    Classificacao:       {analise.get('classificacao_qualitativa','?')}")
        pos = analise.get("pontos_positivos", [])
        print(f"    Pontos positivos:    {', '.join(pos) if pos else 'nenhum'}")
        neg = analise.get("pontos_negativos", [])
        if neg:
            print(f"    PONTOS NEGATIVOS:    {', '.join(neg)}")
        print(f"    Justificativa:       {analise.get('justificativa','')[:150]}")

    # Imovel alvo
    print("\n--- IMOVEL ALVO ---")
    analise_alvo = imovel_alvo.get("analise_qualitativa", {})
    _print_analise(analise_alvo)

    # Comparaveis
    print(f"\n--- CLUSTER A + NA_ZONA: {len(comparaveis)} imoveis ---")
    for c in comparaveis:
        rua = c.get("street") or c.get("neighborhood", "?")
        ranking = c.get("ranking_llm", "?")
        print(f"\n  #{ranking} | {rua}")
        analise = c.get("analise_qualitativa", {})
        _print_analise(analise)

    # Resumo
    print("\n" + "=" * 60)
    print(f"RESUMO:")
    print(f"  Total analisados:    {resumo.get('total_analisados', 0)}")
    print(f"  OK:                  {resumo.get('analisados_ok', 0)}")
    print(f"  Descricao insuf.:    {resumo.get('descricao_insuficiente', 0)}")
    print(f"  Score qualitativo medio: {resumo.get('score_qualitativo_medio', '?')}")
    print(f"\nArquivo salvo: data/imoveis_analisados_ag3.json")

