"""
Avaliacao de imovel de leilao da CAIXA
======================================

Pergunta respondida: qual o retorno (ROI) de arrematar pelo valor minimo, e ate quanto
posso dar de lance para o imovel continuar "Oportunidade"?

Conta do investimento (regra do professor), com venda = valor de liquidez do Agente 5:
  custos antes da venda = arrematacao x (1 + CUSTOS_ANTES_DA_VENDA)      (33%)
  corretagem            = venda x CORRETAGEM                              (5%)
  IR                    = (venda - custos antes da venda) x ALIQUOTA_IR   (15%; 0 se negativo)
  resultado             = venda - custos antes - corretagem - IR
  ROI                   = resultado / custos antes da venda

Regra (nesta ordem):
  1. A estimativa do Agente 5 e confiavel? Usa o status que ele ja calcula
     (price_liquidity.py, MIN_AMOSTRAS_CONFIAVEL). Qualquer status diferente de "ok"
     (sem_amostra, valor_nao_estimado, amostra_insuficiente) ou Agente 5 sem
     resultado -> "Sem estimativa", sem lance maximo.
  2. ROI pagando o valor minimo da etapa atual:
       ROI < 15% -> "Descartar"; 15% a 30% -> "Margem apertada"; 30% ou mais -> "Oportunidade"
  3. lance_maximo = maior lance com ROI de ROI_OPORTUNIDADE (30%): "Lance ate R$ X para
     continuar Oportunidade"; lance_limite_descarte = maior lance com ROI de
     ROI_MARGEM_APERTADA (15%): "Acima de R$ Y, descartar";
     sobra = lance_maximo - valor_minimo (negativa = falta para "Oportunidade")

Modalidades (nomes do site da CAIXA) e etapa atual: avaliar_imovel_leilao.
  Leilao SFI       : 1o e 2o leilao, cada um com data/hora e valor minimo. Ate a data/hora
                     do 1o -> 1o; depois, ate a do 2o -> 2o; depois -> encerrado. O valor
                     do 2o pode ser MAIOR que o do 1o (no 2o o minimo e a divida).
  Licitacao Aberta : data/hora da licitacao (encerramento) e valor minimo.
  Venda Online     : data/hora de encerramento (cronometro do site) e valor minimo.
  Compra Direta    : so valor minimo; sem encerramento (a primeira proposta vence), o
                     "ativo" depende so da situacao manual.

O valor minimo e o "valor minimo de venda" do site da CAIXA. Ele NAO entra em nenhum
agente: preco de leilao fica bem abaixo do mercado e distorceria a escolha dos
comparaveis. O valor de avaliacao CAIXA e so informativo.
"""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone

from services.formatos import ler_numero_br

# Conta do investimento (regra do professor). Unico lugar destes percentuais.
CUSTOS_ANTES_DA_VENDA = 0.33   # sobre a arrematacao (ITBI, registro, debitos, reforma...)
CORRETAGEM = 0.05              # sobre a venda
ALIQUOTA_IR = 0.15             # sobre venda - custos antes da venda

# Faixas de ROI (arrematando pelo valor minimo). Limite exato entra na faixa de cima.
ROI_MARGEM_APERTADA = 0.15
ROI_OPORTUNIDADE = 0.30

ORIGEM_CAIXA = "CAIXA"

# Modalidades do site da CAIXA (nomes exatos). Os registros antigos ("Venda Direta
# Online", "Leilão SFI (valor do 1º/2º leilão)", "Outra") ficam no banco como estao.
MODALIDADE_SFI = "Leilão SFI"
MODALIDADE_LICITACAO = "Licitação Aberta"
MODALIDADE_VENDA_ONLINE = "Venda Online"
MODALIDADE_COMPRA_DIRETA = "Compra Direta"
MODALIDADES_CAIXA = [MODALIDADE_SFI, MODALIDADE_LICITACAO, MODALIDADE_VENDA_ONLINE, MODALIDADE_COMPRA_DIRETA]

# Comissao: no Leilao SFI e na Licitacao Aberta o comprador paga ao leiloeiro; na Venda
# Online e na Compra Direta a corretagem e da CAIXA. So registrada e mostrada: nao entra
# na conta (os custos antes da venda ja cobrem a aquisicao).
COMISSAO_LEILOEIRO = 0.05
MODALIDADES_COM_LEILOEIRO = (MODALIDADE_SFI, MODALIDADE_LICITACAO)

