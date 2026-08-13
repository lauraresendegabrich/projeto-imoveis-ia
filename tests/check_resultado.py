"""Verifica resultado do pipeline."""
import json
import os

files = [
    "data/imoveis_analisados_ag3.json",
    "data/infra_avaliada_ag4.json",
    "data/preco_liquidez_ag5.json",
]

for f in files:
    if os.path.exists(f):
        data = json.load(open(f, encoding="utf-8"))
        print(f"\n{'='*50}")
        print(f"✅ {f}")
        print(f"{'='*50}")
        if "ag3" in f:
            resumo = data.get("resumo", {})
            alvo = data.get("imovel_alvo", {}).get("analise_qualitativa", {})
            print(f"  Alvo: estado={alvo.get('estado_conservacao','?')} | padrao={alvo.get('padrao_acabamento','?')} | score={alvo.get('scores',{}).get('score_qualitativo','?')}")
            print(f"  Comparáveis: {resumo.get('total_analisados', '?')} analisados | score médio: {resumo.get('score_qualitativo_medio', '?')}")
        elif "ag4" in f:
            scores = data.get("scores", {})
            print(f"  Score final: {scores.get('score_final', '?')}")
            cats = scores.get("scores_categoria", {})
            for cat, val in cats.items():
                print(f"    {cat}: {val}")
        elif "ag5" in f:
            av = data.get("avaliacao_planilha", {})
            liq = data.get("liquidez_experimental", {})
            print(f"  Valor mínimo: R$ {av.get('valor_minimo_imovel', 0):,.2f}")
            print(f"  Valor médio:  R$ {av.get('valor_medio_imovel', 0):,.2f}")
            print(f"  Valor liquidez: R$ {av.get('valor_liquidez', 0):,.2f}")
            print(f"  Score liquidez (exp): {liq.get('score_liquidez', '?')}")
            print(f"  Tempo estimado (exp): {liq.get('tempo_estimado', '?')}")
    else:
        print(f"❌ {f} — NAO EXISTE (pipeline nao completou)")
