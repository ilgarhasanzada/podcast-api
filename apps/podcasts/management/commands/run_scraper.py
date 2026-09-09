from django.core.management.base import BaseCommand
from apps.podcasts.models import Country, ChartCategory
from apps.podcasts.services.pipeline import run_full_ingestion_pipeline


class Command(BaseCommand):
    help = "Collect and enrich podcast charts from Spotify and Podchaser across countries and categories."

    def add_arguments(self, parser):
        parser.add_argument(
            "--countries",
            type=str,
            default="us,gb,ca,de",
            help="Comma-separated country codes (default: us,gb,ca,de)"
        )
        parser.add_argument(
            "--country",
            type=str,
            default=None,
            help="Single target country code (e.g. us)"
        )
        parser.add_argument(
            "--all-countries",
            action="store_true",
            help="Scrape all active countries in the database"
        )
        parser.add_argument(
            "--categories",
            type=str,
            default=None,
            help="Comma-separated categories (default: all active categories in database)"
        )
        parser.add_argument(
            "--category",
            type=str,
            default=None,
            help="Single target category slug (e.g. comedy, news, true-crime)"
        )
        parser.add_argument(
            "--all-categories",
            action="store_true",
            help="Scrape all active chart categories in the database"
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=20,
            help="Number of podcasts to fetch per source (default: 20)"
        )
        parser.add_argument(
            "--episodes-limit",
            type=int,
            default=None,
            help="Number of top podcasts to fetch episodes for (default: None - all fetched podcasts)"
        )

    def handle(self, *args, **options):
        # 1. Resolve countries
        if options["all_countries"]:
            countries = list(Country.objects.filter(is_active=True).values_list("code", flat=True))
            if not countries:
                countries = ["us", "gb", "ca", "de"]
        elif options["country"]:
            countries = [options["country"].strip().lower()]
        else:
            countries = [c.strip().lower() for c in options["countries"].split(",") if c.strip()]

        # 2. Resolve categories (default: active categories directly from database)
        if options["all_categories"] or (not options["category"] and not options["categories"]):
            categories = list(ChartCategory.objects.filter(is_active=True).values_list("slug", flat=True))
            if not categories:
                categories = ["top-podcasts"]
        elif options["category"]:
            categories = [options["category"].strip().lower()]
        else:
            categories = [c.strip().lower() for c in options["categories"].split(",") if c.strip()]

        limit = options["limit"]
        episodes_limit = options["episodes_limit"]

        self.stdout.write(self.style.NOTICE(
            f"Starting ingestion pipeline: {len(countries)} Countries x {len(categories)} Categories | Limit={limit}, Episodes={'All' if episodes_limit is None else episodes_limit}..."
        ))

        total_stats = {
            "countries_processed": len(countries),
            "categories_processed": len(categories),
            "spotify_scraped": 0,
            "podchaser_scraped": 0,
            "rankings_saved": 0,
            "episodes_queued": 0,
            "episodes_synced": 0,
        }

        for country in countries:
            for cat in categories:
                self.stdout.write(f"--- Processing: Country={country.upper()} | Category={cat} ---")
                stats = run_full_ingestion_pipeline(
                    country=country,
                    category=cat,
                    limit=limit,
                    fetch_episodes_for_top=episodes_limit
                )
                for k in ["spotify_scraped", "podchaser_scraped", "rankings_saved", "episodes_queued", "episodes_synced"]:
                    total_stats[k] += stats.get(k, 0)

        self.stdout.write(self.style.SUCCESS(
            f"\nSuccessfully finished! Final statistics: {total_stats}"
        ))