# Exercicio do Direito de Preferencia nao e modalidade: so um aviso no Leilao SFI.
AVISO_DIREITO_PREFERENCIA = "O antigo dono pode recomprar até a data do leilão."

# Aviso de gravame/penhora como aparece na pagina da CAIXA (quando so foi marcado sim/nao).
TEXTO_GRAVAME = ("Imóvel com gravame/penhora/indisponibilidade averbada na matrícula. "
                 "Regularização por conta do adquirente.")

# Dados da pagina da CAIXA que so sao mostrados (cartao, laudo) e gravados.
CAMPOS_INFORMATIVOS = (
    "banco", "numero_imovel", "link", "edital", "numero_item", "leiloeiro", "matricula",
    "averbacao_leiloes_negativos", "gravame", "gravame_texto",
)

# Situacao manual do imovel. "Ativo" = situacao ativa e prazo nao encerrado.
SITUACAO_ATIVO = "ativo"
SITUACOES_LEILAO = [SITUACAO_ATIVO, "vendido", "retirado", "suspenso"]

# Formas de pagamento como aparecem na pagina do imovel na CAIXA ("Formas de
# pagamento aceitas"). So registradas: nao entram no calculo.
FORMAS_PAGAMENTO_CAIXA = [
    "Recursos próprios (à vista)",
    "FGTS",
    "Financiamento",
    "Parcelamento",
]

DECISAO_OPORTUNIDADE = "Oportunidade"
DECISAO_MARGEM_APERTADA = "Margem apertada"
DECISAO_DESCARTAR = "Descartar"
DECISAO_SEM_ESTIMATIVA = "Sem estimativa"


def conta_investimento(arrematacao: float, venda: float) -> dict:
    """A conta do professor, linha a linha (tela, laudo e testes usam a mesma)."""
    custos_antes = arrematacao * (1 + CUSTOS_ANTES_DA_VENDA)
    corretagem = venda * CORRETAGEM
    ir = max(0.0, (venda - custos_antes) * ALIQUOTA_IR)
    custos_totais = custos_antes + corretagem + ir
    resultado = venda - custos_totais
    return {
        "arrematacao": arrematacao,
        "custos_antes_da_venda": custos_antes,
        "venda": venda,
        "corretagem": corretagem,
        "ir": ir,
        "custos_totais": custos_totais,
        "resultado": resultado,
        "roi": resultado / custos_antes,
    }


def lance_para_roi(venda: float, roi: float) -> float:
    """
    Maior arrematacao que ainda da o ROI pedido. Invertendo a conta (com IR positivo,
    o que vale para qualquer ROI >= 0):
        ROI = venda x (1 - corretagem - IR) / custos_antes - (1 - IR)
    """
    custos_antes = venda * (1 - CORRETAGEM - ALIQUOTA_IR) / (roi + 1 - ALIQUOTA_IR)
    return custos_antes / (1 + CUSTOS_ANTES_DA_VENDA)


def texto_percentual(valor: float, casas: int = 2) -> str:
    """0.70683 -> '70,68%'; texto_percentual(0.3, 0) -> '30%'."""
    return f"{valor * 100:.{casas}f}%".replace(".", ",")


def classificar_roi(roi: float) -> str:
    roi = round(roi, 9)  # lance exatamente no limite nao cai na faixa de baixo por arredondamento
    if roi >= ROI_OPORTUNIDADE:
        return DECISAO_OPORTUNIDADE
    if roi >= ROI_MARGEM_APERTADA:
        return DECISAO_MARGEM_APERTADA
    return DECISAO_DESCARTAR


def ler_valor_reais(texto) -> float | None:
    """
    Valor em reais digitado no formulario: "323158", "323.158", "323.158,50",
    "R$ 323.158,50", "323158.50". Vazio -> None; invalido -> ValueError.
    """
    return ler_numero_br(texto)


def ler_data_br(texto) -> date | None:
    """
    Data digitada no formulario: "25/11/2026" ou "25/11/26". Vazio -> None;
    invalido -> ValueError.
    """
    texto = str(texto or "").strip()
    if not texto:
        return None
    for formato in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            continue
    raise ValueError(texto)


