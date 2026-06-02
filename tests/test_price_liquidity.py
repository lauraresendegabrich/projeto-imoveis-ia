"""
Teste do Agente 5 — Estimador de Preço e Liquidez
===================================================

COMO RODAR:
    .venv/Scripts/python.exe -m tests.test_price_liquidity

TESTA:
    1. Leitura dos JSONs dos agentes anteriores
    2. Cálculo do m² do terreno (TRIMMEAN)
    3. Cálculo do m² da construção por padrão
    4. Valor mínimo e médio do imóvel
    5. Valor de liquidez (desconto 10%)
    6. Tempo de liquidez (scores Ag.3 + Ag.4)
    7. Fallbacks (sem terrenos, sem padrão, etc.)
"""

import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")

print("=" * 60)
print("TESTE — AGENTE 5: ESTIMADOR DE PREÇO E LIQUIDEZ")
print("=" * 60)

# ==============================================================
# TESTE 1: Execução com dados reais (JSONs já gerados)
# ==============================================================
print("\n--- TESTE 1: Execução com dados reais ---")

from agents.price_liquidity import estimar_preco

resultado = estimar_preco({"area_terreno": 360})

assert resultado, "Resultado vazio!"
assert "avaliacao" in resultado, "Falta seção 'avaliacao'"
assert "liquidez" in resultado, "Falta seção 'liquidez'"

avaliacao = resultado["avaliacao"]
liquidez = resultado["liquidez"]

print(f"  Valor mínimo:  R$ {avaliacao['valor_minimo_imovel']:,.2f}")
print(f"  Valor médio:   R$ {avaliacao['valor_medio_imovel']:,.2f}")
print(f"  Valor liquidez: R$ {avaliacao['valor_liquidez']:,.2f}")
print(f"  Desconto:      {avaliacao['desconto_liquidez_percentual']}%")
print(f"  Score liquidez: {liquidez['score_liquidez']}")
print(f"  Classificação:  {liquidez['classificacao']}")
print(f"  Tempo estimado: {liquidez['tempo_estimado']}")
print(f"  Tempo regional: {liquidez.get('tempo_liquidez_regional_ag4', '?')}")

# Validações
assert avaliacao["valor_medio_imovel"] > 0, "Valor médio deve ser > 0"
assert avaliacao["valor_liquidez"] < avaliacao["valor_medio_imovel"], "Liquidez deve ser menor que médio"
assert avaliacao["desconto_liquidez_percentual"] == 10.0, "Desconto deve ser 10%"
assert 0 <= liquidez["score_liquidez"] <= 1, "Score deve estar entre 0 e 1"
assert liquidez["classificacao"] in ["alta", "media_alta", "media", "baixa"]
assert liquidez["tempo_estimado"] in ["30 a 60 dias", "60 a 90 dias", "90 a 150 dias", "acima de 150 dias"]

print("  ✅ Todas as validações passaram!")

# ==============================================================
# TESTE 2: Verificação do TRIMMEAN
# ==============================================================
print("\n--- TESTE 2: TRIMMEAN (0.5) ---")

from agents.price_liquidity import calcular_media_aparada

valores = [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000, 1100, 1200]
# Remove 25% menores (3) + 25% maiores (3) = sobra [400, 500, 600, 700, 800, 900]
# Média = 650
resultado_trim = calcular_media_aparada(valores, 0.5)
print(f"  Valores: {valores}")
print(f"  TRIMMEAN(0.5): {resultado_trim}")
assert 600 <= resultado_trim <= 700, f"Esperado ~650, got {resultado_trim}"
print("  ✅ TRIMMEAN funcionando corretamente!")

# ==============================================================
# TESTE 3: Fallback com poucos dados (usa mediana)
# ==============================================================
print("\n--- TESTE 3: Fallback com poucos dados ---")

from agents.price_liquidity import calcular_estatistica

# Com 3 valores, deve usar mediana
valores_poucos = [100, 500, 900]
resultado_poucos = calcular_estatistica(valores_poucos, "media_aparada")
print(f"  Valores: {valores_poucos}")
print(f"  Resultado (mediana): {resultado_poucos}")
assert resultado_poucos == 500, f"Esperado 500, got {resultado_poucos}"
print("  ✅ Fallback para mediana funcionando!")

# ==============================================================
# TESTE 4: Imóvel condominial (sem terreno)
# ==============================================================
print("\n--- TESTE 4: Imóvel condominial (apartamento) ---")

from agents.price_liquidity import executar_agente5

resultado_apto = executar_agente5(
    imovel_alvo={"propertyType": "Apartamentos", "area": 80, "bedrooms": 2},
    terrenos_zona=[{"price": 300000, "area": 200, "propertyType": "Terrenos"}],
    comparaveis_zona=[
        {"price": 400000, "area": 80, "propertyType": "Apartamentos", "id": "1"},
        {"price": 500000, "area": 90, "propertyType": "Apartamentos", "id": "2"},
    ],
    dados_ag3={"imovel_alvo": {"analise_qualitativa": {"scores": {"score_qualitativo": 0.7}, "padrao_acabamento": "medio"}}},
    dados_ag4={"scores": {"score_final": 0.6}},
)

print(f"  Tipo: {resultado_apto['imovel_alvo']['tipo']}")
print(f"  Terreno aplicado: {resultado_apto['calculo_terreno']['aplicado']}")
print(f"  Valor médio: R$ {resultado_apto['avaliacao']['valor_medio_imovel']:,.2f}")

assert resultado_apto["calculo_terreno"]["aplicado"] == False, "Apartamento não deve ter terreno"
assert resultado_apto["avaliacao"]["valor_medio_imovel"] > 0, "Valor deve ser > 0"
print("  ✅ Apartamento calculado sem terreno!")

# ==============================================================
# TESTE 5: Verificação do JSON de saída
# ==============================================================
print("\n--- TESTE 5: JSON de saída ---")

caminho = Path("data/preco_liquidez_ag5.json")
assert caminho.exists(), f"Arquivo {caminho} não encontrado!"

with open(caminho, encoding="utf-8") as f:
    dados = json.load(f)

campos_obrigatorios = ["agente", "metodo", "imovel_alvo", "valor_m2_zona_homogenea",
                       "calculo_terreno", "calculo_construcao", "avaliacao", "liquidez", "justificativa"]

for campo in campos_obrigatorios:
    assert campo in dados, f"Falta campo '{campo}' no JSON!"

print(f"  Arquivo: {caminho}")
print(f"  Campos: {len(campos_obrigatorios)} obrigatórios ✓")
print(f"  Justificativa: {dados['justificativa'][:80]}...")
print("  ✅ JSON de saída completo!")

# ==============================================================
print("\n" + "=" * 60)
print("TODOS OS TESTES PASSARAM ✅")
print("=" * 60)
