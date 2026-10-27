"""
Leitura da pagina de um imovel no site da CAIXA
===============================================

O site da CAIXA bloqueia acesso automatico (CAPTCHA "Radware Bot Manager"), entao o
app NAO abre o link. A pessoa abre a pagina no navegador dela e traz o conteudo:
  - a pagina salva (Ctrl+S, arquivo .html), ou
  - o texto copiado da pagina (Ctrl+A, Ctrl+C) colado no app.

Os dois caminhos viram texto e sao lidos pelos rotulos da pagina ("Valor minimo de
venda:", "Matricula(s):", "Data do 1o Leilao - ..."). Regra: nunca inventar valor.
Campo nao achado fica None e entra em `nao_encontrados`, para preencher a mao.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta
from html.parser import HTMLParser

from services.formatos import ler_numero_br
from services.leilao import (
    FORMAS_PAGAMENTO_CAIXA, MODALIDADE_COMPRA_DIRETA, MODALIDADE_LICITACAO, MODALIDADE_SFI,
    MODALIDADE_VENDA_ONLINE, MODALIDADES_CAIXA, agora_brasilia, texto_data_hora,
)

UF_POR_ESTADO = {
    "ACRE": "AC", "ALAGOAS": "AL", "AMAPA": "AP", "AMAZONAS": "AM", "BAHIA": "BA", "CEARA": "CE",
    "DISTRITO FEDERAL": "DF", "ESPIRITO SANTO": "ES", "GOIAS": "GO", "MARANHAO": "MA",
    "MATO GROSSO": "MT", "MATO GROSSO DO SUL": "MS", "MINAS GERAIS": "MG", "PARA": "PA",
    "PARAIBA": "PB", "PARANA": "PR", "PERNAMBUCO": "PE", "PIAUI": "PI", "RIO DE JANEIRO": "RJ",
    "RIO GRANDE DO NORTE": "RN", "RIO GRANDE DO SUL": "RS", "RONDONIA": "RO", "RORAIMA": "RR",
    "SANTA CATARINA": "SC", "SAO PAULO": "SP", "SERGIPE": "SE", "TOCANTINS": "TO",
}

# Area menor que isso e erro de cadastro (ex.: "Area do terreno = 0,01m2" numa casa).
AREA_MINIMA_M2 = 10
# Encerramento da Venda Online calculado pelo tempo restante: arredonda para 5 minutos.
ARREDONDAR_ENCERRAMENTO_MIN = 5

# Tipo da CAIXA -> tipo do formulario (o sistema so avalia casa e apartamento).
TIPO_FORMULARIO = {"CASA": "Casa", "SOBRADO": "Casa", "APARTAMENTO": "Apartamento"}

# Nome de cada campo no aviso "nao encontrado".
NOMES_CAMPOS = {
    "rua": "Rua", "numero": "Número", "bairro": "Bairro", "cidade": "Cidade", "uf": "UF", "cep": "CEP",
    "tipo": "Tipo", "quartos": "Quartos", "banheiros": "Banheiros", "vagas": "Garagem", "area_privativa": "Área privativa",
    "area_total": "Área total", "area_terreno": "Área do terreno", "descricao": "Descrição",
    "modalidade": "Modalidade", "valor_avaliacao": "Valor de avaliação", "valor_minimo": "Valor mínimo de venda",
    "valor_minimo_1": "Valor mínimo do 1º leilão", "valor_minimo_2": "Valor mínimo do 2º leilão",
    "data_1_leilao": "Data do 1º leilão", "data_2_leilao": "Data do 2º leilão",
    "data_encerramento": "Data de encerramento", "edital": "Edital", "numero_item": "Número do item",
    "leiloeiro": "Leiloeiro", "numero_imovel": "Número do imóvel", "matricula": "Matrícula",
    "formas_pagamento": "Formas de pagamento", "regras_despesas": "Regras de despesas",
    "averbacao_leiloes_negativos": "Averbação dos leilões negativos",
}
CAMPOS_GERAIS = (
    "rua", "numero", "bairro", "cidade", "uf", "cep", "tipo", "quartos", "banheiros", "vagas", "area_privativa",
    "area_total", "area_terreno", "descricao", "modalidade", "valor_avaliacao", "numero_imovel", "matricula",
    "formas_pagamento", "regras_despesas", "averbacao_leiloes_negativos",
)
CAMPOS_POR_MODALIDADE = {
    MODALIDADE_SFI: ("valor_minimo_1", "valor_minimo_2", "data_1_leilao", "data_2_leilao",
                     "edital", "numero_item", "leiloeiro"),
    MODALIDADE_LICITACAO: ("valor_minimo", "data_encerramento", "edital", "numero_item", "leiloeiro"),
    MODALIDADE_VENDA_ONLINE: ("valor_minimo", "data_encerramento"),
    MODALIDADE_COMPRA_DIRETA: ("valor_minimo",),
}

_TAGS_BLOCO = {"p", "div", "br", "li", "ul", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "table", "label"}


class _Texto(HTMLParser):
    """HTML -> texto: uma linha por bloco; ignora script, style e noscript."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.partes: list[str] = []
        self._ignorar = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self._ignorar += 1
        elif tag in _TAGS_BLOCO:
            self.partes.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self._ignorar = max(0, self._ignorar - 1)
        elif tag in _TAGS_BLOCO:
            self.partes.append("\n")

    def handle_data(self, data):
        if not self._ignorar:
            self.partes.append(re.sub(r"\s+", " ", data))


