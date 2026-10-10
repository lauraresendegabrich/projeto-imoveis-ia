"""
Leitura de numeros digitados no formulario, no jeito brasileiro ou nao.

Usado nos campos de area (m²) e de valor do leilao (R$), que sao campos de texto
para aceitar virgula decimal e ponto de milhar (o number_input do Streamlit so
aceita ponto decimal).
"""
from __future__ import annotations

import re


def ler_numero_br(texto) -> float | None:
    """
    "179", "179,5", "179.5", "1.250", "1.250,75", "R$ 323.158,50", "179 m²" -> float.
    Vazio ou zero -> None. Texto que nao e numero -> ValueError (a tela mostra o erro).

    Regras: virgula e o separador decimal (pontos antes dela sao de milhar); sem
    virgula, um unico ponto com ate 2 casas e decimal ("179.5"); com mais pontos ou
    grupos de 3 digitos, os pontos sao de milhar ("1.250" = 1250).
    """
    if texto is None:
        return None
    if isinstance(texto, (int, float)):
        return float(texto) if texto > 0 else None
    limpo = re.sub(r"(?i)r\$|m²|m2|\s", "", str(texto).strip())
    if not limpo:
        return None
    if not re.fullmatch(r"[\d.,]+", limpo):
        raise ValueError(f"número inválido: {texto!r}")
    if "," in limpo:
        inteiro, _, decimal = limpo.rpartition(",")
        if "," in inteiro or len(decimal) > 2 or not decimal:
            raise ValueError(f"número inválido: {texto!r}")
        limpo = inteiro.replace(".", "") + "." + decimal
    elif limpo.count(".") == 1 and len(limpo.split(".")[1]) <= 2:
        pass  # ponto decimal ("179.5")
    else:
        grupos = limpo.split(".")
        if any(len(g) != 3 for g in grupos[1:]):
            raise ValueError(f"número inválido: {texto!r}")
        limpo = "".join(grupos)
    if not limpo or limpo == ".":
        raise ValueError(f"número inválido: {texto!r}")
    numero = float(limpo)
    return numero if numero > 0 else None
