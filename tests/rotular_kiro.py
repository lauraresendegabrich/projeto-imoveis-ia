"""
Rotulagem automática pelo Kiro usando os mesmos critérios da LLM.
Imóvel alvo: Casa, 190m², 3 quartos, 3 banheiros, 2 vagas, Cidade Nova, Manaus/AM, R$450.000

Critérios (mesmos do prompt da LLM):
  COMPARÁVEL (1) se:
    - Mesmo tipo (casa)
    - Área na mesma faixa (diferença até 50% → 95m² a 285m²)
    - Quartos ±1 (2 a 4 quartos)
    - Mesmo bairro (Cidade Nova)
    - Preço/m² na mesma faixa (até 50% diferença)
    - NÃO precisa ser idêntico
  NÃO COMPARÁVEL (0) se:
    - Tipo diferente (terreno)
    - Área MUITO diferente (< 95m² ou > 380m²)
    - Padrão MUITO diferente
    - Uso diferente (comercial)
"""
import sys, csv, json, copy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

RESULTADO_DIR = Path(__file__).parent.parent / "data" / "avaliacao"
CSV_INPUT = RESULTADO_DIR / "rotulagem_cega.csv"
CSV_OUTPUT = RESULTADO_DIR / "rotulagem_kiro.csv"

# Alvo
ALVO_AREA = 190
ALVO_QUARTOS = 3
ALVO_BANHEIROS = 3
ALVO_PRECO = 450000
ALVO_PRECO_M2 = 450000 / 190  # ~2368

# Limites
AREA_MIN = ALVO_AREA * 0.50  # 95m²
AREA_MAX = ALVO_AREA * 2.0   # 380m²
QUARTOS_MIN = 2
QUARTOS_MAX = 5
PRECO_M2_MIN = ALVO_PRECO_M2 * 0.30  # ~710
PRECO_M2_MAX = ALVO_PRECO_M2 * 2.5   # ~5921

rows = []
with open(CSV_INPUT, "r", encoding="utf-8") as f:
    reader = csv.DictReader(f)
    for row in reader:
        rows.append(row)

resultados = []
for row in rows:
    tipo = row.get("tipo", "").strip()
    area_str = row.get("area_m2", "0").strip()
    quartos_str = row.get("quartos", "0").strip()
    banheiros_str = row.get("banheiros", "0").strip()
    preco_str = row.get("preco", "").replace("R$", "").replace(",", "").strip()
    preco_m2_str = row.get("preco_m2", "").replace("R$", "").replace(",", "").strip()
    bairro = row.get("bairro", "").strip()
    desc = row.get("descricao", "").lower()

    # Parse numéricos
    try:
        area = float(area_str) if area_str else 0
    except:
        area = 0
    try:
        quartos = int(quartos_str) if quartos_str else 0
    except:
        quartos = 0
    try:
        preco_m2 = float(preco_m2_str) if preco_m2_str and preco_m2_str != "?" else 0
    except:
        preco_m2 = 0

    rotulo = 0  # default: não comparável

    # Regra 1: Terrenos NUNCA são comparáveis
    if "terreno" in tipo.lower():
        rotulo = 0

    # Regra 2: Deve ser casa
    elif "casa" not in tipo.lower():
        rotulo = 0

    # Regra 3: Mesmo bairro (Cidade Nova)
    elif "cidade nova" not in bairro.lower():
        rotulo = 0

    # Regra 4: Área dentro da faixa (95-380m²)
    elif area < AREA_MIN or area > AREA_MAX:
        rotulo = 0

    # Regra 5: Quartos (2 a 5)
    elif quartos < QUARTOS_MIN or quartos > QUARTOS_MAX:
        rotulo = 0

    # Regra 6: Não ser comercial / leilão / kitnet / investimento puro
    elif any(w in desc for w in ["leilão", "leilao", "kitnet", "kit net", "quitinete"]):
        rotulo = 0

    # Regra 7: Imóvel com muitos apartamentos/kitinets = investimento, não comparável
    elif any(w in desc for w in ["4 kitinetes", "3 kitinetes", "5 kitinetes", "barracões", "barracoes"]):
        rotulo = 0

    else:
        # Passou todos os filtros → comparável
        rotulo = 1

    resultados.append({**row, "rotulo_kiro": str(rotulo)})

