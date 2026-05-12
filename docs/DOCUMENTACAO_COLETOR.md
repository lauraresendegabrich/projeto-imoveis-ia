# Documentação do Agente Coletor de Dados Imobiliários

## Resumo

O coletor usa **1 fonte principal** (Apify ocrad) para encontrar imóveis comparáveis ao imóvel alvo, com **enriquecimento** (publishedAt, description, bathrooms, vagas, rua) via `requests.get` + regex.

Funciona para **qualquer bairro, cidade e estado do Brasil**.

---

## Arquitetura Final

```
┌─────────────────────────────────────────────────────────────────┐
│                    coletar_imoveis()                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  FONTE: Apify (ocrad/brazil-real-estate-scraper)                │
│  ┌─────────────────────────────────────────────┐                │
│  │ ImovelWeb                                    │                │
│  │ VivaReal                                     │                │
│  │ LugarCerto                                   │                │
│  │ OLX                                          │                │
│  │ MercadoLivre                                 │                │
│  │                                              │                │
│  │ Tipos: casas, terrenos, apartamentos,        │                │
│  │        comercial (conforme tipo_imovel)      │                │
│  └─────────────────────────────────────────────┘                │
│         │                                                       │
│         ▼                                                       │
│  _normalizar_ocrad()                                            │
│  (preco, quartos, area, rua, bairro, cidade, estado, iptu)      │
│         │                                                       │
│         ▼                                                       │
│  ENRIQUECIMENTO: _extrair_dados_pagina(url)                     │
│  ┌─────────────────────────────────────────────┐                │
│  │ requests.get(url) + regex (1 request/imovel) │                │
│  │                                              │                │
│  │ VivaReal (100%):                             │                │
│  │   → publishedAt (createdAt no JSON)          │                │
│  │   → description (descricao completa)         │                │
│  │   → bathrooms, parkingSpaces, suites         │                │
│  │   → street + streetNumber                    │                │
│  │                                              │                │
│  │ LugarCerto (parcial):                        │                │
│  │   → publishedAt (dt_insercao no JSON)        │                │
│  │   → description (meta description)           │                │
│  │                                              │                │
│  │ OLX: bloqueado por Cloudflare (sem dados)    │                │
│  └─────────────────────────────────────────────┘                │
│         │                                                       │
│         ▼                                                       │
│  Remove duplicatas (por URL)                                    │
│  Remove leilões (preços artificiais)                            │
│  Filtra por bairro (escopo)                                     │
│  Normaliza bairros (acentos, prefixos)                          │
│  Ordena por proximidade (rua → bairro → cidade)                 │
│         │                                                       │
│         ▼                                                       │
│  imoveis_coletados.json (todos)                                 │
│  imoveis_completos.json (só com publishedAt)                    │
└─────────────────────────────────────────────────────────────────┘
```

---

## Ferramentas Utilizadas

### Apify - ocrad/brazil-real-estate-scraper (gratuito, $5/mês por conta)
- **O que é**: Actor do Apify que raspa portais imobiliários brasileiros
- **Portais suportados**: VivaReal, ZAP, ImovelWeb, OLX, MercadoLivre, LugarCerto
- **Como funciona**: Recebe URLs de listagem, executa JavaScript, extrai anúncios
- **Limite**: $5/mês de créditos por conta (~$0.10 por run)
- **Token**: `APIFY_TOKEN_2` (conta separada)
- **Configuração**: `max_items_per_url: 30`, sem proxy (free tier não suporta)

### requests.get (Python, grátis, sem limite)
- **Função**: Enriquecer imóveis com dados da página individual
- **Extrai**: publishedAt, description, bathrooms, parkingSpaces, street
- **Como**: Acessa a URL do anúncio e extrai dados do HTML estático com regex
- **Taxa de sucesso**: 100% VivaReal, parcial LugarCerto, 0% OLX (Cloudflare)
- **Custo**: Zero (sem API, sem limite)

---

## Portais que Funcionam vs Não Funcionam

