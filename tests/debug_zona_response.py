"""Debug: ver resposta completa do Groq para zona homogênea."""
import sys, os, re, json, base64
sys.path.insert(0, ".")
from dotenv import load_dotenv
load_dotenv(override=True)
from groq import Groq

# Carrega imagem já salva
img_path = "data/satelite_zona_homogenea_ag2.png"
with open(img_path, "rb") as f:
    img_bytes = f.read()

# Comprimir como JPEG
from PIL import Image
import io
img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
buffer = io.BytesIO()
img.save(buffer, format="JPEG", quality=85)
img_b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

# Prompt simplificado pra teste
prompt = """Analise esta imagem de satelite. O marcador vermelho indica o imovel alvo no centro.
Responda SOMENTE com JSON valido:
{
  "padrao_construtivo": "casas | sobrados | predios_baixos | misto",
  "homogeneidade_visual": "alta | media | baixa",
  "densidade_urbana": "baixa | media | alta",
  "raio_sugerido_metros": 700,
  "justificativa_raio": "frase curta",
  "confianca": "alta | media | baixa"
}"""

client = Groq(api_key=os.getenv("GROQ_API_KEY"))
response = client.chat.completions.create(
    model="qwen/qwen3.6-27b",
    messages=[{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
    ]}],
    temperature=0,
    max_completion_tokens=4096,
)

texto = response.choices[0].message.content or ""
print(f"Resposta completa ({len(texto)} chars):")
print("=" * 60)
print(texto[:2000])
print("..." if len(texto) > 2000 else "")
print("=" * 60)
print(f"\nHas <think>: {'<think>' in texto}")
print(f"Has </think>: {'</think>' in texto}")

# Tenta parsear
texto_limpo = re.sub(r'<think>[\s\S]*?</think>', '', texto).strip()
if '</think>' in texto:
    texto_limpo = texto.split('</think>', 1)[1].strip()
print(f"\nTexto limpo ({len(texto_limpo)} chars):")
print(texto_limpo[:500])

m = re.search(r'\{[\s\S]+\}', texto_limpo)
if m:
    print(f"\nJSON encontrado!")
    print(m.group(0)[:500])
else:
    print("\nJSON NAO encontrado no texto limpo")
