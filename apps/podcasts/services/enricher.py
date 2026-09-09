import logging
import time
import json
import base64
import warnings
import httpx
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from django.utils.text import slugify
from apps.podcasts.models import Podcast, Category, PodcastRating
from .http_client import get_rotating_browser_headers

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

logger = logging.getLogger(__name__)

ITUNES_SEARCH_URL = "https://itunes.apple.com/search"


def fetch_apple_rating(apple_id: str, web_url: str = None) -> tuple[float | None, int]:
    """
    Fetches podcast rating and review count from Apple Podcasts (via JSON-LD schema or Customer Reviews RSS feed).
    """
    if not apple_id and not web_url:
        return None, 0

    url = web_url if (web_url and "podcasts.apple.com" in web_url) else f"https://podcasts.apple.com/us/podcast/id{apple_id}"
    headers = get_rotating_browser_headers()

    try:
        with httpx.Client(timeout=8.0, follow_redirects=True) as client:
            resp = client.get(url, headers=headers)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                for s in soup.find_all("script", type="application/ld+json"):
                    if not s.string:
                        continue
                    try:
                        data = json.loads(s.string)
                        agg = None
                        if isinstance(data, dict):
                            if "aggregateRating" in data:
                                agg = data["aggregateRating"]
                            elif "@graph" in data:
                                for item in data["@graph"]:
                                    if isinstance(item, dict) and "aggregateRating" in item:
                                        agg = item["aggregateRating"]
                                        break
                        if agg and isinstance(agg, dict):
                            rating_val = agg.get("ratingValue")
                            count_val = agg.get("reviewCount") or agg.get("ratingCount") or 0
                            if rating_val is not None:
                                return round(float(rating_val), 2), int(count_val)
                    except Exception:
                        continue

            # Fallback: Apple Customer Reviews RSS feed
            if apple_id:
                rss_url = f"https://itunes.apple.com/us/rss/customerreviews/id={apple_id}/json"
                rss_resp = client.get(rss_url, headers=headers)
                if rss_resp.status_code == 200:
                    entries = rss_resp.json().get("feed", {}).get("entry", [])
                    ratings = []
                    for entry in entries:
                        if "im:rating" in entry and "label" in entry["im:rating"]:
                            try:
                                ratings.append(float(entry["im:rating"]["label"]))
                            except (ValueError, TypeError):
                                pass
                    if ratings:
                        avg_rating = round(sum(ratings) / len(ratings), 2)
                        return avg_rating, len(ratings)

    except Exception as e:
        logger.debug(f"Error fetching Apple rating ({apple_id}): {e}")

    return None, 0


def fetch_spotify_rating(spotify_id: str, max_retries: int = 2) -> tuple[float | None, int]:
    """
    Extracts live podcast rating and review counts from Spotify SSR initialState block.
    Rotates browser headers to ensure resilience against rate limiting.
    """
    if not spotify_id:
        return None, 0

    url = f"https://open.spotify.com/show/{spotify_id}"

    for attempt in range(1, max_retries + 1):
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        try:
            with httpx.Client(timeout=10.0, follow_redirects=True) as client:
                resp = client.get(url, headers=headers)

                if resp.status_code == 429:
                    logger.warning(f"Spotify rating rate limit (429) for {spotify_id}, attempt {attempt}/{max_retries}. Retrying...")
                    time.sleep(1.0 * attempt)
                    continue

                if resp.status_code != 200:
                    return None, 0

                soup = BeautifulSoup(resp.text, "html.parser")
                init_script = soup.find("script", id="initialState")
                if not init_script or not init_script.string:
                    return None, 0

                decoded = base64.b64decode(init_script.string).decode("utf-8", errors="ignore")
                data = json.loads(decoded)
                items = data.get("entities", {}).get("items", {})

                show = items.get(f"spotify:show:{spotify_id}") or items.get(spotify_id)
                if not show and items:
                    for k, v in items.items():
                        if "spotify:show" in k and isinstance(v, dict):
                            show = v
                            break

                if show and isinstance(show, dict) and "rating" in show:
                    avg_obj = show["rating"].get("averageRating", {})
                    avg = avg_obj.get("average")
                    total = avg_obj.get("totalRatings", 0)
                    if avg is not None:
                        return round(float(avg), 2), int(total)
                return None, 0

        except Exception as e:
            logger.debug(f"Error fetching Spotify rating ({spotify_id}): {e}")

    return None, 0


