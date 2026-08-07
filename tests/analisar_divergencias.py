"""Mostra os imóveis onde houve divergência entre sistema e humano."""
import sys, json, csv
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

DATA_DIR = Path(__file__).parent.parent / "data"
RESULTADO_DIR = DATA_DIR / "avaliacao"

# Carrega mapa
with open(RESULTADO_DIR / "mapa_rotulagem_cega.json", "r", encoding="utf-8") as f:
    mapa = json.load(f)
mapa_dict = {item["numero_csv"]: item for item in mapa}

# Lê CSV rotulado
with open(RESULTADO_DIR / "rotulagem_cega.csv", "r", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    rows = list(reader)

# Classifica divergências
fp_list = []  # Sistema=A, Humano=0 (sistema incluiu, você excluiu)
fn_list = []  # Sistema≠A, Humano=1 (sistema excluiu, você incluiu)

for row in rows:
    rotulo = row.get("rotulo_manual", "").strip()
    if rotulo not in ("0", "1"):
        continue
    numero = int(row["numero"])
    info = mapa_dict.get(numero, {})
    cluster = info.get("cluster_sistema", "?")
    humano = int(rotulo)

    item = {
        "numero": numero,
        "tipo": row.get("tipo", "?"),
        "area": row.get("area_m2", "?"),
        "quartos": row.get("quartos", "?"),
        "banheiros": row.get("banheiros", "?"),
        "preco": row.get("preco", "?"),
        "preco_m2": row.get("preco_m2", "?"),
        "bairro": row.get("bairro", "?"),
        "rua": row.get("rua", "?"),
        "desc": (row.get("descricao", "") or "")[:100],
        "cluster_sistema": cluster,
        "score": info.get("score_similaridade", 0),
    }

    if cluster == "A" and humano == 0:
        fp_list.append(item)
    elif cluster != "A" and humano == 1:
        fn_list.append(item)

# Imóvel alvo para referência
print("=" * 80)
print("REFERÊNCIA: IMÓVEL ALVO")
print("  Casa | 190m² | 3q | 3b | 2v | Cidade Nova, Manaus/AM | R$450.000")
print("=" * 80)

print(f"\n{'='*80}")
print(f"FALSOS POSITIVOS ({len(fp_list)}): Sistema disse COMPARÁVEL, você disse NÃO")
print(f"{'='*80}")
for i, item in enumerate(fp_list, 1):
    print(f"\n  [{item['numero']}] {item['tipo']} | {item['area']}m² | {item['quartos']}q | {item['banheiros']}b | {item['preco']} | {item['preco_m2']}/m²")
    print(f"       Bairro: {item['bairro']} | Rua: {item['rua']}")
    print(f"       Score: {item['score']:.3f} | Desc: {item['desc']}")

print(f"\n{'='*80}")
print(f"FALSOS NEGATIVOS ({len(fn_list)}): Sistema disse NÃO COMPARÁVEL, você disse SIM")
print(f"{'='*80}")
for i, item in enumerate(fn_list, 1):
    print(f"\n  [{item['numero']}] {item['tipo']} | {item['area']}m² | {item['quartos']}q | {item['banheiros']}b | {item['preco']} | {item['preco_m2']}/m²")
    print(f"       Bairro: {item['bairro']} | Rua: {item['rua']}")
    print(f"       Score: {item['score']:.3f} | Cluster: {item['cluster_sistema']} | Desc: {item['desc']}")

# Análise resumida
print(f"\n{'='*80}")
print("ANÁLISE DAS DIVERGÊNCIAS")
print(f"{'='*80}")

# FP: por que o sistema incluiu e você não?
fp_bairros = [item["bairro"] for item in fp_list]
fp_areas = [int(item["area"]) for item in fp_list if item["area"] != "?"]
print(f"\nFALSOS POSITIVOS (sistema generoso demais):")
print(f"  Bairros: {set(fp_bairros)}")
if fp_areas:
    print(f"  Áreas: {min(fp_areas)}m² a {max(fp_areas)}m² (alvo: 190m²)")

# FN: por que o sistema excluiu e você incluiu?
fn_bairros = [item["bairro"] for item in fn_list]
fn_areas = [int(item["area"]) for item in fn_list if item["area"] != "?"]
fn_clusters = [item["cluster_sistema"] for item in fn_list]
print(f"\nFALSOS NEGATIVOS (sistema conservador demais):")
print(f"  Bairros: {set(fn_bairros)}")
if fn_areas:
    print(f"  Áreas: {min(fn_areas)}m² a {max(fn_areas)}m² (alvo: 190m²)")
print(f"  Clusters originais: {set(fn_clusters)}")
