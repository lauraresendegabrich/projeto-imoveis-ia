"""
Retry da geração de filtragem para os imóveis que falharam.
Usa o novo token Apify.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Força reload do .env com novo token
from dotenv import load_dotenv
load_dotenv(override=True)

# Agora importa o resto (que vai pegar o novo token)
import importlib
import agents.collector
importlib.reload(agents.collector)

from tests.gerar_filtragem_11 import (
    AMOSTRA_IMOVEIS, rodar_pipeline_ag2, gerar_csv_cego,
    BASE_DIR, logger, INDICES_VALIDOS
)
import json, time

# Indices que falharam (0-based): 7(idx=6), 9(idx=8), 10(idx=9), 12(idx=11), 13(idx=12), 14(idx=13)
# IDs que falharam: 8, 10, 11, 13, 14, 15
IDS_FALHARAM = [8, 10, 11, 13, 14, 15]
# Mapa de ID -> indice na AMOSTRA_IMOVEIS (0-based)
ID_TO_IDX = {1:0, 2:1, 3:2, 5:4, 7:6, 8:7, 10:9, 11:10, 13:12, 14:13, 15:14}

print("=" * 70)
print("RETRY — GERAÇÃO DE FILTRAGEM (novo token)")
print("=" * 70)

t_total = time.time()
resumo_retry = []

for imovel_id in IDS_FALHARAM:
    idx = ID_TO_IDX[imovel_id]
    imovel = AMOSTRA_IMOVEIS[idx]
    output_dir = BASE_DIR / f"imovel_{imovel_id:02d}"
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"\n{'='*60}")
    logger.info(f"RETRY IMÓVEL {imovel_id} — {imovel['rua']}, {imovel['bairro']}, {imovel['cidade']}/{imovel['estado']}")
    logger.info(f"{'='*60}")

    t0 = time.time()
    try:
        resultado = rodar_pipeline_ag2(imovel, imovel_id)

        if "erro" in resultado:
            logger.error(f"  FALHOU: {resultado['erro']}")
            resumo_retry.append({"id": imovel_id, "status": "erro", "motivo": resultado["erro"]})
            continue

        ag2_path = output_dir / "ag2_resultado.json"
        with open(ag2_path, "w", encoding="utf-8") as f:
            json.dump(resultado, f, ensure_ascii=False, indent=2)

        n_imoveis = gerar_csv_cego(resultado, output_dir, imovel_id)
        tempo = round(time.time() - t0, 1)
        resumo_item = resultado.get("resumo", {})
        logger.info(f"  OK: {n_imoveis} imóveis | {resumo_item.get('cluster_a',0)} A | {resumo_item.get('cluster_b',0)} B | {tempo}s")
        resumo_retry.append({
            "id": imovel_id, "status": "ok",
            "total_csv": n_imoveis,
            "cluster_a": resumo_item.get("cluster_a", 0),
            "cluster_b": resumo_item.get("cluster_b", 0),
            "tempo_s": tempo,
        })
    except Exception as e:
        logger.error(f"  ERRO: {e}")
        resumo_retry.append({"id": imovel_id, "status": "erro", "motivo": str(e)})

# Salva resumo
with open(BASE_DIR / "resumo_retry.json", "w", encoding="utf-8") as f:
    json.dump(resumo_retry, f, ensure_ascii=False, indent=2)

tempo_total = (time.time() - t_total) / 60
ok = sum(1 for r in resumo_retry if r["status"] == "ok")
print(f"\nCONCLUÍDO — {tempo_total:.1f} min | Sucesso: {ok}/6")
