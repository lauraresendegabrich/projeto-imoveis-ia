# Agente 1 — Coletor de Dados Imobiliários

## Objetivo

Coletar imóveis comparáveis ao imóvel alvo a partir de portais imobiliários brasileiros, enriquecendo cada registro com data de publicação (`publishedAt`) e descrição completa do anúncio. O resultado alimenta o Agente 2 para identificação de comparáveis.

A coleta precisa ser **automatizada, escalável e gratuita** — sem depender de scraping manual ou APIs pagas por volume.

---

## Problema Central: Dados Estruturados em Portais Imobiliários

Portais como VivaReal, ZAP e OLX não oferecem APIs públicas. Os dados estão em páginas HTML renderizadas por JavaScript, o que impede scraping simples com `requests.get`. Além disso, cada portal tem estrutura diferente, mecanismos de proteção distintos (Cloudflare, rate limiting) e campos inconsistentes entre si.

O campo `publishedAt` (data de publicação do anúncio) é especialmente crítico para a avaliação imobiliária — imóveis publicados há mais de 6 meses com preço inalterado indicam sobrepreço. Esse campo não é retornado pela maioria dos scrapers e exigiu solução específica.

---

## Abordagem Final

### Fonte principal: Apify (actor `ocrad/brazil-real-estate-scraper`)

O Apify é uma plataforma de web scraping que executa "actors" — scripts de scraping em nuvem. O actor `ocrad/brazil-real-estate-scraper` foi desenvolvido especificamente para portais imobiliários brasileiros: recebe URLs de listagem, executa JavaScript no navegador headless e extrai os anúncios.

**Por que Apify e não scraping local?**
- Portais imobiliários detectam e bloqueiam scrapers locais (Cloudflare, fingerprinting de browser)
- O Apify roda em infraestrutura com IPs rotativos e browsers reais
- O free tier ($5/mês de crédito) é suficiente para o volume do projeto (~$0.10 por run)

### Enriquecimento: `requests.get` + regex

O actor retorna dados básicos (título, preço, localização, features). Para obter `publishedAt` e `description`, acessamos a **página individual** de cada anúncio com `requests.get` simples — sem JavaScript, sem Apify. O VivaReal embute um JSON no HTML estático da página com todos os dados estruturados, incluindo `createdAt`.

**Por que não usar o Apify para isso também?**
- Custo: cada request no Apify consome créditos. Com 100 imóveis, seriam 100 requests extras (~$0.10 adicionais)
- `requests.get` é gratuito, ilimitado e suficiente para HTML estático
- O VivaReal não bloqueia `requests.get` simples (sem JavaScript necessário)

---

## Fluxo Completo

```
1. Monta URLs de listagem por portal e tipo de imóvel
   → VivaReal: /venda/{estado}/{cidade}/bairros/{bairro}/{tipo}/
   → LugarCerto: /busca/compra-e-venda/{estado}/{cidade}/{bairro}/{tipo}
   → Limites: 20 itens/URL (casa), 10 itens/URL (terreno), 30 itens/URL (apto)

2. Envia URLs para o actor Apify (ocrad/brazil-real-estate-scraper)
   → Actor abre cada URL no browser headless, executa JavaScript
   → Extrai anúncios: título, preço, localização, features, URL
   → Aguarda conclusão via polling (status RUNNING → SUCCEEDED)
   → Salva brutos em data/imoveis_brutos_ocrad.json

3. Normaliza o schema do ocrad para o schema padrão do projeto
   → Extrai preço (regex em string "R$ 530.000Cond. não informado...")
   → Extrai área, quartos, banheiros, vagas (features → URL → título)
   → Extrai localização (location → from_url)
   → Extrai IPTU e condomínio do campo price_raw
   → Identifica portal de origem (VivaReal, LugarCerto, etc.)

4. Enriquece cada imóvel com requests.get na página individual
   → VivaReal (100%): extrai createdAt, description, bathrooms,
     parkingSpaces, street, streetNumber do JSON embutido no HTML
   → LugarCerto (parcial): extrai dt_insercao e meta description
   → OLX: bloqueado por Cloudflare (403) — sem enriquecimento
   → Pausa de 1s entre requests para não sobrecarregar os servidores

5. Aplica filtros de qualidade
   → Remove duplicatas por URL
   → Remove leilões (palavras-chave: "leilão", "hasta pública", "judicial"...)
   → Remove imóveis sem preço ou sem localização mínima
   → Filtra por bairro alvo (escopo geográfico)
   → Normaliza nomes de bairros (acentos, prefixos "Bairro X" → "X")

6. Ordena por proximidade ao imóvel alvo
   → Mesma rua primeiro
   → Mesmo bairro depois
   → Restante da cidade por último

7. Salva resultados
   → data/imoveis_coletados.json  — todos os imóveis normalizados
   → data/imoveis_completos.json  — apenas imóveis com publishedAt
```