def ler_data_hora_br(texto) -> date | datetime | None:
    """
    Data e hora digitadas no formulario (ou lidas da pagina da CAIXA):
    "30/11/2026 10:00", "30/11/2026 - 10h00", "30/11/2026 10h" -> datetime;
    so a data ("30/11/2026") -> date (vale ate o fim do dia). Vazio -> None;
    invalido -> ValueError.
    """
    texto = str(texto or "").strip()
    if not texto:
        return None
    m = re.fullmatch(r"(\d{1,2}/\d{1,2}/\d{2,4})(?:\s*(?:-|às|as)?\s*(\d{1,2})\s*[h:]\s*(\d{2})?\s*h?)?", texto, re.I)
    if not m:
        raise ValueError(texto)
    dia = ler_data_br(m.group(1))
    if m.group(2) is None:
        return dia
    hora, minuto = int(m.group(2)), int(m.group(3) or 0)
    if hora > 23 or minuto > 59:
        raise ValueError(texto)
    return datetime.combine(dia, time(hora, minuto))


def texto_data_hora(valor) -> str:
    """datetime -> '30/11/2026 10:00'; date -> '30/11/2026'; None -> ''."""
    if valor is None:
        return ""
    if isinstance(valor, datetime):
        return valor.strftime("%d/%m/%Y %H:%M")
    return valor.strftime("%d/%m/%Y")


# Campos do formulario do leilao: (rotulo no aviso de erro, exemplo).
CAMPOS_VALOR_LEILAO = {
    "valor_minimo": ("Valor mínimo de venda", "323.158,00"),
    "valor_minimo_1": ("Valor mínimo do 1º leilão", "224.000,00"),
    "valor_minimo_2": ("Valor mínimo do 2º leilão", "296.523,50"),
    "valor_avaliacao": ("Valor de avaliação", "410.000,00"),
}
CAMPOS_DATA_LEILAO = {
    "data_1_leilao": "Data do 1º leilão",
    "data_2_leilao": "Data do 2º leilão",
    "data_encerramento": "Data de encerramento",
}
CAMPOS_TEXTO_LEILAO = (
    "numero_imovel", "link", "edital", "numero_item", "leiloeiro", "matricula",
    "averbacao_leiloes_negativos", "gravame_texto", "regras_despesas",
)


def campos_da_modalidade(modalidade: str) -> set:
    """Campos do formulario que valem para a modalidade (os outros sao ignorados)."""
    campos = {"valor_avaliacao", "numero_imovel", "link", "matricula", "averbacao_leiloes_negativos",
              "gravame", "gravame_texto", "formas_pagamento", "regras_despesas"}
    if modalidade == MODALIDADE_SFI:
        campos |= {"valor_minimo_1", "data_1_leilao", "valor_minimo_2", "data_2_leilao"}
    else:
        campos.add("valor_minimo")
        if modalidade in (MODALIDADE_LICITACAO, MODALIDADE_VENDA_ONLINE):
            campos.add("data_encerramento")
    if modalidade in MODALIDADES_COM_LEILOEIRO:
        campos |= {"edital", "numero_item", "leiloeiro"}
    return campos


def ler_formulario_leilao(textos: dict, banco: str, modalidade: str) -> tuple[dict | None, list[str]]:
    """
    Campos do leilao como foram digitados -> (dados para avaliar_imovel_leilao, erros).
    Sem modalidade: (None, []), nao e leilao. So os campos da modalidade sao lidos.
    Valores e datas no jeito brasileiro ("296.523,50", "30/11/2026 10:00").
    gravame: marcado, ou com o texto do aviso preenchido.
    """
    if not modalidade:
        return None, []
    validos = campos_da_modalidade(modalidade)
    dados: dict = {"banco": banco or ORIGEM_CAIXA, "modalidade": modalidade}
    erros: list[str] = []
    for campo, (rotulo, exemplo) in CAMPOS_VALOR_LEILAO.items():
        if campo not in validos:
            continue
        texto = textos.get(campo) or ""
        try:
            dados[campo] = ler_valor_reais(texto)
        except ValueError:
            erros.append(f"{rotulo} inválido: \"{texto}\" (use, por exemplo, {exemplo})")
    for campo, rotulo in CAMPOS_DATA_LEILAO.items():
        if campo not in validos:
            continue
        texto = textos.get(campo) or ""
        try:
            dados[campo] = ler_data_hora_br(texto)
        except ValueError:
            erros.append(f"{rotulo} inválida: \"{texto}\" (use, por exemplo, 30/11/2026 10:00)")
    for campo in CAMPOS_TEXTO_LEILAO:
        if campo in validos:
            dados[campo] = str(textos.get(campo) or "").strip() or None
    dados["gravame"] = bool(textos.get("gravame")) or bool(dados.get("gravame_texto"))
    dados["formas_pagamento"] = list(textos.get("formas_pagamento") or []) or None
    return dados, erros


