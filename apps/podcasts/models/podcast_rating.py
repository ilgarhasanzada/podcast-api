from django.db import models
from apps.common.models import TimeStampedModel
from .podcast import Podcast


class PodcastRating(TimeStampedModel):
    """Platform-specific rating and review statistics for a podcast."""
    class Source(models.TextChoices):
        SPOTIFY = "spotify", "Spotify"
        APPLE = "apple", "Apple Podcasts"
        PODCHASER = "podchaser", "Podchaser"
        YOUTUBE = "youtube", "YouTube Podcasts"
        AMAZON = "amazon", "Amazon Music"

    podcast = models.ForeignKey(
        Podcast,
        on_delete=models.CASCADE,
        related_name="platform_ratings",
        help_text="Associated podcast"
    )
    source = models.CharField(
        max_length=30,
        choices=Source.choices,
        db_index=True,
        help_text="Rating source platform (e.g. spotify, apple)"
    )
    rating = models.FloatField(help_text="Platform rating score (e.g. 4.74)")
    rating_count = models.IntegerField(default=0, help_text="Total number of votes/ratings (e.g. 117106)")
    url = models.URLField(max_length=1000, blank=True, default="", help_text="Podcast URL on the target platform")
    synced_at = models.DateTimeField(auto_now=True, help_text="Last synchronization timestamp")

    class Meta:
        verbose_name = "Podcast Rating"
        verbose_name_plural = "Podcast Ratings"
        ordering = ["-rating_count", "-rating"]
        constraints = [
            models.UniqueConstraint(
                fields=["podcast", "source"],
                name="unique_podcast_platform_rating"
            )
        ]
        indexes = [
            models.Index(fields=["source", "rating"]),
            models.Index(fields=["podcast", "source"]),
        ]

    def __str__(self):
        return f"{self.podcast.title} - {self.get_source_display()}: ★ {self.rating} ({self.rating_count:,})"
