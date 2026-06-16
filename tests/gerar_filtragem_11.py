"""
Gera dados de filtragem para os 11 imóveis válidos da avaliação.
Roda Agente 1 + Agente 2 para cada um, salva resultados separados,
e gera CSVs cegos para rotulagem manual.

COMO RODAR:
    .venv\\Scripts\\python.exe tests/gerar_filtragem_11.py

Saída em: data/avaliacao/filtragem/imovel_XX/
  - ag2_resultado.json     → saída completa do Agente 2
  - rotulagem_cega.csv     → CSV para rotulagem (sem cluster)
  - mapa_interno.json      → mapeamento número CSV ↔ cluster sistema
"""

import sys
import os
import json
import csv
import time
import random
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(override=True)

from agents.collector import coletar_imoveis
from agents.comparables import identificar_comparaveis

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent / "data" / "avaliacao" / "filtragem"
BASE_DIR.mkdir(parents=True, exist_ok=True)

# =============================================================================
# OS 11 IMÓVEIS QUE FUNCIONARAM NA AVALIAÇÃO
# (IDs 1, 2, 3, 5, 7, 8, 10, 11, 13, 14, 15 — da AMOSTRA_IMOVEIS)
# =============================================================================

from tests.avaliacao_liquidez import AMOSTRA_IMOVEIS, montar_imovel_alvo

# Índices (0-based) dos que tiveram resultado válido
INDICES_VALIDOS = [0, 1, 2, 4, 6, 7, 9, 10, 12, 13, 14]


def rodar_pipeline_ag2(imovel_dict: dict, imovel_id: int) -> dict:
    """Roda Agente 1 + Agente 2 e retorna resultado."""
    imovel = dict(imovel_dict)
    # Remove campos de avaliação
    imovel.pop("preco_anunciado", None)
    imovel.pop("data_publicacao", None)

    imovel_alvo = montar_imovel_alvo(imovel)

    logger.info(f"  Agente 1: coletando para {imovel_alvo['bairro']}, {imovel_alvo['cidade']}...")
    imoveis_coletados = coletar_imoveis(
        localizacao=imovel_alvo["localizacao"],
        tipo_imovel=imovel_alvo["tipo"],
        bairro=imovel_alvo.get("bairro", ""),
        rua=imovel_alvo.get("rua", ""),
    )

    if not imoveis_coletados:
        return {"erro": "Agente 1 sem resultados", "imovel_alvo": imovel_alvo}

    logger.info(f"  Agente 1: {len(imoveis_coletados)} coletados")
    logger.info(f"  Agente 2: classificando...")

    # Usa arquivo temporário para não sobrescrever dados globais
    arquivo_saida = f"imoveis_comparaveis_ag2_eval_{imovel_id}.json"
    resultado = identificar_comparaveis(
        imovel_alvo=imovel_alvo,
        imoveis_coletados=imoveis_coletados,
        usar_llm=True,
        arquivo_saida=arquivo_saida,
    )

    return resultado


def gerar_csv_cego(resultado_ag2: dict, output_dir: Path, imovel_id: int):
    """Gera CSVs cegos para 3 avaliadores + mapa interno."""
    comparaveis = resultado_ag2.get("comparaveis", [])
    terrenos = resultado_ag2.get("terrenos", [])
    alvo = resultado_ag2.get("imovel_alvo", {})

    todos = comparaveis + terrenos
    random.seed(imovel_id * 42)  # seed por imóvel para reprodutibilidade
    random.shuffle(todos)

    # Gera CSV para cada avaliador (laura, livia, kiro)
    for avaliador in ["laura", "livia", "kiro"]:
        csv_path = output_dir / f"rotulagem_{avaliador}.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "numero", "tipo", "area_m2", "quartos", "banheiros", "vagas",
                "preco", "preco_m2", "bairro", "rua", "descricao",
                "rotulo_manual"
            ])
            for idx, im in enumerate(todos, 1):
                desc = (im.get("description") or im.get("title") or "")[:300].replace("\n", " ").replace(",", ";")
                preco = im.get("price", 0)
                area = im.get("area", 0)
                preco_m2 = round(preco / area, 2) if area and preco else "?"

                # Kiro preenche automaticamente
                rotulo = ""
                if avaliador == "kiro":
                    rotulo = _rotular_kiro(im, alvo)

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
                    rotulo
                ])

    # Mapa interno (para depois calcular métricas)
    mapa = []
    for idx, im in enumerate(todos, 1):
        mapa.append({
            "numero_csv": idx,
            "id_original": im.get("id", "?"),
            "cluster_sistema": im.get("cluster", "?"),
            "score_similaridade": im.get("score_similaridade", 0),
        })

    mapa_path = output_dir / "mapa_interno.json"
    with open(mapa_path, "w", encoding="utf-8") as f:
        json.dump(mapa, f, ensure_ascii=False, indent=2)

    # Salva info do alvo
    alvo_path = output_dir / "imovel_alvo.json"
    with open(alvo_path, "w", encoding="utf-8") as f:
        json.dump(alvo, f, ensure_ascii=False, indent=2)

    return len(todos)


