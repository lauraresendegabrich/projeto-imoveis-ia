import sys
sys.path.insert(0, ".")
from agents.collector import _slugify

print(f"'Santa Mônica' -> '{_slugify('Santa Mônica')}'")
print(f"'São Gabriel' -> '{_slugify('São Gabriel')}'")
print(f"'Belo Horizonte' -> '{_slugify('Belo Horizonte')}'")

# Testa a URL que seria gerada
bairro_slug = _slugify("Santa Mônica")
cidade_slug = _slugify("Belo Horizonte")
url_vr = f"https://www.vivareal.com.br/venda/minas-gerais/{cidade_slug}/bairros/{bairro_slug}/casa_residencial/"
print(f"\nURL VivaReal: {url_vr}")

# URL correta seria:
url_correta = "https://www.vivareal.com.br/venda/minas-gerais/belo-horizonte/bairros/santa-monica/casa_residencial/"
print(f"URL correta:  {url_correta}")
print(f"Match: {url_vr == url_correta}")