def enrich_podcast_metadata(podcast: Podcast) -> bool:
    """
    Enriches podcast metadata using Apple Podcasts (iTunes) API and public web metadata:
    - Publisher / author
    - High-resolution cover image URL (600x600)
    - Valid RSS feed URL (essential for episode synchronization)
    - Category / genre associations
    - Apple Podcast ID and website URLs
    - Multi-platform ratings and review counts (Apple & Spotify)
    """
    if not podcast.title:
        return False

    has_changed = False

    try:
        # If core metadata is missing, query iTunes API
        if not podcast.feed_url or not podcast.apple_id or not podcast.cover_image_url:
            if podcast.apple_id:
                api_endpoint = "https://itunes.apple.com/lookup"
                params = {"id": podcast.apple_id}
            else:
                api_endpoint = ITUNES_SEARCH_URL
                params = {
                    "term": podcast.title,
                    "media": "podcast",
                    "entity": "podcast",
                    "limit": 1,
                }
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json",
            }

            with httpx.Client(timeout=10.0) as client:
                response = client.get(api_endpoint, params=params, headers=headers)
                
                # Retry on rate limit (429)
                if response.status_code == 429:
                    logger.warning("Apple Podcasts rate limit (429) encountered, waiting 2.0s...")
                    time.sleep(2.0)
                    response = client.get(api_endpoint, params=params, headers=headers)

                response.raise_for_status()
                data = response.json()

            results = data.get("results", [])
            if results:
                item = results[0]

                # 1. Update core metadata
                if item.get("artistName") and not podcast.publisher:
                    podcast.publisher = item.get("artistName")
                    has_changed = True

                if item.get("artworkUrl600"):
                    podcast.cover_image_url = item.get("artworkUrl600")
                    has_changed = True
                elif item.get("artworkUrl100") and not podcast.cover_image_url:
                    podcast.cover_image_url = item.get("artworkUrl100")
                    has_changed = True

                if item.get("feedUrl") and not podcast.feed_url:
                    podcast.feed_url = item.get("feedUrl")
                    has_changed = True

                if item.get("collectionViewUrl") and not podcast.website_url:
                    podcast.website_url = item.get("collectionViewUrl")
                    has_changed = True

                if item.get("collectionId") and not podcast.apple_id:
                    podcast.apple_id = str(item.get("collectionId"))
                    has_changed = True

                if not podcast.frequency:
                    podcast.frequency = "weekly"
                    has_changed = True

                # Link categories
                genres = item.get("genres", [])
                for genre_name in genres:
                    genre_name = str(genre_name).strip()
                    if genre_name and genre_name.lower() != "podcasts":
                        category_slug = slugify(genre_name)
                        category, _ = Category.objects.get_or_create(
                            slug=category_slug,
                            defaults={"name": genre_name}
                        )
                        podcast.categories.add(category)

        # 1.5. If description is empty and feed_url exists, parse description from RSS XML
        if not podcast.description and podcast.feed_url:
            try:
                import feedparser
                with httpx.Client(timeout=8.0, follow_redirects=True) as client:
                    resp = client.get(
                        podcast.feed_url,
                        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Podcast-Aggregator/1.0"}
                    )
                    if resp.status_code == 200:
                        parsed_feed = feedparser.parse(resp.content)
                        raw_desc = (
                            parsed_feed.feed.get("description")
                            or parsed_feed.feed.get("summary")
                            or parsed_feed.feed.get("subtitle")
                            or ""
                        )
                        if raw_desc:
                            clean_desc = BeautifulSoup(raw_desc, "html.parser").get_text(separator=" ").strip()
                            if clean_desc:
                                podcast.description = clean_desc
                                has_changed = True
                                logger.info(f"Successfully extracted description from RSS feed for '{podcast.title}'.")
            except Exception as e:
                logger.debug(f"Error extracting description from RSS ({podcast.title}): {e}")

        # 2. Fetch multi-platform ratings (Apple & Spotify)
        # A) Apple Podcasts rating
        if podcast.apple_id:
            apple_rating_obj = podcast.platform_ratings.filter(source=PodcastRating.Source.APPLE).first()
            if not apple_rating_obj:
                rating_val, rating_cnt = fetch_apple_rating(podcast.apple_id, podcast.website_url)
                if rating_val is not None:
                    PodcastRating.objects.update_or_create(
                        podcast=podcast,
                        source=PodcastRating.Source.APPLE,
                        defaults={
                            "rating": rating_val,
                            "rating_count": rating_cnt,
                            "url": podcast.apple_url,
                        }
                    )
                    has_changed = True
                    logger.info(f"Saved Apple rating for '{podcast.title}': {rating_val} ({rating_cnt} votes)")

        # B) Spotify rating
        if podcast.spotify_id:
            spotify_rating_obj = podcast.platform_ratings.filter(source=PodcastRating.Source.SPOTIFY).first()
            if not spotify_rating_obj:
                sp_val, sp_cnt = fetch_spotify_rating(podcast.spotify_id)
                if sp_val is not None:
                    PodcastRating.objects.update_or_create(
                        podcast=podcast,
                        source=PodcastRating.Source.SPOTIFY,
                        defaults={
                            "rating": sp_val,
                            "rating_count": sp_cnt,
                            "url": podcast.spotify_url,
                        }
                    )
                    has_changed = True
                    logger.info(f"Saved Spotify rating for '{podcast.title}': {sp_val} ({sp_cnt} votes)")

        # C) Synchronize Podcast model aggregated rating fields with platform_ratings
        ratings = list(podcast.platform_ratings.values_list("rating", "rating_count"))
        if ratings:
            total_count = sum(cnt for _, cnt in ratings if cnt)
            if total_count > 0:
                weighted_rating = round(sum(r * cnt for r, cnt in ratings if r and cnt) / total_count, 2)
            else:
                valid_r = [r for r, _ in ratings if r]
                weighted_rating = round(sum(valid_r) / len(valid_r), 2) if valid_r else None

            if weighted_rating is not None and (podcast.rating != weighted_rating or podcast.rating_count != total_count):
                podcast.rating = weighted_rating
                podcast.rating_count = total_count
                has_changed = True

        if has_changed:
            podcast.save()
            logger.info(f"Successfully enriched podcast '{podcast.title}'. Feed: {podcast.feed_url}")
            return True

        return False

    except Exception as e:
        logger.error(f"Error during enrichment for '{podcast.title}': {e}")
        return False
