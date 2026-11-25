"""Teste rapido dos scores com cap."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()
from agents.infra_evaluator import _buscar_pois_classificados, _calcular_score, _buscar_transporte

pois = _buscar_pois_classificados(-19.765276, -43.844099)
trans = _buscar_transporte(-19.765276, -43.844099)
scores = _calcular_score(pois, trans)

print("Scores por categoria:")
for k, v in scores.get("scores_categoria", {}).items():
    print(f"  {k}: {v}")
print(f"  SCORE FINAL: {scores['score_final']}")
