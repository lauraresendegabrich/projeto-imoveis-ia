# Agente 1 — Coletor de Dados Imobiliários

## Objetivo

Coletar imóveis comparáveis ao imóvel alvo. Usa Amazon Athena como fonte principal e Apify como fallback. Normaliza campos, filtra leilões/duplicatas e ordena por proximidade.

---

## Fontes de Dados

| Fonte | Papel | Quando roda |
|-------|-------|-------------|
| **Amazon Athena** | Fonte principal — banco S3 com milhares de anúncios | Sempre (se AWS configurado) |
| **Apify (ocrad)** | Fallback — scraping em tempo real | Só se Athena retornar < 10 imóveis |

---

## Fluxo Completo (8 etapas)

```
ETAPA 1 — ATHENA (fonte principal)
ETAPA 2 — APIFY (fallback se Athena < 10)
ETAPA 3 — NORMALIZAÇÃO DE CAMPOS
ETAPA 4 — COMBINAÇÃO (athena + apify)
ETAPA 5 — FILTROS (leilão, campos, duplicatas)
ETAPA 6 — ESCOPO (mantém só rua/bairro)
ETAPA 7 — ENRIQUECIMENTO (fotos)
ETAPA 8 — ORDENAÇÃO (rua > bairro > cidade)
```

---

## ETAPA 1 — Amazon Athena

Queries SQL na tabela `vivareal` (S3/Parquet).

### Limites por tipo (rua + bairro somados)

**Para `house`:**

| Tipo SQL | Limite total |
|----------|-------------|
| casa | 200 |
| two_story_house | 50 |
| village_house | 50 |
| residential_allotment_land | 60 |
| allotment_land | 60 |

**Para `apartment`:**

| Tipo SQL | Limite total |
|----------|-------------|
| apartamento | 200 |
| flat | 50 |
| cobertura | 50 |

### Lógica de busca (para cada tipo)

Para cada tipo na lista acima, faz:

1. **Busca na RUA** (prioridade)
```sql
SELECT * FROM vivareal 
WHERE cidade='Campinas' AND bairro='Jardim Guanabara' 
  AND rua LIKE '%Conego Nery%' AND tipo='casa' 
  AND finalidade='venda' 
LIMIT 200
```

2. **Se rua < limite, complementa com BAIRRO**
```sql
-- restante = limite - qtd_rua
SELECT * FROM vivareal 
WHERE cidade='Campinas' AND bairro='Jardim Guanabara' 
  AND tipo='casa' AND finalidade='venda' 
LIMIT restante
```
Remove duplicatas que já vieram na rua.

3. **Se TODOS os tipos retornaram 0 → expande pra CIDADE**
```sql
SELECT * FROM vivareal 
WHERE cidade='Campinas' AND tipo='casa' AND finalidade='venda' 
LIMIT 200
```

### Quando o fallback cidade ativa

Só quando **nenhum tipo** encontrou nada (rua + bairro = 0 para TODOS). Exemplo: bairro digitado errado ou não existe no banco.

Se pelo menos 1 tipo trouxe resultados, o fallback cidade NÃO ativa.

### Normalização de acentos

As funções `buscar_rua` e `buscar_bairro` tentam múltiplas variações para lidar com diferenças de acentuação entre o input do usuário e o banco:

**buscar_bairro** (3 tentativas sequenciais):
1. Nome exato como informado → `bairro = 'Cambuí'`
2. Sem acento → `bairro = 'Cambui'`
3. LIKE com parte final (sem prefixos "Jardim", "Vila", "Parque") → `bairro LIKE '%Guanabara%'`

**buscar_rua** (3 tentativas sequenciais):
1. Nome completo → `rua LIKE '%Rua Doutor Liraucio Gomes%'`
2. Sem acento → `rua LIKE '%Rua Doutor Liraucio Gomes%'` (se diferente)
3. Só a parte final (última palavra, ≥4 chars) → `rua LIKE '%Gomes%'`

