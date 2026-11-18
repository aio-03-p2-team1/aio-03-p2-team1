"""Daily cron entry point; synchronize only when seven days have elapsed."""
import asyncio
import logging
import time

from redis.asyncio import from_url

from backend.config import Settings
from scripts.logging_config import configure_logging
from scripts.kind_sync import fetch_records

log = logging.getLogger(__name__)


async def refresh(settings, redis):
    log.info("품종 갱신 확인: backend=%s", settings.storage_backend)
    # A single cron worker owns this lock; expiry protects against killed workers.
    async with redis.lock('meet-again:kinds:refresh-lock', timeout=3600, blocking_timeout=1):
        last = await redis.get('meet-again:kinds:last-refresh')
        if last and time.time() - float(last) < 7 * 86400:
            log.info("품종 갱신 생략: 마지막 성공 후 7일 미경과")
            return False
        log.info("품종 기준정보 수집 시작")
        records = await fetch_records(settings)
        if settings.storage_backend == 'sqlite':
            from scripts.init_kinds_sqlite import SqliteSink
            sink = SqliteSink(settings.sqlite_path)
        else:
            from scripts.init_kinds_supabase import SupabaseSink
            sink = SupabaseSink(settings)
        try:
            for attempt in range(4):
                try:
                    if settings.storage_backend == 'supabase':
                        await asyncio.to_thread(sink.sync, records)
                    else:
                        sink.sync(records)
                    break
                except Exception as exc:
                    if attempt == 3:
                        log.error("DB 동기화 실패: attempts=%d error=%s", attempt + 1, type(exc).__name__)
                        raise
                    log.warning("DB 동기화 재시도: attempt=%d error=%s", attempt + 1, type(exc).__name__)
                    await asyncio.sleep(0.5 * 2 ** attempt)
        finally:
            sink.close()
        # Transaction keeps cache invalidation and successful refresh time together.
        async with redis.pipeline(transaction=True) as pipe:
            pipe.delete(*(f'meet-again:kinds:{s}' for s in ('dog', 'cat', 'etc')))
            pipe.set('meet-again:kinds:last-refresh', str(time.time()))
            await pipe.execute()
        log.info("품종 갱신 완료: records=%d backend=%s Redis 목록 캐시 무효화", len(records), settings.storage_backend)
        return True


async def main():
    configure_logging()
    settings = Settings()
    redis = from_url(settings.redis_url)
    try:
        updated = await refresh(settings, redis)
        if not updated:
            log.info("품종 갱신 작업 종료: 변경 없음")
    finally:
        await redis.aclose()


if __name__ == '__main__':
    asyncio.run(main())
