from django.db import models
from .podcast import Podcast
from .episode import Episode
from .country import Country
from .chart_category import ChartCategory


class ChartRanking(models.Model):
    """Historical chart rankings stream (Spotify and Podchaser)."""
    class Source(models.TextChoices):
        SPOTIFY = "spotify", "Spotify"
        PODCHASER = "podchaser", "Podchaser"

    podcast = models.ForeignKey(Podcast, on_delete=models.CASCADE, related_name="chart_rankings")
    episode = models.ForeignKey(
        Episode,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="chart_rankings",
        help_text="Direct link to individual episode for Top Episodes charts"
    )
    source = models.CharField(max_length=30, choices=Source.choices, db_index=True)
    country = models.ForeignKey(
        Country,
        on_delete=models.CASCADE,
        related_name="chart_rankings",
        to_field="code",
        db_column="country",
        help_text="Country where the ranking was recorded"
    )
    category = models.ForeignKey(
        ChartCategory,
        on_delete=models.CASCADE,
        related_name="chart_rankings",
        to_field="slug",
        db_column="category",
        help_text="Chart board or category"
    )
    rank = models.PositiveIntegerField(help_text="Position on the chart (1, 2, 3...)")
    date = models.DateField(db_index=True, help_text="Date of chart recording")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Chart Ranking"
        verbose_name_plural = "Chart Rankings"
        ordering = ["date", "rank"]
        # Composite indexes for high performance query filtering on country, category, date, and source
        indexes = [
            models.Index(fields=["country", "category", "date", "source"], name="idx_chart_filter"),
            models.Index(fields=["date", "source", "rank"], name="idx_chart_date_rank"),
            models.Index(fields=["category"], name="idx_chart_category"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "country", "category", "date", "rank"],
                name="unique_chart_daily_rank"
            ),
            models.UniqueConstraint(
                fields=["source", "country", "category", "date", "podcast"],
                condition=models.Q(episode__isnull=True),
                name="unique_chart_daily_podcast"
            ),
            models.UniqueConstraint(
                fields=["source", "country", "category", "date", "episode"],
                condition=models.Q(episode__isnull=False),
                name="unique_chart_daily_episode"
            ),
        ]

    def __str__(self):
        c_code = self.country_id.upper() if self.country_id else ""
        return f"#{self.rank} {self.podcast.title} ({self.source.upper()} - {c_code} - {self.date})"
