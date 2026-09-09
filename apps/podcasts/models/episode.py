from django.db import models
from apps.common.models import TimeStampedModel
from .podcast import Podcast


class Episode(TimeStampedModel):
    """Podcast episode / audio track release."""
    podcast = models.ForeignKey(Podcast, on_delete=models.CASCADE, related_name="episodes")
    guid = models.CharField(max_length=500, help_text="Unique identifier within the RSS feed")
    title = models.CharField(max_length=500)
    description = models.TextField(blank=True, default="")
    audio_url = models.URLField(max_length=1500)
    published_at = models.DateTimeField(null=True, blank=True, db_index=True)
    duration = models.CharField(max_length=50, blank=True, default="", help_text="Duration string (e.g. 00:45:30)")
    duration_seconds = models.IntegerField(null=True, blank=True)
    cover_image_url = models.URLField(max_length=1000, blank=True, default="")

    class Meta:
        verbose_name = "Episode"
        verbose_name_plural = "Episodes"
        ordering = ["-published_at", "-id"]
        # Unique constraint for duplicate prevention and bulk UPSERT
        constraints = [
            models.UniqueConstraint(fields=["podcast", "guid"], name="unique_podcast_episode_guid")
        ]
        indexes = [
            models.Index(fields=["podcast", "-published_at"]),
            models.Index(fields=["guid"]),
        ]

    def __str__(self):
        return f"{self.podcast.title} - {self.title}"
