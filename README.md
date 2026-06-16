# Sistema Multiagente de Precificação Imobiliária

Sistema que estima o valor de mercado e liquidez de imóveis usando 5 agentes inteligentes em pipeline.

## Como Rodar

### Pré-requisitos

- Python 3.11+
- Windows (testado no Windows 11)

### Instalação

```bash
# Clone o repositório
git clone https://github.com/lauraresendegabrich/projeto-imoveis-ia.git
cd projeto-imoveis-ia

# Crie o ambiente virtual
python -m venv .venv

# Ative o ambiente
.venv\Scripts\activate

# Instale as dependências
pip install -r requirements.txt
pip install streamlit
```

### Configuração do .env

Crie um arquivo `.env` na raiz com as seguintes chaves:

```env
# Obrigatório — Apify (coleta de imóveis)
APIFY_TOKEN_2=seu_token_aqui

# Obrigatório — Groq (LLM para classificação)
GROQ_API_KEY=seu_token_aqui

# Obrigatório — NVIDIA (análise de fotos)
NVIDIA_API_KEY=seu_token_aqui

# Opcional — Google Maps (zona homogênea com imagem de satélite)
GOOGLE_MAPS_KEY=seu_token_aqui
```

**Onde obter:**
- Apify: https://console.apify.com/account/integrations (plano free: $5/mês)
- Groq: https://console.groq.com (grátis, 14.400 req/dia)
- NVIDIA: https://build.nvidia.com (grátis com limite)
- Google Maps: https://console.cloud.google.com

---

## Opção 1: Interface Web (recomendado para testar)

```bash
.venv\Scripts\streamlit.exe run app/interface.py
```

Acesse http://localhost:8501 no navegador.

**Preencha os campos:**
- Rua, Número, Bairro, Cidade, Estado
- Tipo (Casa, Apartamento ou Terreno)
- Área construída, Área do terreno
- Quartos, Banheiros, Vagas
- Descrição (opcional)
- URLs de fotos (opcional, melhora análise qualitativa)

Clique em **Avaliar Imóvel** e aguarde ~5 minutos.

**Resultado exibido:**
- Valor médio estimado
- Valor de liquidez (-10%)
- Tempo estimado de venda
- Detalhes do cálculo (m²/terreno, m²/construção)
- Infraestrutura da região
- Comparáveis encontrados

---

## Opção 2: Pipeline via Terminal

```bash
.venv\Scripts\python.exe -m app.main
```

Edite o dicionário `IMOVEL_ALVO` em `app/main.py` com os dados do imóvel desejado.

---

## Opção 3: Rodar a Avaliação Completa

### Avaliação de Liquidez (15 imóveis)

```bash
.venv\Scripts\python.exe tests/avaliacao_liquidez.py
```

Resultado salvo em `data/avaliacao/resultado_avaliacao.json`

### Avaliação de Filtragem (Precisão/Revocação)

```bash
# Calcula métricas a partir das rotulagens já feitas
.venv\Scripts\python.exe tests/calcular_filtragem_final.py
```

Resultado salvo em `data/avaliacao/resultado_filtragem_final.json`

---

## Estrutura do Projeto

```
projeto-imoveis-ia/
├── app/
│   ├── interface.py          # Interface Streamlit
│   ├── graph.py              # Orquestrador do pipeline
│   └── main.py               # Execução via terminal
├── agents/
│   ├── collector.py          # Agente 1: Coleta (Apify)
│   ├── comparables.py        # Agente 2: Comparáveis (LLM)
│   ├── text_analyzer.py      # Agente 3: Análise qualitativa (NVIDIA Vision)
│   ├── infra_evaluator.py    # Agente 4: Infraestrutura (OSM + LLM)
│   └── price_liquidity.py    # Agente 5: Preço e Liquidez
├── data/
│   └── avaliacao/            # Resultados das avaliações
├── docs/
│   ├── DOCUMENTACAO_PROJETO.md
│   └── DOCUMENTACAO_METRICAS_AVALIACAO.md
├── tests/
│   ├── avaliacao_liquidez.py
│   └── calcular_filtragem_final.py
├── .env                      # Chaves de API (não commitado)
└── requirements.txt
```

---

## Pipeline (5 Agentes)

```
Agente 1 (Coleta) → Agente 2 (Comparáveis) → Agentes 3+4 (paralelo) → Agente 5 (Preço)
```

| Agente | Função | API |
|--------|--------|-----|
| 1 - Coletor | Scraping de portais imobiliários | Apify |
| 2 - Comparáveis | Classificação de similaridade | Groq (Llama-3.3-70b) |
| 3 - Analisador | Avaliação qualitativa (fotos + texto) | NVIDIA Vision |
| 4 - Infraestrutura | POIs do entorno | OpenStreetMap + Groq |
| 5 - Preço/Liquidez | Cálculo final (TRIMMEAN) | Cálculo local |

---

## Resultados da Avaliação

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

---

## Tempo de Execução

- Interface (1 imóvel): ~5 minutos
- Avaliação completa (15 imóveis): ~80 minutos
- Custo por avaliação: ~$0.15-0.30 (Apify)

---

## Observações para os Orientadores

1. **APIs necessárias**: O sistema depende de APIs externas (Apify, Groq, NVIDIA). Sem elas, não funciona. Os tokens no `.env` têm limite mensal.

2. **Cobertura geográfica**: Funciona melhor em capitais e cidades grandes. Cidades pequenas podem não ter dados suficientes nos portais.

3. **Tempo**: Cada avaliação leva ~5 minutos (coleta via scraping é o gargalo).

4. **Reprodutibilidade**: Os resultados podem variar ligeiramente entre execuções (dados dos portais mudam, LLM tem aleatoriedade).

5. **Documentação detalhada**: Ver `docs/DOCUMENTACAO_METRICAS_AVALIACAO.md` para explicação completa das métricas e fórmulas.
