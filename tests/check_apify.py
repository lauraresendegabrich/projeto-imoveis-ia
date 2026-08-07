"""Verifica uso e limites da conta Apify."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv
load_dotenv()
import requests

token = os.getenv("APIFY_TOKEN_2") or os.getenv("APIFY_TOKEN")
print(f"Token: {token[:10]}...")

# Info do usuario
r = requests.get(f"https://api.apify.com/v2/users/me?token={token}")
data = r.json().get("data", {})

plan = data.get("plan", {})
usage = data.get("usage", {})
limits = data.get("limits", {})

print(f"Username: {data.get('username', '?')}")
print(f"Plano: {plan.get('id', '?')}")
print(f"Uso mensal (USD): ${usage.get('monthlyUsageUsd', 0):.4f}")
print(f"Limite mensal (USD): ${plan.get('monthlyUsageLimitUsd', 0):.2f}")
print(f"Uso atual vs limite: {usage.get('monthlyUsageUsd', 0):.4f} / {plan.get('monthlyUsageLimitUsd', 0):.2f}")

# Ultimas runs
r2 = requests.get(f"https://api.apify.com/v2/actor-runs?token={token}&limit=5&desc=true")
runs = r2.json().get("data", {}).get("items", [])
print(f"\nUltimas 5 runs:")
for run in runs:
    print(f"  {run.get('startedAt', '?')} | status={run.get('status', '?')} | usage=${run.get('usageTotalUsd', 0):.4f}")
