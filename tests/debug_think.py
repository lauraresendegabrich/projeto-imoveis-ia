"""Debug: verificar se </think> está na resposta grande."""
import os, base64, io, re, sys
sys.path.insert(0, ".")
from dotenv import load_dotenv
load_dotenv(override=True)
from groq import Groq
from PIL import Image

img = Image.open("data/satelite_zona_homogenea_ag2.png").convert("RGB")
buf = io.BytesIO()
img.save(buf, format="JPEG", quality=85)
b64 = base64.b64encode(buf.getvalue()).decode()

# Usa prompt curto pra garantir que tem tokens pro JSON
prompt = "Analise esta imagem de satelite. O marcador vermelho indica o imovel alvo. Responda SOMENTE JSON: {\"padrao_construtivo\": \"...\", \"homogeneidade_visual\": \"...\", \"densidade_urbana\": \"...\", \"raio_sugerido_metros\": 700, \"confianca\": \"...\"}"

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
print(f"Len={len(t)}")
print(f"Has <think>: {'<think>' in t}")
print(f"Has </think>: {'</think>' in t}")

if '</think>' in t:
    pos = t.find('</think>')
    after = t[pos+8:].strip()
    print(f"\nAfter </think> ({len(after)} chars):")
    print(after[:500])
else:
    print("\nNO </think> tag found!")
    print("Full response:")
    print(t[:1000])
