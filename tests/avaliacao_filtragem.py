"""
Avaliação da Qualidade de Filtragem — Agente 2 (Identificador de Comparáveis)
===============================================================================

Avalia a eficácia do Agente 2 na classificação de imóveis como
"homogêneo/comparável" (Cluster A) ou "não comparável" (Cluster B).

Trata como problema de classificação binária:
  - Classe POSITIVA: imóvel é comparável (homogêneo ao alvo)
  - Classe NEGATIVA: imóvel não é comparável

Métricas calculadas:
  - Precisão: dos que o sistema classificou como comparáveis, quantos realmente são?
  - Revocação: dos que realmente são comparáveis, quantos o sistema identificou?
  - F1-score: média harmônica entre precisão e revocação

FLUXO:
  1. Rodar `gerar_csv_rotulagem()` → cria CSV com amostra para rotular
  2. Você abre o CSV, analisa cada imóvel e preenche a coluna "rotulo_manual"
     com 1 (comparável) ou 0 (não comparável)
  3. Rodar `calcular_metricas_filtragem()` → calcula P/R/F1

COMO RODAR:
    # Passo 1: gerar CSV para rotulagem
    .venv\\Scripts\\python.exe tests/avaliacao_filtragem.py --gerar

    # Passo 2: após rotular manualmente o CSV
    .venv\\Scripts\\python.exe tests/avaliacao_filtragem.py --calcular
"""

import sys
import os
import json
import csv
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

DATA_DIR = Path(__file__).parent.parent / "data"
RESULTADO_DIR = DATA_DIR / "avaliacao"
RESULTADO_DIR.mkdir(parents=True, exist_ok=True)

CSV_ROTULAGEM = RESULTADO_DIR / "rotulagem_comparaveis.csv"
RESULTADO_FILTRAGEM = RESULTADO_DIR / "resultado_filtragem.json"


# =============================================================================
# PASSO 1: GERAR CSV PARA ROTULAGEM MANUAL
# =============================================================================

