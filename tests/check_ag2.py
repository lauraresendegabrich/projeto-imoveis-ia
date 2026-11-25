import json

with open("data/imoveis_comparaveis_ag2.json", "r", encoding="utf-8") as f:
    data = json.load(f)

print(f"Total imóveis: {len(data)}")
print(f"Keys amostra: {list(data[0].keys())}")
clusters = set(d.get("cluster") for d in data)
print(f"Clusters: {clusters}")
for c in clusters:
    qtd = sum(1 for d in data if d.get("cluster") == c)
    print(f"  {c}: {qtd}")

# Mostra 1 exemplo
print("\nExemplo (1o imóvel):")
ex = data[0]
for k in ["street", "neighborhood", "area", "bedrooms", "price", "propertyType", "cluster", "score_similaridade"]:
    print(f"  {k}: {ex.get(k)}")