def contar_status_zona(resultado_ag5: dict | None) -> dict:
    """
    Quantos comparaveis usados pelo Agente 5 (construcao e terreno) foram:
      confirmado    = dentro do raio da zona homogenea;
      fallback      = "zona nao verificada": completaram a amostra porque havia menos
                      de 5 confirmados (a distancia nao pode ser medida);
      sem_validacao = socorro do Agente 5: Cluster A usado sem nenhum confirmado.
    Os de fallback e sem_validacao contam para o minimo de 5 (decisao do professor,
    17/10/2026); o aviso na tela, no laudo e nos logs deixa isso claro.
    """
    usados = (resultado_ag5 or {}).get("comparaveis_usados") or {}
    contagem = {"confirmado": 0, "fallback": 0, "sem_validacao": 0}
    for lista in (usados.get("construcao") or [], usados.get("terreno") or []):
        for comparavel in lista:
            status = comparavel.get("status_zona") or "confirmado"
            contagem[status if status in contagem else "confirmado"] += 1
    contagem["total"] = sum(contagem.values())
    return contagem


def texto_aviso_zona(contagem: dict, escopo_busca: str | None = None) -> str | None:
    """
    Aviso com numeros sobre os comparaveis cuja distancia nao foi verificada (e sobre
    a busca na cidade toda). None quando todos foram confirmados perto do imovel.
    """
    partes = []
    total = contagem.get("total", 0)
    if contagem.get("sem_validacao"):
        partes.append(
            f"Nenhum comparável foi confirmado perto do imóvel. O valor usa "
            + (f"1 imóvel parecido encontrado na busca" if contagem["sem_validacao"] == 1 else
               f"{contagem['sem_validacao']} imóveis parecidos encontrados na busca")
            + ", sem verificar a distância. Confira esses anúncios antes de decidir."
        )
    elif contagem.get("fallback"):
        partes.append(
            (f"Nenhum dos {total} comparáveis foi confirmado" if not contagem.get("confirmado") else
             f"Só 1 dos {total} comparáveis foi confirmado" if contagem.get("confirmado") == 1 else
             f"Só {contagem['confirmado']} dos {total} comparáveis foram confirmados")
            + " perto do imóvel (dentro da zona homogênea). "
            + ("O outro não tem localização exata no anúncio, então não foi possível medir a "
               "distância: pode estar perto ou longe. Ele conta para o mínimo de 5. Confira esse "
               "anúncio antes de decidir." if contagem["fallback"] == 1 else
               f"Os outros {contagem['fallback']} não têm localização exata no anúncio, então não foi "
               f"possível medir a distância: podem estar perto ou longe. Eles contam para o mínimo "
               f"de 5. Confira esses anúncios antes de decidir.")
        )
    if escopo_busca == "cidade":
        partes.append(
            "Nenhum anúncio foi encontrado na rua ou no bairro do imóvel; o valor usa imóveis "
            "parecidos de outros bairros da cidade."
        )
    return " ".join(partes) or None


def texto_aviso_lancamento(resultado_ag5: dict | None) -> str | None:
    """
    Aviso para os comparaveis usados que sao provavel lancamento: varios anuncios
    iguais (mesmo preco e area, imobiliarias diferentes) contados como 1 imovel.
    """
    usados = (resultado_ag5 or {}).get("comparaveis_usados") or {}
    frases = [
        f"{c['provavel_lancamento']['anuncios']} anúncios iguais (mesmo preço e área, imobiliárias "
        f"diferentes; provável lançamento) foram contados como 1 imóvel."
        for c in (usados.get("construcao") or []) if c.get("provavel_lancamento")
    ]
    return " ".join(frases) or None


