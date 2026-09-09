import logging
import io
from datetime import datetime, timezone
import time
import feedparser
import httpx
from bs4 import BeautifulSoup
from apps.podcasts.models import Podcast, Episode, ChartRanking
from apps.podcasts.services.http_client import get_random_user_agent

logger = logging.getLogger(__name__)

# Resilient 25-second timeout for RSS feeds
RSS_TIMEOUT = httpx.Timeout(25.0, connect=10.0, read=25.0, write=15.0)
MAX_FEED_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB safety limit


def fetch_and_sync_episodes(
    podcast: Podcast | int,
    max_episodes: int | None = None,
    raise_errors: bool = False
) -> int:
    """
    Fetches all episodes from a podcast's RSS feed and synchronizes them to the database via bulk UPSERT.
    - Streaming: Reads large feeds (25MB+) in chunks to prevent excessive memory consumption.
    - 25s Timeout: Accommodates slow external media hosts (Megaphone, Libsyn, Art19).
    - Bulk UPSERT: Creates or updates episodes in a single SQL query matching on unique GUID.
    - Frequency calculation: Dynamically computes release cadence from publishing intervals.
    - raise_errors: Bubbles exceptions when invoked by Celery for autoretry.
    """
    if isinstance(podcast, (int, str)):
        podcast = Podcast.objects.filter(id=int(podcast)).first()
        if not podcast:
            return 0

    if not podcast.feed_url:
        logger.warning(f"No RSS feed URL found for '{podcast.title}'.")
        return 0

    try:
        # Fetch RSS feed with resilient timeout and chunked streaming
        headers = {
            "User-Agent": get_random_user_agent(),
            "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
        }
        buffer = io.BytesIO()
        with httpx.Client(timeout=RSS_TIMEOUT, follow_redirects=True) as client:
            with client.stream("GET", podcast.feed_url, headers=headers) as response:
                response.raise_for_status()
                for chunk in response.iter_bytes(chunk_size=65536):
                    buffer.write(chunk)
                    if buffer.tell() > MAX_FEED_SIZE_BYTES:
                        logger.warning(f"RSS feed exceeds 50MB safety limit for '{podcast.title}'. Streaming aborted.")
                        break

        buffer.seek(0)
        feed = feedparser.parse(buffer)

        # If podcast description is empty, populate from RSS channel metadata
        if not podcast.description:
            raw_desc = (
                feed.feed.get("description")
                or feed.feed.get("summary")
                or feed.feed.get("subtitle")
                or ""
            )
            if raw_desc:
                clean_desc = BeautifulSoup(raw_desc, "html.parser").get_text(separator=" ").strip()
                if clean_desc:
                    podcast.description = clean_desc
                    podcast.save(update_fields=["description"])

        entries = feed.entries[:max_episodes] if max_episodes else feed.entries
        episodes_by_guid = {}

        for entry in entries:
            # 1. Unique episode identifier (GUID)
            guid = entry.get("id") or entry.get("guid")
            
            # Extract audio URL (enclosures)
            audio_url = ""
            if hasattr(entry, "enclosures") and entry.enclosures:
                for enc in entry.enclosures:
                    if "audio" in enc.get("type", "") or enc.get("href"):
                        audio_url = enc.get("href", "")
                        break

            if not audio_url:
                audio_url = entry.get("link", "")

            if not guid:
                guid = audio_url

            if not guid:
                continue

            # 2. Episode attributes
            title = entry.get("title", "Untitled Episode")[:500]
            description = entry.get("summary") or entry.get("description", "")
            duration = entry.get("itunes_duration", "")
            
            # Publication timestamp
            published_at = None
            if entry.get("published_parsed"):
                try:
                    ts = time.mktime(entry.published_parsed)
                    published_at = datetime.fromtimestamp(ts, tz=timezone.utc)
                except Exception:
                    published_at = None

            # Episode artwork
            ep_image = ""
            if hasattr(entry, "image") and isinstance(entry.image, dict):
                ep_image = entry.image.get("href", "")
            if not ep_image:
                ep_image = podcast.cover_image_url

            clean_guid = str(guid)[:500]
            episodes_by_guid[clean_guid] = Episode(
                podcast=podcast,
                guid=clean_guid,
                title=title,
                description=description,
                audio_url=str(audio_url)[:1500],
                published_at=published_at,
                duration=str(duration)[:50],
                cover_image_url=str(ep_image)[:1000],
            )

        synced_count = 0
        if episodes_by_guid:
            # 3. High-performance Bulk UPSERT (single SQL query)
            Episode.objects.bulk_create(
                episodes_by_guid.values(),
                update_conflicts=True,
                unique_fields=["podcast", "guid"],
                update_fields=["title", "description", "audio_url", "published_at", "duration", "cover_image_url"]
            )
            synced_count = len(episodes_by_guid)

            # 4. Link chart ranking stubs that lacked audio URLs to newly ingested RSS episodes
            stubs = ChartRanking.objects.filter(podcast=podcast, episode__isnull=False, episode__audio_url="")
            for r in stubs:
                better = podcast.episodes.filter(title__iexact=r.episode.title).exclude(audio_url="").first()
                if not better and len(r.episode.title) > 10:
                    better = podcast.episodes.filter(title__icontains=r.episode.title[:35]).exclude(audio_url="").first()
                if better:
                    old_ep = r.episode
                    r.episode = better
                    r.save(update_fields=["episode"])
                    if old_ep.chart_rankings.count() == 0:
                        old_ep.delete()

            # 5. Dynamically calculate publishing frequency
            recent_dates = list(podcast.episodes.filter(published_at__isnull=False).order_by("-published_at").values_list("published_at", flat=True)[:6])
            if len(recent_dates) >= 3:
                diffs = [(recent_dates[i] - recent_dates[i+1]).total_seconds() / 86400.0 for i in range(len(recent_dates)-1)]
                avg_days = sum(diffs) / len(diffs)
                freq = "daily" if avg_days <= 2.5 else ("weekly" if avg_days <= 10.0 else ("bi-weekly" if avg_days <= 20.0 else ("monthly" if avg_days <= 45.0 else "irregular")))
                if podcast.frequency != freq:
                    podcast.frequency = freq
                    podcast.save(update_fields=["frequency"])

        # Update podcast updated_at timestamp to maintain fair FIFO polling order
        from django.utils import timezone as dj_timezone
        Podcast.objects.filter(id=podcast.id).update(updated_at=dj_timezone.now())

        logger.info(f"Successfully synced {synced_count} episodes for '{podcast.title}' (Bulk UPSERT).")
        return synced_count

    except Exception as e:
        logger.error(f"Error fetching episodes for '{podcast.title}': {e}")
        if raise_errors:
            raise
        return 0
