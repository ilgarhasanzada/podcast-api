import logging
from django.core.management.base import BaseCommand
from apps.podcasts.models import Podcast
from apps.podcasts.services.rss_fetcher import fetch_and_sync_episodes

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Synchronize episodes for podcasts with feed_url in high performance mode (async or bulk)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--top",
            type=int,
            default=10,
            help="Only process podcasts ranked at or above this threshold (<= TOP, default: 10)",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Maximum number of podcasts to process (0 = all)",
        )
        parser.add_argument(
            "--max-episodes",
            type=int,
            default=15,
            help="Maximum episodes to fetch per podcast (default: 15)",
        )
        parser.add_argument(
            "--sync",
            action="store_true",
            help="Run synchronously in current process instead of delegating to Celery",
        )

    def handle(self, *args, **options):
        top = options["top"]
        limit = options["limit"]
        max_episodes = options["max_episodes"]
        run_sync = options["sync"]

        qs = (
            Podcast.objects.filter(feed_url__isnull=False)
            .exclude(feed_url="")
            .filter(episodes__isnull=True)
        )

        if top > 0:
            qs = qs.filter(chart_rankings__rank__lte=top)

        qs = qs.distinct().order_by("id")

        if limit > 0:
            podcasts = list(qs[:limit])
        else:
            podcasts = list(qs)

        total = len(podcasts)
        self.stdout.write(self.style.NOTICE(f"Found {total} podcasts matching criteria (Top <={top}, without episodes)."))

        if total == 0:
            self.stdout.write(self.style.SUCCESS("All matching podcasts already have episodes synced."))
            return

        if run_sync:
            self.stdout.write("Starting synchronous episode fetching...")
            success = 0
            for idx, p in enumerate(podcasts, start=1):
                try:
                    count = fetch_and_sync_episodes(p, max_episodes=max_episodes)
                    success += 1
                    self.stdout.write(f"[{idx}/{total}] {p.title}: {count} episodes")
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"[{idx}/{total}] {p.title} error: {e}"))
            self.stdout.write(self.style.SUCCESS(f"Completed: {success}/{total} podcasts synced."))
        else:
            self.stdout.write("Distributing tasks to Celery async queue...")
            from apps.podcasts.tasks.episodes import sync_episodes_task

            queued = 0
            for p in podcasts:
                sync_episodes_task.delay(p.id, max_episodes=max_episodes)
                queued += 1

            self.stdout.write(self.style.SUCCESS(f"Success: {queued} podcasts dispatched to Celery queue."))