def _metros(valor) -> str:
    return f"{int(round(float(valor))):,}".replace(",", ".")


def texto_aviso_raio(zona: dict | None) -> str | None:
    """
    Aviso quando o Agente 2 ampliou o raio da zona para chegar ao minimo de
    comparaveis (sem chamar a IA de novo). None quando nao houve ampliacao.
    """
    zona = zona or {}
    amp = zona.get("ampliacao_raio") or {}
    if not amp.get("ampliado"):
        return None
    minimo, limite = amp.get("minimo", 5), amp.get("limite_m", 1500)
    raio_ia = zona.get("raio_ia_m")
    partes = []
    for nome, raio_final, n in (
        ("comparáveis", zona.get("raio_final_m"), amp.get("confirmados_depois", 0)),
        ("terrenos", zona.get("raio_final_terrenos_m"), amp.get("terrenos_depois", 0)),
    ):
        if raio_final is None or raio_ia is None or raio_final == raio_ia:
            continue
        if n >= minimo:
            partes.append(
                f"Havia menos de {minimo} {nome} no raio de {_metros(raio_ia)} m; o raio foi "
                f"ampliado para {_metros(raio_final)} m para chegar a {n}."
            )
        else:
            partes.append(
                f"Havia menos de {minimo} {nome} no raio de {_metros(raio_ia)} m; o raio foi "
                f"ampliado até {_metros(limite)} m e ainda assim "
                + ("nenhum foi confirmado." if n == 0 else "só 1 foi confirmado." if n == 1 else
                   f"só {n} foram confirmados.")
            )
    return " ".join(partes) or None


def _numero(valor) -> float | None:
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None
    return numero if numero > 0 else None


def avaliar_leilao(
    resultado_ag5: dict | None,
    valor_minimo: float | None,
    valor_avaliacao: float | None = None,
) -> dict | None:
    """
    Decisao do leilao a partir do resultado do Agente 5.

    Retorna None quando o valor minimo nao foi informado (o bloco nao aparece).
    Caso contrario, um dict com: origem, decisao, valor_minimo, valor_avaliacao,
    roi (arrematando pelo valor minimo), conta (conta_investimento no valor minimo),
    lance_maximo (ROI de 30%), lance_limite_descarte (ROI de 15%), sobra, liquidez,
    status_agente5 e comparaveis_fora_da_regiao (quantos comparaveis usados nao foram
    confirmados dentro da zona homogenea: entraram por fallback ou sem validacao de
    distancia).
    """
    valor_minimo = _numero(valor_minimo)
    if valor_minimo is None:
        return None

    resultado_ag5 = resultado_ag5 or {}
    status = resultado_ag5.get("status_avaliacao") or "sem_resultado"
    base = {
        "origem": ORIGEM_CAIXA,
        "valor_minimo": valor_minimo,
        "valor_avaliacao": _numero(valor_avaliacao),
        "status_agente5": status,
        "decisao": DECISAO_SEM_ESTIMATIVA,
        "roi": None,
        "conta": None,
        "lance_maximo": None,
        "lance_limite_descarte": None,
        "sobra": None,
        "liquidez": None,
        "comparaveis_fora_da_regiao": 0,
    }

    # 1. Estimativa confiavel? So o status "ok" do Agente 5 segue.
    liquidez = _numero((resultado_ag5.get("avaliacao_planilha") or {}).get("valor_liquidez"))
    if status != "ok" or not resultado_ag5.get("avaliacao_confiavel", False) or liquidez is None:
        return base

    # 2. ROI arrematando pelo valor minimo. 3. Lances limite e sobra.
    conta = conta_investimento(valor_minimo, liquidez)
    lance_maximo = lance_para_roi(liquidez, ROI_OPORTUNIDADE)
    sobra = lance_maximo - valor_minimo

    usados = resultado_ag5.get("comparaveis_usados") or {}
    fora_da_regiao = sum(
        1
        for lista in (usados.get("construcao") or [], usados.get("terreno") or [])
        for comparavel in lista
        if comparavel.get("status_zona") in ("fallback", "sem_validacao")
    )

    return {
        **base,
        "decisao": classificar_roi(conta["roi"]),
        "roi": conta["roi"],
        "conta": conta,
        "lance_maximo": lance_maximo,
        "lance_limite_descarte": lance_para_roi(liquidez, ROI_MARGEM_APERTADA),
        "sobra": sobra,
        "liquidez": liquidez,
        "comparaveis_fora_da_regiao": fora_da_regiao,
    }