---

## Ferramentas Testadas e Descartadas

### 1. Apify viralanalyzer
**O que é:** Actor do Apify para portais imobiliários, alternativa ao ocrad.
**Resultado:** Retornava apenas 10 resultados no free tier — insuficiente para análise estatística de comparáveis.
**Decisão:** Descartado. Substituído pelo ocrad que retorna 20–30 por URL.

### 2. ZAP Imóveis via ocrad
**O que é:** Portal imobiliário do grupo OLX Brasil, mesmo grupo do VivaReal.
**Resultado:** Testado com 26 anúncios — 25 tinham o mesmo `posting_id` do VivaReal. 95% de duplicatas.
**Decisão:** Removido do código. Gastar créditos do Apify para coletar duplicatas não faz sentido.

### 3. Bright Data MCP para OLX
**O que é:** Serviço de proxy residencial que contorna Cloudflare. Testado para obter `publishedAt` da OLX.
**Resultado:** Funcionou tecnicamente — conseguiu acessar as páginas da OLX. Porém, a data na página individual aparece como "16/12 às 23:52" (sem ano), tornando o dado impreciso para análise temporal.
**Decisão:** Descartado. Dado impreciso não justifica o custo ($8/GB).

### 4. Playwright local
**O que é:** Biblioteca Python para automação de browser headless (Chromium).
**Resultado:** Cloudflare detecta e bloqueia Playwright mesmo com configurações de evasão (user-agent, viewport, etc.).
**Decisão:** Descartado.

### 5. ScraperAPI
**O que é:** Serviço de proxy + rendering que contorna bloqueios.
**Resultado:** Funcionou no trial de 7 dias. Porém, o plano pago custa $49/mês — inviável para o projeto.
**Decisão:** Descartado.

### 6. Bright Data Browser API
**O que é:** API de browser headless gerenciado pela Bright Data.
**Resultado:** Funcionou. Custo: $8/GB de dados trafegados.
**Decisão:** Descartada. Custo variável e imprevisível para um projeto acadêmico.

### 7. LLM para acessar URLs e extrair dados
**O que é:** Tentativa de usar Groq (llama-3.1-8b) e Ollama local para acessar URLs e extrair `publishedAt`.
**Resultado:** LLMs não acessam a internet via API. São processadores de texto puro — recebem texto e geram texto. Quando o ChatGPT "acessa" uma URL, é uma ferramenta de browsing externa acoplada ao modelo, não o modelo em si. Via API (nosso caso), essa ferramenta não existe. Testado: Groq responde "I'm not able to directly access the URL".
**Decisão:** Descartado. Confirmou-se empiricamente o que a teoria já indicava.

### 8. Apify Proxy (free tier)
**O que é:** Recurso do Apify para rotacionar IPs durante a coleta.
**Resultado:** Com `useApifyProxy: true`, o actor retornou 0 resultados. Sem proxy: funciona normalmente.
**Decisão:** Descartado. A documentação do ocrad recomenda proxy para melhores resultados, mas é recurso pago e desnecessário para o volume atual.

---

## Portais: Resultado de Cada Um

