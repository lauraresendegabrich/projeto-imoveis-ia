# Agente 3 — Analisador Qualitativo de Descrição e Imagens

## Objetivo

Analisar a descrição e as fotos dos imóveis comparáveis usando LLM multimodal, extraindo características qualitativas como estado de conservação e diferenciais, e convertendo em um score qualitativo e fator de impacto no valor do imóvel.

---

## Arquitetura Final

```
Título + Descrição + 8 fotos espaçadas → LLM Vision (uma chamada) → Python (valida + calcula) → JSON
```

O LLM analisa texto e imagens juntos em uma única chamada. O Python valida, normaliza e calcula o score.

---

## Modelo

| Parâmetro | Valor |
|---|---|
| Provider | NVIDIA NIM |
| Modelo | `mistralai/ministral-14b-instruct-2512` |
| Tipo | Multimodal (texto + imagem) |
| Limite de imagens | 8 por prompt |
| Custo | Gratuito, sem limite diário |
| Velocidade | ~11s por imóvel |
| Base URL | `https://integrate.api.nvidia.com/v1` |
| Configuração | `NVIDIA_API_KEY` no `.env` |

---

## Histórico de Decisões

### 1. Groq Vision (Llama 4 Scout 17B) — descartado
**Resultado:** funcionou bem com 3 fotos por imóvel (~3s). Porém, limite diário de 500K tokens esgotava com ~10 imóveis.
**Decisão:** descartado por limite diário insuficiente.

### 2. Google Gemini (gemini-2.5-flash) — descartado
**Resultado:** aceita muitas imagens, mas quota diária de apenas 20 requests para o modelo 2.5-flash. Esgotava antes de processar todos os imóveis.
**Decisão:** descartado por limite diário insuficiente.

### 3. NVIDIA NIM (mistral-large-675b) — descartado
**Resultado:** funcionou sem limite diário, mas cada chamada demorava ~90s (modelo muito grande).
**Decisão:** descartado por velocidade.

### 4. NVIDIA NIM (ministral-14b) — adotado
**Resultado:** ~11s por imóvel, sem limite diário, aceita até 8 imagens por prompt, gratuito.
**Decisão:** adotado como modelo principal.

### 5. Seleção de fotos espaçadas
**Problema:** o limite de 8 imagens por prompt não cobre todas as fotos (média de 20 por imóvel).
**Solução:** selecionar fotos distribuídas uniformemente ao longo do anúncio (1ª, 4ª, 7ª, 10ª...) para cobrir fachada, sala, quartos, banheiro, cozinha e área externa.

### 6. Justificativa única
**Problema:** três campos separados (justificativa_score, justificativa_classificacao, justificativa_fator) eram redundantes.
**Solução:** um único campo `justificativa` que resume tudo em uma frase.

### 7. Renomeação: analise_textual → analise_qualitativa
**Motivo:** o agente agora analisa texto + fotos, não apenas texto.

### 8. Renomeação: fator_valor_textual → fator_valor_qualitativo
**Motivo:** consistência com a mudança acima.

---

## Fluxo Completo

```
1. Carrega zona_homogenea_ag2.json (Agente 2 — Etapa 3)
   → Filtra: cluster="A" E classificacao_zona="na_zona"

2. Para cada imóvel filtrado:
   a. Monta prompt com título, descrição e campos estruturados
   b. Seleciona até 8 fotos espaçadas uniformemente
   c. Envia tudo junto para NVIDIA NIM (ministral-14b)
   d. LLM retorna JSON com estado, padrão, pontos positivos/negativos
   e. Python normaliza vocabulário
   f. Python calcula score qualitativo
   g. Python aplica regra de neutro se necessário
   h. Python gera justificativa

3. Imóvel alvo: analisado separadamente (de imoveis_comparaveis_ag2.json)

4. Salva em data/imoveis_analisados_ag3.json
```

---

## Cálculo do Score

Base: **0.50** (neutro)

