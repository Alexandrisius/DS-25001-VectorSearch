"""WebSocket endpoint для real-time прогресса фоновых задач.

Подписывается на Redis pub/sub канал `job:{job_id}` и проксирует события клиенту.
Celery worker пушит события через `publish_job_progress(job_id, payload)`.
"""
from __future__ import annotations

import asyncio
import json
from uuid import UUID

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status
from loguru import logger

from app.core.security import decode_access_token
from app.db.redis import get_redis

router = APIRouter(prefix="/admin/jobs", tags=["jobs-ws"])


@router.websocket("/{job_id}/ws")
async def job_progress_ws(
    websocket: WebSocket,
    job_id: str,
    token: str = Query(default=""),
) -> None:
    """WebSocket: real-time прогресс задачи.

    Авторизация — через query param `token` (JWT, как в authFetch).
    Подписывается на Redis pub/sub `job:{job_id}` и шлёт JSON-сообщения клиенту.
    """
    # Авторизация
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="No token")
        return
    try:
        payload = decode_access_token(token)
    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid token")
        return

    # Validate job_id format
    try:
        UUID(job_id)
    except ValueError:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid job_id")
        return

    await websocket.accept()
    logger.info(f"[ws] client connected: job_id={job_id} user={payload.get('sub', '?')}")

    redis = get_redis()
    pubsub = redis.pubsub()
    channel = f"job:{job_id}"

    try:
        await pubsub.subscribe(channel)
        # Сразу шлём текущий статус из БД
        from app.db.postgres import session_scope
        from app.models.background_job import BackgroundJob
        from sqlalchemy import select
        async with session_scope() as session:
            res = await session.execute(select(BackgroundJob).where(BackgroundJob.id == UUID(job_id)))
            job = res.scalar_one_or_none()
            if job:
                # job.status — str (не Enum), потому что PgEnum(create_type=False)
                status_str = str(job.status) if not hasattr(job.status, "value") else job.status.value
                await websocket.send_json({
                    "type": "status",
                    "data": {
                        "id": str(job.id),
                        "status": status_str,
                        "progress": job.progress,
                        "total": job.total,
                        "details": job.details,
                        "result": job.result,
                        "error": job.error,
                    },
                })
                # Если задача уже завершена — закрываемся
                if status_str in ("completed", "error", "cancelled"):
                    await websocket.send_json({
                        "type": "done",
                        "data": {
                            "id": str(job.id),
                            "status": status_str,
                            "progress": 100,
                            "result": job.result,
                            "error": job.error,
                        },
                    })
                    await websocket.close()
                    return

        # Слушаем pub/sub
        await websocket.send_json({"type": "subscribed", "channel": channel})
        sent_count = 0
        failed_sends = 0

        async def reader() -> None:
            nonlocal sent_count, failed_sends
            try:
                # ВАЖНО: get_message(timeout=0.01) в цикле надёжнее listen()
                # на высокочастотном потоке. listen() может терять сообщения
                # под нагрузкой или блокироваться.
                while True:
                    msg = await pubsub.get_message(
                        ignore_subscribe_messages=True,
                        timeout=0.01,
                    )
                    if msg is None:
                        await asyncio.sleep(0)  # yield control
                        continue
                    if msg.get("type") != "message":
                        continue
                    data = msg.get("data")
                    if isinstance(data, bytes):
                        data = data.decode("utf-8", errors="replace")
                    try:
                        payload_out = json.loads(data)
                    except (TypeError, ValueError):
                        payload_out = {"type": "progress", "data": {"raw": str(data)}}
                    # ВАЖНО: wait_for с timeout — если клиент медленный или TCP
                    # buffer заполнен, отправка блокируется. Считаем клиент мёртвым.
                    try:
                        await asyncio.wait_for(
                            websocket.send_json(payload_out),
                            timeout=2.0,
                        )
                        sent_count += 1
                    except asyncio.TimeoutError:
                        failed_sends += 1
                        logger.warning(
                            f"[ws] send timeout for {job_id} "
                            f"(sent={sent_count}, failed={failed_sends})"
                        )
                        # Клиент слишком медленный — закрываем
                        raise WebSocketDisconnect(code=1011, reason="send timeout")
            except WebSocketDisconnect:
                raise
            except Exception as e:
                logger.error(f"[ws] reader error: {e}", exc_info=True)
                raise

        async def pinger() -> None:
            try:
                while True:
                    await asyncio.sleep(25)
                    try:
                        await asyncio.wait_for(
                            websocket.send_json({"type": "ping"}),
                            timeout=2.0,
                        )
                    except (asyncio.TimeoutError, Exception):
                        return
            except asyncio.CancelledError:
                return

        reader_task = asyncio.create_task(reader())
        pinger_task = asyncio.create_task(pinger())

        # Ждём пока клиент не отключится
        try:
            while True:
                # Сервер не ждёт сообщений от клиента, но receive_text держит цикл
                await websocket.receive_text()
        except WebSocketDisconnect:
            logger.info(f"[ws] client disconnected: job_id={job_id} sent={sent_count} failed={failed_sends}")
        except Exception as e:
            logger.error(f"[ws] receive error for {job_id}: {e}")
        finally:
            reader_task.cancel()
            pinger_task.cancel()
    finally:
        try:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()
        except Exception:
            pass
        try:
            await websocket.close()
        except Exception:
            pass


__all__ = ["router"]
