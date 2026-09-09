import logging
from typing import List, Dict, Any
import httpx
from django.utils.text import slugify

logger = logging.getLogger(__name__)

PRIMARY_CHART_BOARDS = [
    {
        "slug": "top-podcasts",
        "name": "Top Podcasts",
        "platform": "all",
        "display_order": 1,
        "description": "Overall most popular podcasts across countries",
        "apple_genre_id": 26,
        "is_active": True,
    },
    {
        "slug": "top-episodes",
        "name": "Top Episodes",
        "platform": "spotify",
        "display_order": 2,
        "description": "Most listened individual podcast episodes",
        "apple_genre_id": None,
        "is_active": True,
    },
    {
        "slug": "trending",
        "name": "Trending",
        "platform": "spotify",
        "display_order": 3,
        "description": "Fastest rising new podcasts",
        "apple_genre_id": None,
        "is_active": True,
    },
    {
        "slug": "podcasts",
        "name": "All Podcasts",
        "platform": "all",
        "display_order": 4,
        "description": "Complete podcast catalog",
        "apple_genre_id": 26,
        "is_active": True,
    },
]

ITUNES_GENRES_API_URL = "https://itunes.apple.com/WebObjects/MZStoreServices.woa/ws/genres?id=26"


class CategoryDiscoveryService:
    """
    Service for dynamically discovering Apple Podcasts (iTunes) genre taxonomy and synchronizing models.
    """

    @classmethod
    def fetch_all_official_categories(cls) -> List[Dict[str, Any]]:
        """
        Dynamically fetches all parent categories and subgenres from the official Apple iTunes taxonomy.
        """
        categories = list(PRIMARY_CHART_BOARDS)
        current_order = 10

        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Podcast-Aggregator/1.0"}
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(ITUNES_GENRES_API_URL, headers=headers)
                if resp.status_code == 200:
                    data = resp.json().get("26", {}).get("subgenres", {})
                    for gid, parent in data.items():
                        parent_name = parent.get("name", "").strip()
                        parent_slug = slugify(parent_name)
                        if parent_slug and not any(c["slug"] == parent_slug for c in categories):
                            categories.append({
                                "slug": parent_slug,
                                "name": parent_name,
                                "apple_genre_id": int(gid) if str(gid).isdigit() else None,
                                "parent_slug": None,
                                "platform": "all",
                                "display_order": current_order,
                                "description": f"Top podcasts in {parent_name}",
                                "is_active": True,
                            })
                            current_order += 1

                        # Subcategories (subgenres) supported by Apple Podcasts and Podchaser
                        for sid, sub in parent.get("subgenres", {}).items():
                            sub_name = sub.get("name", "").strip()
                            sub_slug = slugify(sub_name)
                            if sub_slug and not any(c["slug"] == sub_slug for c in categories):
                                categories.append({
                                    "slug": sub_slug,
                                    "name": sub_name,
                                    "apple_genre_id": int(sid) if str(sid).isdigit() else None,
                                    "parent_slug": parent_slug,
                                    "platform": "apple",
                                    "display_order": current_order,
                                    "description": f"Rankings in {parent_name} / {sub_name}",
                                    "is_active": True,
                                })
                                current_order += 1
                    logger.info(f"Successfully fetched {len(categories)} official categories from iTunes API.")
                    return categories
        except Exception as e:
            logger.warning(f"Error fetching categories from official API: {e}. Falling back to default list.")

        return categories

    @classmethod
    def sync_categories_to_db(cls) -> Dict[str, int]:
        """
        Synchronizes discovered categories and parent-child hierarchies into ChartCategory and PodcastCategory models.
        """
        from apps.podcasts.models import ChartCategory, PodcastCategory

        all_categories = cls.fetch_all_official_categories()

        # 1. Create or update ChartCategory and PodcastCategory records
        chart_count = 0
        for item in all_categories:
            ChartCategory.objects.update_or_create(
                slug=item["slug"],
                defaults={
                    "name": item["name"],
                    "platform": item.get("platform", "all"),
                    "display_order": item.get("display_order", 0),
                    "description": item.get("description", ""),
                    "apple_genre_id": item.get("apple_genre_id"),
                    "is_active": item.get("is_active", True),
                }
            )
            PodcastCategory.objects.update_or_create(
                slug=item["slug"],
                defaults={"name": item["name"]}
            )
            chart_count += 1

        # 2. Link subcategories to parent categories (self-referencing tree)
        linked_count = 0
        for item in all_categories:
            p_slug = item.get("parent_slug")
            if p_slug:
                parent_chart = ChartCategory.objects.filter(slug=p_slug).first()
                if parent_chart:
                    ChartCategory.objects.filter(slug=item["slug"]).update(parent=parent_chart)
                    linked_count += 1

                parent_pod = PodcastCategory.objects.filter(slug=p_slug).first()
                if parent_pod:
                    PodcastCategory.objects.filter(slug=item["slug"]).update(parent=parent_pod)

        logger.info(f"Category synchronization completed: {chart_count} categories, {linked_count} subcategories linked.")
        return {
            "total_categories": chart_count,
            "linked_subcategories": linked_count,
        }
