import os
import logging
import re
from typing import List, Dict, Any, Optional
import httpx
from django.core.cache import cache

logger = logging.getLogger(__name__)

CACHE_KEY_APPLE_COUNTRIES = "supported_countries_apple"
CACHE_KEY_SPOTIFY_COUNTRIES = "supported_countries_spotify"
CACHE_TTL = 7 * 24 * 60 * 60  # 7 days (in seconds)

# Reliable fallback lists to maintain availability during network failures
FALLBACK_SPOTIFY_COUNTRIES = [
    "us", "ar", "au", "at", "br", "ca", "cl", "co", "dk", "fi", "fr", "de",
    "in", "id", "ie", "it", "jp", "mx", "nz", "no", "ph", "pl", "es", "se", "nl", "gb"
]

FALLBACK_POPULAR_APPLE_COUNTRIES = [
    {"code": "us", "name": "United States"},
    {"code": "gb", "name": "United Kingdom"},
    {"code": "ca", "name": "Canada"},
    {"code": "de", "name": "Germany"},
    {"code": "fr", "name": "France"},
    {"code": "az", "name": "Azerbaijan"},
    {"code": "tr", "name": "Turkey"},
    {"code": "au", "name": "Australia"},
    {"code": "in", "name": "India"},
    {"code": "jp", "name": "Japan"},
    {"code": "br", "name": "Brazil"},
    {"code": "es", "name": "Spain"},
    {"code": "it", "name": "Italy"},
    {"code": "nl", "name": "Netherlands"},
]


class CountryDiscoveryService:
    """
    Service for discovering and syncing official countries supported by Apple Podcasts and Spotify.
    """

    @classmethod
    def get_apple_countries(cls, force_refresh: bool = False) -> List[Dict[str, str]]:
        """
        Fetches official Apple Podcasts storefront countries (175 markets).
        Cached in Redis for 7 days.
        """
        if not force_refresh:
            cached = cache.get(CACHE_KEY_APPLE_COUNTRIES)
            if cached:
                return cached

        url = "https://rss.marketingtools.apple.com/apple/podcasts/storefronts"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "text/javascript, application/javascript, */*",
        }

        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(url, headers=headers)
                if resp.status_code == 200:
                    matches = re.findall(r'value=\\"([a-z]{2})\\">([^<]+)<', resp.text)
                    if matches:
                        result = [{"code": code.lower(), "name": name.strip()} for code, name in matches]
                        cache.set(CACHE_KEY_APPLE_COUNTRIES, result, timeout=CACHE_TTL)
                        logger.info(f"Successfully cached {len(result)} storefront countries for Apple Podcasts.")
                        return result
        except Exception as e:
            logger.warning(f"Error fetching Apple storefronts: {e}")

        # If network request fails, read from local 175 storefront fixture
        fixture_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "fixtures", "apple_storefronts.json")
        if os.path.exists(fixture_path):
            try:
                import json
                with open(fixture_path, "r", encoding="utf-8") as f:
                    fixture_countries = json.load(f)
                if fixture_countries:
                    cache.set(CACHE_KEY_APPLE_COUNTRIES, fixture_countries, timeout=CACHE_TTL)
                    return fixture_countries
            except Exception:
                pass

        return FALLBACK_POPULAR_APPLE_COUNTRIES

    @classmethod
    def get_spotify_countries(cls, force_refresh: bool = False) -> List[str]:
        """
        Dynamically extracts officially supported markets from Spotify Charts Next.js bundles.
        Cached in Redis for 7 days.
        """
        if not force_refresh:
            cached = cache.get(CACHE_KEY_SPOTIFY_COUNTRIES)
            if cached:
                return cached

        client_headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

        try:
            with httpx.Client(follow_redirects=True, headers=client_headers, timeout=10.0) as client:
                home_resp = client.get("https://podcastcharts.byspotify.com/")
                if home_resp.status_code == 200:
                    chunk_urls = re.findall(r'src="(/_next/static/chunks/[^"]+)"', home_resp.text)
                    for chunk_url in chunk_urls:
                        if "categoryId" in chunk_url or "marketCode" in chunk_url:
                            chunk_resp = client.get("https://podcastcharts.byspotify.com" + chunk_url)
                            if chunk_resp.status_code == 200:
                                match = re.search(r'apiSlug:"top",markets:([a-zA-Z0-9_]+)', chunk_resp.text)
                                if match:
                                    var_name = match.group(1)
                                    var_def = re.search(rf'let\s+{var_name}\s*=\s*\[([^\]]+)\]', chunk_resp.text)
                                    if var_def:
                                        codes = [c.lower() for c in re.findall(r'"([a-z]{2})"', var_def.group(1))]
                                        if codes:
                                            cache.set(CACHE_KEY_SPOTIFY_COUNTRIES, codes, timeout=CACHE_TTL)
                                            logger.info(f"Successfully cached {len(codes)} market countries for Spotify Charts.")
                                            return codes
        except Exception as e:
            logger.warning(f"Error dynamically extracting Spotify countries: {e}")

        return FALLBACK_SPOTIFY_COUNTRIES

    @classmethod
    def get_all_supported_countries(cls, platform: Optional[str] = None, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """
        Returns unified list of supported countries with platform availability flags:
        [
            {"code": "az", "name": "Azerbaijan", "platforms": ["apple"]},
            {"code": "us", "name": "United States", "platforms": ["apple", "spotify"]}
        ]
        """
        apple_countries = cls.get_apple_countries(force_refresh=force_refresh)
        spotify_countries = set(cls.get_spotify_countries(force_refresh=force_refresh))

        country_map: Dict[str, Dict[str, Any]] = {}

        for item in apple_countries:
            code = item["code"]
            country_map[code] = {
                "code": code,
                "name": item["name"],
                "platforms": ["apple"],
            }
            if code in spotify_countries:
                country_map[code]["platforms"].append("spotify")

        for sp_code in spotify_countries:
            if sp_code not in country_map:
                country_map[sp_code] = {
                    "code": sp_code,
                    "name": sp_code.upper(),
                    "platforms": ["spotify"],
                }

        results = list(country_map.values())
        results.sort(key=lambda x: x["name"])

        if platform:
            plat = platform.lower()
            results = [c for c in results if plat in c["platforms"]]

        return results

    @classmethod
    def sync_countries_to_db(cls, force_refresh: bool = False) -> int:
        """
        Synchronizes discovered countries into the Country database table.
        """
        from apps.podcasts.models import Country
        countries_data = cls.get_all_supported_countries(force_refresh=force_refresh)
        synced_count = 0
        for item in countries_data:
            code = item["code"]
            name = item["name"]
            platforms = item["platforms"]
            Country.objects.update_or_create(
                code=code,
                defaults={
                    "name": name,
                    "supports_apple": "apple" in platforms,
                    "supports_spotify": "spotify" in platforms,
                }
            )
            synced_count += 1
        logger.info(f"Successfully synced {synced_count} countries to database.")
        return synced_count

