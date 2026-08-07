"""Testa se o Agente 5 funciona localmente com os dados atuais."""
import sys
sys.path.insert(0, ".")
from dotenv import load_dotenv
load_dotenv(override=True)

from agents.price_liquidity import carregar_dados_pipeline, executar_agente5

print("Carregando dados do pipeline...")
imovel, terrenos, comp, ag3, ag4 = carregar_dados_pipeline()
print(f"  Alvo: {imovel.get('area','?')}m2, {imovel.get('neighborhood','?')}")
print(f"  Terrenos: {len(terrenos)}")
print(f"  Comparaveis: {len(comp)}")
print(f"  Ag3: {'ok' if ag3 else 'vazio'} ({list(ag3.keys())[:3] if ag3 else '-'})")
print(f"  Ag4: {'ok' if ag4 else 'vazio'} ({list(ag4.keys())[:3] if ag4 else '-'})")

if not comp:
    print("\n❌ Sem comparáveis — Agente 5 não pode calcular")
else:
    print("\nRodando Agente 5...")
    try:
        resultado = executar_agente5(
            imovel_alvo=imovel,
            terrenos_zona=terrenos,
            comparaveis_zona=comp,
            dados_ag3=ag3,
            dados_ag4=ag4,
        )
        print(f"\n✅ Valor médio: R$ {resultado['avaliacao']['valor_medio_imovel']:,.2f}")
        print(f"   Valor liquidez: R$ {resultado['avaliacao']['valor_liquidez']:,.2f}")
        print(f"   Tempo estimado: {resultado['liquidez']['tempo_estimado']}")
    except Exception as e:
        print(f"\n❌ ERRO: {e}")
        import traceback
        traceback.print_exc()
