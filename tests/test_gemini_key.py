"""Testa se GOOGLE_API_KEY_2 funciona com gemini-3.5-flash-lite."""
import sys, os
sys.path.insert(0, ".")
from dotenv import load_dotenv
load_dotenv(override=True)

key = os.getenv("GOOGLE_API_KEY_2", "")
print(f"GOOGLE_API_KEY_2: {key[:15]}..." if key else "GOOGLE_API_KEY_2: NAO CONFIGURADA")

key1 = os.getenv("GOOGLE_API_KEY", "")
print(f"GOOGLE_API_KEY:   {key1[:15]}..." if key1 else "GOOGLE_API_KEY: NAO CONFIGURADA")

if not key:
    print("\nSem chave - nao pode testar")
    exit()

try:
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=key)
    response = client.models.generate_content(
        model="gemini-3.5-flash-lite",
        contents=[types.Content(role="user", parts=[types.Part.from_text(text="Responda apenas: oi")])],
        config=types.GenerateContentConfig(temperature=0),
    )
    print(f"\nResposta: {response.text}")
    print("Gemini gemini-3.5-flash-lite FUNCIONA!")
except Exception as e:
    print(f"\nERRO: {e}")