def _eh_html(conteudo: str) -> bool:
    return bool(re.search(r"<(html|body|div|p)\b", conteudo[:5000], re.I))


def texto_da_pagina(conteudo: str) -> str:
    """Pagina salva (HTML) ou texto colado -> linhas de texto limpas, sem linhas vazias."""
    if _eh_html(conteudo):
        leitor = _Texto()
        leitor.feed(conteudo)
        conteudo = "".join(leitor.partes)
    linhas = (re.sub(r"\s+", " ", l).strip() for l in conteudo.splitlines())
    return "\n".join(l for l in linhas if l)


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def _achar(padrao: str, texto: str) -> str | None:
    m = re.search(padrao, texto, re.I | re.M)
    return m.group(1).strip() if m else None


def _reais(padrao: str, texto: str) -> float | None:
    valor = _achar(padrao + r"\s*R\$\s*([\d.]+,\d{2})", texto)
    return ler_numero_br(valor) if valor else None


def _area(rotulo: str, texto: str) -> float | None:
    valor = _achar(rf"^{rotulo}\s*=\s*([\d.]+(?:,\d+)?)\s*m2", texto)
    return ler_numero_br(valor) if valor else None


def _inteiro(rotulo: str, texto: str) -> int | None:
    valor = _achar(rf"^{rotulo}:\s*(\d+)\s*$", texto)
    return int(valor) if valor else None


def _data_hora(texto: str | None) -> datetime | None:
    """'30/11/2026 - 10h00', '26/10/2026 18:00:00' ou '04/11/2026 10:00' -> datetime."""
    if not texto:
        return None
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})\D+(\d{1,2})[h:](\d{2})(?::(\d{2}))?", texto)
    if not m:
        return None
    dia, mes, ano, hora, minuto, segundo = m.groups()
    return datetime(int(ano), int(mes), int(dia), int(hora), int(minuto), int(segundo or 0))


def _linhas_depois(rotulo: str, linhas: list[str], fim: tuple[str, ...]) -> list[str]:
    """Linhas logo abaixo do rotulo, ate a primeira que comeca com algum de `fim`."""
    for i, linha in enumerate(linhas):
        if linha.upper().startswith(rotulo.upper()):
            saida = []
            for seguinte in linhas[i + 1:]:
                if seguinte.upper().startswith(tuple(f.upper() for f in fim)):
                    break
                saida.append(seguinte)
            return saida
    return []