def agora_brasilia() -> datetime:
    """
    Hora de Brasilia (UTC-3, sem horario de verao desde 2019), sem fuso, para comparar
    com as datas do site da CAIXA. No Streamlit Cloud o servidor roda em UTC: usar
    datetime.now() erraria a etapa e o "encerrado" em 3 horas.
    """
    return (datetime.now(timezone.utc) - timedelta(hours=3)).replace(tzinfo=None)


def como_datahora(valor) -> datetime | None:
    """Data sem hora vale ate o fim do dia; None continua None."""
    if valor is None or isinstance(valor, datetime):
        return valor
    if isinstance(valor, date):
        return datetime.combine(valor, time.max)
    raise TypeError(f"data invalida: {valor!r}")


def etapa_atual(leilao: dict, agora: datetime) -> dict:
    """
    Etapa em que o imovel esta agora e o valor minimo que vale para ela.

    Leilao SFI: ate a data/hora do 1o -> etapa 1; depois, ate a do 2o -> etapa 2; depois
    do 2o -> encerrado (o ROI usa o valor da ultima etapa). Sem nenhuma data, usa o
    valor do 1o (ou do 2o, se so ele foi informado). Nao supoe que o 2o e mais barato.
    Demais modalidades: valor_minimo e data_encerramento (Compra Direta nao tem).

    Retorna {etapa (1, 2 ou None), valor_minimo, encerramento, encerrado,
    outra_etapa, valor_minimo_outra_etapa}.
    """
    if leilao.get("modalidade") != MODALIDADE_SFI:
        encerramento = como_datahora(leilao.get("data_encerramento"))
        return {
            "etapa": None, "valor_minimo": _numero(leilao.get("valor_minimo")),
            "encerramento": encerramento, "encerrado": encerramento is not None and agora > encerramento,
            "outra_etapa": None, "valor_minimo_outra_etapa": None,
        }

    datas = {1: como_datahora(leilao.get("data_1_leilao")), 2: como_datahora(leilao.get("data_2_leilao"))}
    valores = {1: _numero(leilao.get("valor_minimo_1")), 2: _numero(leilao.get("valor_minimo_2"))}
    encerrado = False
    if datas[1] is not None and agora <= datas[1]:
        etapa = 1
    elif datas[2] is not None and agora <= datas[2]:
        etapa = 2
    elif datas[1] is not None or datas[2] is not None:
        etapa, encerrado = (2 if datas[2] is not None else 1), True
    else:
        etapa = 1 if valores[1] is not None or valores[2] is None else 2
    outra = 2 if etapa == 1 else 1
    return {
        "etapa": etapa, "valor_minimo": valores[etapa],
        "encerramento": datas[etapa], "encerrado": encerrado,
        "outra_etapa": outra, "valor_minimo_outra_etapa": valores[outra],
    }


def esta_ativo(situacao: str | None, encerrado: bool) -> bool:
    """Ativo = situacao manual ativa (vazia conta como ativa) e prazo nao encerrado."""
    return (situacao or SITUACAO_ATIVO) == SITUACAO_ATIVO and not encerrado


def _data_hora_br(momento: datetime) -> str:
    return momento.strftime("%d/%m/%Y %H:%M")


def texto_prazo(encerramento: datetime | None, agora: datetime) -> str | None:
    """'Encerra em 3 dias e 4 h (29/10/2026 10:00)' ou 'Encerrado em 29/10/2026 10:00'."""
    if encerramento is None:
        return None
    if agora > encerramento:
        return f"Encerrado em {_data_hora_br(encerramento)}"
    falta = encerramento - agora
    dias, horas = falta.days, falta.seconds // 3600
    if dias:
        partes = f"{dias} {'dia' if dias == 1 else 'dias'} e {horas} h"
    else:
        partes = f"{horas} h" if horas else "menos de 1 h"
    return f"Encerra em {partes} ({_data_hora_br(encerramento)})"


