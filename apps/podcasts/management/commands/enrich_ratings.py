import time
from django.core.management.base import BaseCommand
from apps.podcasts.models import Podcast
from apps.podcasts.services.enricher import enrich_podcast_metadata, fetch_apple_rating


class Command(BaseCommand):
    help = "Enrich podcast ratings and rating counts from Apple Podcasts for podcasts missing rating data."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Maximum number of podcasts to update (0 = all)"
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Refresh ratings even for podcasts that already have rating data"
        )

    def handle(self, *args, **options):
        limit = options["limit"]
        refresh_all = options["all"]

        if refresh_all:
            qs = Podcast.objects.all()
        else:
            qs = Podcast.objects.filter(rating__isnull=True)

        total = qs.count()
        if limit > 0:
            qs = qs[:limit]
            total = min(total, limit)

        self.stdout.write(self.style.NOTICE(f"Starting rating enrichment for {total} podcasts..."))

        success_count = 0
        skipped_count = 0

        for idx, podcast in enumerate(qs, start=1):
            # If apple_id is missing, run full metadata enrichment first
            if not podcast.apple_id:
                enrich_podcast_metadata(podcast)
                podcast.refresh_from_db()

            if podcast.apple_id:
                rating, count = fetch_apple_rating(podcast.apple_id, podcast.website_url)
                if rating is not None:
                    podcast.rating = rating
                    podcast.rating_count = count
                    podcast.save(update_fields=["rating", "rating_count", "updated_at"])
                    success_count += 1
                    self.stdout.write(self.style.SUCCESS(
                        f"[{idx}/{total}] {podcast.title[:35]}: Rating={rating}, Count={count}"
                    ))
                else:
                    skipped_count += 1
                    self.stdout.write(self.style.WARNING(
                        f"[{idx}/{total}] {podcast.title[:35]}: Rating not found."
                    ))
            else:
                skipped_count += 1
                self.stdout.write(self.style.WARNING(
                    f"[{idx}/{total}] {podcast.title[:35]}: Missing Apple ID."
                ))

            time.sleep(0.2)

        self.stdout.write(self.style.SUCCESS(
            f"\nCompleted! Successful: {success_count}, Skipped/Failed: {skipped_count}"
        ))
