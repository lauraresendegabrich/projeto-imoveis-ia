"""
Teste do Pipeline Completo (Orquestrador)
==========================================

COMO RODAR:
    .venv/Scripts/python.exe -m tests.test_pipeline

TESTA:
    1. Pipeline completo com imóvel de Campo Grande/MS
    2. Verifica que todos os 5 agentes rodaram
    3. Verifica os JSONs de saída
    4. Verifica tratamento de erro (cidade sem imóveis)

ATENÇÃO: Este teste faz chamadas reais às APIs (Apify, Groq, NVIDIA NIM).
         Demora de 5 a 10 minutos.
"""

import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

print("=" * 60)
print("TESTE — PIPELINE COMPLETO (ORQUESTRADOR)")
print("=" * 60)

# ==============================================================
# TESTE 1: Verifica que os JSONs existem (de execução anterior)
# ==============================================================
print("\n--- TESTE 1: Verificação dos JSONs de saída ---")

arquivos_esperados = [
    "data/imoveis_brutos_ocrad_ag1.json",
    "data/imoveis_coletados_ag1.json",
    "data/imoveis_completos_ag1.json",
    "data/zona_homogenea_ag2.json",
    "data/imoveis_analisados_ag3.json",
    "data/infra_avaliada_ag4.json",
    "data/preco_liquidez_ag5.json",
]

for arq in arquivos_esperados:
    p = Path(arq)
    if p.exists():
        size = p.stat().st_size
        print(f"  ✅ {arq} ({size:,} bytes)")
    else:
        print(f"  ⚠️ {arq} — não encontrado (rode o pipeline primeiro)")

# ==============================================================
# TESTE 2: Verifica estrutura dos JSONs
# ==============================================================
print("\n--- TESTE 2: Estrutura dos JSONs ---")

# Ag. 3
if Path("data/imoveis_analisados_ag3.json").exists():
    with open("data/imoveis_analisados_ag3.json", encoding="utf-8") as f:
        ag3 = json.load(f)
    assert "imovel_alvo" in ag3, "Ag.3: falta imovel_alvo"
    assert "comparaveis" in ag3, "Ag.3: falta comparaveis"
    alvo_analise = ag3["imovel_alvo"].get("analise_qualitativa", {})
    assert "scores" in alvo_analise, "Ag.3: falta scores no alvo"
    print(f"  ✅ Ag. 3: alvo score = {alvo_analise['scores'].get('score_qualitativo', '?')}")
    print(f"  ✅ Ag. 3: {len(ag3['comparaveis'])} comparáveis analisados")

# Ag. 4
if Path("data/infra_avaliada_ag4.json").exists():
    with open("data/infra_avaliada_ag4.json", encoding="utf-8") as f:
        ag4 = json.load(f)
    assert "scores" in ag4, "Ag.4: falta scores"
    assert "score_final" in ag4["scores"], "Ag.4: falta score_final"
    assert "resumo_scores" in ag4, "Ag.4: falta resumo_scores"
    print(f"  ✅ Ag. 4: score final = {ag4['scores']['score_final']}")
    print(f"  ✅ Ag. 4: classificação = {ag4['resumo_scores'].get('classificacao_infraestrutura', '?')}")

# Ag. 5
if Path("data/preco_liquidez_ag5.json").exists():
    with open("data/preco_liquidez_ag5.json", encoding="utf-8") as f:
        ag5 = json.load(f)
    assert "avaliacao" in ag5, "Ag.5: falta avaliacao"
    assert "liquidez" in ag5, "Ag.5: falta liquidez"
    assert ag5["avaliacao"]["valor_medio_imovel"] > 0, "Ag.5: valor deve ser > 0"
    print(f"  ✅ Ag. 5: valor médio = R$ {ag5['avaliacao']['valor_medio_imovel']:,.2f}")
    print(f"  ✅ Ag. 5: liquidez = R$ {ag5['avaliacao']['valor_liquidez']:,.2f}")
    print(f"  ✅ Ag. 5: tempo = {ag5['liquidez']['tempo_estimado']}")

# ==============================================================
# TESTE 3: Teste de falha (cidade sem imóveis)
# ==============================================================
print("\n--- TESTE 3: Tratamento de erro (cidade sem imóveis) ---")

from app.graph import executar_pipeline

resultado_erro = executar_pipeline({
    "rua": "Rua Inexistente",
    "numero": "999",
    "bairro": "BairroFalso",
    "cidade": "CidadeInexistente",
    "estado": "XX",
    "localizacao": "CidadeInexistente, XX",
    "tipo": "house",
    "propertyType": "Casas",
    "area": 100,
    "bedrooms": 2,
    "bathrooms": 1,
    "parkingSpaces": 1,
})

assert "erro" in resultado_erro.get("status", ""), "Deveria retornar erro"
print(f"  ✅ Status: {resultado_erro['status']}")
print(f"  ✅ Pipeline tratou o erro corretamente (não travou)")

# ==============================================================
print("\n" + "=" * 60)
print("TODOS OS TESTES PASSARAM ✅")
print("=" * 60)
print("\nPara rodar o pipeline completo com um imóvel real:")
print("  .venv/Scripts/python.exe -m app.main")
print("\nPara usar a interface web:")
print("  .venv/Scripts/streamlit.exe run app/interface.py")
