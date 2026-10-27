"""
Cronometro do leilao: conta no navegador (JavaScript) ate a proxima data do imovel
(1o leilao, 2o leilao, licitacao ou encerramento da Venda Online), em dias, horas,
minutos e segundos, sem recarregar a pagina. Compra Direta nao tem cronometro.

As datas do site da CAIXA estao no horario de Brasilia (UTC-3, sem horario de verao
desde 2019): o navegador converte certo em qualquer fuso.
"""
from __future__ import annotations

import html
from datetime import datetime

FUSO_BRASILIA = "-03:00"
ALTURA_PX = 46

# Fundo e texto proprios: legivel com o tema claro ou escuro do Streamlit (o
# componente roda num iframe e nao herda o tema).
_ESTILO = (
    "font-family: 'Source Sans Pro', sans-serif; font-size: 15px; color: #1f2937; "
    "background: #eef2f7; border-radius: 8px; padding: 9px 14px; margin: 0;"
)


def rotulo_prazo(leilao: dict) -> str:
    """'1º leilão', '2º leilão', 'Licitação' ou 'Encerramento da venda'."""
    if leilao.get("etapa"):
        return f"{leilao['etapa']}º leilão"
    if leilao.get("modalidade") == "Licitação Aberta":
        return "Licitação"
    return "Encerramento da venda"


def html_cronometro(encerramento: datetime, rotulo: str, agora: datetime) -> str:
    """
    HTML do cronometro. Ja encerrado quando a tela e montada: so o texto fixo
    "Encerrado em (data)", sem script. Senao, o script conta e, ao chegar a zero,
    troca para "Encerrado em (data)".
    """
    data_txt = encerramento.strftime("%d/%m/%Y %H:%M")
    rotulo = html.escape(rotulo)
    if agora > encerramento:
        return f'<p style="{_ESTILO}">⏱️ Encerrado em {data_txt}</p>'
    alvo = encerramento.strftime("%Y-%m-%dT%H:%M:%S") + FUSO_BRASILIA
    return f"""<p id="cronometro" style="{_ESTILO}">⏱️ {rotulo}: {data_txt}</p>
<script>
(function () {{
  var fim = new Date("{alvo}").getTime();
  var el = document.getElementById("cronometro");
  function dois(n) {{ return (n < 10 ? "0" : "") + n; }}
  function atualizar() {{
    var falta = Math.floor((fim - Date.now()) / 1000);
    if (falta <= 0) {{
      el.textContent = "⏱️ Encerrado em {data_txt}";
      clearInterval(timer);
      return;
    }}
    var d = Math.floor(falta / 86400), h = Math.floor(falta % 86400 / 3600);
    var m = Math.floor(falta % 3600 / 60), s = falta % 60;
    el.textContent = "⏱️ {rotulo} em {data_txt} — faltam " + d + (d === 1 ? " dia " : " dias ")
      + dois(h) + " h " + dois(m) + " min " + dois(s) + " s";
  }}
  var timer = setInterval(atualizar, 1000);
  atualizar();
}})();
</script>"""


def mostrar_cronometro(leilao: dict, agora: datetime | None = None) -> None:
    """Cronometro no cartao do leilao. Sem data (ex.: Compra Direta), nada aparece."""
    encerramento = leilao.get("encerramento")
    if not isinstance(encerramento, datetime):
        return
    import streamlit.components.v1 as components
    from services.leilao import agora_brasilia
    components.html(html_cronometro(encerramento, rotulo_prazo(leilao), agora or agora_brasilia()), height=ALTURA_PX)
