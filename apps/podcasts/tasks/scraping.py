import logging
from celery import shared_task
from apps.podcasts.services.pipeline import run_full_ingestion_pipeline
from apps.podcasts.services.country_discovery import CountryDiscoveryService
from apps.podcasts.services.category_discovery import CategoryDiscoveryService

logger = logging.getLogger(__name__)


@shared_task(name="apps.podcasts.tasks.scrape_single_chart_task")
def scrape_single_chart_task(
    country: str,
    category: str,
    limit: int = 50,
    fetch_episodes_for_top: int | None = None
):
    """
    Individual asynchronous background task to scrape charts for a single country and category.
    Enables parallel distributed execution across Celery workers.
    """
    return run_full_ingestion_pipeline(
        country=country,
        category=category,
        limit=limit,
        fetch_episodes_for_top=fetch_episodes_for_top
    )


@shared_task(name="apps.podcasts.tasks.daily_chart_scraping_task")
def daily_chart_scraping_task(
    countries: list[str] = None,
    categories: list[str] = None,
    limit: int = 50,
    fetch_episodes_for_top: int | None = None,
    dispatch_async: bool = True
):
    """
    Daily scheduled Celery task to scrape Spotify and Podchaser charts across active countries and categories.
    Active country and category lists are dynamically read from database tables (Country and ChartCategory).
    """
    if isinstance(countries, str):
        target_countries = [countries]
    elif countries:
        target_countries = list(countries)
    else:
        try:
            from apps.podcasts.models import Country
            active_codes = list(Country.objects.filter(is_active=True).values_list('code', flat=True))
            target_countries = active_codes if active_codes else ["us", "gb", "ca", "de"]
        except Exception:
            spotify_markets = CountryDiscoveryService.get_spotify_countries()
            target_countries = spotify_markets if spotify_markets else ["us", "gb", "ca", "de"]

    if isinstance(categories, str):
        target_categories = [categories]
    elif categories:
        target_categories = list(categories)
    else:
        try:
            from apps.podcasts.models import ChartCategory
            active_cats = list(ChartCategory.objects.filter(is_active=True).values_list('slug', flat=True))
            target_categories = active_cats if active_cats else ["top-podcasts", "top-episodes"]
        except Exception:
            target_categories = ["top-podcasts", "top-episodes"]

    logger.info(f"Celery: Daily chart scraping started ({len(target_countries)} Countries x {len(target_categories)} Categories)")

    if dispatch_async:
        dispatched_count = 0
        for country in target_countries:
            for cat in target_categories:
                scrape_single_chart_task.delay(
                    country=country,
                    category=cat,
                    limit=limit,
                    fetch_episodes_for_top=fetch_episodes_for_top
                )
                dispatched_count += 1
        logger.info(f"Celery: Dispatched {dispatched_count} individual chart scraping tasks to worker queue.")
        return {"dispatched_tasks": dispatched_count}

    all_results = []
    seen_podcast_ids = set()
    seen_enrichment_ids = set()
    for country in target_countries:
        for cat in target_categories:
            result = run_full_ingestion_pipeline(
                country=country,
                category=cat,
                limit=limit,
                fetch_episodes_for_top=fetch_episodes_for_top,
                seen_podcast_ids=seen_podcast_ids,
                seen_enrichment_ids=seen_enrichment_ids,
            )
            all_results.append(result)
    logger.info(f"Celery: Daily chart scraping completed successfully: {len(all_results)} combinations processed.")
    return all_results


@shared_task(name="apps.podcasts.tasks.discover_and_cache_countries_task")
def discover_and_cache_countries_task():
    """
    Weekly scheduled Celery task to dynamically discover official country storefronts from Apple and Spotify,
    refreshing the 7-day Redis cache.
    """
    logger.info("Celery: Dynamic country discovery task started...")
    apple_countries = CountryDiscoveryService.get_apple_countries(force_refresh=True)
    spotify_countries = CountryDiscoveryService.get_spotify_countries(force_refresh=True)
    logger.info(f"Celery: Countries updated successfully. Apple: {len(apple_countries)}, Spotify: {len(spotify_countries)}")
    return {
        "apple_count": len(apple_countries),
        "spotify_count": len(spotify_countries)
    }


@shared_task(name="apps.podcasts.tasks.discover_and_sync_categories_task")
def discover_and_sync_categories_task():
    """
    Weekly scheduled Celery task to dynamically verify official Apple Podcasts iTunes genres
    and synchronize new categories and parent hierarchies into the database.
    """
    logger.info("Celery: Dynamic category discovery task started...")
    result = CategoryDiscoveryService.sync_categories_to_db()
    logger.info(f"Celery: Categories updated successfully: {result}")
    return result


