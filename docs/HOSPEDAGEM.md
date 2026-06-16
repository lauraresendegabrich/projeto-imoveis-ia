# Hospedagem — Decisão Técnica

## Plataforma Escolhida: Streamlit Community Cloud

**URL do deploy:** https://projeto-imoveis-ia-sd5kashfzhslavnmflkcyq.streamlit.app

## Por que não Vercel ou Render?

### Vercel (descartada)
- **Timeout de 10 segundos** no plano gratuito (Serverless Functions)
- O pipeline precisa de **5+ minutos** para executar (scraping + LLM + análise de fotos)
- Não suporta WebSocket nativamente — Streamlit depende de WebSocket para comunicação em tempo real
- Projetada para aplicações frontend estáticas ou APIs rápidas, não para processos de longa duração

### Render (descartada)
- **Timeout de 30 segundos** em requests HTTP no plano gratuito
- O serviço web free hiberna após 15 minutos de inatividade (cold start de ~30s)
- Mesmo no plano pago, o timeout de 60 segundos não é suficiente para o pipeline completo
- Seria necessário separar em background worker + web server, adicionando complexidade desnecessária

### Streamlit Community Cloud (escolhida)
- **Sem timeout curto** — processos podem rodar por vários minutos
- **Feita para aplicações Streamlit** — suporte nativo a WebSocket, progress bars, e atualizações em tempo real
- **Deploy direto do GitHub** — atualiza automaticamente a cada push
- **Gratuita** para repositórios públicos
- **Secrets management** integrado (variáveis de ambiente via interface web)
- **1GB de RAM** disponível (suficiente para o pipeline)

## Limitações do Streamlit Cloud

1. **App hiberna após inatividade** — se ninguém acessa por ~7 dias, o app "dorme". A primeira visita depois leva ~1 minuto para acordar.
2. **Sem disco persistente** — arquivos gerados durante a execução (JSONs intermediários) existem apenas durante a sessão. Não há persistência entre reinicializações.
3. **1 app grátis por conta** (no plano Community). Para múltiplos apps, precisaria de conta adicional ou plano pago.
4. **Recursos limitados** — 1GB RAM, CPU compartilhada. Para processos muito pesados (muitos comparáveis com fotos), pode ficar lento.

## Configuração do Deploy

### Requisitos
- Repositório público no GitHub
- Arquivo `requirements.txt` na raiz
- Arquivo principal: `app/interface.py`

### Secrets (variáveis de ambiente)
Configurados via Settings → Secrets no painel do Streamlit Cloud, em formato TOML:

```toml
APIFY_TOKEN_2 = "token_apify"
GROQ_API_KEY = "token_groq"
GROQ_API_KEY_2 = "token_groq_backup"
NVIDIA_API_KEY = "token_nvidia"
GOOGLE_MAPS_KEY = "token_google_maps"
```

### Adaptação no código
Para que o app funcione tanto localmente (com `.env`) quanto no cloud (com `st.secrets`), foi adicionado no início de `app/interface.py`:

```python
# Streamlit Cloud: carrega secrets como variáveis de ambiente
try:
    for key, value in st.secrets.items():
        if isinstance(value, str):
            os.environ[key] = value
except Exception:
    pass  # Roda local sem secrets
```

Isso injeta as secrets do Streamlit Cloud como variáveis de ambiente, permitindo que o código existente (que usa `os.getenv()`) funcione sem modificação nos agentes.

## APIs Externas Necessárias

| API | Uso | Plano | Limite |
|-----|-----|-------|--------|
| Apify | Scraping de portais imobiliários | Free ($5/mês) | ~20-30 execuções |
| Groq | LLM para classificação de comparáveis | Free | 14.400 req/dia |
| NVIDIA NIM | Análise de fotos (visão computacional) | Free | Rate limit variável |
| Google Maps | Geocodificação e imagem de satélite | Free ($200 crédito/mês) | 28.000 geocoding/mês |

## Tempo de Execução no Cloud

| Etapa | Tempo médio | Observação |
|-------|-------------|------------|
| Agente 1 (Coleta) | 1-3 min | Depende da velocidade do Apify |
| Agente 2 (Comparáveis) | 20-40s | Depende do rate limit da Groq |
| Zona Homogênea | 30-60s | Opcional, depende do Google Maps |
| Agente 3 (Qualidade) | 2-5 min | O mais demorado (NVIDIA Vision por imóvel) |
| Agente 4 (Infraestrutura) | 10-30s | Roda em paralelo com Agente 3 |
| Agente 5 (Preço) | <1s | Cálculo local |
| **Total** | **4-10 min** | Varia com quantidade de comparáveis |
