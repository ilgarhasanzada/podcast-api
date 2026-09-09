import logging
from celery import shared_task
from apps.podcasts.models import Podcast
from apps.podcasts.services.enricher import enrich_podcast_metadata

logger = logging.getLogger(__name__)


@shared_task(
    name="apps.podcasts.tasks.enrich_single_podcast_task",
    bind=True,
    max_retries=2,
    default_retry_delay=5,
    soft_time_limit=30,
    time_limit=45,
    rate_limit="180/m"
)
def enrich_single_podcast_task(self, podcast_id: int, sync_episodes_after: bool = False, max_episodes: int | None = None):
    """
    Background task to enrich metadata and ratings for an individual podcast.
    Includes rate limiting to prevent 429 throttling from external APIs.
    """
    try:
        podcast = Podcast.objects.get(id=podcast_id)
        had_feed = bool(podcast.feed_url)
        enriched = enrich_podcast_metadata(podcast)
        if enriched or had_feed:
            podcast.refresh_from_db()
            # If podcast feed_url exists and episodes have not been ingested yet:
            if podcast.feed_url and not podcast.episodes.exists():
                from apps.podcasts.tasks.episodes import sync_episodes_task
                sync_episodes_task.delay(podcast.id, max_episodes=max_episodes)
        return enriched
    except Podcast.DoesNotExist:
        return False
    except Exception as exc:
        logger.warning(f"Enrichment error ({podcast_id}): {exc}")
        return False


@shared_task(
    name="apps.podcasts.tasks.enrich_podcasts_batch_task",
    bind=True,
    soft_time_limit=180,
    time_limit=240
)
def enrich_podcasts_batch_task(self, podcast_ids: list, sync_episodes_after: bool = False, max_episodes: int | None = None):
    """
    Enriches a batch of podcast IDs to optimize worker queue overhead.
    """
    enriched_count = 0
    episodes_to_sync = []
    for pid in podcast_ids:
        try:
            podcast = Podcast.objects.get(id=pid)
            had_feed = bool(podcast.feed_url)
            enriched = enrich_podcast_metadata(podcast)
            if enriched:
                enriched_count += 1
            if enriched or had_feed:
                podcast.refresh_from_db()
                if podcast.feed_url and not podcast.episodes.exists():
                    episodes_to_sync.append(podcast.id)
        except Podcast.DoesNotExist:
            continue
        except Exception as exc:
            logger.warning(f"Batch enrichment error ({pid}): {exc}")

    if episodes_to_sync and sync_episodes_after:
        from apps.podcasts.tasks.episodes import sync_episodes_batch_task
        for i in range(0, len(episodes_to_sync), 10):
            chunk = episodes_to_sync[i:i + 10]
            sync_episodes_batch_task.delay(chunk, max_episodes=max_episodes)

    return enriched_count


@shared_task(name="apps.podcasts.tasks.enrich_all_ratings_task")
def enrich_all_ratings_task(limit: int = 50):
    """Background task to fetch ratings for podcasts currently missing platform reviews."""
    unrated = Podcast.objects.filter(platform_ratings__isnull=True).distinct()[:limit]
    count = 0
    for p in unrated:
        if enrich_podcast_metadata(p):
            count += 1
    logger.info(f"Celery: Enriched ratings for {count} podcasts.")
    return count
