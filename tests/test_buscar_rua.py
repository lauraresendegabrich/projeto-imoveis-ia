"""Teste rápido do buscar_rua com fallback de acento."""
import sys
sys.path.insert(0, ".")
from dotenv import load_dotenv
load_dotenv(override=True)
from services.athena_client import AthenaClient

c = AthenaClient()

print("Buscando casas na 'Rua Conego Nery' (sem acento)...")
r = c.buscar_rua("Campinas", "Jardim Guanabara", "Rua Conego Nery", tipo="casa")
print(f"Resultado: {len(r)} casas")
for x in r[:5]:
    print(f"  {x.get('rua', '?')} | {x.get('area_construida', '?')}m2 | R$ {x.get('preco', '?')}")

print("\nBuscando apartamentos na 'Rua Conego Nery' (sem acento)...")
r2 = c.buscar_rua("Campinas", "Jardim Guanabara", "Rua Conego Nery", tipo="apartamento")
print(f"Resultado: {len(r2)} apartamentos")
for x in r2[:5]:
    print(f"  {x.get('rua', '?')} | {x.get('area_construida', '?')}m2 | R$ {x.get('preco', '?')}")
