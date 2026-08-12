import json

d = json.load(open("data/imoveis_coletados_ag1.json", encoding="utf-8"))
total = len(d)
com_pub = sum(1 for i in d if i.get("publishedAt"))
print(f"Total: {total}")
print(f"Com publishedAt: {com_pub}")
print(f"Sem publishedAt: {total - com_pub}")
print()
print("Primeiros 5:")
for i in d[:5]:
    print(f"  publishedAt: {i.get('publishedAt', 'NULO')} | source: {i.get('source', '?')}")

# Verifica se completos e coletados sao diferentes
import os
if os.path.exists("data/imoveis_completos_ag1.json"):
    c = json.load(open("data/imoveis_completos_ag1.json", encoding="utf-8"))
    print(f"\nimoveis_completos_ag1.json: {len(c)} imóveis")
    print(f"imoveis_coletados_ag1.json: {len(d)} imóveis")
    print(f"Diferença: {len(d) - len(c)}")
else:
    print("\nimoveis_completos_ag1.json NAO EXISTE")
