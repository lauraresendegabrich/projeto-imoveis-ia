"""Teste Geoapify + Google fallback no novo Ag4."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()

from agents.infra_evaluator import _buscar_pois_classificados, _buscar_transporte, _calcular_score

LAT = -19.765276
LON = -43.844099

print("=" * 55)
print("TESTE: Geoapify + Google fallback (Santa Luzia)")
print("=" * 55)
print(f"GEOAPIFY_API_KEY: {'OK' if os.getenv('GEOAPIFY_API_KEY') else 'NAO'}")
print(f"GOOGLE_MAPS_KEY: {'OK' if os.getenv('GOOGLE_MAPS_KEY') else 'NAO'}")
print()

pois, diag, status_cats = _buscar_pois_classificados(LAT, LON)
print(f"\nDiagnostico: {diag}")
print(f"\nStatus categorias: {status_cats}")

trans = _buscar_transporte(LAT, LON)
print(f"\nTransporte: {trans['status']} | fonte={trans.get('fonte')} | paradas={len(trans['paradas'])}")

scores = _calcular_score(pois, trans, status_cats)
print(f"\nScores:")
for k, v in scores.get("scores_categoria", {}).items():
    print(f"  {k}: {v}")
print(f"  FINAL: {scores['score_final']}")