**Cobertura:**
- ✅ Input com acento + banco com acento → match direto
- ✅ Input com acento + banco sem acento → fallback sem acento
- ✅ Input sem acento + banco sem acento → match direto
- ✅ Rua com acento diferente → fallback parte final (ex: "Liraucio" → busca "Gomes")
- ⚠️ Bairro sem acento + banco com acento → pode falhar, expande pra cidade

**Limitação:** Athena/Presto não ignora acentos no LIKE. Se "Cambui" ≠ "Cambuí", a busca falha. Solução: a interface deve preservar acentos.

### Exemplo real (Jardim Eulina, Campinas — house)

```
casa:                        96 rua + 92 bairro = 188 (limite 200)
two_story_house:             0
village_house:               0
residential_allotment_land:  0 rua + 60 bairro = 60 (limite 60)
allotment_land:              0 rua + 8 bairro = 8 (limite 60)
Total: 177 (após dedup)
Ordenação: 48 na rua | 129 no bairro
```
### Exemplo real (Cambuí, Campinas — apartment)

```
apartamento: 25 rua + 169 bairro = 194 (limite 200)
flat:        0 rua + 1 bairro = 1 (limite 50)
cobertura:   0 rua + 10 bairro = 10 (limite 50)
Total: 199 (após dedup)
Ordenação: 23 na rua | 176 no bairro
```

---

## ETAPA 2 — Apify (fallback)

Só roda se o total do Athena ficou **< 10 imóveis**.

| Portal | URL | Max itens |
|--------|-----|-----------|
| VivaReal | `/venda/{estado}/{cidade}/bairros/{bairro}/{tipo}/` | 30 |
| LugarCerto | `/busca/compra-e-venda/{estado}/{cidade}/{bairro}/{tipo}` | 30 |

Usa o actor `ocrad/brazil-real-estate-scraper` no Apify:
- Envia URLs de listagem
- Actor abre com navegador headless, executa JavaScript
- Retorna anúncios

Depois acessa cada URL individual com `requests.get` para extrair:
- `publishedAt` (data publicação) do JSON embutido no HTML do VivaReal
- `description`, `bathrooms`, `parkingSpaces`

**Portais desativados:** OLX (Cloudflare), ImovelWeb (não retorna), MercadoLivre (não retorna), ZAP (95% duplicata do VivaReal).

---

## ETAPA 3 — Normalização de Campos

O Athena retorna strings. O código converte para tipos corretos:

| Campo Athena | Campo normalizado | Tipo |
|---|---|---|
| preco | price | float |
| area_construida | area | float |
| quartos | bedrooms | int |
| banheiros | bathrooms | int |
| vagas | parkingSpaces | int |
| bairro | neighborhood | str |
| cidade | city | str |
| estado | state | str |
| rua | street | str |
| data_publicacao | publishedAt | str |
| descricao | description | str |
| titulo | title | str |
| latitude / longitude | lat / lon | float |
| fotos_urls | images | list (split por `\|`) |
| tipo | propertyType | "Casas" / "Apartamentos" / "Terrenos" |

Templates das fotos resolvidos:
- `{description}` → "imovel"
- `{action}` → "fit-in"
- `{width}x{height}` → "870x653"

Os campos originais do Athena são **preservados** (strings). Os normalizados são **adicionados**. Ambos coexistem no JSON.

---

## ETAPA 4 — Combinação

```python
todos = athena_imoveis + apify_imoveis
```

Athena primeiro na lista.

---

## ETAPA 5 — Filtros

| Filtro | O que remove |
|--------|-------------|
| **Leilão** | Título contém: "leilão", "hasta publica", "judicial", "caixa economica", "lance inicial", etc. |
| **Campos obrigatórios** | Não tem `price` OU não tem `city`/`neighborhood` |
| **Duplicatas URL** | Mesma URL aparece mais de 1 vez → fica só 1 |

---

## ETAPA 6 — Escopo

Verifica cada imóvel:
- `street` contém o nome da rua do alvo? OU
- `neighborhood` contém o nome do bairro do alvo?

Se sim → mantém. Se nenhum → descarta.

Normaliza acentos antes de comparar.

