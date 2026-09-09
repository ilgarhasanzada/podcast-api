import logging
import httpx
from celery import shared_task
from apps.podcasts.models import Podcast
from apps.podcasts.services.rss_fetcher import fetch_and_sync_episodes

logger = logging.getLogger(__name__)


@shared_task(
    name="apps.podcasts.tasks.sync_episodes_task",
    bind=True,
    autoretry_for=(httpx.HTTPError, httpx.TimeoutException, ConnectionError, OSError),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=3,
    soft_time_limit=60,
    time_limit=90,
    rate_limit="180/m"
)
def sync_episodes_task(self, podcast_id: int, max_episodes: int | None = None):
    """
    Background task to synchronize all episodes for an individual podcast.
    - rate_limit="180/m": Prevents sudden traffic bursts to external media hosts.
    - autoretry_for: Exponential backoff with jitter on network timeouts.
    """
    try:
        podcast = Podcast.objects.get(id=podcast_id)
        return fetch_and_sync_episodes(podcast, max_episodes=max_episodes, raise_errors=True)
    except Podcast.DoesNotExist:
        return 0
    except (httpx.HTTPError, httpx.TimeoutException, ConnectionError, OSError) as exc:
        logger.warning(
            f"[{podcast_id}] RSS network error, Celery retrying (attempt {self.request.retries + 1}/3): {exc}"
        )
        raise exc
    except Exception as exc:
        logger.error(f"[{podcast_id}] Unexpected error in episode sync: {exc}")
        return 0


@shared_task(
    name="apps.podcasts.tasks.sync_episodes_batch_task",
    bind=True,
    soft_time_limit=300,
    time_limit=360
)
def sync_episodes_batch_task(self, podcast_ids: list, max_episodes: int | None = None):
    """
    Processes a batch of podcast IDs sequentially to minimize queue overhead and Redis memory consumption.
    """
    total_synced = 0
    for pid in podcast_ids:
        try:
            podcast = Podcast.objects.get(id=pid)
            total_synced += fetch_and_sync_episodes(podcast, max_episodes=max_episodes, raise_errors=False)
        except Podcast.DoesNotExist:
            continue
        except Exception as e:
            logger.warning(f"Error in batch episode sync for podcast {pid}: {e}")
    return total_synced


@shared_task(name="apps.podcasts.tasks.sync_missing_episodes_task")
def sync_missing_episodes_task(batch_size: int = 100, max_episodes: int | None = None, chunk_size: int = 10):
    """
    Finds podcasts that have a valid feed_url but zero episodes ingested, dispatching them in batches.
    """
    podcasts = list(
        Podcast.objects.filter(feed_url__isnull=False)
        .exclude(feed_url="")
        .filter(episodes__isnull=True)
        .order_by("id")
        .values_list("id", flat=True)[:batch_size]
    )
    if not podcasts:
        return 0

    batches_queued = 0
    for i in range(0, len(podcasts), chunk_size):
        chunk = podcasts[i:i + chunk_size]
        sync_episodes_batch_task.delay(chunk, max_episodes=max_episodes)
        batches_queued += 1

    logger.info(f"Celery: Dispatched episode sync for {len(podcasts)} podcasts ({batches_queued} batches).")
    return len(podcasts)


@shared_task(name="apps.podcasts.tasks.sync_all_existing_podcasts_episodes_task")
def sync_all_existing_podcasts_episodes_task(batch_size: int = 100, max_episodes: int | None = None, chunk_size: int = 10):
    """
    Periodically checks RSS feeds of existing podcasts in FIFO order (by updated_at) to fetch new releases.
    """
    podcasts = list(
        Podcast.objects.filter(feed_url__isnull=False)
        .exclude(feed_url="")
        .order_by("updated_at")
        .values_list("id", flat=True)[:batch_size]
    )
    if not podcasts:
        return 0

    batches_queued = 0
    for i in range(0, len(podcasts), chunk_size):
        chunk = podcasts[i:i + chunk_size]
        sync_episodes_batch_task.delay(chunk, max_episodes=max_episodes)
        batches_queued += 1

    logger.info(f"Celery: Dispatched periodic episode refresh for {len(podcasts)} podcasts ({batches_queued} batches).")
    return len(podcasts)

