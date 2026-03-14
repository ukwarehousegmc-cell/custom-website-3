"""Quick script to list available Gemini models that support image generation."""
import os
from dotenv import load_dotenv
load_dotenv()

from google import genai

api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    print("Set GEMINI_API_KEY first")
    exit(1)

client = genai.Client(api_key=api_key)

print("All available models:")
print("=" * 60)
for model in client.models.list():
    name = model.name
    if "image" in name.lower() or "imagen" in name.lower() or "flash" in name.lower():
        methods = getattr(model, 'supported_generation_methods', [])
        print(f"  {name}  →  {methods}")
