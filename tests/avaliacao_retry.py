"""
Re-executa a avaliação APENAS para os imóveis que falharam.
Atualiza o resultado_avaliacao.json com os novos dados.

COMO RODAR:
    .venv\\Scripts\\python.exe tests/avaliacao_retry.py
"""

import sys
import json
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(override=True)  # override=True para pegar o novo token

from tests.avaliacao_liquidez import (
    AMOSTRA_IMOVEIS,
    montar_imovel_alvo,
    executar_pipeline_completo,
    calcular_dom,
    calcular_metricas,
    gerar_relatorio,
    logger,
    RESULTADO_DIR,
)

# IDs que falharam (0-indexed): 4, 6, 9, 11, 12, 13, 14, 15
IDS_FALHARAM = [3, 5, 8, 10, 11, 12, 13, 14]  # 0-indexed

# Carrega resultado anterior
resultado_path = RESULTADO_DIR / "resultado_avaliacao.json"
with open(resultado_path, "r", encoding="utf-8") as f:
    resultado_anterior = json.load(f)

resultados = resultado_anterior["resultados_individuais"]

print("=" * 70)
print("RE-EXECUÇÃO — IMÓVEIS QUE FALHARAM")
print("=" * 70)
print(f"Imóveis para reprocessar: {len(IDS_FALHARAM)}")
print()

t_total = time.time()

for idx in IDS_FALHARAM:
    imovel = dict(AMOSTRA_IMOVEIS[idx])
    i = idx + 1  # 1-indexed para display

    logger.info(f"\n{'='*60}")
    logger.info(f"RETRY IMÓVEL {i}/15 — {imovel['rua']}, {imovel['bairro']}")
    logger.info(f"{'='*60}")

    preco_anunciado = imovel.pop("preco_anunciado")
    data_publicacao = imovel.pop("data_publicacao")
    dom = calcular_dom(data_publicacao)

    imovel_alvo = montar_imovel_alvo(imovel)

    t0 = time.time()
    try:
        resultado_pipeline = executar_pipeline_completo(imovel_alvo)

        if "erro" in resultado_pipeline:
            raise Exception(resultado_pipeline["erro"])

        ag5 = resultado_pipeline.get("preco_estimado", {})
        if ag5 and isinstance(ag5, dict):
            avaliacao = ag5.get("avaliacao", {})
            preco_sistema = avaliacao.get("valor_medio_imovel", 0)
            preco_liquidez = avaliacao.get("valor_liquidez", 0)
            liquidez_info = ag5.get("liquidez", {})
            tempo_estimado = liquidez_info.get("tempo_estimado", "N/A")
            score_liquidez = liquidez_info.get("score_liquidez", 0)
            classificacao = liquidez_info.get("classificacao", "N/A")
        else:
            preco_sistema = 0
            preco_liquidez = 0
            tempo_estimado = "N/A"
            score_liquidez = 0
            classificacao = "N/A"

        erro_relativo = (
            abs(preco_sistema - preco_anunciado) / preco_anunciado
            if preco_anunciado > 0 and preco_sistema > 0
            else None
        )
        sobrepreco = (
            (preco_anunciado - preco_sistema) / preco_sistema
            if preco_sistema > 0
            else None
        )

        resultado = {
            "id": i,
            "endereco": f"{imovel['rua']}, {imovel['bairro']}",
            "tipo": imovel["tipo"],
            "area": imovel["area"],
            "preco_anunciado": preco_anunciado,
            "preco_sistema": round(preco_sistema, 2),
            "preco_liquidez": round(preco_liquidez, 2),
            "dom_dias": dom,
            "erro_relativo": round(erro_relativo, 4) if erro_relativo else None,
            "sobrepreco_percentual": round(sobrepreco * 100, 2) if sobrepreco else None,
            "tempo_estimado_sistema": tempo_estimado,
            "classificacao_liquidez": classificacao,
            "score_liquidez": score_liquidez,
            "n_comparaveis": len(resultado_pipeline.get("comparaveis", [])),
            "tempo_execucao_s": round(time.time() - t0, 1),
            "status": "ok",
        }

    except Exception as e:
        logger.error(f"  ERRO: {e}")
        resultado = {
            "id": i,
            "endereco": f"{imovel.get('rua', '?')}, {imovel.get('bairro', '?')}",
            "tipo": imovel.get("tipo", "?"),
            "area": imovel.get("area", 0),
            "preco_anunciado": preco_anunciado,
            "preco_sistema": 0,
            "preco_liquidez": 0,
            "dom_dias": dom,
            "erro_relativo": None,
            "sobrepreco_percentual": None,
            "tempo_estimado_sistema": "ERRO",
            "classificacao_liquidez": "ERRO",
            "score_liquidez": 0,
            "n_comparaveis": 0,
            "tempo_execucao_s": round(time.time() - t0, 1),
            "status": f"erro: {str(e)}",
        }

    # Atualiza no array de resultados
    resultados[idx] = resultado

    logger.info(f"  Preço anunciado:  R$ {preco_anunciado:,.2f}")
    logger.info(f"  Preço sistema:    R$ {resultado['preco_sistema']:,.2f}")
    logger.info(f"  Status:           {resultado['status']}")

# Recalcula métricas com todos os resultados atualizados
from datetime import datetime
metricas = calcular_metricas(resultados)
gerar_relatorio(resultados, metricas)

# Salva resultado atualizado
saida = {
    "data_avaliacao": datetime.now().isoformat(),
    "metricas": metricas,
    "resultados_individuais": resultados,
}
with open(resultado_path, "w", encoding="utf-8") as f:
    json.dump(saida, f, ensure_ascii=False, indent=2)

print(f"\n⏱️  Tempo total retry: {(time.time() - t_total)/60:.1f} minutos")
