import json
import base64
from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.db import IntegrityError
from rest_framework.test import APIClient
from apps.podcasts.models import (
    Podcast,
    PodcastCategory,
    Category,
    ChartRanking,
    PodcastRating,
    Country,
    ChartCategory,
    Episode,
)

from apps.podcasts.services.enricher import (
    fetch_apple_rating,
    fetch_spotify_rating,
    enrich_podcast_metadata,
)
from apps.podcasts.services.category_discovery import CategoryDiscoveryService
from apps.podcasts.tasks import discover_and_sync_categories_task


class PodcastRatingTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.p1 = Podcast.objects.create(
            title="High Rated Podcast",
            apple_id="111111",
            spotify_id="spotify111",
        )
        self.p2 = Podcast.objects.create(
            title="Medium Rated Podcast",
            apple_id="222222",
        )
        self.p3 = Podcast.objects.create(
            title="Unrated Podcast",
            apple_id="333333",
        )
        # Ratings
        self.r1_apple = PodcastRating.objects.create(
            podcast=self.p1,
            source=PodcastRating.Source.APPLE,
            rating=4.9,
            rating_count=10000,
            url="https://podcasts.apple.com/us/podcast/id111111",
        )
        self.r1_spotify = PodcastRating.objects.create(
            podcast=self.p1,
            source=PodcastRating.Source.SPOTIFY,
            rating=4.85,
            rating_count=5000,
            url="https://open.spotify.com/show/spotify111",
        )
        self.r2_apple = PodcastRating.objects.create(
            podcast=self.p2,
            source=PodcastRating.Source.APPLE,
            rating=4.2,
            rating_count=500,
        )

        self.country_us, _ = Country.objects.get_or_create(code="us", defaults={"name": "United States"})
        self.cat_top, _ = ChartCategory.objects.get_or_create(slug="top", defaults={"name": "Top Podcasts"})

        ChartRanking.objects.create(
            podcast=self.p1,
            source="spotify",
            country=self.country_us,
            category=self.cat_top,
            rank=1,
            date="2026-09-08",
        )
        ChartRanking.objects.create(
            podcast=self.p2,
            source="podchaser",
            country=self.country_us,
            category=self.cat_top,
            rank=1,
            date="2026-09-08",
        )

    def test_filter_by_source(self):
        response = self.client.get("/api/v1/podcasts/?source=spotify", HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["title"], "High Rated Podcast")

    def test_filter_by_min_rating(self):
        response = self.client.get("/api/v1/podcasts/?min_rating=4.5", HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["title"], "High Rated Podcast")

    def test_filter_by_rating_source(self):
        response = self.client.get("/api/v1/podcasts/?rating_source=spotify", HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["title"], "High Rated Podcast")

    def test_ordering_by_rating_desc_nulls_last(self):
        response = self.client.get("/api/v1/podcasts/?ordering=-rating", HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 200)
        results = response.json()["results"]
        titles = [r["title"] for r in results]
        self.assertEqual(titles[0], "High Rated Podcast")
        self.assertEqual(titles[1], "Medium Rated Podcast")
        self.assertEqual(titles[2], "Unrated Podcast")

    def test_podcast_detail_contains_platform_ratings_and_no_fake_aggregate(self):
        response = self.client.get(f"/api/v1/podcasts/{self.p1.id}/", HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Ensure no confusing artificial aggregate fields are returned
        self.assertNotIn("rating", data)
        self.assertNotIn("rating_count", data)

        # Ensure platform_ratings contains exact platform figures
        self.assertIn("platform_ratings", data)
        self.assertEqual(len(data["platform_ratings"]), 2)
        sources = [pr["source"] for pr in data["platform_ratings"]]
        self.assertIn("apple", sources)
        self.assertIn("spotify", sources)

    def test_podcast_list_contains_platform_ratings_and_no_fake_aggregate(self):
        response = self.client.get("/api/v1/podcasts/", HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        first_result = data["results"][0]

        # No confusing fake aggregate
        self.assertNotIn("rating", first_result)
        self.assertNotIn("rating_count", first_result)

        # Platform ratings are present
        self.assertIn("platform_ratings", first_result)

    def test_podcast_rating_unique_constraint(self):
        with self.assertRaises(IntegrityError):
            PodcastRating.objects.create(
                podcast=self.p1,
                source=PodcastRating.Source.APPLE,
                rating=4.95,
                rating_count=200,
            )

    @patch("apps.podcasts.services.enricher.httpx.Client")
    def test_fetch_apple_rating_from_json_ld(self, mock_client_cls):
        html_content = """
        <html><head>
        <script type="application/ld+json">
        {
            "@type": "CreativeWorkSeries",
            "aggregateRating": {
                "@type": "AggregateRating",
                "ratingValue": 4.85,
                "reviewCount": 12500
            }
        }
        </script>
        </head><body></body></html>
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = html_content
        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__.return_value = mock_client
        mock_client_cls.return_value = mock_client

        rating, count = fetch_apple_rating("123456")
        self.assertEqual(rating, 4.85)
        self.assertEqual(count, 12500)

    @patch("apps.podcasts.services.enricher.httpx.Client")
    def test_fetch_spotify_rating_from_initial_state(self, mock_client_cls):
        state = {
            "entities": {
                "items": {
                    "spotify:show:mockshow123": {
                        "rating": {
                            "averageRating": {
                                "average": 4.74,
                                "totalRatings": 117106,
                            }
                        }
                    }
                }
            }
        }
        encoded_state = base64.b64encode(json.dumps(state).encode("utf-8")).decode("utf-8")
        html_content = f"""
        <html><head>
        <script id="initialState">{encoded_state}</script>
        </head><body></body></html>
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = html_content
        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__.return_value = mock_client
        mock_client_cls.return_value = mock_client

        rating, count = fetch_spotify_rating("mockshow123")
        self.assertEqual(rating, 4.74)
        self.assertEqual(count, 117106)


class CountryDiscoveryTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        Country.objects.create(code="us", name="United States", supports_apple=True, supports_spotify=True, is_active=True)
        Country.objects.create(code="az", name="Azerbaijan", supports_apple=True, supports_spotify=False, is_active=True)


    @patch("apps.podcasts.services.country_discovery.httpx.Client")
    def test_get_apple_countries_parsing(self, mock_client_cls):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = 'var sf = document.getElementById("storefronts"); sf.innerHTML = "<option value=\\"us\\">United States</option>\\n<option value=\\"az\\">Azerbaijan</option>";'
        mock_client = MagicMock()
        mock_client.get.return_value = mock_response
        mock_client.__enter__.return_value = mock_client
        mock_client_cls.return_value = mock_client

        from apps.podcasts.services.country_discovery import CountryDiscoveryService
        countries = CountryDiscoveryService.get_apple_countries(force_refresh=True)
        self.assertEqual(len(countries), 2)
        codes = [c["code"] for c in countries]
        self.assertIn("us", codes)
        self.assertIn("az", codes)

    @patch("apps.podcasts.services.country_discovery.httpx.Client")
    def test_get_spotify_countries_parsing(self, mock_client_cls):
        home_resp = MagicMock()
        home_resp.status_code = 200
        home_resp.text = '<html><script src="/_next/static/chunks/pages/%5BmarketCode%5D/%5BcategoryId%5D-123.js"></script></html>'

        chunk_resp = MagicMock()
        chunk_resp.status_code = 200
        chunk_resp.text = 'let r=["us","gb","de","ca"];let s=[{id:"top",apiSlug:"top",markets:r}];'

        mock_client = MagicMock()
        mock_client.get.side_effect = [home_resp, chunk_resp]
        mock_client.__enter__.return_value = mock_client
        mock_client_cls.return_value = mock_client

        from apps.podcasts.services.country_discovery import CountryDiscoveryService
        codes = CountryDiscoveryService.get_spotify_countries(force_refresh=True)
        self.assertEqual(codes, ["us", "gb", "de", "ca"])

    def test_api_countries_endpoint(self):
        response = self.client.get("/api/v1/countries/", HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("total", data)
        self.assertIn("results", data)
        self.assertGreater(data["total"], 0)

    def test_api_countries_filter_platform(self):
        response = self.client.get("/api/v1/countries/?platform=spotify", HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["platform_filter"], "spotify")
        for c in data["results"]:
            self.assertIn("spotify", c["platforms"])


class ChartCategoryTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        ChartCategory.objects.create(
            slug="top-podcasts",
            name="Top Podcasts",
            platform="all",
            display_order=1,
            is_active=True,
        )
        ChartCategory.objects.create(
            slug="trending",
            name="Trending",
            platform="spotify",
            display_order=2,
            is_active=True,
        )
        ChartCategory.objects.create(
            slug="inactive-chart",
            name="Inactive Chart",
            platform="all",
            display_order=3,
            is_active=False,
        )

    def test_chart_category_api(self):
        response = self.client.get("/api/v1/charts/categories/", HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 2)  # only active by default
        slugs = [c["slug"] for c in data["results"]]
        self.assertIn("top-podcasts", slugs)
        self.assertIn("trending", slugs)
        self.assertNotIn("inactive-chart", slugs)

    def test_chart_category_api_platform_filter(self):
        response = self.client.get("/api/v1/charts/categories/?platform=spotify", HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        slugs = [c["slug"] for c in data["results"]]
        self.assertIn("trending", slugs)
        self.assertIn("top-podcasts", slugs)  # 'all' matches 'spotify'

    @patch("apps.podcasts.services.category_discovery.httpx.Client")
    def test_category_discovery_service(self, mock_client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "26": {
                "subgenres": {
                    "1321": {
                        "name": "Business",
                        "subgenres": {
                            "1412": {"name": "Investing"}
                        }
                    }
                }
            }
        }
        mock_instance = MagicMock()
        mock_instance.get.return_value = mock_resp
        mock_instance.__enter__.return_value = mock_instance
        mock_client.return_value = mock_instance

        res = CategoryDiscoveryService.sync_categories_to_db()
        self.assertGreater(res["total_categories"], 0)
        self.assertTrue(ChartCategory.objects.filter(slug="business").exists())
        self.assertTrue(ChartCategory.objects.filter(slug="investing").exists())
        investing = ChartCategory.objects.get(slug="investing")
        self.assertIsNotNone(investing.parent)
        self.assertEqual(investing.parent.slug, "business")

    @patch("apps.podcasts.services.category_discovery.CategoryDiscoveryService.sync_categories_to_db")
    def test_discover_and_sync_categories_task(self, mock_sync):
        mock_sync.return_value = {"total_categories": 114, "linked_subcategories": 91}
        result = discover_and_sync_categories_task()
        self.assertEqual(result["total_categories"], 114)
        mock_sync.assert_called_once()

    @patch("apps.podcasts.services.category_discovery.CategoryDiscoveryService.sync_categories_to_db")
    def test_chart_category_api_refresh(self, mock_sync):
        mock_sync.return_value = {"total_categories": 114, "linked_subcategories": 91}
        response = self.client.get("/api/v1/charts/categories/?refresh=true", HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 200)
        mock_sync.assert_called_once()



class PodcastCategoryModelTests(TestCase):
    def test_podcast_category_and_alias(self):
        cat = PodcastCategory.objects.create(name="Tech", slug="tech")
        self.assertEqual(cat.name, "Tech")
        self.assertEqual(Category, PodcastCategory)


class ScraperResilienceAndFeaturesTests(TestCase):
    @patch("apps.podcasts.services.podchaser_scraper.httpx.Client.get")
    def test_podchaser_retry_on_502(self, mock_get):
        from apps.podcasts.services.podchaser_scraper import scrape_podchaser_charts
        import httpx

        # Simulation: 1st attempt returns 502, 2nd attempt succeeds with 200
        req = httpx.Request("GET", "https://rss.marketingtools.apple.com")
        resp_502 = httpx.Response(502, request=req)
        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.json.return_value = {
            "feed": {
                "results": [
                    {
                        "name": "Retried Podcast",
                        "artistName": "Host",
                        "artworkUrl100": "http://img.jpg",
                        "id": "12345",
                        "genres": [{"name": "News"}],
                    }
                ]
            }
        }
        mock_get.side_effect = [
            httpx.HTTPStatusError("502 Bad Gateway", request=req, response=resp_502),
            resp_200,
        ]

        results = scrape_podchaser_charts(country="ca", limit=5, max_retries=2)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "Retried Podcast")
        self.assertEqual(mock_get.call_count, 2)

    def test_spotify_skips_unsupported_region(self):
        from apps.podcasts.services.spotify_scraper import scrape_spotify_charts

        # 'az' is not supported in Spotify Charts -> return [] immediately without network request
        results = scrape_spotify_charts(region="az")
        self.assertEqual(results, [])

    @patch("apps.podcasts.services.spotify_scraper.httpx.Client.get")
    def test_spotify_category_404_graceful(self, mock_get):
        from apps.podcasts.services.spotify_scraper import scrape_spotify_charts

        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_get.return_value = mock_resp

        # Return [] gracefully for category not available in region
        results = scrape_spotify_charts(region="us", category="non-existent")
        self.assertEqual(results, [])

    @patch("apps.podcasts.services.enricher.httpx.Client.get")
    def test_enricher_extracts_description_from_rss(self, mock_get):
        from apps.podcasts.services.enricher import enrich_podcast_metadata

        podcast = Podcast.objects.create(
            title="RSS Desc Test Podcast",
            apple_id="123456",
            feed_url="https://example.com/feed.xml",
            description="",
            cover_image_url="http://img.png",
        )

        rss_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
          <channel>
            <title>RSS Desc Test Podcast</title>
            <description>&lt;p&gt;Bu podkast haqda RSS tesviridir.&lt;/p&gt;</description>
          </channel>
        </rss>""".encode("utf-8")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = rss_xml
        mock_resp.text = rss_xml.decode("utf-8")
        mock_get.return_value = mock_resp

        changed = enrich_podcast_metadata(podcast)
        podcast.refresh_from_db()
        self.assertTrue(changed)
        self.assertEqual(podcast.description, "Bu podkast haqda RSS tesviridir.")

    @patch("apps.podcasts.tasks.sync_episodes_task.delay")
    @patch("apps.podcasts.services.pipeline.scrape_spotify_charts")
    @patch("apps.podcasts.services.pipeline.scrape_podchaser_charts")
    def test_pipeline_async_episode_decoupling(self, mock_pc, mock_sp, mock_delay):
        from apps.podcasts.services.pipeline import run_full_ingestion_pipeline

        mock_sp.return_value = []
        mock_pc.return_value = [
            {
                "rank": 1,
                "title": "Async Test Podcast",
                "publisher": "Host",
                "cover_image_url": "http://img.jpg",
                "apple_id": "99999",
                "source": "podchaser",
                "country": "us",
                "category": "top",
            }
        ]

        podcast = Podcast.objects.create(
            title="Async Test Podcast",
            feed_url="https://example.com/feed.xml",
            description="Existing description",
            cover_image_url="http://img.jpg",
        )

        stats = run_full_ingestion_pipeline(country="us", fetch_episodes_for_top=5, async_episodes=True)
        self.assertEqual(stats["rankings_saved"], 1)
        self.assertEqual(stats["episodes_queued"], 1)
        mock_delay.assert_called_once()


class TablePartitioningAndEpisodeChartTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.country = Country.objects.create(code="us", name="United States")
        self.chart_cat = ChartCategory.objects.create(slug="top-episodes", name="Top Episodes")
        self.podcast = Podcast.objects.create(
            title="Partitioned Hub Podcast",
            feed_url="https://example.com/feed.xml"
        )
        self.episode = Episode.objects.create(
            podcast=self.podcast,
            guid="ep-unique-guid-999",
            title="Episode 999: The Future of Scaling",
            audio_url="https://example.com/audio999.mp3",
        )

    def test_partitioning_dates_inserts_across_years(self):
        """Verify successful insert and query operations across year partitions."""
        r_2025 = ChartRanking.objects.create(
            podcast=self.podcast,
            source="spotify",
            country=self.country,
            category=self.chart_cat,
            rank=1,
            date="2025-06-15",
        )
        r_2026 = ChartRanking.objects.create(
            podcast=self.podcast,
            source="spotify",
            country=self.country,
            category=self.chart_cat,
            rank=2,
            date="2026-06-15",
        )
        r_2027 = ChartRanking.objects.create(
            podcast=self.podcast,
            source="spotify",
            country=self.country,
            category=self.chart_cat,
            rank=3,
            date="2027-06-15",
        )
        # Default partition (e.g. 2028)
        r_2028 = ChartRanking.objects.create(
            podcast=self.podcast,
            source="spotify",
            country=self.country,
            category=self.chart_cat,
            rank=4,
            date="2028-01-01",
        )

        self.assertEqual(ChartRanking.objects.count(), 4)
        self.assertEqual(ChartRanking.objects.filter(date="2025-06-15").first().rank, 1)
        self.assertEqual(ChartRanking.objects.filter(date="2026-06-15").first().rank, 2)
        self.assertEqual(ChartRanking.objects.filter(date="2027-06-15").first().rank, 3)
        self.assertEqual(ChartRanking.objects.filter(date="2028-01-01").first().rank, 4)

    def test_chart_api_returns_episode_for_top_episodes(self):
        """Verify API returns episode details for top-episodes chart."""
        ChartRanking.objects.create(
            podcast=self.podcast,
            episode=self.episode,
            source="spotify",
            country=self.country,
            category=self.chart_cat,
            rank=1,
            date="2026-09-08",
        )

        response = self.client.get("/api/v1/charts/?country=us&category=top-episodes", HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 1)
        result = data["results"][0]
        self.assertEqual(result["podcast"]["title"], "Partitioned Hub Podcast")
        self.assertIsNotNone(result["episode"])
        self.assertEqual(result["episode"]["title"], "Episode 999: The Future of Scaling")
        self.assertEqual(result["episode"]["guid"], "ep-unique-guid-999")

    @patch("apps.podcasts.tasks.episodes.sync_episodes_batch_task.delay")
    def test_sync_all_existing_podcasts_episodes_task(self, mock_delay):
        """Test periodic sync task for all existing podcasts."""
        from apps.podcasts.tasks.episodes import sync_all_existing_podcasts_episodes_task
        queued = sync_all_existing_podcasts_episodes_task(batch_size=10)
        self.assertEqual(queued, 1)
        mock_delay.assert_called_once_with([self.podcast.id], max_episodes=None)


class ResilientRSSFetcherTests(TestCase):
    """RSS streaming, 25s timeout, and Celery retry tests."""

    def setUp(self):
        self.podcast = Podcast.objects.create(
            title="Streaming Tech Talk",
            feed_url="https://feeds.example.com/tech-talk.xml"
        )

    @patch("apps.podcasts.services.rss_fetcher.httpx.Client")
    def test_fetch_and_sync_episodes_streaming_success(self, mock_client_cls):
        """Verify RSS chunks streaming and bulk UPSERT into database."""
        from apps.podcasts.services.rss_fetcher import fetch_and_sync_episodes

        sample_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
            <channel>
                <title>Streaming Tech Talk</title>
                <description>A great tech podcast.</description>
                <item>
                    <title>Episode 1: Scalable Systems</title>
                    <guid>tech-ep-001</guid>
                    <description>Discussion on big data and streaming.</description>
                    <enclosure url="https://audio.example.com/ep1.mp3" type="audio/mpeg" length="12345" />
                </item>
            </channel>
        </rss>"""

        # Mock stream response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.iter_bytes.return_value = [sample_xml[:100], sample_xml[100:]]

        mock_context = MagicMock()
        mock_context.__enter__.return_value = mock_response
        mock_context.__exit__.return_value = False

        mock_client = MagicMock()
        mock_client.stream.return_value = mock_context
        mock_client_cls.return_value.__enter__.return_value = mock_client

        count = fetch_and_sync_episodes(self.podcast, raise_errors=True)
        self.assertEqual(count, 1)

        ep = Episode.objects.get(guid="tech-ep-001")
        self.assertEqual(ep.title, "Episode 1: Scalable Systems")
        self.assertEqual(ep.podcast, self.podcast)
        self.assertEqual(ep.audio_url, "https://audio.example.com/ep1.mp3")

    @patch("apps.podcasts.services.rss_fetcher.httpx.Client")
    def test_fetch_and_sync_episodes_timeout_reraise_for_celery(self, mock_client_cls):
        """Verify network timeout raises exception for Celery autoretry when raise_errors=True."""
        import httpx
        from apps.podcasts.services.rss_fetcher import fetch_and_sync_episodes

        mock_client = MagicMock()
        mock_client.stream.side_effect = httpx.ReadTimeout("Connection timed out after 25s")
        mock_client_cls.return_value.__enter__.return_value = mock_client

        with self.assertRaises(httpx.ReadTimeout):
            fetch_and_sync_episodes(self.podcast, raise_errors=True)

    def test_sync_episodes_task_retry_configuration(self):
        """Verify Celery task retry and time limit configuration."""
        from apps.podcasts.tasks.episodes import sync_episodes_task
        import httpx

        self.assertEqual(sync_episodes_task.max_retries, 3)
        self.assertEqual(sync_episodes_task.soft_time_limit, 60)
        self.assertEqual(sync_episodes_task.time_limit, 90)
        self.assertTrue(sync_episodes_task.retry_backoff)
        self.assertIn(httpx.TimeoutException, sync_episodes_task.autoretry_for)


class BatchProcessingAndRotationTests(TestCase):
    """Celery batch processing and User-Agent rotation tests."""

    def test_rotating_browser_headers(self):
        """Verify dynamic User-Agent and browser headers generation."""
        from apps.podcasts.services.http_client import get_rotating_browser_headers

        headers1 = get_rotating_browser_headers()
        self.assertIn("User-Agent", headers1)
        self.assertIn("Accept-Language", headers1)
        self.assertTrue(len(headers1["User-Agent"]) > 10)

    @patch("apps.podcasts.tasks.episodes.fetch_and_sync_episodes")
    def test_sync_episodes_batch_task(self, mock_fetch):
        """Verify sequential batch processing of podcast episodes."""
        from apps.podcasts.tasks.episodes import sync_episodes_batch_task

        p1 = Podcast.objects.create(title="Batch Podcast 1", feed_url="https://feeds.example.com/1.xml")
        p2 = Podcast.objects.create(title="Batch Podcast 2", feed_url="https://feeds.example.com/2.xml")

        mock_fetch.return_value = 5
        total = sync_episodes_batch_task([p1.id, p2.id], max_episodes=10)

        self.assertEqual(total, 10)
        self.assertEqual(mock_fetch.call_count, 2)

    @patch("apps.podcasts.tasks.enrichment.enrich_podcast_metadata")
    def test_enrich_podcasts_batch_task(self, mock_enrich):
        """Verify batch enrichment of podcasts."""
        from apps.podcasts.tasks.enrichment import enrich_podcasts_batch_task

        p1 = Podcast.objects.create(title="Batch Enrich 1")
        p2 = Podcast.objects.create(title="Batch Enrich 2")

        mock_enrich.return_value = True
        total = enrich_podcasts_batch_task([p1.id, p2.id])

        self.assertEqual(total, 2)
        self.assertEqual(mock_enrich.call_count, 2)


class PaginatedAdminInlineTests(TestCase):
    def setUp(self):
        from django.test import Client
        from django.contrib.auth.models import User
        self.client = Client()
        self.admin_user = User.objects.create_superuser("admin_test", "admin@example.com", "pass123")
        self.client.force_login(self.admin_user)

        self.podcast = Podcast.objects.create(
            title="Inline Pagination Podcast",
            feed_url="https://example.com/feed.xml"
        )
        # Create 25 episodes (per_page = 20 yields 2 pages)
        episodes = [
            Episode(
                podcast=self.podcast,
                guid=f"ep-page-guid-{i}",
                title=f"Episode {i:02d}",
                audio_url=f"https://example.com/audio-{i}.mp3"
            )
            for i in range(1, 26)
        ]
        Episode.objects.bulk_create(episodes)

    def test_inline_pagination_rendering_and_page_switch(self):
        # 1. First page request (default: p_ep=1)
        response1 = self.client.get(f"/admin/podcasts/podcast/{self.podcast.id}/change/")
        self.assertEqual(response1.status_code, 200)
        content1 = response1.content.decode("utf-8")

        self.assertIn("inline-pagination", content1)
        self.assertIn("Total 25 records", content1)
        self.assertIn("p_ep=2#episodes-group", content1)
        self.assertIn("View All Records in Table", content1)

        # 2. Second page request (p_ep=2)
        response2 = self.client.get(f"/admin/podcasts/podcast/{self.podcast.id}/change/?p_ep=2")
        self.assertEqual(response2.status_code, 200)
        content2 = response2.content.decode("utf-8")

        self.assertIn("inline-pagination", content2)
        self.assertIn("Page 2 / 2", content2)
        self.assertIn("p_ep=1#episodes-group", content2)


class OptimizationAndRotationTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_podcast_list_api_episodes_count(self):
        podcast = Podcast.objects.create(title="Counting Show")
        Episode.objects.create(podcast=podcast, guid="g1", title="Ep 1")
        Episode.objects.create(podcast=podcast, guid="g2", title="Ep 2")
        Episode.objects.create(podcast=podcast, guid="g3", title="Ep 3")

        response = self.client.get("/api/v1/podcasts/", HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["episodes_count"], 3)

    def test_enrich_all_ratings_task_skips_already_rated(self):
        podcast = Podcast.objects.create(title="Rated Podcast")
        PodcastRating.objects.create(
            podcast=podcast,
            source=PodcastRating.Source.APPLE,
            rating=4.5,
            rating_count=100
        )
        from apps.podcasts.tasks.enrichment import enrich_all_ratings_task
        with patch("apps.podcasts.tasks.enrichment.enrich_podcast_metadata") as mock_enrich:
            count = enrich_all_ratings_task()
            self.assertEqual(count, 0)
            mock_enrich.assert_not_called()

    def test_slashless_url_support_returns_200_without_redirect(self):
        podcast = Podcast.objects.create(title="Slashless Show")
        Episode.objects.create(podcast=podcast, guid="g_slash", title="Ep Slash")

        endpoints = [
            "/api/v1/charts",
            "/api/v1/charts/",
            "/api/v1/podcasts",
            "/api/v1/podcasts/",
            f"/api/v1/podcasts/{podcast.id}",
            f"/api/v1/podcasts/{podcast.id}/",
            f"/api/v1/podcasts/{podcast.id}/episodes",
            f"/api/v1/podcasts/{podcast.id}/episodes/",
        ]
        for url in endpoints:
            res = self.client.get(url, HTTP_HOST="localhost")
            self.assertEqual(res.status_code, 200, f"URL {url} failed with status {res.status_code}")

    def test_chart_ranking_category_index_present(self):
        index_names = [idx.name for idx in ChartRanking._meta.indexes]
        self.assertIn("idx_chart_category", index_names)