| Portal | Coleta (ocrad) | Enriquecimento (requests.get) | Observação |
|--------|:-:|:-:|------------|
| **VivaReal** | ✅ | ✅ publishedAt + description + campos | Principal fonte (~45 resultados) |
| **OLX** | ✅ | ❌ Cloudflare | ~34 resultados, sem publishedAt/description |
| **LugarCerto** | ✅ | ✅ publishedAt + description | Poucos resultados em cidades menores |
| **ImovelWeb** | ❌ | — | URL funciona no navegador mas ocrad não extrai |
| **MercadoLivre** | ❌ | — | Mesmo problema do ImovelWeb |
| **ZAP Imóveis** | ❌ REMOVIDO | — | 95% duplicata do VivaReal (mesmo grupo) |

---

## Enriquecimento — Como Funciona

O ocrad retorna dados básicos (título, preço, localização, features). Para completar o JSON, acessamos a **página individual** de cada anúncio com `requests.get` e extraímos dados adicionais:

### VivaReal (100% sucesso)
```
requests.get(url) → HTML estático (247KB)
  → "createdAt":"2026-04-08T00:01:45.354Z"     → publishedAt
  → "description":"MOBILIADA, PRONTA PARA..."   → description
  → "bathrooms":4                               → bathrooms
  → "parkingSpaces":2                           → parkingSpaces
  → "street":"Rua Franklin Máximo Pereira"      → street
  → "streetNumber":"188"                        → street (complemento)
```

### LugarCerto (parcial)
```
requests.get(url) → HTML estático (228KB)
  → "dt_insercao":"2023-07-01T23:59:00Z"       → publishedAt
  → <meta name="description" content="...">    → description (resumo)
```

### OLX (bloqueado)
- `requests.get` retorna 403 (Cloudflare)
- Dados do título são extraídos como fallback (bathrooms, vagas)
- publishedAt e description ficam null

---

## publishedAt — Detalhes

### Por que a OLX fica sem data
- OLX bloqueia `requests.get` com Cloudflare (retorna 403)
- A data aparece na **listagem** como "16/12/2024, 23:52" (com ano) — mas o ocrad não extrai esse campo
- Na **página individual** mostra "16/12 às 23:52" (sem ano)
- Testamos Bright Data MCP (contorna Cloudflare) — funcionou, mas a data sem ano é imprecisa. Removido.

### Por que a LLM não extrai publishedAt
Testamos usar LLM (Groq, Ollama local) para acessar URLs e extrair datas. **Não funciona** porque:
1. **LLMs não acessam a internet** — são processadores de texto puro
2. Quando o ChatGPT "acessa" uma URL, é uma ferramenta de browsing externa que faz o request, não o modelo
3. Via API (nosso caso), não existe ferramenta de browsing acoplada
4. Testado: Groq responde "I'm not able to directly access the URL"

---

## Limitações Conhecidas

### 1. ImovelWeb e MercadoLivre não retornam resultados
- As URLs estão corretas (funcionam no navegador)
- O actor ocrad não consegue extrair dados desses portais
- Motivo desconhecido — pode ser bloqueio do actor ou formato não suportado

### 2. Apify Proxy NÃO funciona no free tier
- Testado: `useApifyProxy: true` retorna 0 resultados
- Sem proxy: funciona normalmente
- A documentação do ocrad recomenda proxy, mas é recurso pago

### 3. OLX não filtra por bairro na URL
- URL usa query string: `?q=casa+a+venda+centro+itajai+santa-catarina`
- Retorna resultados da região (não só do bairro)
- Filtro por bairro é aplicado depois, no código (escopo)

### 4. OLX sem publishedAt e description
- Cloudflare bloqueia `requests.get` (403)
- A data existe na listagem ("16/12/2024, 23:52") mas o ocrad não extrai
- **Impacto**: ~30-40% dos imóveis ficam sem data e descrição

### 5. ZAP = duplicata do VivaReal
- Mesmo grupo (OLX Brasil), mesma base de anúncios
- Testado: 25 de 26 anúncios tinham o mesmo ID
- Removido para não gastar créditos com duplicatas

---

## Configuração (.env)

