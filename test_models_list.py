"""Get all embedding models from OpenRouter (dedicated endpoint)."""
import httpx

API_KEY = "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"

with httpx.Client(timeout=30.0) as client:
    resp = client.get(
        "https://openrouter.ai/api/v1/embeddings/models",
        headers={"Authorization": f"Bearer {API_KEY}"},
    )

data = resp.json()
models = data.get("data", [])

print(f"Embedding моделей на OpenRouter: {len(models)}\n")
print(f"{'ID':<45} {'Name':<35} {'CTX':>7} {'Price/1M':>10}")
print("-" * 100)

for m in sorted(models, key=lambda x: x.get("id", "")):
    mid = m.get("id", "")
    name = m.get("name", "")[:34]
    ctx = m.get("context_length", "?")
    pricing = m.get("pricing", {})
    prompt_price = pricing.get("prompt", "?")
    print(f"  {mid:<43} {name:<35} {str(ctx):>7} {str(prompt_price):>10}")