def gerar_csv_rotulagem():
    """
    Carrega a saída do Agente 2 e gera um CSV com os imóveis para
    rotulagem manual. Inclui tanto Cluster A quanto B para permitir
    avaliação completa (precisão E revocação).

    O CSV terá as colunas:
      - id, cluster_sistema, score_similaridade
      - area, quartos, banheiros, vagas, preco, tipo, bairro, rua
      - descricao (resumida)
      - rotulo_manual (PREENCHER: 1=comparável, 0=não comparável)
    """
    # Carrega saída do Agente 2
    arquivo_ag2 = DATA_DIR / "imoveis_comparaveis_ag2.json"
    if not arquivo_ag2.exists():
        print("❌ Arquivo imoveis_comparaveis_ag2.json não encontrado.")
        print("   Rode o pipeline primeiro para gerar os dados do Agente 2.")
        sys.exit(1)

    with open(arquivo_ag2, "r", encoding="utf-8") as f:
        dados = json.load(f)

    imovel_alvo = dados.get("imovel_alvo", {})
    comparaveis = dados.get("comparaveis", [])
    terrenos = dados.get("terrenos", [])

    # Mostra o imóvel alvo como referência
    print("=" * 70)
    print("IMÓVEL ALVO (referência para rotulagem)")
    print("=" * 70)
    print(f"  Tipo:     {imovel_alvo.get('propertyType', '?')}")
    print(f"  Área:     {imovel_alvo.get('area', '?')} m²")
    print(f"  Quartos:  {imovel_alvo.get('bedrooms', '?')}")
    print(f"  Banheiros:{imovel_alvo.get('bathrooms', '?')}")
    print(f"  Vagas:    {imovel_alvo.get('parkingSpaces', '?')}")
    print(f"  Bairro:   {imovel_alvo.get('neighborhood', '?')}")
    print(f"  Cidade:   {imovel_alvo.get('localizacao', '?')}")
    print(f"  Descrição:{imovel_alvo.get('description', '?')[:100]}...")
    print()

    # Junta todos (comparáveis + terrenos) para rotulagem completa
    todos = comparaveis + terrenos

    if not todos:
        print("❌ Nenhum imóvel encontrado na saída do Agente 2.")
        sys.exit(1)

    # Seleciona amostra: todos do Cluster A + amostra do Cluster B + terrenos
    # Para calcular revocação, precisamos rotular também imóveis do Cluster B
    # (pode haver comparáveis lá que o sistema errou ao excluir)
    cluster_a = [c for c in comparaveis if c.get("cluster") == "A"]
    cluster_b = [c for c in comparaveis if c.get("cluster") != "A"]

    # Pega todos do A + até 20 do B (para ter amostra balanceada)
    amostra_b = cluster_b[:20] if len(cluster_b) > 20 else cluster_b
    amostra_terrenos = terrenos[:5] if len(terrenos) > 5 else terrenos

    amostra = cluster_a + amostra_b + amostra_terrenos
    print(f"Amostra para rotulagem: {len(amostra)} imóveis")
    print(f"  Cluster A (sistema diz comparável): {len(cluster_a)}")
    print(f"  Cluster B (sistema diz não comparável): {len(amostra_b)}")
    print(f"  Terrenos (sistema excluiu): {len(amostra_terrenos)}")
    print()

    # Gera CSV
    with open(CSV_ROTULAGEM, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "id", "cluster_sistema", "score_similaridade",
            "tipo", "area_m2", "quartos", "banheiros", "vagas",
            "preco", "bairro", "rua", "descricao_resumida",
            "rotulo_manual"
        ])

        for im in amostra:
            desc = (im.get("description") or "")[:150].replace("\n", " ").replace(",", ";")
            writer.writerow([
                im.get("id", "?"),
                im.get("cluster", "?"),
                round(im.get("score_similaridade", 0), 3),
                im.get("propertyType", "?"),
                im.get("area", "?"),
                im.get("bedrooms", "?"),
                im.get("bathrooms", "?"),
                im.get("parkingSpaces", "?"),
                im.get("price", "?"),
                im.get("neighborhood", "?"),
                im.get("street", "?"),
                desc,
                ""  # <- PREENCHER MANUALMENTE: 1=comparável, 0=não
            ])

    print(f"✅ CSV gerado: {CSV_ROTULAGEM}")
    print()
    print("PRÓXIMOS PASSOS:")
    print(f"  1. Abra o arquivo: {CSV_ROTULAGEM}")
    print(f"  2. Para cada linha, analise se o imóvel é COMPARÁVEL ao alvo")
    print(f"  3. Preencha a coluna 'rotulo_manual' com:")
    print(f"       1 = sim, é comparável (homogêneo)")
    print(f"       0 = não, não é comparável")
    print(f"  4. Salve o CSV e rode:")
    print(f"       .venv\\Scripts\\python.exe tests/avaliacao_filtragem.py --calcular")
    print()
    print("CRITÉRIOS SUGERIDOS PARA ROTULAGEM:")
    print("  COMPARÁVEL (1) se:")
    print("    - Mesmo tipo (casa vs casa, apto vs apto)")
    print("    - Área dentro de ±30% do alvo")
    print("    - Mesmo bairro ou bairro adjacente")
    print("    - Padrão construtivo similar (não misturar popular com alto luxo)")
    print("  NÃO COMPARÁVEL (0) se:")
    print("    - Tipo diferente (terreno vs casa construída)")
    print("    - Área muito diferente (ex: 42m² vs 250m²)")
    print("    - Bairro muito distante")
    print("    - Padrão muito diferente (ex: kitnet vs mansão)")


# =============================================================================
# PASSO 2: CALCULAR MÉTRICAS DE FILTRAGEM
# =============================================================================

