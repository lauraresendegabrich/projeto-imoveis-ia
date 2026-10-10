"""
Testes da leitura de numeros digitados no formulario (services/formatos.py).

    .venv/Scripts/python.exe -m tests.test_formatos
"""
import sys

sys.path.insert(0, ".")

from services.formatos import ler_numero_br


def test_areas():
    casos = {
        "179": 179.0, "179,5": 179.5, "179,50": 179.5, "179.5": 179.5, "179.50": 179.5,
        "1.250": 1250.0, "1.250,75": 1250.75, "179 m²": 179.0, "179m2": 179.0, " 300 ": 300.0,
        "399,99": 399.99,
    }
    for texto, esperado in casos.items():
        assert ler_numero_br(texto) == esperado, (texto, ler_numero_br(texto))


def test_valores_em_reais():
    assert ler_numero_br("R$ 323.158,50") == 323158.5
    assert ler_numero_br("1.250.000") == 1250000.0


def test_vazio_e_zero_viram_none():
    for texto in ("", "  ", None, "0", "0,0", 0):
        assert ler_numero_br(texto) is None, texto


def test_invalidos():
    for texto in ("abc", "179,5,0", "12,345", "1.2.3", "-50", ",", "180 metros"):
        try:
            ler_numero_br(texto)
        except ValueError:
            continue
        raise AssertionError(f"deveria recusar {texto!r}")


if __name__ == "__main__":
    testes = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    falhas = 0
    for nome, fn in testes:
        try:
            fn()
            print(f"OK    {nome}")
        except AssertionError as e:
            falhas += 1
            print(f"FALHA {nome}: {e}")
    print(f"\n{len(testes) - falhas}/{len(testes)} testes passaram")
    sys.exit(1 if falhas else 0)