def _endereco(linha: str | None) -> dict:
    """
    'RUA WALDIR PIRES,N. 643 APTO. 404 BL 01, CENTRO - CEP: 42702-270, LAURO DE FREITAS - BAHIA'
    -> rua, numero, complemento, bairro, cep, cidade, uf. Sem 'N.' o numero fica None.
    """
    campos = dict.fromkeys(("rua", "numero", "complemento", "bairro", "cep", "cidade", "uf"))
    if not linha or " - CEP:" not in linha.upper():
        return campos
    antes, depois = re.split(r"\s*-\s*CEP:\s*", linha, maxsplit=1, flags=re.I)
    m = re.match(r"(\d{5}-?\d{3})\s*,\s*(.+?)\s*-\s*(.+)$", depois.strip())
    if m:
        campos["cep"], campos["cidade"] = m.group(1), m.group(2).strip()
        campos["uf"] = UF_POR_ESTADO.get(_sem_acento(m.group(3)).strip().upper())
    partes = [p.strip() for p in antes.split(",")]
    if len(partes) >= 2:
        campos["bairro"] = partes[-1] or None
        logradouro = ",".join(partes[:-1])
        m = re.match(r"(.*?)\s*,\s*N\.\s*(\S+)\s*(.*)$", logradouro, re.I)
        if m:
            campos["rua"], campos["numero"] = m.group(1).strip(), m.group(2).strip()
            campos["complemento"] = m.group(3).strip() or None
        else:
            campos["rua"] = logradouro.strip() or None
    return campos


def _banheiros_da_descricao(descricao: str | None) -> int | None:
    """
    A pagina nao tem campo de banheiros: eles aparecem na descricao, como "Wc", "2 Wc"
    ou "wc Emp" (banheiro de empregada). Soma os itens que comecam com Wc ou Banheiro
    (com o numero antes, se houver): "3 Wc, wc Emp" -> 4. Lavabo e suite nao contam.
    Nenhum item assim -> None (nao informado).
    """
    total, achou = 0, False
    for item in (descricao or "").split(","):
        m = re.match(r"\s*(\d+)?\s*(wc|banheiros?)\b", item, re.I)
        if m:
            total += int(m.group(1) or 1)
            achou = True
    return total if achou else None


def _formas_pagamento(linhas_formas: list[str]) -> list[str]:
    """Textos da CAIXA -> opcoes do formulario (FORMAS_PAGAMENTO_CAIXA), na mesma ordem."""
    texto = _sem_acento(" ".join(linhas_formas)).lower()
    chaves = ("recursos proprios", "fgts", "financiamento", "parcelamento")
    return [forma for forma, chave in zip(FORMAS_PAGAMENTO_CAIXA, chaves) if chave in texto]


def _encerramento_pelo_tempo_restante(texto: str, agora: datetime) -> datetime | None:
    """
    "Tempo restante: 01 DIAS 03 HORAS 03 MINUTOS 02 SEGUNDOS" -> agora + tempo restante,
    arredondado para os 5 minutos mais proximos: o relogio do site continua andando
    entre copiar e ler, e os encerramentos da CAIXA caem em horarios redondos (18:00).
    Tudo zero (pagina salva depois do fim ou sem o contador) -> None.
    """
    m = re.search(r"Tempo restante:?\s*(\d+)\s*DIAS?\s*(\d+)\s*HORAS?\s*(\d+)\s*MINUTOS?\s*(\d+)\s*SEGUNDOS?",
                  texto, re.I)
    if not m:
        return None
    dias, horas, minutos, segundos = (int(g) for g in m.groups())
    restante = timedelta(days=dias, hours=horas, minutes=minutos, seconds=segundos)
    if not restante:
        return None
    fim = agora + restante
    passo = ARREDONDAR_ENCERRAMENTO_MIN * 60
    segundos_do_dia = fim.hour * 3600 + fim.minute * 60 + fim.second
    arredondado = round(segundos_do_dia / passo) * passo
    return fim.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(seconds=arredondado)