# Salva CSV com rotulação do Kiro
with open(CSV_OUTPUT, "w", newline="", encoding="utf-8") as f:
    fieldnames = list(rows[0].keys()) + ["rotulo_kiro"]
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    for r in resultados:
        writer.writerow(r)

# Estatísticas
total = len(resultados)
comparaveis = sum(1 for r in resultados if r["rotulo_kiro"] == "1")
nao_comparaveis = total - comparaveis
print(f"Total: {total}")
print(f"Comparáveis (1): {comparaveis}")
print(f"Não comparáveis (0): {nao_comparaveis}")
print(f"\nCSV salvo em: {CSV_OUTPUT}")

# Agora calcula métricas vs sistema
mapa_file = RESULTADO_DIR / "mapa_rotulagem_cega.json"
with open(mapa_file, "r", encoding="utf-8") as f:
    mapa = json.load(f)
mapa_dict = {item["numero_csv"]: item for item in mapa}

vp, fp, fn, vn = 0, 0, 0, 0
for r in resultados:
    numero = int(r["numero"])
    info = mapa_dict.get(numero, {})
    cluster = info.get("cluster_sistema", "?")
    kiro = int(r["rotulo_kiro"])

    sistema_positivo = cluster == "A"
    kiro_positivo = kiro == 1

    if sistema_positivo and kiro_positivo:
        vp += 1
    elif sistema_positivo and not kiro_positivo:
        fp += 1
    elif not sistema_positivo and kiro_positivo:
        fn += 1
    else:
        vn += 1

precisao = vp / (vp + fp) if (vp + fp) > 0 else 0
revocacao = vp / (vp + fn) if (vp + fn) > 0 else 0
f1 = (2 * precisao * revocacao / (precisao + revocacao)) if (precisao + revocacao) > 0 else 0
acuracia = (vp + vn) / total

print(f"\n{'='*60}")
print(f"MÉTRICAS: SISTEMA vs KIRO")
print(f"{'='*60}")
print(f"  VP={vp} | FP={fp} | FN={fn} | VN={vn}")
print(f"  Precisão:  {precisao:.1%}")
print(f"  Revocação: {revocacao:.1%}")
print(f"  F1-score:  {f1:.1%}")
print(f"  Acurácia:  {acuracia:.1%}")

# Também calcula vs rotulação humana
print(f"\n{'='*60}")
print(f"MÉTRICAS: SISTEMA vs HUMANO (sua rotulação)")
print(f"{'='*60}")

vp2, fp2, fn2, vn2 = 0, 0, 0, 0
for r in resultados:
    numero = int(r["numero"])
    info = mapa_dict.get(numero, {})
    cluster = info.get("cluster_sistema", "?")
    humano = r.get("rotulo_manual", "").strip()
    if humano not in ("0", "1"):
        continue
    humano = int(humano)
    sistema_positivo = cluster == "A"
    if sistema_positivo and humano == 1:
        vp2 += 1
    elif sistema_positivo and humano == 0:
        fp2 += 1
    elif not sistema_positivo and humano == 1:
        fn2 += 1
    else:
        vn2 += 1

total2 = vp2 + fp2 + fn2 + vn2
if total2 > 0:
    p2 = vp2 / (vp2 + fp2) if (vp2 + fp2) > 0 else 0
    r2 = vp2 / (vp2 + fn2) if (vp2 + fn2) > 0 else 0
    f12 = (2 * p2 * r2 / (p2 + r2)) if (p2 + r2) > 0 else 0
    print(f"  VP={vp2} | FP={fp2} | FN={fn2} | VN={vn2}")
    print(f"  Precisão:  {p2:.1%}")
    print(f"  Revocação: {r2:.1%}")
    print(f"  F1-score:  {f12:.1%}")

# Concordância Kiro vs Humano
print(f"\n{'='*60}")
print(f"CONCORDÂNCIA: KIRO vs HUMANO")
print(f"{'='*60}")
concordam = 0
discordam = 0
for r in resultados:
    humano = r.get("rotulo_manual", "").strip()
    if humano not in ("0", "1"):
        continue
    if r["rotulo_kiro"] == humano:
        concordam += 1
    else:
        discordam += 1
total_comp = concordam + discordam
if total_comp > 0:
    print(f"  Concordam: {concordam}/{total_comp} ({concordam/total_comp:.1%})")
    print(f"  Discordam: {discordam}/{total_comp} ({discordam/total_comp:.1%})")
