"""
Calcula Precisão, Revocação e F1 a partir da rotulagem cega.
Cruza os rótulos manuais com a classificação do sistema (mapa interno).
"""
import sys, json, csv
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

DATA_DIR = Path(__file__).parent.parent / "data"
RESULTADO_DIR = DATA_DIR / "avaliacao"

CSV_ROTULAGEM = RESULTADO_DIR / "rotulagem_cega.csv"
MAPA_FILE = RESULTADO_DIR / "mapa_rotulagem_cega.json"
RESULTADO_FILE = RESULTADO_DIR / "resultado_filtragem.json"

# Carrega mapa (número CSV → cluster do sistema)
with open(MAPA_FILE, "r", encoding="utf-8") as f:
    mapa = json.load(f)

mapa_dict = {item["numero_csv"]: item for item in mapa}

# Lê CSV rotulado
registros = []
with open(CSV_ROTULAGEM, "r", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        rotulo = row.get("rotulo_manual", "").strip()
        if rotulo not in ("0", "1"):
            continue
        numero = int(row["numero"])
        info_sistema = mapa_dict.get(numero, {})
        registros.append({
            "numero": numero,
            "cluster_sistema": info_sistema.get("cluster_sistema", "?"),
            "rotulo_manual": int(rotulo),
        })

if not registros:
    print("❌ Nenhum imóvel rotulado encontrado. Verifique a coluna 'rotulo_manual'.")
    sys.exit(1)

print(f"Total rotulados: {len(registros)}")

# Calcula VP, FP, FN, VN
# Positivo = sistema classifica como comparável (cluster "A")
# Negativo = sistema classifica como não comparável (cluster "B" ou "terreno")
vp = 0  # sistema=A, humano=1
fp = 0  # sistema=A, humano=0
fn = 0  # sistema≠A, humano=1
vn = 0  # sistema≠A, humano=0

for r in registros:
    sistema_positivo = r["cluster_sistema"] == "A"
    humano_positivo = r["rotulo_manual"] == 1

    if sistema_positivo and humano_positivo:
        vp += 1
    elif sistema_positivo and not humano_positivo:
        fp += 1
    elif not sistema_positivo and humano_positivo:
        fn += 1
    else:
        vn += 1

# Métricas
precisao = vp / (vp + fp) if (vp + fp) > 0 else 0
revocacao = vp / (vp + fn) if (vp + fn) > 0 else 0
f1 = (2 * precisao * revocacao / (precisao + revocacao)) if (precisao + revocacao) > 0 else 0
acuracia = (vp + vn) / len(registros) if registros else 0

# Relatório
print()
print("=" * 70)
print("AVALIAÇÃO DA FILTRAGEM — AGENTE 2 (Rotulagem Cega)")
print("=" * 70)

print(f"\nTotal rotulados: {len(registros)}")
print(f"\nMatriz de Confusão:")
print(f"                        Humano: COMPARÁVEL   Humano: NÃO COMPARÁVEL")
print(f"  Sistema: Cluster A    VP = {vp:<14}  FP = {fp}")
print(f"  Sistema: Cluster B    FN = {fn:<14}  VN = {vn}")

print(f"\n─── MÉTRICAS ───")
print(f"  Precisão:   {precisao:.1%}  (dos selecionados pelo sistema, {precisao:.0%} são de fato comparáveis)")
print(f"  Revocação:  {revocacao:.1%}  (dos comparáveis reais, o sistema encontrou {revocacao:.0%})")
print(f"  F1-score:   {f1:.1%}  (equilíbrio entre precisão e revocação)")
print(f"  Acurácia:   {acuracia:.1%}  (classificações corretas no total)")

print(f"\n─── INTERPRETAÇÃO ───")
if f1 >= 0.8:
    print("  ✅ F1 alto: sistema classifica comparáveis com alta qualidade")
elif f1 >= 0.6:
    print("  ⚠️ F1 moderado: sistema funciona mas com margem de melhoria")
else:
    print("  ❌ F1 baixo: sistema precisa melhorar a classificação")

if precisao > revocacao:
    print(f"  → Sistema é mais CONSERVADOR (precisão > revocação): prefere não incluir do que incluir errado")
else:
    print(f"  → Sistema é mais GENEROSO (revocação > precisão): prefere incluir demais do que perder comparáveis")

# Salva resultado
resultado = {
    "data_avaliacao": "2026-06-09",
    "total_rotulados": len(registros),
    "matriz_confusao": {
        "verdadeiro_positivo_VP": vp,
        "falso_positivo_FP": fp,
        "falso_negativo_FN": fn,
        "verdadeiro_negativo_VN": vn,
    },
    "metricas": {
        "precisao": round(precisao, 4),
        "revocacao": round(revocacao, 4),
        "f1_score": round(f1, 4),
        "acuracia": round(acuracia, 4),
    },
    "explicacao": {
        "precisao": "Dos imóveis que o sistema classificou como comparáveis (Cluster A), qual proporção é realmente comparável. Precisão = VP / (VP + FP).",
        "revocacao": "De todos os imóveis realmente comparáveis (rotulação humana), qual proporção o sistema identificou. Revocação = VP / (VP + FN).",
        "f1_score": "Média harmônica entre precisão e revocação. F1 = 2×P×R / (P+R).",
    },
}

with open(RESULTADO_FILE, "w", encoding="utf-8") as f:
    json.dump(resultado, f, ensure_ascii=False, indent=2)

print(f"\n📁 Resultado salvo em: {RESULTADO_FILE}")
