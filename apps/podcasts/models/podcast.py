from django.db import models
from apps.common.models import TimeStampedModel
from .category import Category


class Podcast(TimeStampedModel):
    """Podcast core metadata and enrichment attributes."""
    title = models.CharField(max_length=500, db_index=True)
    publisher = models.CharField(max_length=500, blank=True, default="", db_index=True)
    description = models.TextField(blank=True, default="")
    cover_image_url = models.URLField(max_length=1000, blank=True, default="")
    feed_url = models.URLField(max_length=1000, blank=True, default="", db_index=True)
    website_url = models.URLField(max_length=1000, blank=True, default="")
    
    # Metadata enrichment fields
    categories = models.ManyToManyField(Category, related_name="podcasts", blank=True)
    rating = models.FloatField(null=True, blank=True, help_text="Average rating score (e.g. 4.8)")
    rating_count = models.IntegerField(default=0, help_text="Total number of ratings/reviews")
    frequency = models.CharField(max_length=100, blank=True, default="", help_text="Publishing frequency (daily, weekly, etc.)")
    language = models.CharField(max_length=20, blank=True, default="en")

    # External platform IDs (for cross-platform enrichment)
    apple_id = models.CharField(max_length=100, blank=True, default="", db_index=True)
    spotify_id = models.CharField(max_length=100, blank=True, default="", db_index=True)

    class Meta:
        verbose_name = "Podcast"
        verbose_name_plural = "Podcasts"
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["title"]),
            models.Index(fields=["publisher"]),
        ]

    @property
    def spotify_url(self) -> str:
        if self.spotify_id:
            return f"https://open.spotify.com/show/{self.spotify_id}"
        return ""

    @property
    def apple_url(self) -> str:
        if self.apple_id:
            return f"https://podcasts.apple.com/us/podcast/id{self.apple_id}"
        return ""

    def __str__(self):
        return self.title