Se NENHUM imóvel passar → fallback: usa todos (cidade toda).

---

## ETAPA 7 — Enriquecimento

Imóveis sem fotos: `requests.get` na URL do VivaReal para extrair imagens do HTML.

---

## ETAPA 8 — Ordenação Final

| Prioridade | Critério |
|---|---|
| 0 (primeiro) | Mesma rua no campo `street` |
| 1 | Mesmo bairro no campo `neighborhood` |
| 2 (último) | Restante |

---

## Arquivos de Saída

| Arquivo | Conteúdo | Usado por |
|---------|----------|-----------|
| `data/imoveis_coletados_ag1.json` | Todos os imóveis (filtrados + ordenados) | Agente 2 (fallback) |
| `data/imoveis_completos_ag1.json` | Só os que têm `publishedAt` | **Agente 2** (entrada principal) |
| `data/imoveis_brutos_ocrad_ag1.json` | Brutos do Apify (debug) | Ninguém |

**Diferença:** `completos` = tem data de publicação. `coletados` = todos.

---

## Schema de Saída (exemplo real)

```json
{
  "url": "https://www.vivareal.com.br/imovel/2752976859",
  "titulo": "Apartamento 2 quartos à venda, 78 m² - Jardim Guanabara - Campinas/SP",
  "descricao": "Apartamento moderno no Condomínio Vizzi...",
  "tipo": "apartamento",
  "finalidade": "venda",
  "preco": "989990.0",
  "preco_condominio": "800.0",
  "iptu": "280.0",
  "area_construida": "78.0",
  "area_terreno": "88.0",
  "quartos": "2",
  "suites": "1",
  "banheiros": "2",
  "vagas": "2",
  "rua": "Rua Cônego Nery",
  "bairro": "Jardim Guanabara",
  "cidade": "Campinas",
  "estado": "SP",
  "cep": "13073180",
  "latitude": "-22.886324",
  "longitude": "-47.060136",
  "fotos_urls": "https://...{description}.jpg?action={action}...|...",
  "image_count": "31",
  "data_publicacao": "2024-10-30T17:37:51.871Z",
  "data_ultima_atualizacao": "2026-08-09T03:30:54.467Z",
  "amenities": "POOL|GOURMET_BALCONY|AIR_CONDITIONING|...",
  "preco_por_m2": "12692.18",
  "usage_types": "RESIDENTIAL",
  "property_sub_type": "APARTMENT",
  "andar": "0",
  "status_anuncio": "ACTIVE",
  "anunciante_nome": "Mega Imob",
  "listing_id": "2752976859",
  "portal": "vivareal",
  "data_coleta": "2026-08-09T12:35:41.217234",

  "source": "Athena/S3",
  "price": 989990.0,
  "area": 78.0,
  "bedrooms": 2,
  "bathrooms": 2,
  "parkingSpaces": 2,
  "neighborhood": "Jardim Guanabara",
  "city": "Campinas",
  "state": "SP",
  "street": "Rua Cônego Nery",
  "publishedAt": "2024-10-30T17:37:51.871Z",
  "description": "Apartamento moderno no Condomínio Vizzi...",
  "title": "Apartamento 2 quartos à venda, 78 m² - Jardim Guanabara - Campinas/SP",
  "lat": -22.886324,
  "lon": -47.060136,
  "propertyType": "Apartamentos",
  "images": ["https://...870x653...jpg", "..."],
  "imageCount": 30
}
```

---

## Dependências

| Pacote/Serviço | Uso | Configuração |
|---|---|---|
| `boto3` | Consultas Athena | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` no `.env` |
| `requests` | Enriquecimento HTML + API Apify | Nenhuma |
| Apify (ocrad) | Scraping portais (fallback) | `APIFY_TOKEN_2` no `.env` |

---

## Como Rodar

```bash
# Pipeline completo
.venv/Scripts/python.exe -m app.main

# Teste isolado
.venv/Scripts/python.exe tests/test_ag1_isolado.py

# Teste casa + apartamento
.venv/Scripts/python.exe tests/test_ag1_casa_apto.py
```
