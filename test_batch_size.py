"""Quick test: max batch size for one request."""
import httpx
import time

API_KEY = "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"
MODEL = "qwen/qwen3-embedding-4b"
URL = "https://openrouter.ai/api/v1/embeddings"

texts = [f"тестовый текст номер {i} для проверки batch size" for i in range(20)]
print(f"Отправляю {len(texts)} текстов в одном запросе...", flush=True)

t0 = time.perf_counter()
with httpx.Client(timeout=60.0) as client:
    resp = client.post(URL, headers={
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://ksr-matcher.local",
        "Connection": "close",
    }, json={"model": MODEL, "input": texts, "encoding_format": "float"})

elapsed = time.perf_counter() - t0
body = resp.json()

if "error" in body:
    err = body["error"]
    print(f"ERROR: {err.get('message', err)}")
elif "data" in body:
    print(f"OK: {len(body['data'])} embeddings, dim={len(body['data'][0]['embedding'])}, time={elapsed:.2f}s")
else:
    print(f"Unexpected: {str(body)[:300]}")
