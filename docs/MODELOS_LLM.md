# Modelos de IA usados no pipeline

Todas as IAs são de planos gratuitos. Os nomes dos modelos ficam no `.env` (ou nos
Secrets do Streamlit Cloud). Sem a variável, vale o padrão de `services/ia.py`.

## Provedores e modelos (nov/2026)

| Variável | Padrão | Provedor | Usado em |
|---|---|---|---|
| `GROQ_MODELO_TEXTO_GRANDE` | `openai/gpt-oss-120b` | Groq | Ag.2 comparáveis |
| `GROQ_MODELO_TEXTO_PEQUENO` | `openai/gpt-oss-20b` | Groq | Ag.4 região |
| `GROQ_MODELO_VISAO` | `qwen/qwen3.8-27b` | Groq | Ag.2 zona no satélite, Ag.3 fotos |
| `GEMINI_MODELO` | `gemini-3.5-flash-lite` | Google | Ag.2, Ag.3 e Ag.4 |
| `NVIDIA_MODELO_TEXTO` | `nvidia/nemotron-3.5-lightning-30b-a3b` | NVIDIA NIM | Ag.2 comparáveis, Ag.4 região |
| `NVIDIA_MODELO_VISAO` | `nvidia/nemotron-3.5-super-vl-120b-a12b` | NVIDIA NIM | Ag.2 zona no satélite, Ag.3 fotos |
| `ZAI_MODELO_TEXTO` | `glm-4.7-flash` | Z.AI | ainda não usado nas cadeias |
| `ZAI_MODELO_VISAO` | `glm-4.6v-flash` | Z.AI | ainda não usado (sobrecarregado no plano gratuito, 24/11/2026) |

O Qwen do Google Colab (`QWEN_API_URL`, `QWEN_API_KEY`) está **desligado**. O Colab
está fora do ar, e as duas linhas estão comentadas no `.env`. Sem elas, o código
pula o Qwen.

### NVIDIA e Z.AI: o "pensar" desligado

Os modelos novos da NVIDIA e da Z.AI "pensam" antes de responder. Com o pensar ligado,
2 de 5 respostas vieram vazias no teste (24/11/2026), porque o limite de tokens acabou
antes da resposta. A chamada única `services/ia.chamar_openai_compativel` desliga o
pensar:
- NVIDIA: `reasoning_effort: "none"`;
- Z.AI: `thinking: {"type": "disabled"}`.

Ela também usa um tempo máximo por chamada e nenhuma repetição automática da biblioteca.

## Ordem de tentativa (hoje)

Se uma IA falha ou responde algo inválido, o agente tenta a próxima.

| Tarefa | Ordem |
|---|---|
| Ag.2 comparáveis | Groq (chave 1) → Groq (chave 2) → Gemini → NVIDIA → 20 melhores pelo cálculo |
| Ag.2 zona no satélite | Gemini → Groq → NVIDIA → raio padrão de 500 m |
| Ag.3 fotos do imóvel da CAIXA | Gemini → Groq → NVIDIA → melhor resultado parcial |
| Ag.3 fotos dos comparáveis | Groq → NVIDIA → Gemini → melhor resultado parcial |
| Ag.4 região | Gemini → Groq → NVIDIA → texto montado pelo cálculo |

Com o Qwen ligado, ele entra em primeiro em todas as tarefas.

## Fotos por chamada (Agente 3)

| Provedor | Fotos (`MAX_FOTOS_*` em `agents/text_analyzer.py`) |
|---|---|
| Gemini | 4 |
| Groq | 2 |
| NVIDIA | 1 (o nemotron aceitou 4 no teste) |

## Onde fica registrado quem respondeu

- **Ag.2 comparáveis:** `provider_llm` e `modelo_llm` em cada comparável.
- **Ag.2 zona:** `provider_visao` e `modelo_visao`.
- **Ag.3:** `llm_usada` em cada análise (`provedor/modelo`).
- **Ag.4:** `provider_llm` e `modelo_llm` nos scores.

O banco guarda o resumo em `execucoes.modelos_ia` (ex.: `"agente4": "NVIDIA/nvidia/nemotron-3.5-lightning-30b-a3b"`).

## Limites dos planos gratuitos

| Provedor | Limite |
|---|---|
| Groq | por modelo e por conta: tokens por minuto (8 mil no gpt-oss-120b e no qwen3.8-27b) e tokens por dia |
| Gemini | pedidos por minuto e por dia |
| NVIDIA NIM | ~40 pedidos por minuto; créditos gratuitos da conta |
| Z.AI | 1 pedido por vez |

## Histórico de migrações

| Data | Mudança | Motivo |
|------|---------|--------|
| 13/08/2026 | Ag.2 zona: NVIDIA NIM → Groq qwen3.6-27b | Melhor modelo (27B vs 11B), mais rápido |
| 13/08/2026 | Ag.3: NVIDIA NIM → Gemini 2.5 Flash | 8 fotos por chamada, muito mais rápido |
| 13/08/2026 | Ag.2 clustering: llama-3.3-70b → gpt-oss-120b | Llama desligado 16/08, GPT-OSS tem 200k/dia |
| 13/08/2026 | Ag.4: llama-3.1-8b → gpt-oss-20b | Llama desligado 16/08 |
| 03/09/2026 | Ag.2 clustering (NVIDIA): llama-3.3-70b-instruct → gpt-oss-20b | EOL 26/08 (erro 410) |
| 03/09/2026 | Ag.2 zona (NVIDIA visão): gemma-4-31b-it → llama-3.2-11b-vision-instruct | gemma-4 indisponível |
| 03/09/2026 | Ag.2 e Ag.3 (visão Groq): qwen3.6-27b → qwen3.8-27b | Groq descontinuou o 3.6 (14/09/2026) |
| nov/2026 | Gemini: 2.5 Flash → 3.5 Flash Lite | — |
| 24/11/2026 | NVIDIA texto: gpt-oss-20b → nemotron-3.5-lightning-30b-a3b | gpt-oss-20b da NVIDIA saiu do ar em 18/11/2026 |
| 24/11/2026 | NVIDIA visão: llama-3.2-11b-vision → nemotron-3.5-super-vl-120b-a12b | llama-3.2-11b-vision desativado (erro 410) |
| 24/11/2026 | Nomes dos modelos no `.env` (`services/ia.py`) | Trocar modelo sem mexer no código |
| 24/11/2026 | Qwen do Colab desligado | Colab fora do ar; lento para tarefas reais desde 06/10/2026 |