| Ajuste | Valor |
|---|---|
| estado = novo | +0.20 |
| estado = reformado | +0.15 |
| estado = bom | +0.10 |
| estado = regular | −0.08 |
| estado = precisa_reforma | −0.25 |
| padrao = alto_padrao | +0.15 |
| padrao = medio | +0.08 |
| cada ponto positivo | +0.03 (máx +0.20) |
| infiltração / umidade | −0.15 |
| documentação irregular | −0.20 |
| outros negativos | −0.08 cada |

**Regra de segurança:** estado=desconhecido + padrao=desconhecido + sem negativos + confiança=baixa → score=0.50, neutro, fator=0.00

---

## Classificação

| Score | Classificação | Significado |
|---|---|---|
| 0.81–1.00 | muito_favoravel | Imóvel com qualidade muito acima da média |
| 0.61–0.80 | favoravel | Imóvel com qualidade acima da média |
| 0.40–0.60 | neutro | Sem evidência suficiente ou qualidade média |
| 0.00–0.39 | desfavoravel | Imóvel com problemas identificados |

---

## Schema de Saída (por imóvel)

```json
{
  "id_imovel": "...",
  "status": "ok",
  "estado_conservacao": "novo",
  "padrao_acabamento": "alto_padrao",
  "pontos_positivos": ["suite", "vagas de garagem", "churrasqueira", "porcelanato"],
  "pontos_negativos": [],
  "confianca_extracao": "alta",
  "fotos_analisadas": 8,
  "total_fotos_disponiveis": 26,
  "observacoes": [],
  "scores": {"score_qualitativo": 1.0},
  "classificacao_qualitativa": "muito_favoravel",
  "justificativa": "estado de conservacao: novo. padrao de acabamento: alto_padrao. 10 pontos positivos identificados. score qualitativo 1.0 -> classificacao muito_favoravel.",
  "analise_qualitativa": "Estado: novo. Padrao: alto_padrao. Positivos: suite, vagas de garagem, churrasqueira.",
  "limitacoes": [
    "A analise depende da qualidade e completude da descricao e das fotos do anuncio.",
    "As informacoes extraidas devem ser validadas por vistoria ou fonte oficial."
  ]
}
```

---

## Resultado dos Testes (Centro de Itajaí/SC — maio 2026)

```
Provider: NVIDIA NIM (ministral-14b-instruct-2512)
Imóveis analisados: 19
Tempo total: ~5 minutos (~11s por imóvel)
Fotos por imóvel: até 8 (espaçadas)

Score qualitativo médio: 0.807

Exemplos:
  #2  Rua Jorge Mattos (11 fotos)     → novo, alto_padrao → score=1.0, muito_favoravel
  #4  Rua Juvenal Garcia (6 fotos)    → novo, alto_padrao → score=1.0, muito_favoravel
  #9  Centro (27 fotos)               → novo, alto_padrao → score=1.0, muito_favoravel
  #1  Rua Franklin (26 fotos)         → bom, medio       → score=0.88, muito_favoravel
  #10 Centro (24 fotos)               → regular, medio   → score=0.03, desfavoravel
  Alvo (sem fotos)                    → desconhecido     → score=0.50, neutro
```

---

## Entrada

| Parâmetro | Tipo | Descrição |
|---|---|---|
| `arquivo_entrada` | str | `zona_homogenea_ag2.json` (default) |
| `arquivo_saida` | str | `imoveis_analisados_ag3.json` (default) |

---

## Dependências

| Serviço | Uso | Custo | Configuração |
|---|---|---|---|
| NVIDIA NIM | Análise multimodal (texto + fotos) | Gratuito, sem limite | `NVIDIA_API_KEY` no `.env` |
| openai (pacote Python) | Cliente para API compatível OpenAI | — | `pip install openai` |

---

## Como Rodar

```bash
.venv/Scripts/python.exe -m tests.test_text_analyzer
```

**Pré-requisitos:**
- `data/zona_homogenea_ag2.json` gerado pelo Agente 2
- `data/imoveis_comparaveis_ag2.json` gerado pelo Agente 2
- `NVIDIA_API_KEY` no `.env`
