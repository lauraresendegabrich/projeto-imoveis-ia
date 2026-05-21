# -*- coding: utf-8 -*-
"""
Teste do Agente 4 - Avaliador de Infraestrutura

Analisa o entorno do imovel alvo em 3 raios (400m, 800m, 1500m)
via osmnx (OpenStreetMap) com pesos diferenciados por categoria.

COMO RODAR:
    .venv/Scripts/python.exe -m tests.test_infra_evaluator

PRE-REQUISITOS:
    - data/imoveis_analisados_ag3.json (gerado pelo Agente 3)
    - GROQ_API_KEY no .env

ARQUIVOS GERADOS:
    data/infra_avaliada_ag4.json -> analise multirraio de infraestrutura
"""

import sys
import os

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agents.infra_evaluator import avaliar_infraestrutura

if __name__ == "__main__":
    print("\n" + "=" * 55)
    print("TESTE - AGENTE 4: AVALIADOR DE INFRAESTRUTURA")
    print("=" * 55)

    resultado = avaliar_infraestrutura()

    if not resultado:
        print("Erro: nao foi possivel avaliar a infraestrutura.")
        print("Verifique se data/imoveis_analisados_ag3.json existe.")
        sys.exit(1)

    alvo         = resultado.get("imovel_alvo", {})
    coords       = resultado.get("coordenadas", {})
    pois_faixa   = resultado.get("pois_por_faixa", {})
    transporte   = resultado.get("transporte", {})
    scores       = resultado.get("scores", {})
    analise      = resultado.get("analise_llm", {})

    print(f"\nImovel alvo: {alvo.get('rua','?')}, {alvo.get('numero','')}")
    print(f"Coordenadas: {coords.get('lat','?'):.6f}, {coords.get('lon','?'):.6f}")
    print(f"Tolerancia:  {resultado.get('tolerancia_pct',5)}% nos limites de faixa")

    # POIs por faixa (exceto transporte)
    faixas_label = {
        "microentorno_imediato": "0–400m   (microentorno imediato)",
        "entorno_caminhavel":    "401–800m (entorno caminhavel)",
        "infraestrutura_ampliada": "801–1500m (infraestrutura ampliada)",
    }
    for faixa, label in faixas_label.items():
        cats = pois_faixa.get(faixa, {})
        total = sum(len(v) for cat, v in cats.items() if cat != "transporte")
        print(f"\n--- {label} ({total} POIs) ---")
        for cat, pois in cats.items():
            if cat == "transporte":
                continue
            if pois:
                nomes = [f"{p['nome']} ({p['distancia_metros']}m)" for p in pois[:3]]
                print(f"  {cat:20}: {len(pois):2d}  |  {', '.join(nomes)}")
            else:
                print(f"  {cat:20}:  0")

    # Transporte expandido
    print(f"\n--- TRANSPORTE PUBLICO (status: {transporte.get('status','?')}) ---")
    paradas = transporte.get("paradas", [])
    estacoes = transporte.get("estacoes", [])
    rotas = transporte.get("rotas", [])
    if paradas:
        print(f"  Paradas ({len(paradas)}):")
        for p in paradas[:5]:
            print(f"    {p['nome']} ({p['distancia_metros']}m) [{p.get('faixa','?')}]")
    if estacoes:
        print(f"  Estacoes ({len(estacoes)}):")
        for e in estacoes[:3]:
            print(f"    {e['nome']} ({e['distancia_metros']}m)")
    if rotas:
        print(f"  Rotas ({len(rotas)}): {', '.join(r['nome'] for r in rotas[:5])}")
    if not paradas and not estacoes and not rotas:
        print(f"  Nenhum dado encontrado — possivel sub-representacao no OSM")

    # Scores
    print(f"\n--- SCORES POR CATEGORIA ---")
    for cat, score in scores.items():
        if cat in ("score_final", "transporte_dados_insuficientes", "transporte_status"):
            continue
        if cat == "transporte":
            status = scores.get("transporte_status", "?")
            sufixo = f" [{status}]"
        else:
            sufixo = ""
        barra = "█" * int(score * 20)
        print(f"  {cat:20}: {score:.2f}  {barra}{sufixo}")
    print(f"  {'SCORE FINAL':20}: {scores.get('score_final', 0):.2f}")

    # Analise LLM
    print(f"\n--- ANALISE LLM ---")
    print(f"  Score final:    {scores.get('score_final', 0):.2f}")
    resumo = resultado.get("resumo_scores", {})
    print(f"  Classificacao:  {resumo.get('classificacao_infraestrutura','?')}")
    print(f"  Perfil:         {analise.get('perfil_regiao','?')}")
    print(f"  Impacto valor:  {analise.get('impacto_estimado_no_valor','?')}")
    if analise.get("pontos_fortes"):
        print(f"  Pontos fortes:")
        for p in analise["pontos_fortes"]:
            print(f"    + {p}")
    if analise.get("pontos_de_atencao"):
        print(f"  Pontos de atencao:")
        for p in analise["pontos_de_atencao"]:
            print(f"    ~ {p}")
    if analise.get("limitacoes"):
        print(f"  Limitacoes:")
        for p in analise["limitacoes"]:
            print(f"    ! {p}")
    if analise.get("justificativa"):
        print(f"  Justificativa: {analise['justificativa']}")
    if analise.get("conclusao"):
        print(f"  Conclusao: {analise['conclusao']}")

    print(f"\nArquivo salvo: data/infra_avaliada_ag4.json")
