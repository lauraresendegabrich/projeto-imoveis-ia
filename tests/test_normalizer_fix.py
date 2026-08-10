import sys
sys.path.insert(0, ".")
from agents.collector import _normalizar_ocrad

# Testa com imóvel real do LugarCerto
imovel_lc = {
    "title": "Casa, 3 Quartos, 3 Vagas, 1 Suite  Rua Lírica, Santa Mônica, Belo Horizonte, MG",
    "price": "R$ 650.000,00",
    "source_site": "lugar-certo",
    "from_url": "https://www.lugarcerto.com.br/busca/compra-e-venda/mg/belo-horizonte/santa-monica/casa",
    "url": "https://estadodeminas.lugarcerto.com.br/imovel/casa-3-quartos-santa-monica-belo-horizonte-com-garagem-230m2-compra-e-venda-rs650000-id-341944752",
    "location": "",
    "posting_id": "341944752",
}

r = _normalizar_ocrad(imovel_lc)
print(f"neighborhood: {r['neighborhood']}")
print(f"city: {r['city']}")
print(f"street: {r['street']}")
print(f"state: {r['state']}")
print(f"area: {r['area']}")
print(f"price: {r['price']}")
print(f"source: {r['source']}")
