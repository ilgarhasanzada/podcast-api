import time
import logging
from typing import List, Dict, Any
import httpx
from .http_client import get_rotating_browser_headers

logger = logging.getLogger(__name__)

# Officially supported 26 markets on Spotify Charts
SPOTIFY_SUPPORTED_REGIONS = {
    'ar', 'at', 'au', 'br', 'ca', 'cl', 'co', 'de', 'dk', 'es',
    'fi', 'fr', 'gb', 'id', 'ie', 'in', 'it', 'jp', 'mx', 'nl',
    'no', 'nz', 'ph', 'pl', 'se', 'us'
}

SPOTIFY_CHARTS_BASE_URL = "https://podcastcharts.byspotify.com/api/charts"


def scrape_spotify_charts(
    region: str = "us",
    category: str = "top-podcasts",
    limit: int = 50,
    max_retries: int = 2
) -> List[Dict[str, Any]]:
    """
    Scrapes ranking data from Spotify Podcast Charts.
    URL: https://podcastcharts.byspotify.com/api/charts/{category}?region={region}
    - Skips request if region is unsupported to avoid unnecessary 400 errors.
    - Gracefully handles 400/404 responses when a category is not available in a country.
    """
    clean_region = region.lower().strip()

    # 1. Filter out unsupported regions (prevents unnecessary 400 Bad Requests)
    if clean_region not in SPOTIFY_SUPPORTED_REGIONS:
        logger.info(f"Spotify Charts does not support region '{clean_region.upper()}', skipping request.")
        return []

    # Category normalization (default: top-podcasts)
    clean_category = category.lower().strip() if category else "top-podcasts"
    if clean_category in ("top", "all"):
        clean_category = "top-podcasts"

    api_url = f"{SPOTIFY_CHARTS_BASE_URL}/{clean_category}"
    params = {
        "region": clean_region,
        "limit": limit
    }

    for attempt in range(1, max_retries + 1):
        headers = get_rotating_browser_headers()
        headers["Accept"] = "application/json"
        try:
            with httpx.Client(timeout=12.0) as client:
                response = client.get(api_url, params=params, headers=headers)

                # Spotify returns 400/404 for unsupported category/region pairs
                if response.status_code in (400, 404):
                    logger.info(f"Spotify Charts does not offer '{clean_category}' for '{clean_region.upper()}' ({response.status_code}).")
                    return []

                if response.status_code == 429:
                    logger.warning(f"Spotify Charts rate limit (429), attempt {attempt}/{max_retries}. Retrying with rotated user-agent...")
                    time.sleep(1.5 * attempt)
                    continue

                response.raise_for_status()
                data = response.json()

            results = []
            for idx, item in enumerate(data[:limit], start=1):
                title = item.get("showName", "").strip()
                episode_title = item.get("episodeName", "").strip()
                if not title and not episode_title:
                    continue
                if not title and episode_title:
                    title = episode_title

                show_uri = item.get("showUri", "")
                spotify_id = show_uri.replace("spotify:show:", "") if show_uri else ""

                ep_uri = item.get("episodeUri", "")
                episode_spotify_id = ep_uri.replace("spotify:episode:", "") if ep_uri else ""

                entry_data = {
                    "rank": idx,
                    "title": title,
                    "publisher": item.get("showPublisher", "").strip(),
                    "description": item.get("showDescription", "").strip(),
                    "cover_image_url": item.get("showImageUrl", "").strip(),
                    "spotify_id": spotify_id,
                    "source": "spotify",
                    "country": clean_region,
                    "category": clean_category,
                }
                if episode_title:
                    entry_data["episode_title"] = episode_title
                    entry_data["episode_spotify_id"] = episode_spotify_id
                    entry_data["episode_description"] = item.get("episodeDescription", "").strip()
                    entry_data["episode_cover_url"] = item.get("episodeImageUrl", "").strip()

                results.append(entry_data)

            logger.info(f"Successfully scraped {len(results)} podcasts from Spotify ({clean_region.upper()} / {clean_category}).")
            return results

        except (httpx.HTTPStatusError, httpx.TransportError, httpx.TimeoutException) as e:
            delay = 2 ** (attempt - 1)
            if attempt < max_retries:
                logger.warning(
                    f"Spotify charts request error ({e}), attempt {attempt}/{max_retries}. "
                    f"Retrying in {delay}s ({clean_region.upper()})..."
                )
                time.sleep(delay)
            else:
                logger.error(f"Spotify charts scraping failed after {max_retries} attempts ({clean_region.upper()}): {e}")
                return []
        except Exception as e:
            logger.error(f"Unexpected error while processing Spotify charts ({clean_region.upper()}): {e}")
            return []

    return []
