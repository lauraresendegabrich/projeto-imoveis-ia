# Sistema Multiagente de Precificação Imobiliária

Estima o valor de mercado e o valor de liquidez de um imóvel a partir de anúncios
parecidos da região, usando 5 agentes em sequência. Para imóveis em leilão da CAIXA,
também calcula o retorno (ROI) de arrematar e até quanto vale a pena dar de lance.

**App publicado:** https://projeto-imoveis-ia-sd5kashfzhslavnmflkcyq.streamlit.app/

## Como rodar

### Pré-requisitos

- Python 3.11+
- Windows (testado no Windows 11)

### Instalação

```bash
git clone https://github.com/lauraresendegabrich/projeto-imoveis-ia.git
cd projeto-imoveis-ia
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

### Arquivo `.env`

Fica na raiz e **nunca vai para o GitHub**. Peça o arquivo para quem já trabalha no projeto,
ou copie o `.env.example` e preencha.

| Chave | Para quê |
|---|---|
| `DATABASE_URL` | Banco Postgres no Neon: grava e lê as avaliações (ver `docs/BANCO.md`) |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` | Base de anúncios na Amazon Athena (fonte principal do Agente 1) |
| `APIFY_TOKEN_2` | Coleta reserva no VivaReal/LugarCerto. **Créditos esgotados (403).** |
| `GROQ_API_KEY`, `GROQ_API_KEY_2` | IA dos Agentes 2, 3 e 4 (Groq) |
| `GOOGLE_API_KEY`, `GOOGLE_API_KEY_2` | IA dos Agentes 2, 3 e 4 (Gemini) |
| `GOOGLE_MAPS_KEY` | Geocodificação, imagem de satélite e Google Places |
| `TOMTOM_API_KEY` | Geocodificação |
| `GEOAPIFY_API_KEY` | Pontos de interesse do entorno (Agente 4) |
| `NVIDIA_API_KEY` | IA de reserva dos Agentes 2, 3 e 4 (nemotron) |
| `ZAI_API_KEY` | Z.AI (GLM), última reserva de texto (Agentes 2 e 4) |
| `QWEN_API_URL`, `QWEN_API_KEY` | Qwen no Colab. **Desligado** (linhas comentadas; ver `docs/MODELOS_LLM.md`) |
| `*_MODELO_*` | Nomes dos modelos de IA (opcional; ver `.env.example` e `docs/MODELOS_LLM.md`) |
| `ORDEM_*`, `FOTOS_*` | Ordem das IAs em cada tarefa e fotos por chamada no Agente 3 (opcional; ver `docs/MODELOS_LLM.md`) |

No Streamlit Cloud, as mesmas chaves ficam em Settings → Secrets.

### Interface web

```bash
.venv\Scripts\streamlit.exe run app/interface.py
```

Abra http://localhost:8501. O menu tem duas páginas:

- **Avaliação de imóvel:** formulário do imóvel (rua, número, bairro, cidade, tipo, áreas,
  quartos, banheiros, vagas, descrição, fotos). Para um imóvel da CAIXA, cole o texto da
  página do imóvel no site da CAIXA (ou o .html salvo), e os campos são preenchidos. Uma
  avaliação leva de 4 a 10 minutos.
- **Leilões ativos:** um card por imóvel de leilão já avaliado, com a decisão, o ROI, o
  cronômetro, a avaliação completa e a **calculadora de simulação** no menu lateral.

### Terminal

Avalia um imóvel sem abrir o site, com **o mesmo fluxo da tela** (`services/pipeline.py`).
Os campos ficam no topo de `app/main.py`.

```bash
.venv\Scripts\python.exe -m app.main            # não grava no banco
.venv\Scripts\python.exe -m app.main --gravar   # grava, como a tela
```

### Testes

Cada arquivo de teste roda sozinho e imprime OK/FALHA e o total. Não usamos pytest.

```bash
.venv\Scripts\python.exe -m tests.test_leilao
.venv\Scripts\python.exe -m tests.test_calculadora
```

Rode os testes da área que você mudou antes de fazer o commit.

---

## Pipeline (5 agentes)

```
Entrada → Agente 1 (Coleta) → Agente 2 (Comparáveis e zona) → Agentes 3 + 4 (juntos)
        → Agente 5 (Preço e liquidez) → ROI e decisão do leilão → banco Neon e telas
```

| Agente | Função | Fontes |
|--------|--------|--------|
| 1 - Coletor | Busca anúncios da rua, do bairro ou da cidade; tira leilões e repetidos | Amazon Athena (principal), Apify (reserva) |
| 2 - Comparáveis | Filtra e classifica os parecidos; zona homogênea no mapa | IA (Groq, Gemini, NVIDIA, Z.AI), Google/TomTom/Nominatim, imagem de satélite |
| 3 - Analisador | Estado e padrão pelas fotos e pela descrição | IA (Gemini, Groq, NVIDIA) |
| 4 - Infraestrutura | Pontos de interesse do entorno | Geoapify, Google Places, IA (Gemini, Groq, NVIDIA, Z.AI) |
| 5 - Preço/Liquidez | Valor de mercado (planilha do professor) e liquidez (90%) | Cálculo local |