def ler_pagina_caixa(conteudo: str, agora: datetime | None = None) -> dict:
    """
    Le a pagina do imovel (HTML salvo ou texto colado). `agora` (hora de Brasilia) so
    serve para calcular o encerramento da Venda Online pelo tempo restante.

    Retorna {"ok", "erro", "campos", "nao_encontrados", "avisos"}. `campos` usa os nomes do
    formulario e de services/leilao.py (valor_minimo_1, data_1_leilao, data_encerramento...).
    `nao_encontrados` lista os nomes legiveis dos campos esperados para a modalidade que
    nao foram achados.
    """
    conteudo = conteudo or ""
    agora = agora or agora_brasilia()
    texto = texto_da_pagina(conteudo)
    if not re.search(r"Valor m[ií]nimo de venda", texto, re.I) or not re.search(r"N[uú]mero do im[oó]vel", texto, re.I):
        return {"ok": False, "erro": "Não parece a página de um imóvel da CAIXA (faltam o valor mínimo de "
                                      "venda e o número do imóvel). Confira se salvou ou copiou a página certa.",
                "campos": {}, "nao_encontrados": [], "avisos": []}
    linhas = texto.splitlines()
    avisos: list[str] = []
    campos: dict = {}

    # Modalidade: linha que e exatamente um dos 4 nomes do site.
    campos["modalidade"] = next((l for l in linhas if l in MODALIDADES_CAIXA), None)

    campos["valor_avaliacao"] = _reais(r"Valor de avalia[cç][aã]o:", texto)
    campos["valor_minimo"] = _reais(r"Valor m[ií]nimo de venda:", texto)
    campos["valor_minimo_1"] = _reais(r"Valor m[ií]nimo de venda 1[º°o] Leil[aã]o:", texto)
    campos["valor_minimo_2"] = _reais(r"Valor m[ií]nimo de venda 2[º°o] Leil[aã]o:", texto)

    tipo_caixa = _achar(r"^Tipo de im[oó]vel:\s*(.+)$", texto)
    campos["tipo_caixa"] = tipo_caixa
    campos["tipo"] = TIPO_FORMULARIO.get(_sem_acento(tipo_caixa or "").upper())
    if tipo_caixa and not campos["tipo"]:
        avisos.append(f"Tipo de imóvel na CAIXA: {tipo_caixa}. O sistema só avalia casa e apartamento.")

    campos["quartos"] = _inteiro(r"Quartos", texto)
    campos["vagas"] = _inteiro(r"Garagem", texto)
    campos["numero_imovel"] = _achar(r"^N[uú]mero do im[oó]vel:\s*([\d-]+)", texto)
    campos["matricula"] = _achar(r"^Matr[ií]cula\(s\):\s*(.+)$", texto)
    campos["comarca"] = _achar(r"^Comarca:\s*(.+)$", texto)
    campos["oficio"] = _achar(r"^Of[ií]cio:\s*(.+)$", texto)
    campos["inscricao_imobiliaria"] = _achar(r"^Inscri[cç][aã]o imobili[aá]ria:\s*(.+)$", texto)
    campos["averbacao_leiloes_negativos"] = _achar(r"^Averba[cç][aã]o dos leil[oõ]es negativos:\s*(.+)$", texto)

    campos["area_total"] = _area(r"[ÁA]rea total", texto)
    campos["area_privativa"] = _area(r"[ÁA]rea privativa", texto)
    campos["area_terreno"] = _area(r"[ÁA]rea do terreno", texto)
    for campo, nome in (("area_total", "total"), ("area_privativa", "privativa"), ("area_terreno", "do terreno")):
        # Erro de cadastro da CAIXA (ex.: "Área do terreno = 0,01m2" numa casa): nao entra
        # no calculo; fica vazio para preencher a mao.
        if campos[campo] is not None and campos[campo] < AREA_MINIMA_M2:
            avisos.append(f"Área {nome} na CAIXA ({_area_br(campos[campo])} m²) parece errada: "
                          f"não foi preenchida. Confira na matrícula.")
            campos[campo] = None

    campos["edital"] = _achar(r"^Edital:\s*(.+)$", texto)
    campos["numero_item"] = _achar(r"^N[uú]mero do item:\s*(.+)$", texto)
    campos["leiloeiro"] = _achar(r"^Leiloeiro\(a\):\s*(.+)$", texto)

    campos["data_1_leilao"] = _data_hora(_achar(r"^Data do 1[º°o] Leil[aã]o\s*-\s*(.+)$", texto))
    campos["data_2_leilao"] = _data_hora(_achar(r"^Data do 2[º°o] Leil[aã]o\s*-\s*(.+)$", texto))
    campos["data_encerramento"] = _data_hora(_achar(r"^Data da Licita[cç][aã]o Aberta\s*-\s*(.+)$", texto))
    if campos["modalidade"] == MODALIDADE_VENDA_ONLINE:
        # Encerrada: o texto traz a data. Em andamento: a data exata so esta no script do
        # cronometro da pagina salva ("1@@" + "26/10/2026 18:00:00"). No texto colado so
        # vem o tempo restante: a data e calculada (agora + tempo restante) e avisada.
        campos["data_encerramento"] = (
            _data_hora(_achar(r"Venda online encerrada em\s*(.+)$", texto))
            or _data_hora(_achar(r'"1@@"\s*\+\s*"([^"]+)"', conteudo))
        )
        if campos["data_encerramento"] is None:
            campos["data_encerramento"] = _encerramento_pelo_tempo_restante(texto, agora)
            if campos["data_encerramento"] is not None:
                avisos.append(
                    "Data de encerramento calculada pelo tempo restante do site: "
                    f"{texto_data_hora(campos['data_encerramento'])}. Confira no site da CAIXA."
                )

    endereco = _linhas_depois("Endereço:", linhas, ("Baixar", "Descrição:"))
    campos.update(_endereco(endereco[0] if endereco else None))
    sem_numero = (campos["numero"] or "").upper().replace("/", "") == "SN"
    if sem_numero:
        # "N. SN" = sem numero: nao e o numero do imovel.
        campos["numero"] = None
        avisos.append("Endereço sem número na CAIXA (S/N): o número fica vazio.")
    descricao = _linhas_depois("Descrição:", linhas, ("FORMAS DE PAGAMENTO", "REGRAS PARA PAGAMENTO"))
    campos["descricao"] = " ".join(descricao).strip(" .") or None
    campos["banheiros"] = _banheiros_da_descricao(campos["descricao"])

    formas = _linhas_depois("FORMAS DE PAGAMENTO ACEITAS:", linhas, ("REGRAS PARA PAGAMENTO",))
    campos["formas_pagamento_texto"] = formas or None
    campos["formas_pagamento"] = _formas_pagamento(formas) or None
    # Aviso de gravame/penhora: a CAIXA so mostra quando existe, no meio do bloco das
    # despesas e em duas linhas ("Imovel com gravame..." e "Regularizacao por conta do
    # adquirente."). Sai das regras de despesas e vira o aviso inteiro.
    i_gravame = next((i for i, l in enumerate(linhas) if re.search(r"gravame|penhora|indisponibilidade", l, re.I)),
                     None)
    linhas_gravame = []
    if i_gravame is not None:
        linhas_gravame = [linhas[i_gravame]]
        if i_gravame + 1 < len(linhas) and re.match(r"Regulariza[cç][aã]o", linhas[i_gravame + 1], re.I):
            linhas_gravame.append(linhas[i_gravame + 1])
    campos["gravame"] = bool(linhas_gravame)
    campos["gravame_texto"] = " ".join(linhas_gravame) or None

    regras = _linhas_depois("REGRAS PARA PAGAMENTO DAS DESPESAS", linhas,
                            ("Corretores credenciados", "Regras da Venda Online", "Baixar edital", "Galeria"))
    campos["regras_despesas"] = "\n".join(l for l in regras if l not in linhas_gravame) or None

    link = _achar(r"saved from url=\(\d+\)(https?://\S+?)\s*-->", conteudo)
    campos["link"] = link

    esperados = CAMPOS_GERAIS + CAMPOS_POR_MODALIDADE.get(campos["modalidade"], ())
    nao_encontrados = [NOMES_CAMPOS[c] for c in esperados
                       if campos.get(c) in (None, "", []) and not (c == "numero" and sem_numero)]
    return {"ok": True, "erro": None, "campos": campos, "nao_encontrados": nao_encontrados, "avisos": avisos}


