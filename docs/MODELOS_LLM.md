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
| `ZAI_MODELO_TEXTO` | `glm-4.7-flash` | Z.AI | Ag.2 comparáveis e Ag.4 região (última reserva) |
| `ZAI_MODELO_VISAO` | `glm-4.6v-flash` | Z.AI | fora das listas (sobrecarregado no plano gratuito, 24/11/2026); entra se for posto numa `ORDEM_*` de visão |

O Qwen do Google Colab (`QWEN_API_URL`, `QWEN_API_KEY`) está **desligado**. O Colab
está fora do ar, e as duas linhas estão comentadas no `.env`. Para religar: preencher
as duas linhas e pôr `qwen` no começo das `ORDEM_*` desejadas.

### NVIDIA e Z.AI: o "pensar" desligado

Os modelos novos da NVIDIA e da Z.AI "pensam" antes de responder. Com o pensar ligado,
2 de 5 respostas vieram vazias no teste (24/11/2026), porque o limite de tokens acabou
antes da resposta. A chamada única `services/ia.chamar_openai_compativel` desliga o
pensar:
- NVIDIA: `reasoning_effort: "none"`;
- Z.AI: `thinking: {"type": "disabled"}`.

Ela também usa um tempo máximo por chamada e nenhuma repetição automática da biblioteca.

### Z.AI: uma chamada por vez

O plano gratuito do Z.AI atende um pedido por vez (erro 1302 se chegarem dois). Como os
Agentes 3 e 4 rodam juntos, `services/ia.py` tem uma trava: a segunda chamada espera a
primeira terminar, até 90 s (`ZAI_ESPERA_TRAVA_S`); passou disso, desiste e vai para a
próxima IA.

## Ordem de tentativa

Se uma IA falha ou responde algo inválido, o agente tenta a próxima. A ordem de cada
tarefa fica no `.env` (`ORDEM_*`); sem a linha, vale o padrão abaixo, que é a ordem que
já existia antes de 24/11/2026, com o Z.AI no fim das tarefas de texto.

| Variável | Tarefa | Padrão | Se todas falharem |
|---|---|---|---|
| `ORDEM_COMPARAVEIS` | Ag.2 comparáveis | `groq,gemini,nvidia,zai` | 20 melhores pelo cálculo |
| `ORDEM_ZONA` | Ag.2 zona no satélite | `gemini,groq1,nvidia` | raio padrão de 500 m |
| `ORDEM_FOTOS_ALVO` | Ag.3 fotos do imóvel avaliado | `gemini,groq1,nvidia` | melhor resultado parcial |
| `ORDEM_FOTOS_COMPARAVEIS` | Ag.3 fotos dos comparáveis | `groq1,nvidia,gemini` | melhor resultado parcial |
| `ORDEM_REGIAO` | Ag.4 região | `gemini,groq1,nvidia,zai` | texto montado pelo cálculo |

**Nomes aceitos:** `groq` (as duas chaves: `GROQ_API_KEY` e depois `GROQ_API_KEY_2`),
`groq1` ou `groq2` (só uma), `gemini`, `nvidia`, `zai`, `qwen`. Separar por vírgula. Nome
errado é ignorado, com aviso no log; lista toda errada volta ao padrão. IA sem chave no
`.env` é pulada.

Exemplo: para tirar o Gemini da zona e testar o Z.AI de visão,
`ORDEM_ZONA=groq,nvidia,zai`.

## Erro 429 (limite de uso): regra única

Vale para todas as IAs e tarefas (`services/ia.com_regra_429`):

| O que a IA disse | O que o sistema faz |
|---|---|
| Limite **por minuto**, pedindo espera de até 30 s (ou sem dizer quanto) | Espera (o tempo pedido + 1 s, ou 10 s) e tenta **mais uma vez** |
| Falha passageira do servidor (**500, 502, 503**) | Espera 3 s e tenta **mais uma vez** |
| Limite por minuto pedindo mais de 30 s | Vai direto para a próxima IA |
| Limite **por dia** (Groq TPD/RPD, Gemini PerDay, Z.AI 1113) | Vai direto para a próxima IA |
| Tempo esgotado, chave errada, outro erro | Vai direto para a próxima IA |

Nunca há terceira tentativa: se a segunda falhar, vai para a próxima IA. O custo, quando
a falha acontece, é a espera mais o tempo de uma chamada (Gemini e Groq: 1 a 6 s;
NVIDIA com imagem: ~25 s).

As repetições que cada agente tinha por conta própria saíram: Groq do Ag.2 e Ag.4
repetia 2 vezes sozinho; Ag.3 esperava 429 de até 15 s; o Gemini do Ag.3 repetia o erro
500 só no imóvel avaliado (agora a regra vale para todos). O intervalo de 8 s entre fotos no Groq do Ag.3 continua (é prevenção, não
repetição).

## Fotos por chamada (Agente 3)

| Provedor | Variável | Padrão |
|---|---|---|
| Gemini | `FOTOS_GEMINI` | 4 |
| Groq | `FOTOS_GROQ` | 2 |
| NVIDIA | `FOTOS_NVIDIA` | 1 (o nemotron aceitou 4 no teste) |
| Z.AI | `FOTOS_ZAI` | 1 |
| Qwen | `FOTOS_QWEN` | 4 |

Mudar o número de fotos pode mudar a análise do Agente 3 (e o score de liquidez).

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
| Z.AI | 1 pedido por vez (trava em `services/ia.py`) |

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
| 24/11/2026 | Ordem das IAs no `.env` (`ORDEM_*`), Z.AI no fim das tarefas de texto, regra única do 429, trava do Z.AI, fotos por provedor no `.env` | Trocar a ordem sem mexer no código; mais uma reserva gratuita |
