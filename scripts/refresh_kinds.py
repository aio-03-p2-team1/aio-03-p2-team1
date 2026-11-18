"""Daily cron entry point; synchronize only when seven days have elapsed."""
import asyncio
import time

from redis.asyncio import from_url

from backend.config import Settings
from scripts.kind_sync import fetch_records


async def refresh(settings, redis):
    # A single cron worker owns this lock; expiry protects against killed workers.
    async with redis.lock('meet-again:kinds:refresh-lock', timeout=3600, blocking_timeout=1):
        last = await redis.get('meet-again:kinds:last-refresh')
        if last and time.time() - float(last) < 7 * 86400:
            return False
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
                except Exception:
                    if attempt == 3:
                        raise
                    await asyncio.sleep(0.5 * 2 ** attempt)
        finally:
            sink.close()
        # Transaction keeps cache invalidation and successful refresh time together.
        async with redis.pipeline(transaction=True) as pipe:
            pipe.delete(*(f'meet-again:kinds:{s}' for s in ('dog', 'cat', 'etc')))
            pipe.set('meet-again:kinds:last-refresh', str(time.time()))
            await pipe.execute()
        return True


async def main():
    settings = Settings()
    redis = from_url(settings.redis_url)
    try:
        await refresh(settings, redis)
    finally:
        await redis.aclose()


if __name__ == '__main__':
    asyncio.run(main())
