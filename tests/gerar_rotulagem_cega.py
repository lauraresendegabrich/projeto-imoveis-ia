"""
Gera CSV para rotulagem CEGA — mesmo formato que a LLM recebe.
Remove qualquer indicação de cluster/score do sistema.
"""
import sys, json, csv
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

DATA_DIR = Path(__file__).parent.parent / "data"
RESULTADO_DIR = DATA_DIR / "avaliacao"
CSV_SAIDA = RESULTADO_DIR / "rotulagem_cega.csv"

# Carrega saída do Agente 2
with open(DATA_DIR / "imoveis_comparaveis_ag2.json", "r", encoding="utf-8") as f:
    dados = json.load(f)

alvo = dados["imovel_alvo"]
comparaveis = dados.get("comparaveis", [])
terrenos = dados.get("terrenos", [])

# Imprime o alvo (mesmo que a LLM vê)
print("=" * 70)
print("IMÓVEL ALVO:")
print("=" * 70)
print(f"  Tipo: {alvo.get('propertyType', '?')}")
print(f"  Área: {alvo.get('area', '?')} m²")
print(f"  Quartos: {alvo.get('bedrooms', '?')}")
print(f"  Banheiros: {alvo.get('bathrooms', '?')}")
print(f"  Vagas: {alvo.get('parkingSpaces', '?')}")
print(f"  Bairro: {alvo.get('neighborhood', '?')}")
print(f"  Rua: {alvo.get('street', '?')}")
print(f"  Descrição: {(alvo.get('description') or '')[:200]}")
print("=" * 70)

# Junta todos e embaralha para não dar pista de clustering
import random
todos = comparaveis + terrenos
random.seed(42)  # seed fixa para reprodutibilidade
random.shuffle(todos)

print(f"\nTotal de imóveis para rotular: {len(todos)}")
print(f"CSV gerado em: {CSV_SAIDA}")
print()
print("CRITÉRIOS (mesmos que a LLM usa):")
print("  COMPARÁVEL (1) se:")
print("    - Mesmo tipo de imóvel (casa com casa)")
print("    - Área na mesma faixa (diferença até 50%)")
print("    - Nº de quartos próximo (diferença de 1 é aceitável)")
print("    - Mesmo bairro ou região equivalente")
print("    - Preço/m² na mesma faixa (diferença até 50%)")
print("    - NÃO precisa ser idêntico — basta ser comparável para avaliação")
print("  NÃO COMPARÁVEL (0) se:")
print("    - Tipo diferente (terreno vazio vs casa construída)")
print("    - Área MUITO diferente (>2x maior/menor)")
print("    - Padrão MUITO diferente (kitnet vs mansão)")
print("    - Uso diferente (comercial vs residencial)")

# Gera CSV — mesmas colunas que a LLM vê, SEM cluster e score
with open(CSV_SAIDA, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow([
        "numero", "tipo", "area_m2", "quartos", "banheiros", "vagas",
        "preco", "preco_m2", "bairro", "rua", "descricao",
        "rotulo_manual"
    ])

    for idx, im in enumerate(todos, 1):
        desc = (im.get("description") or "")[:300].replace("\n", " ").replace(",", ";")
        preco = im.get("price", 0)
        area = im.get("area", 0)
        preco_m2 = round(preco / area, 2) if area and preco else "?"

        writer.writerow([
            idx,
            im.get("propertyType", "?"),
            im.get("area", "?"),
            im.get("bedrooms", "?"),
            im.get("bathrooms", "?"),
            im.get("parkingSpaces", "?"),
            f"R$ {preco:,.0f}" if preco else "?",
            f"R$ {preco_m2:,.2f}" if isinstance(preco_m2, float) else "?",
            im.get("neighborhood", "?"),
            im.get("street", "?"),
            desc,
            ""  # PREENCHER: 1=comparável, 0=não
        ])

# Salva mapeamento interno (para depois cruzar com cluster do sistema)
mapa = []
for idx, im in enumerate(todos, 1):
    mapa.append({
        "numero_csv": idx,
        "id_original": im.get("id", "?"),
        "cluster_sistema": im.get("cluster", "?"),
        "score_similaridade": im.get("score_similaridade", 0),
    })

with open(RESULTADO_DIR / "mapa_rotulagem_cega.json", "w", encoding="utf-8") as f:
    json.dump(mapa, f, ensure_ascii=False, indent=2)

print(f"\n✅ CSV gerado: {CSV_SAIDA}")
print(f"✅ Mapa interno salvo (NÃO abra antes de rotular): mapa_rotulagem_cega.json")