def avaliar_imovel_leilao(resultado_ag5: dict | None, leilao: dict, agora: datetime | None = None) -> dict | None:
    """
    Avaliacao completa de um imovel da CAIXA, pela modalidade.

    `leilao` traz: modalidade, valor_avaliacao, situacao e, conforme a modalidade,
    valor_minimo_1, data_1_leilao, valor_minimo_2, data_2_leilao (Leilao SFI) ou
    valor_minimo, data_encerramento (as outras). Datas: datetime (ou date = fim do dia).

    Retorna o dict de avaliar_leilao (no valor minimo da etapa atual) mais: modalidade,
    etapa, encerramento, encerrado, prazo, situacao, ativo, comissao_leiloeiro,
    aviso_direito_preferencia e, no SFI, outra_etapa, valor_minimo_outra_etapa e
    roi_outra_etapa. None sem valor minimo da etapa.
    """
    agora = agora or agora_brasilia()
    modalidade = leilao.get("modalidade")
    etapa = etapa_atual(leilao, agora)
    avaliacao = avaliar_leilao(resultado_ag5, etapa["valor_minimo"], leilao.get("valor_avaliacao"))
    if avaliacao is None:
        return None

    situacao = leilao.get("situacao") or SITUACAO_ATIVO
    avaliacao.update({
        "modalidade": modalidade,
        "etapa": etapa["etapa"],
        "encerramento": etapa["encerramento"],
        "encerrado": etapa["encerrado"],
        "prazo": texto_prazo(etapa["encerramento"], agora),
        "situacao": situacao,
        "ativo": esta_ativo(situacao, etapa["encerrado"]),
        "comissao_leiloeiro": COMISSAO_LEILOEIRO if modalidade in MODALIDADES_COM_LEILOEIRO else None,
        "aviso_direito_preferencia": AVISO_DIREITO_PREFERENCIA if modalidade == MODALIDADE_SFI else None,
        "outra_etapa": None,
        "valor_minimo_outra_etapa": None,
        "roi_outra_etapa": None,
        **{campo: leilao.get(campo) for campo in CAMPOS_INFORMATIVOS},
    })
    avaliacao["banco"] = avaliacao["banco"] or ORIGEM_CAIXA
    if modalidade == MODALIDADE_SFI and etapa["valor_minimo_outra_etapa"] is not None:
        avaliacao["outra_etapa"] = etapa["outra_etapa"]
        avaliacao["valor_minimo_outra_etapa"] = etapa["valor_minimo_outra_etapa"]
        if avaliacao["liquidez"] is not None:
            avaliacao["roi_outra_etapa"] = conta_investimento(
                etapa["valor_minimo_outra_etapa"], avaliacao["liquidez"])["roi"]
    return avaliacao


def texto_lance_maximo(leilao: dict, fmt_brl) -> str:
    """'Lance até R$ X para continuar Oportunidade' (ROI de 30%)."""
    return f"Lance até {fmt_brl(leilao['lance_maximo'])} para continuar {DECISAO_OPORTUNIDADE}"


def texto_lance_descarte(leilao: dict, fmt_brl) -> str:
    """'Acima de R$ Y, descartar' (ROI de 15%)."""
    return f"Acima de {fmt_brl(leilao['lance_limite_descarte'])}, descartar"


def texto_cabecalho(leilao: dict) -> str:
    """'CAIXA · Leilão SFI · 2º leilão' (a etapa so no Leilao SFI)."""
    partes = [leilao.get("banco") or ORIGEM_CAIXA, leilao.get("modalidade")]
    if leilao.get("etapa"):
        partes.append(f"{leilao['etapa']}º leilão")
    return " · ".join(p for p in partes if p)


def texto_roi_outra_etapa(leilao: dict, fmt_brl) -> str | None:
    """'No 1º leilão (mínimo R$ 224.000), o ROI seria 70,68%.' (so Leilao SFI)."""
    if leilao.get("roi_outra_etapa") is None:
        return None
    return (f"No {leilao['outra_etapa']}º leilão (mínimo {fmt_brl(leilao['valor_minimo_outra_etapa'])}), "
            f"o ROI seria {texto_percentual(leilao['roi_outra_etapa'])}.")


