"""Teste isolado do Agente 4 — Avaliador de Infraestrutura."""
import sys
import logging

sys.path.insert(0, ".")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

from dotenv import load_dotenv
load_dotenv(override=True)

from agents.infra_evaluator import avaliar_infraestrutura

print("=" * 60)
print("TESTE ISOLADO — AGENTE 4: AVALIADOR DE INFRAESTRUTURA")
print("=" * 60)

resultado = avaliar_infraestrutura()

print(f"\n{'=' * 60}")
print("RESULTADO DO AGENTE 4")
print(f"{'=' * 60}")

scores = resultado.get("scores", {})
print(f"Score final: {scores.get('score_final', '?')}")
print(f"Classificação: {scores.get('classificacao_infraestrutura', '?')}")
print(f"Perfil: {scores.get('perfil_infraestrutura', '?')}")
print(f"Impacto: {scores.get('impacto_infraestrutura', '?')}")

print("\nScores por categoria:")
cats = scores.get("scores_categoria", {})
for cat, val in cats.items():
    print(f"  {cat}: {val}")

interp = resultado.get("interpretacao_llm", {})
if interp:
    print(f"\nPontos fortes: {interp.get('pontos_fortes', [])}")
    print(f"Pontos atenção: {interp.get('pontos_atencao', [])}")

meta = resultado.get("metadados", {})
if meta:
    print(f"\nMetadados:")
    print(f"  Fonte: {meta.get('fonte_infraestrutura', '?')}")
    print(f"  Raio máximo: {meta.get('raio_maximo_metros', '?')}m")
    print(f"  Total POIs: {meta.get('total_pois_validos', '?')}")