def _reais_br(valor: float | None) -> str:
    """224000.0 -> '224.000,00' (como o formulario aceita)."""
    if valor is None:
        return ""
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _area_br(valor: float | None) -> str:
    """54.68 -> '54,68'; 300.0 -> '300'."""
    if valor is None:
        return ""
    return f"{valor:g}".replace(".", ",") if valor != int(valor) else str(int(valor))


def valores_para_formulario(campos: dict) -> dict:
    """
    Campos lidos da pagina -> valores dos campos do formulario (chave do widget ->
    valor), no formato que o formulario aceita ("224.000,00", "30/11/2026 10:00").
    Campo nao lido nao entra: o que a pessoa ja digitou fica como esta.
    Area construida = area privativa (ou a total, se a pagina so tiver ela); terreno
    so para casa.
    """
    area = campos.get("area_privativa") or campos.get("area_total")
    valores = {
        "f_rua": campos.get("rua"),
        "f_numero": campos.get("numero"),
        "f_bairro": campos.get("bairro"),
        "f_cidade": campos.get("cidade"),
        "f_uf": campos.get("uf"),
        "f_tipo": campos.get("tipo"),
        "f_area": _area_br(area) or None,
        "f_terreno": _area_br(campos.get("area_terreno")) if campos.get("tipo") == "Casa" else None,
        "f_quartos": campos.get("quartos"),
        "f_banheiros": campos.get("banheiros"),
        "f_vagas": campos.get("vagas"),
        "f_descricao": campos.get("descricao"),
        "f_modalidade": campos.get("modalidade"),
        "f_valor_minimo": _reais_br(campos.get("valor_minimo")) or None,
        "f_valor_minimo_1": _reais_br(campos.get("valor_minimo_1")) or None,
        "f_data_1_leilao": texto_data_hora(campos.get("data_1_leilao")) or None,
        "f_valor_minimo_2": _reais_br(campos.get("valor_minimo_2")) or None,
        "f_data_2_leilao": texto_data_hora(campos.get("data_2_leilao")) or None,
        "f_data_encerramento": texto_data_hora(campos.get("data_encerramento")) or None,
        "f_valor_avaliacao": _reais_br(campos.get("valor_avaliacao")) or None,
        "f_numero_imovel": campos.get("numero_imovel"),
        "f_link_caixa": campos.get("link"),
        "f_edital": campos.get("edital"),
        "f_numero_item": campos.get("numero_item"),
        "f_leiloeiro": campos.get("leiloeiro"),
        "f_matricula": campos.get("matricula"),
        "f_averbacao": campos.get("averbacao_leiloes_negativos"),
        "f_gravame": campos.get("gravame"),
        "f_gravame_texto": campos.get("gravame_texto"),
        "f_formas_pagamento": campos.get("formas_pagamento"),
        "f_regras_despesas": campos.get("regras_despesas"),
    }
    return {chave: valor for chave, valor in valores.items() if valor not in (None, "", [])}