def _rotular_kiro(imovel: dict, alvo: dict) -> str:
    """
    Rotulagem automática por regras objetivas (mesmos critérios da LLM):
    - Mesmo tipo (casa com casa)
    - Área ±50% do alvo
    - Quartos ±1 do alvo
    - Mesmo bairro
    - Não ser terreno/comercial/kitnet
    """
    import unicodedata

    def _norm(t):
        return unicodedata.normalize("NFD", str(t or "")).encode("ascii", "ignore").decode().lower().strip()

    # Tipo
    tipo_im = _norm(imovel.get("propertyType", ""))
    tipo_alvo = _norm(alvo.get("propertyType", ""))

    # Terreno nunca é comparável a casa/apto
    if "terreno" in tipo_im:
        return "0"

    # Tipo diferente (casa vs apto)
    if tipo_alvo and tipo_im and tipo_alvo != tipo_im:
        return "0"

    # Bairro
    bairro_im = _norm(imovel.get("neighborhood", ""))
    bairro_alvo = _norm(alvo.get("neighborhood", ""))
    if bairro_alvo and bairro_im and bairro_alvo not in bairro_im and bairro_im not in bairro_alvo:
        return "0"

    # Área (±50%)
    area_alvo = alvo.get("area", 0) or 0
    area_im = imovel.get("area", 0) or 0
    if area_alvo > 0 and area_im > 0:
        if area_im < area_alvo * 0.5 or area_im > area_alvo * 2.0:
            return "0"

    # Quartos (±2)
    quartos_alvo = alvo.get("bedrooms", 0) or 0
    quartos_im = imovel.get("bedrooms", 0) or 0
    if quartos_alvo > 0 and quartos_im > 0:
        if abs(quartos_im - quartos_alvo) > 2:
            return "0"

    # Descrição: exclui kitnet, comercial, leilão
    desc = _norm(imovel.get("description", "") or imovel.get("title", "") or "")
    if any(w in desc for w in ["kitnet", "kit net", "quitinete", "leilao", "leilão", "comercial"]):
        return "0"

    return "1"


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("GERAÇÃO DE DADOS DE FILTRAGEM — 11 IMÓVEIS")
    print("=" * 70)

    t_total = time.time()
    resumo = []

    for i, idx in enumerate(INDICES_VALIDOS):
        imovel = AMOSTRA_IMOVEIS[idx]
        imovel_id = idx + 1  # 1-based
        output_dir = BASE_DIR / f"imovel_{imovel_id:02d}"
        output_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"\n{'='*60}")
        logger.info(f"[{i+1}/11] IMÓVEL {imovel_id} — {imovel['rua']}, {imovel['bairro']}, {imovel['cidade']}/{imovel['estado']}")
        logger.info(f"{'='*60}")

        t0 = time.time()
        try:
            resultado = rodar_pipeline_ag2(imovel, imovel_id)

            if "erro" in resultado:
                logger.error(f"  FALHOU: {resultado['erro']}")
                resumo.append({"id": imovel_id, "status": "erro", "motivo": resultado["erro"]})
                continue

            # Salva resultado completo do Ag2
            ag2_path = output_dir / "ag2_resultado.json"
            with open(ag2_path, "w", encoding="utf-8") as f:
                json.dump(resultado, f, ensure_ascii=False, indent=2)

            # Gera CSV cego
            n_imoveis = gerar_csv_cego(resultado, output_dir, imovel_id)

            tempo = round(time.time() - t0, 1)
            resumo_item = resultado.get("resumo", {})
            logger.info(f"  OK: {n_imoveis} imóveis no CSV | {resumo_item.get('cluster_a', 0)} Cluster A | {resumo_item.get('cluster_b', 0)} Cluster B | {tempo}s")
            resumo.append({
                "id": imovel_id,
                "status": "ok",
                "total_csv": n_imoveis,
                "cluster_a": resumo_item.get("cluster_a", 0),
                "cluster_b": resumo_item.get("cluster_b", 0),
                "terrenos": resumo_item.get("terrenos_excluidos", 0),
                "tempo_s": tempo,
            })

        except Exception as e:
            logger.error(f"  ERRO: {e}")
            resumo.append({"id": imovel_id, "status": "erro", "motivo": str(e)})

    # Salva resumo geral
    resumo_path = BASE_DIR / "resumo_geracao.json"
    with open(resumo_path, "w", encoding="utf-8") as f:
        json.dump(resumo, f, ensure_ascii=False, indent=2)

    tempo_total = (time.time() - t_total) / 60
    print(f"\n{'='*70}")
    print(f"CONCLUÍDO — {tempo_total:.1f} minutos")
    print(f"{'='*70}")
    print(f"\nResumo:")
    ok = sum(1 for r in resumo if r["status"] == "ok")
    erro = sum(1 for r in resumo if r["status"] == "erro")
    print(f"  Sucesso: {ok}/11 | Erros: {erro}/11")
    print(f"\nArquivos gerados em: {BASE_DIR}")
    print(f"  Cada pasta imovel_XX/ contém:")
    print(f"    - imovel_alvo.json    (referência do imóvel)")
    print(f"    - ag2_resultado.json  (saída do Agente 2)")
    print(f"    - rotulagem_cega.csv  (para rotulagem manual)")
    print(f"    - mapa_interno.json   (para calcular métricas depois)")
    print(f"\nPróximos passos:")
    print(f"  1. Copie rotulagem_cega.csv para 'rotulagem_laura.csv' e 'rotulagem_livia.csv'")
    print(f"  2. Cada pessoa rotula sua cópia (coluna rotulo_manual: 1 ou 0)")
    print(f"  3. Rode: python tests/calcular_filtragem_final.py")