| Portal | Coleta (ocrad) | publishedAt | Motivo |
|---|:-:|:-:|---|
| VivaReal | ✅ ~20–30/URL | ✅ 100% | `createdAt` no HTML estático |
| LugarCerto | ✅ 1–5/URL | ✅ parcial | `dt_insercao` no HTML, poucos resultados |
| OLX | ❌ comentado | ❌ | Cloudflare bloqueia `requests.get` — sem publishedAt |
| ImovelWeb | ❌ comentado | — | Actor não extrai resultados (motivo desconhecido) |
| MercadoLivre | ❌ comentado | — | Mesmo problema do ImovelWeb |
| ZAP Imóveis | ❌ removido | — | 95% duplicata do VivaReal |

### Por que OLX foi comentado e não removido
A OLX retorna resultados via ocrad (~30/URL), mas sem `publishedAt` e sem `description` (Cloudflare bloqueia o enriquecimento). Para o Agente 2, imóveis sem data de publicação são menos confiáveis para análise temporal. A decisão foi comentar a URL para não gastar créditos do Apify com dados incompletos, mas manter o código para reativação futura caso o problema de enriquecimento seja resolvido.

---

## Enriquecimento via `requests.get`

### Como o VivaReal expõe os dados
O VivaReal renderiza a página com JavaScript, mas embute um objeto JSON no HTML estático (dentro de uma tag `<script>`) com todos os dados estruturados do anúncio. Esse JSON inclui `createdAt`, `description`, `bathrooms`, `parkingSpaces`, `street` e `streetNumber`. Um `requests.get` simples (sem JavaScript) já retorna esse HTML com o JSON embutido.

```
requests.get(url_vivareal) → HTML estático (247KB)
  → regex: "createdAt":"2026-04-08T00:01:45.354Z"  → publishedAt
  → regex: "description":"MOBILIADA..."             → description
  → regex: "bathrooms":4                            → bathrooms
  → regex: "parkingSpaces":2                        → parkingSpaces
  → regex: "street":"Rua Franklin Máximo Pereira"   → street
```

Taxa de sucesso: **100%** nos testes realizados.

### LugarCerto
Não bloqueia `requests.get`. Expõe `dt_insercao` (data de inserção) no HTML e `description` via meta tag. Taxa de sucesso parcial — a meta description é um resumo, não a descrição completa.

### OLX
Retorna HTTP 403 (Cloudflare) para qualquer `requests.get`. A data existe na listagem ("16/12/2024, 23:52") mas o actor ocrad não extrai esse campo. Na página individual, a data aparece sem ano ("16/12 às 23:52"), tornando-a imprecisa.

---

## Limites de Coleta por Tipo de URL

Definidos em `_montar_urls_listagem()` e enviados individualmente no payload do Apify:

| Tipo de imóvel | Limite por URL | Justificativa |
|---|---|---|
| Casa | 20 | Volume adequado para análise sem exceder créditos |
| Terreno | 10 | Terrenos não passam pelo clustering — volume menor é suficiente |
| Apartamento | 30 | Maior variação de preço/m² exige mais amostras |

Antes dessa mudança, o limite era fixo em 30 para todas as URLs (`max_items_per_url: 30`). A diferenciação por tipo reduz o consumo de créditos do Apify e evita coletar terrenos em excesso (que não serão ranqueados pelo Agente 2).

---

## Filtros Aplicados Após Coleta

1. **Remoção de duplicatas por URL** — mais confiável que hash de campos, pois o mesmo imóvel pode ter área/preço ligeiramente diferente entre portais
2. **Remoção de leilões** — palavras-chave no título: "leilão", "hasta pública", "judicial", "lance inicial", etc. Leilões têm preços artificialmente baixos que distorceriam a estimativa de valor justo
3. **Filtro por campos obrigatórios** — descarta imóveis sem preço ou sem localização mínima
4. **Filtro por bairro (escopo)** — mantém apenas imóveis do bairro alvo para garantir comparabilidade geográfica
5. **Normalização de bairros** — remove acentos e prefixos ("Bairro Centro" → "Centro") para comparação consistente
6. **Ordenação por proximidade** — mesma rua primeiro, depois mesmo bairro, depois cidade

---

## Arquivos Gerados