def texto_comissao(leilao: dict) -> str | None:
    """Quem paga a comissao (so registrado: nao entra na conta)."""
    if not leilao.get("modalidade"):
        return None
    if leilao.get("comissao_leiloeiro"):
        return (f"Comissão do leiloeiro: {texto_percentual(leilao['comissao_leiloeiro'], 0)} do lance, "
                f"paga pelo comprador (não entra na conta do ROI).")
    return "Corretagem por conta da CAIXA."


def texto_gravame(leilao: dict) -> str | None:
    if not leilao.get("gravame"):
        return None
    return leilao.get("gravame_texto") or TEXTO_GRAVAME


def linhas_laudo(leilao: dict | None, fmt_brl) -> list[str]:
    """
    Linhas da secao "AVALIACAO DE LEILAO (CAIXA)" do laudo TXT. `fmt_brl` formata
    valores em reais. Sem estimativa confiavel: so a decisao e o valor minimo.
    """
    if not leilao:
        return []
    linhas = [f"Decisão: {leilao['decisao']}"]
    if leilao.get("modalidade"):
        linhas.append(texto_cabecalho(leilao))
    if leilao.get("prazo"):
        linhas.append(leilao["prazo"])
    if texto_gravame(leilao):
        linhas.append(f"Atenção: {texto_gravame(leilao)}")
    if leilao.get("alvo_sem_localizacao"):
        linhas.append(
            "Atenção: endereço não localizado no mapa com precisão de rua ou bairro; "
            "a distância dos comparáveis não foi verificada."
        )
    if leilao.get("lance_maximo") is not None:
        conta = leilao["conta"]
        linhas += [
            f"ROI pagando o valor mínimo: {texto_percentual(leilao['roi'])}",
            f"Valor mínimo CAIXA: {fmt_brl(leilao['valor_minimo'])}",
            texto_lance_maximo(leilao, fmt_brl),
            texto_lance_descarte(leilao, fmt_brl),
            "",
            "Conta do investimento (pagando o valor mínimo):",
            f"  Custos antes da venda (arrematação + {texto_percentual(CUSTOS_ANTES_DA_VENDA, 0)}): "
            f"{fmt_brl(conta['custos_antes_da_venda'])}",
            f"  Receita da venda (valor de liquidez): {fmt_brl(conta['venda'])}",
            f"  Corretagem ({texto_percentual(CORRETAGEM, 0)} da venda): {fmt_brl(conta['corretagem'])}",
            f"  IR ({texto_percentual(ALIQUOTA_IR, 0)} de venda − custos antes da venda): {fmt_brl(conta['ir'])}",
            f"  Todos os custos: {fmt_brl(conta['custos_totais'])}",
            f"  Resultado: {fmt_brl(conta['resultado'])}",
            f"  ROI (resultado ÷ custos antes da venda): {texto_percentual(conta['roi'])}",
        ]
        if leilao.get("aviso_zona"):
            linhas.append(f"Atenção: {leilao['aviso_zona']}")
    else:
        linhas.append(f"Valor mínimo CAIXA: {fmt_brl(leilao['valor_minimo'])}")
    if texto_roi_outra_etapa(leilao, fmt_brl):
        linhas.append(texto_roi_outra_etapa(leilao, fmt_brl))
    if leilao.get("valor_avaliacao"):
        linhas.append(f"Valor de avaliação CAIXA (informativo): {fmt_brl(leilao['valor_avaliacao'])}")
    if texto_comissao(leilao):
        linhas.append(texto_comissao(leilao))
    if leilao.get("aviso_direito_preferencia"):
        linhas.append(leilao["aviso_direito_preferencia"])
    for rotulo, campo in (("Número do imóvel", "numero_imovel"), ("Edital", "edital"), ("Item", "numero_item"),
                          ("Leiloeiro(a)", "leiloeiro"), ("Matrícula", "matricula"),
                          ("Averbação dos leilões negativos", "averbacao_leiloes_negativos")):
        if leilao.get(campo):
            linhas.append(f"{rotulo}: {leilao[campo]}")
    return linhas