def calcular_metricas_filtragem():
    """
    Lê o CSV rotulado e calcula Precisão, Revocação e F1-score.

    Definições:
      - VP (Verdadeiro Positivo): sistema diz A + humano diz 1
      - FP (Falso Positivo): sistema diz A + humano diz 0
      - FN (Falso Negativo): sistema diz B/terreno + humano diz 1
      - VN (Verdadeiro Negativo): sistema diz B/terreno + humano diz 0

    Métricas:
      - Precisão = VP / (VP + FP)
      - Revocação = VP / (VP + FN)
      - F1 = 2 × (Precisão × Revocação) / (Precisão + Revocação)
    """
    if not CSV_ROTULAGEM.exists():
        print("❌ CSV de rotulagem não encontrado. Rode primeiro com --gerar")
        sys.exit(1)

    # Lê CSV rotulado
    registros = []
    with open(CSV_ROTULAGEM, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rotulo = row.get("rotulo_manual", "").strip()
            if rotulo not in ("0", "1"):
                continue  # pula linhas não rotuladas
            registros.append({
                "id": row["id"],
                "cluster_sistema": row["cluster_sistema"],
                "rotulo_manual": int(rotulo),
            })

    if not registros:
        print("❌ Nenhum imóvel rotulado encontrado no CSV.")
        print("   Preencha a coluna 'rotulo_manual' com 0 ou 1.")
        sys.exit(1)

    # Calcula VP, FP, FN, VN
    vp = 0  # sistema=A, humano=1
    fp = 0  # sistema=A, humano=0
    fn = 0  # sistema=B ou terreno, humano=1
    vn = 0  # sistema=B ou terreno, humano=0

    for r in registros:
        sistema_diz_comparavel = r["cluster_sistema"] == "A"
        humano_diz_comparavel = r["rotulo_manual"] == 1

        if sistema_diz_comparavel and humano_diz_comparavel:
            vp += 1
        elif sistema_diz_comparavel and not humano_diz_comparavel:
            fp += 1
        elif not sistema_diz_comparavel and humano_diz_comparavel:
            fn += 1
        else:
            vn += 1

    # Calcula métricas
    precisao = vp / (vp + fp) if (vp + fp) > 0 else 0
    revocacao = vp / (vp + fn) if (vp + fn) > 0 else 0
    f1 = (2 * precisao * revocacao / (precisao + revocacao)) if (precisao + revocacao) > 0 else 0
    acuracia = (vp + vn) / len(registros) if registros else 0

    # Relatório
    print("=" * 70)
    print("AVALIAÇÃO DA FILTRAGEM — AGENTE 2 (Identificador de Comparáveis)")
    print("=" * 70)

    print(f"\nTotal rotulados: {len(registros)}")
    print(f"\nMatriz de Confusão:")
    print(f"                      Humano diz SIM    Humano diz NÃO")
    print(f"  Sistema diz A       VP = {vp:<12}  FP = {fp}")
    print(f"  Sistema diz B/terr  FN = {fn:<12}  VN = {vn}")

    print(f"\n─── MÉTRICAS ───")
    print(f"  Precisão:   {precisao:.1%}  (dos que o sistema selecionou, {precisao:.0%} são de fato comparáveis)")
    print(f"  Revocação:  {revocacao:.1%}  (dos comparáveis reais, o sistema encontrou {revocacao:.0%})")
    print(f"  F1-score:   {f1:.1%}  (equilíbrio entre precisão e revocação)")
    print(f"  Acurácia:   {acuracia:.1%}  (classificações corretas no total)")

    print(f"\n─── INTERPRETAÇÃO ───")
    if precisao >= 0.8:
        print("  ✅ Precisão alta: sistema raramente inclui imóveis irrelevantes")
    elif precisao >= 0.6:
        print("  ⚠️ Precisão moderada: alguns imóveis irrelevantes são incluídos")
    else:
        print("  ❌ Precisão baixa: muitos imóveis irrelevantes incluídos")

    if revocacao >= 0.8:
        print("  ✅ Revocação alta: sistema encontra a maioria dos comparáveis")
    elif revocacao >= 0.6:
        print("  ⚠️ Revocação moderada: alguns comparáveis são perdidos")
    else:
        print("  ❌ Revocação baixa: sistema perde muitos comparáveis")

    # Salva resultado
    resultado = {
        "data_avaliacao": str(Path(CSV_ROTULAGEM).stat().st_mtime),
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
        "explicacao_metricas": {
            "precisao": "Dos imóveis que o sistema classificou como comparáveis (Cluster A), qual proporção é realmente comparável segundo avaliação humana. Precisão = VP / (VP + FP).",
            "revocacao": "De todos os imóveis que realmente são comparáveis (segundo avaliação humana), qual proporção o sistema conseguiu identificar. Revocação = VP / (VP + FN).",
            "f1_score": "Média harmônica entre precisão e revocação. F1 = 2×P×R / (P+R). Fornece visão balanceada: penaliza se uma métrica é alta e outra baixa.",
            "acuracia": "Proporção total de classificações corretas (VP + VN) / Total.",
        },
    }

    with open(RESULTADO_FILTRAGEM, "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)

    print(f"\n📁 Resultados salvos em: {RESULTADO_FILTRAGEM}")


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Avaliação de filtragem do Agente 2")
    parser.add_argument("--gerar", action="store_true", help="Gera CSV para rotulagem manual")
    parser.add_argument("--calcular", action="store_true", help="Calcula métricas a partir do CSV rotulado")
    args = parser.parse_args()

    if args.gerar:
        gerar_csv_rotulagem()
    elif args.calcular:
        calcular_metricas_filtragem()
    else:
        print("Uso:")
        print("  --gerar    → Gera CSV para rotulagem manual")
        print("  --calcular → Calcula Precisão/Revocação/F1 após rotulagem")
        print()
        print("Fluxo completo:")
        print("  1. python tests/avaliacao_filtragem.py --gerar")
        print("  2. Rotule manualmente o CSV gerado (coluna rotulo_manual: 1 ou 0)")
        print("  3. python tests/avaliacao_filtragem.py --calcular")