| Arquivo | Conteúdo | Usado por |
|---|---|---|
| `data/imoveis_brutos_ocrad.json` | Schema original do actor, sem normalização | Debug |
| `data/imoveis_coletados.json` | Normalizados, filtrados, todos os imóveis | Referência |
| `data/imoveis_completos.json` | Apenas imóveis com `publishedAt` | Agente 2 |

A separação entre `imoveis_coletados.json` e `imoveis_completos.json` permite ao Agente 2 trabalhar com o subconjunto de dados mais completo, sem descartar imóveis que podem ser úteis para análise exploratória.

---

## Schema de Saída

```json
{
  "id": "2877438284",
  "title": "Casa para comprar com 170 m², 3 quartos, 4 banheiros, 2 vagas em Centro, Itajaí",
  "description": "MOBILIADA, PRONTA PARA MORAR - Casa com 154m² privativos...",
  "price": 1395000,
  "priceFormatted": "R$ 1.395.000",
  "condominiumFee": null,
  "iptu": 150,
  "transactionType": "sale",
  "propertyType": "Casas",
  "area": 170,
  "bedrooms": 3,
  "bathrooms": 4,
  "parkingSpaces": 2,
  "street": "Rua Franklin Máximo Pereira",
  "neighborhood": "Centro",
  "city": "Itajai",
  "state": "SC",
  "url": "https://www.vivareal.com.br/imovel/...",
  "publishedAt": "2026-03-26T17:43:38.524Z",
  "pricePerSqm": 8205.88,
  "source": "VivaReal",
  "scrapedAt": "2026-05-12T19:24:05.392865"
}
```

---

## Resultado dos Testes (Centro de Itajaí/SC)

```
URLs enviadas ao actor:
  [20 itens] VivaReal — casas
  [10 itens] VivaReal — terrenos
  [20 itens] LugarCerto — casas
  [10 itens] LugarCerto — terrenos

Brutos coletados:  102
Após filtros:       99
Após escopo:        95

Portais:  VivaReal: 95  (LugarCerto retornou 0 nesta execução)
Tipos:    Casas: 77 | Terrenos: 18
Com rua:  62/95
Com data: 95/95  ← 100% publishedAt
Tempo:    ~4.7 minutos
```

---

## Dependências Externas

| Serviço | Uso | Custo | Configuração |
|---|---|---|---|
| Apify | Coleta via actor ocrad | $5/mês grátis (~$0.10/run) | `APIFY_TOKEN_2` no `.env` |
| requests (Python) | Enriquecimento HTML | Gratuito, sem limite | Sem configuração |

---

## Como Rodar

```bash
.venv/Scripts/python.exe -m tests.test_coleta
```

Configurar o imóvel alvo em `tests/test_coleta.py`:
```python
IMOVEL_ALVO = {
    "rua":         "Rua Franklin Maximo Pereira",
    "bairro":      "Centro",
    "cidade":      "Itajai",
    "estado":      "SC",
    "localizacao": "Itajai, SC",
    "tipo":        "house",   # "house" ou "apartment"
}
```

---

## Entrada

### Parâmetros da função `coletar_imoveis()`

| Parâmetro | Tipo | Descrição |
|---|---|---|
| `localizacao` | str | Cidade e estado no formato "Cidade, UF" (ex: "Itajai, SC") |
| `tipo_imovel` | str | `"house"` (casas + terrenos) ou `"apartment"` (apartamentos) |
| `bairro` | str | Bairro do imóvel alvo — usado para montar URLs e filtrar resultados |
| `rua` | str | Rua do imóvel alvo — usada para ordenação por proximidade |

---

## Instalação das Dependências

```bash
# Dependências do requirements.txt (já instaladas no setup inicial)
.venv/Scripts/pip install -r requirements.txt

# Pacotes adicionais necessários para o Agente 1
.venv/Scripts/pip install apify-client
```

Pacotes utilizados pelo Agente 1:
| Pacote | Uso |
|---|---|
| `requests` | Coleta via Apify REST API + enriquecimento HTML |
| `apify-client` | Cliente oficial do Apify (alternativo à REST API) |
| `python-dotenv` | Leitura do `.env` (APIFY_TOKEN_2) |
