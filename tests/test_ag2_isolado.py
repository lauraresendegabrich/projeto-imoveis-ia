"""Teste isolado do Agente 2 — Identificação de Comparáveis."""
import sys
import os
import json
import logging
import time

sys.path.insert(0, ".")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

from dotenv import load_dotenv
load_dotenv(override=True)

from agents.comparables import identificar_comparaveis

print("=" * 60)
print("TESTE ISOLADO — AGENTE 2: IDENTIFICADOR DE COMPARÁVEIS")
print("=" * 60)

# ── IMÓVEL ALVO (ajuste conforme seu teste) ────────────────────────
imovel_alvo = {
    "endereco": "Rua Codajás, 14, São Gabriel, Belo Horizonte, MG, Brasil",
    "localizacao": "Belo Horizonte, MG",
    "cidade": "Belo Horizonte",
    "estado": "MG",
    "bairro": "São Gabriel",
    "rua": "Rua Codajás",
    "tipo_imovel": "apartment",
    "propertyType": "apartment",
    "area": 120,
    "area_terreno": 0,
    "bedrooms": 3,
    "bathrooms": 2,
    "suites": 1,
    "parkingSpaces": 2,
    "price": 450000,
}

# ── VERIFICA SE TEM DADOS DO AG1 ──────────────────────────────────
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
arquivo_ag1 = os.path.join(DATA_DIR, "imoveis_completos_ag1.json")

if not os.path.exists(arquivo_ag1):
    print(f"\n⚠️  Arquivo não encontrado: {arquivo_ag1}")
    print("   Rode o Agente 1 primeiro ou ajuste o caminho.")
    sys.exit(1)

with open(arquivo_ag1, "r", encoding="utf-8") as f:
    imoveis_ag1 = json.load(f)

print(f"\n📂 Dados do Ag1: {len(imoveis_ag1)} imóveis carregados")
print(f"📍 Imóvel alvo: {imovel_alvo['endereco']}")
print(f"   Área: {imovel_alvo['area']}m² | Quartos: {imovel_alvo['bedrooms']} | Vagas: {imovel_alvo['parkingSpaces']}")
print()

# ── EXECUTA O AGENTE 2 ─────────────────────────────────────────────
t0 = time.time()

resultado = identificar_comparaveis(
    imovel_alvo=imovel_alvo,
    imoveis_coletados=imoveis_ag1,
    usar_llm=True,
)

tempo = time.time() - t0

# ── RESULTADOS ─────────────────────────────────────────────────────
print(f"\n{'=' * 60}")
print(f"RESULTADO — Tempo: {tempo:.1f}s")
print(f"{'=' * 60}")

comparaveis = resultado.get("comparaveis", [])
resumo = resultado.get("resumo", {})

print(f"\n📊 Resumo:")
print(f"   Total comparáveis: {len(comparaveis)}")
print(f"   Cluster A: {sum(1 for c in comparaveis if c.get('cluster') == 'A')}")
print(f"   Cluster B: {sum(1 for c in comparaveis if c.get('cluster') == 'B')}")

terrenos = resultado.get("terrenos", [])
if terrenos:
    print(f"   Terrenos identificados: {len(terrenos)}")

# Top 10 do Cluster A
cluster_a = [c for c in comparaveis if c.get("cluster") == "A"]
cluster_a.sort(key=lambda x: x.get("ranking_llm") or x.get("score_numerico") or 999)

print(f"\n🏆 Top 10 Cluster A (mais similares):")
for i, c in enumerate(cluster_a[:10], 1):
    area = c.get("area") or c.get("area_construida") or "?"
    quartos = c.get("bedrooms") or c.get("quartos") or "?"
    preco = c.get("price") or c.get("preco") or 0
    rua = c.get("street") or c.get("rua") or "?"
    bairro = c.get("neighborhood") or c.get("bairro") or "?"
    ranking = c.get("ranking_llm") or "-"
    score = c.get("score_numerico") or 0
    try:
        preco = float(preco)
    except (ValueError, TypeError):
        preco = 0
    print(f"  [{i:>2}] {area:>5}m² | {quartos}q | R$ {preco:>12,.0f} | rank={ranking} | score={score:.2f} | {rua[:30]} | {bairro}")

# Zona homogênea
zona_path = os.path.join(DATA_DIR, "zona_homogenea_ag2.json")
if os.path.exists(zona_path):
    with open(zona_path, "r", encoding="utf-8") as f:
        zona = json.load(f)
    confirmados = zona.get("comparaveis_confirmados", [])
    na_zona = [c for c in confirmados if c.get("classificacao_zona") == "na_zona"]
    fora = [c for c in confirmados if c.get("classificacao_zona") == "fora_zona"]
    print(f"\n🗺️  Zona Homogênea:")
    print(f"   Na zona: {len(na_zona)}")
    print(f"   Fora da zona: {len(fora)}")
    print(f"   Total confirmados: {len(confirmados)}")

print(f"\n✅ Teste finalizado em {tempo:.1f}s")
