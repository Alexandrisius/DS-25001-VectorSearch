"""
СТРЕСС-ТЕСТ qwen/qwen3-embedding-8b на OpenRouter.

20 последовательных запросов без пауз — проверка стабильности под нагрузкой.
Каждый запрос с жёстким таймаутом 30с.
Включает одиночные запросы и батчи (5 и 10 текстов).
"""

import httpx
import time
import threading
import statistics

API_KEY = "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"
BASE_URL = "https://openrouter.ai/api/v1/embeddings"
MODEL = "qwen/qwen3-embedding-8b"

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
    "HTTP-Referer": "https://ksr-matcher.local",
    "X-Title": "KSR Matcher Test",
    "Connection": "close",
}

HARD_TIMEOUT = 30  # секунд на запрос

SAMPLE_TEXTS = [
    "насос центробежный КМ 80-50-200",
    "задвижка клиновая фланцевая ДУ100",
    "труба стальная бесшовная 108х4",
    "электродвигатель асинхронный 5.5 кВт",
    "кабель силовой ВВГнг 3х2.5",
    "фильтр масляный для компрессора",
    "клапан обратный поворотный Ду50",
    "манометр показывающий 0-10 МПа",
    "теплообменник пластинчатый 100 кВт",
    "вентилятор радиальный ВР 80-75",
]


def timed_request(request_fn, timeout=HARD_TIMEOUT):
    result = {"ok": False, "error": f"TIMEOUT ({timeout}s)", "elapsed": timeout}
    def worker():
        nonlocal result
        t0 = time.perf_counter()
        try:
            r = request_fn()
            result = {"ok": True, "elapsed": time.perf_counter() - t0, "data": r}
        except Exception as e:
            result = {"ok": False, "error": str(e)[:150], "elapsed": time.perf_counter() - t0}
    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout=timeout)
    return result


def embed(texts):
    with httpx.Client(timeout=25.0) as client:
        resp = client.post(BASE_URL, headers=HEADERS,
                           json={"model": MODEL, "input": texts, "encoding_format": "float"})
    body = resp.json()
    if "error" in body:
        raise Exception(body["error"].get("message", str(body["error"])))
    return len(body["data"]), len(body["data"][0]["embedding"])


def run_stress(label, texts_fn, count, delay):
    """Серия запросов с заданной паузой."""
    print(f"\n{'='*70}")
    print(f"  {label}")
    print(f"  {count} запросов, пауза {delay}с между ними")
    print(f"{'='*70}", flush=True)
    
    times = []
    fails = 0
    
    for i in range(count):
        if i > 0 and delay > 0:
            time.sleep(delay)
        
        texts = texts_fn(i)
        r = timed_request(lambda: embed(texts))
        
        icon = "✅" if r["ok"] else "❌"
        detail = f'{r["elapsed"]:.2f}s'
        if r["ok"]:
            times.append(r["elapsed"])
            count_emb, dim = r["data"]
            detail += f" [{count_emb} emb, dim={dim}]"
        else:
            fails += 1
            detail += f" — {r['error']}"
        
        print(f"  {icon} #{i+1:>2}: {detail}", flush=True)
    
    # Статистика
    print(f"\n  --- Результат ---")
    print(f"  Успешно: {len(times)}/{count}")
    print(f"  Ошибок:  {fails}/{count}")
    if times:
        print(f"  Время:   min={min(times):.2f}s  avg={statistics.mean(times):.2f}s  max={max(times):.2f}s")
        if len(times) > 1:
            print(f"  Stdev:   {statistics.stdev(times):.2f}s")
    
    return {"ok_count": len(times), "fail_count": fails, "times": times}


def main():
    print("=" * 70)
    print(f"  СТРЕСС-ТЕСТ: {MODEL}")
    print(f"  Таймаут на запрос: {HARD_TIMEOUT}с")
    print("=" * 70, flush=True)

    # Фаза 1: одиночные запросы, без пауз
    r1 = run_stress(
        "ФАЗА 1: Одиночные запросы БЕЗ ПАУЗ (спам)",
        lambda i: [f"тестовый запрос номер {i}"],
        count=10, delay=0
    )

    # Фаза 2: одиночные запросы, пауза 3с
    r2 = run_stress(
        "ФАЗА 2: Одиночные запросы, пауза 3с",
        lambda i: [f"запрос с паузой три секунды номер {i}"],
        count=5, delay=3
    )

    # Фаза 3: батчи по 5 текстов, без пауз
    r3 = run_stress(
        "ФАЗА 3: Батчи по 5 текстов БЕЗ ПАУЗ",
        lambda i: SAMPLE_TEXTS[:5],
        count=5, delay=0
    )

    # Фаза 4: батчи по 10 текстов, пауза 3с
    r4 = run_stress(
        "ФАЗА 4: Батчи по 10 текстов, пауза 3с",
        lambda i: SAMPLE_TEXTS[:10],
        count=5, delay=3
    )

    # Итог
    print(f"\n\n{'='*70}")
    print(f"  ИТОГ СТРЕСС-ТЕСТА: {MODEL}")
    print(f"{'='*70}")
    
    phases = [
        ("Одиночные, без пауз", r1),
        ("Одиночные, 3с пауза", r2),
        ("Батч 5, без пауз", r3),
        ("Батч 10, 3с пауза", r4),
    ]
    
    for label, r in phases:
        total = r["ok_count"] + r["fail_count"]
        pct = r["ok_count"] / total * 100 if total else 0
        avg_t = statistics.mean(r["times"]) if r["times"] else 0
        icon = "✅" if r["fail_count"] == 0 else "⚠️" if pct >= 50 else "❌"
        print(f"  {icon} {label:<30} {r['ok_count']}/{total} ({pct:.0f}%)  avg={avg_t:.2f}s")
    
    total_ok = sum(r["ok_count"] for _, r in phases)
    total_all = sum(r["ok_count"] + r["fail_count"] for _, r in phases)
    print(f"\n  Общий результат: {total_ok}/{total_all} запросов успешно ({total_ok/total_all*100:.0f}%)")
    
    if total_ok == total_all:
        print(f"  🏆 {MODEL} — ПОЛНОСТЬЮ СТАБИЛЬНА!")
    elif total_ok / total_all >= 0.8:
        print(f"  ⚠️ {MODEL} — в основном стабильна, есть редкие сбои")
    else:
        print(f"  ❌ {MODEL} — нестабильна, rate limit мешает")
    
    print(flush=True)


if __name__ == "__main__":
    main()
