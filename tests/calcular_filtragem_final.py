"""
Calcula Precisão, Revocação e F1 para todos os 11 imóveis,
comparando Sistema vs Laura, Lívia e Kiro.

COMO RODAR:
    .venv\\Scripts\\python.exe tests/calcular_filtragem_final.py
"""
import sys, json, csv
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).parent.parent))

BASE_DIR = Path(__file__).parent.parent / "data" / "avaliacao" / "filtragem"
RESULTADO_FILE = Path(__file__).parent.parent / "data" / "avaliacao" / "resultado_filtragem_final.json"

IMOVEL_IDS = [1, 2, 3, 5, 7, 8, 10, 11, 13, 14, 15]
AVALIADORES = ["laura", "livia", "kiro"]


def calcular_metricas_avaliador(mapa: list, rotulos: dict) -> dict:
    """Calcula VP, FP, FN, VN, P, R, F1 para um avaliador."""
    vp, fp, fn, vn = 0, 0, 0, 0
    total_rotulados = 0

    for item in mapa:
        numero = item["numero_csv"]
        cluster = item["cluster_sistema"]
        rotulo = rotulos.get(numero)

        if rotulo is None:
            continue
        total_rotulados += 1

        sistema_positivo = cluster == "A"
        humano_positivo = rotulo == 1

        if sistema_positivo and humano_positivo:
            vp += 1
        elif sistema_positivo and not humano_positivo:
            fp += 1
        elif not sistema_positivo and humano_positivo:
            fn += 1
        else:
            vn += 1

    precisao = vp / (vp + fp) if (vp + fp) > 0 else 0
    revocacao = vp / (vp + fn) if (vp + fn) > 0 else 0
    f1 = (2 * precisao * revocacao / (precisao + revocacao)) if (precisao + revocacao) > 0 else 0
    acuracia = (vp + vn) / total_rotulados if total_rotulados > 0 else 0

    return {
        "total_rotulados": total_rotulados,
        "vp": vp, "fp": fp, "fn": fn, "vn": vn,
        "precisao": round(precisao, 4),
        "revocacao": round(revocacao, 4),
        "f1_score": round(f1, 4),
        "acuracia": round(acuracia, 4),
    }


def ler_rotulos(csv_path: Path) -> dict:
    """Lê rotulagem de um CSV e retorna {numero: rotulo}."""
    rotulos = {}
    if not csv_path.exists():
        return rotulos
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rotulo = (row.get("rotulo_manual") or "").strip()
            if rotulo in ("0", "1"):
                try:
                    rotulos[int(row["numero"])] = int(rotulo)
                except (ValueError, KeyError):
                    continue
    return rotulos


# =============================================================================
# MAIN
# =============================================================================

print("=" * 70)
print("AVALIAÇÃO FINAL — FILTRAGEM DO AGENTE 2")
print("Sistema vs Laura vs Lívia vs Kiro (11 imóveis)")
print("=" * 70)

resultados_por_imovel = []
metricas_globais = {av: {"vp": 0, "fp": 0, "fn": 0, "vn": 0, "total": 0} for av in AVALIADORES}

for imovel_id in IMOVEL_IDS:
    pasta = BASE_DIR / f"imovel_{imovel_id:02d}"
    mapa_path = pasta / "mapa_interno.json"

    if not mapa_path.exists():
        print(f"  ⚠️ Imóvel {imovel_id}: mapa não encontrado, pulando")
        continue

    with open(mapa_path, "r", encoding="utf-8") as f:
        mapa = json.load(f)

    resultado_imovel = {"id": imovel_id, "avaliadores": {}}

    for av in AVALIADORES:
        csv_path = pasta / f"rotulagem_{av}.csv"
        rotulos = ler_rotulos(csv_path)

        if not rotulos:
            resultado_imovel["avaliadores"][av] = {"status": "sem_rotulagem"}
            continue

        metricas = calcular_metricas_avaliador(mapa, rotulos)
        resultado_imovel["avaliadores"][av] = metricas

        # Acumula globais
        metricas_globais[av]["vp"] += metricas["vp"]
        metricas_globais[av]["fp"] += metricas["fp"]
        metricas_globais[av]["fn"] += metricas["fn"]
        metricas_globais[av]["vn"] += metricas["vn"]
        metricas_globais[av]["total"] += metricas["total_rotulados"]

    resultados_por_imovel.append(resultado_imovel)

# Calcula métricas globais (micro-average)
print("\n" + "=" * 70)
print("RESULTADOS GLOBAIS (micro-average de todos os imóveis)")
print("=" * 70)

resultado_global = {}
for av in AVALIADORES:
    g = metricas_globais[av]
    vp, fp, fn, vn = g["vp"], g["fp"], g["fn"], g["vn"]
    total = g["total"]

    p = vp / (vp + fp) if (vp + fp) > 0 else 0
    r = vp / (vp + fn) if (vp + fn) > 0 else 0
    f1 = (2 * p * r / (p + r)) if (p + r) > 0 else 0
    acc = (vp + vn) / total if total > 0 else 0

    resultado_global[av] = {
        "total_rotulados": total,
        "vp": vp, "fp": fp, "fn": fn, "vn": vn,
        "precisao": round(p, 4),
        "revocacao": round(r, 4),
        "f1_score": round(f1, 4),
        "acuracia": round(acc, 4),
    }

    print(f"\n  {av.upper()}:")
    print(f"    Total rotulados: {total}")
    print(f"    VP={vp} | FP={fp} | FN={fn} | VN={vn}")
    print(f"    Precisão:  {p:.1%}")
    print(f"    Revocação: {r:.1%}")
    print(f"    F1-score:  {f1:.1%}")
    print(f"    Acurácia:  {acc:.1%}")

# Concordância entre avaliadores
print("\n" + "=" * 70)
print("CONCORDÂNCIA ENTRE AVALIADORES")
print("=" * 70)

concordancias = {}
pares = [("laura", "livia"), ("laura", "kiro"), ("livia", "kiro")]
for av1, av2 in pares:
    concordam = 0
    total_pares = 0
    for imovel_id in IMOVEL_IDS:
        pasta = BASE_DIR / f"imovel_{imovel_id:02d}"
        r1 = ler_rotulos(pasta / f"rotulagem_{av1}.csv")
        r2 = ler_rotulos(pasta / f"rotulagem_{av2}.csv")
        for num in set(r1.keys()) & set(r2.keys()):
            total_pares += 1
            if r1[num] == r2[num]:
                concordam += 1

    pct = concordam / total_pares * 100 if total_pares > 0 else 0
    concordancias[f"{av1}_vs_{av2}"] = round(pct, 1)
    print(f"  {av1.capitalize()} vs {av2.capitalize()}: {concordam}/{total_pares} ({pct:.1f}%)")

# Salva resultado completo
saida = {
    "data_avaliacao": "2026-06-09",
    "total_imoveis": len(IMOVEL_IDS),
    "resultado_global": resultado_global,
    "concordancia_entre_avaliadores": concordancias,
    "resultados_por_imovel": resultados_por_imovel,
}

with open(RESULTADO_FILE, "w", encoding="utf-8") as f:
    json.dump(saida, f, ensure_ascii=False, indent=2)

print(f"\n📁 Resultado salvo em: {RESULTADO_FILE}")