**Leilão CAIXA:** a venda é o valor de liquidez. Custos antes da venda de 33% da
arrematação, corretagem de 5% e IR de 15% sobre o lucro.

| ROI pagando o mínimo | Decisão |
|---|---|
| 30% ou mais | Oportunidade |
| 15% a 30% | Margem apertada |
| menos de 15% | Descartar |
| estimativa não confiável (por exemplo, menos de 5 comparáveis) | Sem estimativa |

Detalhes em `docs/LEILAO_DOCUMENTACAO.md`.

---

## Estrutura do projeto

```
projeto-imoveis-ia/
├── app/
│   ├── interface.py          # Entrada do Streamlit (menu das páginas)
│   ├── paginas/
│   │   ├── avaliacao.py      # Página "Avaliação de imóvel"
│   │   └── leiloes_ativos.py # Página "Leilões ativos"
│   ├── calculadora.py        # Calculadora de simulação (menu lateral)
│   ├── resultado_tela.py     # Tela do resultado
│   ├── cronometro.py         # Contagem regressiva do leilão
│   ├── graph.py              # Terminal: chama o fluxo de services/pipeline.py
│   └── main.py               # Avaliação pelo terminal (mesmo fluxo da tela)
├── agents/
│   ├── collector.py          # Agente 1
│   ├── identidade.py         # Agente 1: mesmo imóvel em vários anúncios
│   ├── comparables.py        # Agente 2
│   ├── text_analyzer.py      # Agente 3
│   ├── infra_evaluator.py    # Agente 4
│   └── price_liquidity.py    # Agente 5
├── services/
│   ├── pipeline.py           # O fluxo da avaliação (tela e terminal)
│   ├── ia.py                 # Modelos de IA e chamada aos provedores
│   ├── leilao.py             # Conta do ROI, decisão e etapas do leilão
│   ├── caixa_pagina.py       # Leitura da página da CAIXA
│   ├── leiloes_ativos.py     # Lista de leilões do banco
│   ├── detalhe_leilao.py     # Avaliação completa gravada
│   ├── banco.py              # Gravação no Neon
│   └── alertas.py            # Alertas do resultado
├── db/                       # schema.sql e migrações
├── docs/                     # Documentação (abaixo)
└── tests/
```

## Documentação

| Arquivo | Assunto |
|---|---|
| `docs/AGENT1_...` a `docs/AGENT5_...` | Cada agente, com as regras e os casos que as motivaram |
| `docs/ORQUESTRADOR_DOCUMENTACAO.md` | Como os agentes são chamados |
| `docs/LEILAO_DOCUMENTACAO.md` | ROI, decisão, modalidades, leitura da CAIXA, telas e calculadora |
| `docs/BANCO.md` | Tabelas, views e alertas do banco Neon |
| `docs/HOSPEDAGEM.md` | Streamlit Cloud |
| `docs/PENDENCIAS.md` | O que está em aberto, incluindo as perguntas para o professor |
| `docs/DOCUMENTACAO_METRICAS_AVALIACAO.md` | Métricas da avaliação acadêmica |

---

## Resultados da avaliação (jun–ago/2026)

### Liquidez (15 imóveis, 11 válidos)

| Métrica | Resultado |
|---------|-----------|
| Erro médio (MAE) | 18.5% |
| % dentro de ±20% | 62.5% |
| Correlação DoM×Sobrepreço | 0.33 (positiva) |
| Coerência preço-liquidez | 72.7% (8/11) |

### Filtragem (11 imóveis, ~570 candidatos, 3 avaliadores)

| Métrica | Resultado |
|---------|-----------|
| Precisão média | 52.2% |
| Revocação média | 67.9% |
| F1-score médio | 58.8% |
| Acurácia média | 77.3% |
| Concordância humana | 85% |

Para refazer: `tests/avaliacao_liquidez.py` e `tests/calcular_filtragem_final.py`
(resultados em `data/avaliacao/`).

---

## Observações

1. **APIs externas:** o sistema depende delas. As chaves do `.env` têm limite mensal.
2. **Cidades pequenas** podem não ter anúncios suficientes. Nesses casos, a resposta é
   "Sem estimativa".
3. **Reprodutibilidade:** os resultados podem variar um pouco entre execuções, porque os
   anúncios mudam e a IA tem aleatoriedade.
4. **Método:** as regras de cálculo seguem a planilha do professor. Mudanças de método
   são combinadas com ele antes (ver `docs/PENDENCIAS.md`).
