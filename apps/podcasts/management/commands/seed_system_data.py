import logging
from django.core.management.base import BaseCommand
from apps.podcasts.services.country_discovery import CountryDiscoveryService
from apps.podcasts.services.category_discovery import CategoryDiscoveryService

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Populate supported 175 countries and 110+ chart categories from Podchaser/Spotify into the database."

    def handle(self, *args, **options):
        self.stdout.write("Starting synchronization of countries and chart categories...")

        country_count = CountryDiscoveryService.sync_countries_to_db(force_refresh=True)
        self.stdout.write(self.style.SUCCESS(f"Successfully completed: {country_count} countries synced to database."))

        self.stdout.write("Fetching all official categories from Podchaser & Apple Podcasts...")
        cat_result = CategoryDiscoveryService.sync_categories_to_db()

        self.stdout.write(self.style.SUCCESS(
            f"Successfully completed: {cat_result['total_categories']} chart categories created/updated and "
            f"{cat_result['linked_subcategories']} subcategories linked to parent categories."
        ))

