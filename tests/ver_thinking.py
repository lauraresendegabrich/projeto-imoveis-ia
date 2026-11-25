"""Mostra o raciocínio completo do modelo na última execução da zona homogênea."""
import os, base64, io, sys
sys.path.insert(0, ".")
from dotenv import load_dotenv
load_dotenv(override=True)
from groq import Groq
from PIL import Image

img = Image.open("data/satelite_zona_homogenea_ag2.png").convert("RGB")
buf = io.BytesIO()
img.save(buf, format="JPEG", quality=85)
b64 = base64.b64encode(buf.getvalue()).decode()

# Usa o mesmo prompt grande do código
endereco = "Rua Doutor Liraucio Gomes, 119, Cambuí, Campinas, SP"
prompt = f"""Você é um assistente especializado em análise visual urbana para apoio à avaliação imobiliária.
Sua tarefa é analisar uma imagem de satélite ou mapa híbrido centrada em um imóvel alvo e sugerir um raio para representar aproximadamente sua ZONA HOMOGÊNEA.

IMÓVEL ALVO
Endereço: {endereco}
O imóvel alvo está identificado por um marcador vermelho na imagem.

Analise a imagem e responda SOMENTE com JSON válido:
{{
  "padrao_construtivo": "casas | sobrados | predios_baixos | misto | indefinido",
  "homogeneidade_visual": "alta | media | baixa",
  "densidade_urbana": "baixa | media | alta",
  "raio_sugerido_metros": 700,
  "justificativa_raio": "frase curta",
  "confianca": "alta | media | baixa"
}}"""

c = Groq(api_key=os.getenv("GROQ_API_KEY"))
r = c.chat.completions.create(
    model="qwen/qwen3.6-27b",
    messages=[{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
    ]}],
    temperature=0,
    max_completion_tokens=4096,
)
t = r.choices[0].message.content or ""

# Separa thinking do JSON
if '</think>' in t:
    thinking = t.split('</think>')[0].replace('<think>', '').strip()
    json_part = t.split('</think>')[1].strip()
else:
    thinking = t
    json_part = ""

print("=" * 60)
print("RACIOCÍNIO DO MODELO (thinking)")
print("=" * 60)
print(thinking)
print()
print("=" * 60)
print("RESPOSTA JSON")
print("=" * 60)
print(json_part)
