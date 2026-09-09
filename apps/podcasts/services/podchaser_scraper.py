import os
import time
import logging
from typing import List, Dict, Any
import httpx

logger = logging.getLogger(__name__)

# Public RSS feed representing Apple Podcasts charts (default board on Podchaser)
PODCHASER_APPLE_CHARTS_URL = "https://rss.marketingtools.apple.com/api/v2/{country}/podcasts/top/{limit}/podcasts.json"
PODCHASER_GRAPHQL_URL = "https://api.podchaser.com/graphql"


_GENRE_ID_CACHE: Dict[str, int | None] = {}


def get_apple_genre_id(category_slug: str) -> int | None:
    """
    Dynamically retrieves the official Apple genre ID from the ChartCategory database table.
    """
    clean_slug = category_slug.lower().strip()
    if clean_slug in _GENRE_ID_CACHE:
        return _GENRE_ID_CACHE[clean_slug]
    try:
        from apps.podcasts.models import ChartCategory
        genre_id = ChartCategory.objects.filter(slug=clean_slug).values_list("apple_genre_id", flat=True).first()
        _GENRE_ID_CACHE[clean_slug] = genre_id
        return genre_id
    except Exception as e:
        logger.debug(f"Error retrieving genre_id from ChartCategory: {e}")
        return None


def scrape_podchaser_charts(country: str = "us", category: str = "top-podcasts", limit: int = 50, max_retries: int = 3) -> List[Dict[str, Any]]:
    """
    Scrapes chart ranking data from Podchaser Charts (https://www.podchaser.com/charts).
    Uses the official GraphQL API when configured, or the underlying Apple Podcasts chart feeds.
    Includes exponential backoff and retry handling for 502/503/504 network errors.
    """
    api_key = os.getenv("PODCHASER_API_KEY")
    clean_category = category.lower().strip() if category else "top-podcasts"

    if not api_key and clean_category == "top-episodes":
        logger.info("Podchaser public feed only provides show-level charts. Spotify charts are used for 'top-episodes'.")
        return []

    genre_id = get_apple_genre_id(clean_category)
    if not api_key and clean_category != "top-podcasts" and not genre_id:
        logger.info(f"Podchaser/Apple does not provide charts for '{clean_category}', skipping.")
        return []

    # 1. If PODCHASER_API_KEY is configured, query official GraphQL API
    if api_key:
        try:
            query = """
            query GetCharts($country: String!, $limit: Int!) {
              charts(platform: APPLE_PODCASTS, day: "latest", country: $country, first: $limit) {
                data {
                  position
                  category
                  podcast {
                    id
                    title
                    description
                    imageUrl
                  }
                }
              }
            }
            """
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            with httpx.Client(timeout=15.0) as client:
                res = client.post(PODCHASER_GRAPHQL_URL, json={"query": query, "variables": {"country": country.upper(), "limit": limit}}, headers=headers)
                res.raise_for_status()
                data = res.json()
                
            entries = data.get("data", {}).get("charts", {}).get("data", [])
            if entries:
                results = []
                for item in entries:
                    pod = item.get("podcast") or {}
                    results.append({
                        "rank": item.get("position"),
                        "title": pod.get("title", "").strip(),
                        "description": pod.get("description", "").strip(),
                        "cover_image_url": pod.get("imageUrl", "").strip(),
                        "source": "podchaser",
                        "country": country.lower(),
                        "category": clean_category,
                    })
                return results
        except Exception as e:
            logger.warning(f"Podchaser GraphQL error, falling back to alternative feed: {e}")

    # 2. Standard Podchaser / Apple Podcasts charts feed with retries
    # Apple RSS v2 API supports up to 100 items; iTunes RSS v1 is used for limits up to 200 or specific genre IDs
    headers = {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    fetch_limit = min(limit, 200)
    if genre_id:
        url = f"https://itunes.apple.com/{country.lower()}/rss/toppodcasts/limit={fetch_limit}/genre={genre_id}/json"
        use_v1 = True
    elif limit > 100:
        url = f"https://itunes.apple.com/{country.lower()}/rss/toppodcasts/limit={fetch_limit}/json"
        use_v1 = True
    else:
        fetch_limit = min(limit, 100)
        url = PODCHASER_APPLE_CHARTS_URL.format(country=country.lower(), limit=fetch_limit)
        use_v1 = False

    for attempt in range(1, max_retries + 1):
        try:
            with httpx.Client(timeout=12.0) as client:
                response = client.get(url, headers=headers)

                if response.status_code == 404:
                    logger.info(f"Podchaser / Apple feed for '{country}' not found (404 Not Found).")
                    return []

                response.raise_for_status()
                data = response.json()

            results = []
            if use_v1:
                entries_raw = data.get("feed", {}).get("entry", [])
                for idx, item in enumerate(entries_raw, start=1):
                    title = item.get("im:name", {}).get("label", "").strip()
                    if not title:
                        continue
                    publisher = item.get("im:artist", {}).get("label", "").strip()
                    apple_id = item.get("id", {}).get("attributes", {}).get("im:id", "")
                    images = item.get("im:image", [])
                    cover_url = images[-1].get("label", "") if images else ""
                    genre_name = item.get("category", {}).get("attributes", {}).get("label", "")
                    genres = [genre_name] if genre_name else []

                    results.append({
                        "rank": idx,
                        "title": title,
                        "publisher": publisher,
                        "cover_image_url": cover_url,
                        "apple_id": str(apple_id),
                        "source": "podchaser",
                        "country": country.lower(),
                        "category": clean_category,
                        "genres": genres,
                    })
            else:
                results_raw = data.get("feed", {}).get("results", [])
                for idx, item in enumerate(results_raw, start=1):
                    title = item.get("name", "").strip()
                    if not title:
                        continue

                    genres = [g.get("name") for g in item.get("genres", []) if g.get("name")]

                    results.append({
                        "rank": idx,
                        "title": title,
                        "publisher": item.get("artistName", "").strip(),
                        "cover_image_url": item.get("artworkUrl100", "").strip(),
                        "apple_id": str(item.get("id", "")),
                        "source": "podchaser",
                        "country": country.lower(),
                        "category": clean_category,
                        "genres": genres,
                    })

            logger.info(f"Successfully scraped {len(results)} podcasts from Podchaser/Apple ({country.upper()}).")
            return results

        except httpx.TimeoutException:
            logger.info(f"Podchaser / Apple feed for '{country.upper()}' timed out.")
            return []

        except httpx.HTTPStatusError as e:
            status_code = getattr(getattr(e, 'response', None), 'status_code', None)
            if status_code in (500, 502, 503, 504) and attempt < max_retries:
                delay = 1.5
                logger.warning(
                    f"Podchaser feed request error ({status_code}), attempt {attempt}/{max_retries}. "
                    f"Retrying in {delay}s ({country.upper()})..."
                )
                time.sleep(delay)
            else:
                logger.warning(f"Podchaser feed returned error for '{country.upper()}': {status_code or e}.")
                return []

        except Exception as e:
            logger.warning(f"Error processing Podchaser charts ({country.upper()}): {e}")
            return []

    return []