```
# Apify (conta do ocrad, $5/mês grátis)
APIFY_TOKEN_2=seu_token_apify

# Opcional (fallback se APIFY_TOKEN_2 não existir)
APIFY_TOKEN=token_conta_alternativa

# Não usados atualmente pelo coletor
BRIGHTDATA_TOKEN=token_bright_data
GROQ_API_KEY=key_groq
GROQ_API_KEY_2=key_groq_2
GOOGLE_API_KEY=key_gemini
SCRAPERAPI_KEY=key_scraperapi
```

---

## Arquivos Gerados

| Arquivo | Conteúdo |
|---|---|
| `data/imoveis_brutos_ocrad.json` | Brutos do ocrad (schema original do actor) |
| `data/imoveis_coletados.json` | Resultado final normalizado e filtrado (todos) |
| `data/imoveis_completos.json` | Só imóveis com publishedAt (dados completos pra análise) |

---

## Como Rodar

```bash
.venv/Scripts/python.exe -m tests.test_coleta
```

Alterar o imóvel alvo em `tests/test_coleta.py`:
```python
IMOVEL_ALVO = {
    "rua": "Rua Franklin Maximo Pereira",
    "bairro": "Centro",
    "cidade": "Itajai",
    "estado": "SC",
    "localizacao": "Itajai, SC",
    "tipo": "house",  # "house" ou "apartment"
}
```

---

## Dependências

```
pip install requests python-dotenv
```

---

## Histórico de Decisões

1. **Começamos com Bright Data MCP + Apify viralanalyzer** — viralanalyzer retornava só 10 resultados no free tier, descartado
2. **Adicionamos ocrad** — raspa listagens com JS, muito mais resultados (~100+)
3. **Removemos ZAP do ocrad** — 95% duplicata do VivaReal (mesmo grupo OLX Brasil)
4. **ImovelWeb e MercadoLivre**: URLs corretas mas ocrad não extrai — mantidos no código
5. **publishedAt via requests.get**: VivaReal coloca createdAt no HTML estático — grátis, 100% sucesso
6. **LugarCerto via requests.get**: não bloqueia, tem dt_insercao (publishedAt) e meta description
7. **Bright Data MCP para OLX publishedAt**: testado e funcionou, mas removido — a data na página individual não tem ano ("DD/MM às HH:MM"), não justifica gastar requests
8. **Apify Proxy testado e descartado**: free tier retorna 0 resultados com proxy ativo
9. **Playwright local testado**: Cloudflare bloqueia — descartado
10. **ScraperAPI testado**: funciona mas é trial de 7 dias ($49/mês depois) — descartado
11. **Bright Data Browser API testada**: funciona mas é paga ($8/GB) — descartada
12. **LLM para acessar URLs**: testado com Groq e Ollama — confirmado que LLMs não acessam internet via API
13. **Extração de description**: VivaReal tem descrição completa no HTML, LugarCerto tem meta description — extraídos no mesmo request do publishedAt (custo zero)
14. **Extração de bathrooms/vagas do título**: fallback quando features não tem — regex no título do anúncio

---

## Schema de Saída (imoveis_coletados.json)

```json
{
  "id": "2877438284",
  "title": "Casa para comprar com 170 m², 3 quartos, 4 banheiros, 2 vagas em Centro, Itajaí",
  "description": "MOBILIADA, PRONTA PARA MORAR - Casa com 154m² privativos, 01 suíte...",
  "price": 1395000,
  "priceFormatted": "R$ 1.395.000",
  "condominiumFee": null,
  "iptu": 150,
  "transactionType": "sale",
  "propertyType": "Casas",
  "propertySubType": null,
  "area": 170,
  "bedrooms": 3,
  "bathrooms": 4,
  "parkingSpaces": 2,
  "amenities": null,
  "complexAmenities": null,
  "street": "Rua Franklin Máximo Pereira",
  "neighborhood": "Centro",
  "city": "Itajai",
  "state": "SC",
  "images": [],
  "imageCount": 0,
  "url": "https://www.vivareal.com.br/imovel/...",
  "publishedAt": "2026-03-26T17:43:38.524Z",
  "pricePerSqm": 8205.88,
  "source": "VivaReal",
  "scrapedAt": "2026-05-09T18:55:22.981875",
  "data_coleta": "2026-05-09T18:55:22.981929"
}
```
