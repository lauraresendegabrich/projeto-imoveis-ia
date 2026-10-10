"""
Busca de endereco por CEP, com mais de um servico.

O ViaCEP costuma recusar ou demorar com servidores fora do Brasil (caso do Streamlit
Cloud), entao tentamos BrasilAPI e OpenCEP tambem, na ordem, e usamos o primeiro que
responder.
"""
from __future__ import annotations

import re

import requests

TIMEOUT_CEP_S = 4


def limpar_cep(texto) -> str | None:
    """'82950-190', '82950190', ' 82.950-190 ' -> '82950190'. Sem 8 digitos -> None."""
    digitos = re.sub(r"\D", "", str(texto or ""))
    return digitos if len(digitos) == 8 else None


def _viacep(cep: str) -> dict | None:
    d = requests.get(f"https://viacep.com.br/ws/{cep}/json/", timeout=TIMEOUT_CEP_S).json()
    if d.get("erro"):
        return None
    return {"rua": d.get("logradouro", ""), "bairro": d.get("bairro", ""),
            "cidade": d.get("localidade", ""), "estado": d.get("uf", "")}


def _brasilapi(cep: str) -> dict | None:
    r = requests.get(f"https://brasilapi.com.br/api/cep/v1/{cep}", timeout=TIMEOUT_CEP_S)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    d = r.json()
    return {"rua": d.get("street", ""), "bairro": d.get("neighborhood", ""),
            "cidade": d.get("city", ""), "estado": d.get("state", "")}


def _opencep(cep: str) -> dict | None:
    r = requests.get(f"https://opencep.com/v1/{cep}", timeout=TIMEOUT_CEP_S)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    d = r.json()
    return {"rua": d.get("logradouro", ""), "bairro": d.get("bairro", ""),
            "cidade": d.get("localidade", ""), "estado": d.get("uf", "")}


SERVICOS_CEP = [("ViaCEP", _viacep), ("BrasilAPI", _brasilapi), ("OpenCEP", _opencep)]


def buscar_cep(cep: str) -> tuple[dict | None, str]:
    """
    Endereco do CEP (ja limpo, 8 digitos). Retorna (endereco, situacao):
      ({rua, bairro, cidade, estado}, "ok")
      (None, "nao_encontrado")  -> algum servico respondeu que o CEP nao existe
      (None, "indisponivel")    -> nenhum servico respondeu
    """
    nao_encontrado = False
    for _nome, servico in SERVICOS_CEP:
        try:
            endereco = servico(cep)
        except Exception:
            continue
        if endereco and endereco.get("cidade"):
            return endereco, "ok"
        nao_encontrado = True
    return None, ("nao_encontrado" if nao_encontrado else "indisponivel")
