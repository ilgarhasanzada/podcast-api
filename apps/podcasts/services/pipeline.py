import logging
from typing import Dict, Any
from django.utils import timezone
from django.utils.text import slugify

from apps.podcasts.models import Podcast, ChartRanking, Country, ChartCategory, PodcastCategory, Episode
from apps.podcasts.services.spotify_scraper import scrape_spotify_charts
from apps.podcasts.services.podchaser_scraper import scrape_podchaser_charts
from apps.podcasts.services.enricher import enrich_podcast_metadata
from apps.podcasts.services.rss_fetcher import fetch_and_sync_episodes

logger = logging.getLogger(__name__)

def run_full_ingestion_pipeline(
    country: str = "us",
    category: str = "top-podcasts",
    limit: int = 50,
    fetch_episodes_for_top: int | None = None,
    max_episodes_per_podcast: int | None = None,
    async_episodes: bool = True,
    seen_podcast_ids: set | None = None,
    seen_enrichment_ids: set | None = None,
) -> Dict[str, Any]:
    """
    Executes the full podcast ingestion, enrichment, and episode synchronization pipeline:
    1. Scrapes Spotify Charts (with region and category support).
    2. Scrapes Podchaser / Apple Podcasts charts (with network resilience).
    3. For each podcast:
       - Retrieves or creates the Podcast model record.
       - Enriches metadata and multi-platform ratings via Apple Podcasts and RSS.
       - Records daily chart rankings in ChartRanking for historical tracking.
    4. Asynchronously dispatches episode fetching for top podcasts to Celery workers.
    """
    today = timezone.now().date()
    stats = {
        "date": str(today),
        "country": country.lower(),
        "category": category.lower(),
        "spotify_scraped": 0,
        "podchaser_scraped": 0,
        "rankings_saved": 0,
        "podcasts_enriched": 0,
        "episodes_synced": 0,
        "episodes_queued": 0,
    }

    logger.info(f"[{today}] Podcast ingestion pipeline started (Country: {country.upper()}, Category: {category})")

    # 1. Scrape Spotify and Podchaser charts
    spotify_items = scrape_spotify_charts(region=country, category=category, limit=limit)
    podchaser_items = scrape_podchaser_charts(country=country, category=category, limit=limit)

    stats["spotify_scraped"] = len(spotify_items)
    stats["podchaser_scraped"] = len(podchaser_items)

    all_chart_entries = spotify_items + podchaser_items

    if seen_podcast_ids is None:
        seen_podcast_ids = set()
    if seen_enrichment_ids is None:
        seen_enrichment_ids = set()

    for entry in all_chart_entries:
        title = entry.get("title")
        if not title:
            continue

        source = entry.get("source", "")
        spotify_id = entry.get("spotify_id", "")
        apple_id = entry.get("apple_id", "")

        default_website = ""
        if source == "spotify" and spotify_id:
            default_website = f"https://open.spotify.com/show/{spotify_id}"
        elif apple_id:
            default_website = f"https://podcasts.apple.com/us/podcast/id{apple_id}"

        # 2. Retrieve or create Podcast record
        podcast, created = Podcast.objects.get_or_create(
            title=title,
            defaults={
                "publisher": entry.get("publisher", ""),
                "description": entry.get("description", ""),
                "cover_image_url": entry.get("cover_image_url", ""),
                "website_url": default_website,
                "spotify_id": spotify_id,
                "apple_id": apple_id,
            }
        )

        if not created:
            fields_to_update = []
            if spotify_id and not podcast.spotify_id:
                podcast.spotify_id = spotify_id
                fields_to_update.append("spotify_id")
            if apple_id and not podcast.apple_id:
                podcast.apple_id = apple_id
                fields_to_update.append("apple_id")
            if source == "spotify" and spotify_id and (not podcast.website_url or "podcasts.apple.com" in podcast.website_url):
                podcast.website_url = f"https://open.spotify.com/show/{spotify_id}"
                fields_to_update.append("website_url")
            if fields_to_update:
                podcast.save(update_fields=fields_to_update)

        # 2.1. Link genres to PodcastCategory if returned by scraper
        genres = entry.get("genres", [])
        for g_name in genres:
            g_name = str(g_name).strip()
            if g_name and g_name.lower() != "podcasts":
                cat_slug = slugify(g_name)
                cat_obj, _ = PodcastCategory.objects.get_or_create(
                    slug=cat_slug,
                    defaults={"name": g_name}
                )
                podcast.categories.add(cat_obj)

        # 3. Metadata enrichment (if feed_url, cover, description, or ratings are missing)
        needs_enrichment = not podcast.feed_url or not podcast.cover_image_url or not podcast.description or not podcast.platform_ratings.exists()
        if needs_enrichment and (podcast.id not in seen_enrichment_ids):
            seen_enrichment_ids.add(podcast.id)
            is_episode_ranking = bool(entry.get("episode_title"))
            if async_episodes and not is_episode_ranking:
                try:
                    from apps.podcasts.tasks import enrich_single_podcast_task
                    enrich_single_podcast_task.delay(
                        podcast.id,
                        sync_episodes_after=True,
                        max_episodes=max_episodes_per_podcast
                    )
                    stats["podcasts_enrichment_queued"] = stats.get("podcasts_enrichment_queued", 0) + 1
                except Exception as e:
                    logger.debug(f"Celery enrichment task dispatch failed, executing synchronously: {e}")
                    if enrich_podcast_metadata(podcast):
                        stats["podcasts_enriched"] += 1
                        podcast.refresh_from_db()
            else:
                if enrich_podcast_metadata(podcast):
                    stats["podcasts_enriched"] += 1
                    podcast.refresh_from_db()

        # 4. Record ChartRanking (historical data is retained)
        source = entry.get("source")
        category_name = entry.get("category") or category
        rank = entry.get("rank")

        # Retrieve or create Country and ChartCategory foreign keys
        country_obj, _ = Country.objects.get_or_create(
            code=country.lower(),
            defaults={"name": country.upper()}
        )
        chart_cat_obj, _ = ChartCategory.objects.get_or_create(
            slug=category_name.lower(),
            defaults={"name": category_name.replace("-", " ").title()}
        )

        # 4.1. If ranking corresponds to an individual episode, link Episode model
        episode_obj = None
        if entry.get("episode_title"):
            ep_title = str(entry.get("episode_title")).strip()
            ep_spotify_id = entry.get("episode_spotify_id") or ""

            # If podcast has no audio episodes yet but feed_url is present, fetch from RSS
            if not podcast.episodes.filter(audio_url__gt="").exists() and podcast.feed_url:
                try:
                    fetch_and_sync_episodes(podcast, max_episodes=50)
                except Exception as e:
                    logger.debug(f"RSS episode fetch error: {e}")

            # Match against existing RSS episodes (preferring full audio episode)
            episode_obj = podcast.episodes.filter(title__iexact=ep_title).order_by("-audio_url", "-published_at").first()
            if not episode_obj and len(ep_title) > 10:
                episode_obj = podcast.episodes.filter(title__icontains=ep_title[:40]).order_by("-audio_url", "-published_at").first()

            if not episode_obj:
                ep_guid = ep_spotify_id or ep_title
                episode_obj, _ = Episode.objects.get_or_create(
                    podcast=podcast,
                    guid=str(ep_guid)[:500],
                    defaults={
                        "title": ep_title[:500],
                        "description": entry.get("episode_description", ""),
                        "audio_url": "",
                        "cover_image_url": entry.get("episode_cover_url", "") or podcast.cover_image_url,
                    }
                )

        # Remove previous rank conflict for the same day to satisfy UniqueConstraint
        if episode_obj:
            ChartRanking.objects.filter(
                source=source,
                country=country_obj,
                category=chart_cat_obj,
                date=today,
                episode=episode_obj
            ).exclude(rank=rank).delete()
        else:
            ChartRanking.objects.filter(
                source=source,
                country=country_obj,
                category=chart_cat_obj,
                date=today,
                podcast=podcast,
                episode__isnull=True
            ).exclude(rank=rank).delete()

        ranking, _ = ChartRanking.objects.update_or_create(
            source=source,
            country=country_obj,
            category=chart_cat_obj,
            date=today,
            rank=rank,
            defaults={"podcast": podcast, "episode": episode_obj}
        )
        stats["rankings_saved"] += 1

        # 5. Fetch episodes for podcast (asynchronously via Celery or synchronously)
        should_fetch_episodes = (fetch_episodes_for_top is None) or (rank <= fetch_episodes_for_top)
        if should_fetch_episodes and (podcast.id not in seen_podcast_ids):
            seen_podcast_ids.add(podcast.id)
            if podcast.feed_url:
                if async_episodes:
                    try:
                        from apps.podcasts.tasks import sync_episodes_task
                        sync_episodes_task.delay(podcast.id, max_episodes=max_episodes_per_podcast)
                        stats["episodes_queued"] += 1
                    except Exception as e:
                        logger.debug(f"Celery task dispatch failed, executing synchronously: {e}")
                        ep_count = fetch_and_sync_episodes(podcast, max_episodes=max_episodes_per_podcast)
                        stats["episodes_synced"] += ep_count
                else:
                    ep_count = fetch_and_sync_episodes(podcast, max_episodes=max_episodes_per_podcast)
                    stats["episodes_synced"] += ep_count

    logger.info(f"[{today}] Ingestion pipeline completed: {stats}")
    return stats

