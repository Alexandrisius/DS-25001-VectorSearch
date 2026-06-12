"""A/B тест Phase 4: 5 кейсов из реального использования.

Запуск:
    docker compose exec api python /app/scripts/test_search_phases.py
"""
import asyncio
import time

from app.db.postgres import get_session_maker
from app.services.collection_service import CollectionService
from app.services.search_service import SearchService
from app.di import get_embedding_service, get_rerank_service
from app.main import create_app
from fastapi import Request


CASES = [
    "Котёл",
    "Задвижка",
    "Кран шаровой DN50",
    "Задвижка клиновая фланцевая PN16 DN150 стальная с обрезиненным клином",
    "Котёл газовый настенный",
]

# max_results передаётся в search() — проверяем, что confident/low_confidence
# ветки возвращают до 50 кaндидатов (как заказывал инженер, чтобы видеть все
# похожие котлы/задвижки и выбрать нужный по параметрам).
TEST_MAX_RESULTS = 50


async def main():
    app = create_app()
    fake_req = Request(scope={"type": "http", "app": app})
    SessionLocal = get_session_maker()
    async with SessionLocal() as s:
        coll = await CollectionService(s).get_current_active("ksr_1")
        embedding = await get_embedding_service(fake_req)
        rerank = await get_rerank_service(s)
        svc = SearchService(s, embedding, rerank)

        total_pass = 0
        total_fail = 0
        for q in CASES:
            print(f"\n{'=' * 70}")
            print(f"Q: {q!r}")
            print("=" * 70)
            t0 = time.time()
            result = await svc.search(coll, q, max_results=TEST_MAX_RESULTS)
            elapsed = time.time() - t0
            cands = result.get("candidates", [])
            trace = result.get("search_trace") or {}
            branch = trace.get("adaptive_branch")
            hint = result.get("hint")
            max_rs = trace.get("max_rerank_score")

            print(f"  status        : {result.get('status')}")
            print(f"  branch        : {branch}")
            print(f"  max_rerank    : {max_rs}")
            print(f"  count         : {len(cands)}")
            print(f"  elapsed       : {elapsed:.2f}s")
            if hint:
                print(f"  hint          : {hint}")
            if cands:
                top3 = cands[:3]
                for c in top3:
                    desc = (c.get("description") or "")[:80].replace("\n", " ")
                    print(
                        f"    #{c['rank']:2} cos={c.get('cosine_similarity', 0):.3f} "
                        f"rr={c.get('reranker_score', 0):.3f} [{c.get('code', '?')}] {desc}"
                    )

            # Проверки:
            ok = bool(cands)
            if ok and branch in ("confident", "low_confidence"):
                # Confident/low_confidence должны отдавать <= max_results
                if len(cands) > TEST_MAX_RESULTS:
                    print(f"  FAIL: branch={branch} returned {len(cands)} > max_results={TEST_MAX_RESULTS}")
                    ok = False
            if ok and branch == "uncertain":
                # Uncertain жёстко capped до 5 (хинт)
                if len(cands) > 5:
                    print(f"  FAIL: branch=uncertain returned {len(cands)} > 5")
                    ok = False
            if ok:
                total_pass += 1
                print(f"  PASS")
            else:
                total_fail += 1
                print(f"  FAIL")

        print(f"\n{'=' * 70}")
        print(f"ИТОГО: {total_pass} PASS, {total_fail} FAIL (max_results={TEST_MAX_RESULTS})")
        print("=" * 70)


asyncio.run(main())
