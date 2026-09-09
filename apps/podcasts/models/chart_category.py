from django.db import models


class ChartCategory(models.Model):
    """
    Chart boards and rankings categories (Top Podcasts, Trending, Comedy, etc.).
    """
    class Platform(models.TextChoices):
        ALL = "all", "All Platforms"
        SPOTIFY = "spotify", "Spotify"
        APPLE = "apple", "Apple Podcasts"

    slug = models.SlugField(
        max_length=100,
        primary_key=True,
        help_text="Unique chart category slug (e.g. top-podcasts, trending, comedy)"
    )
    name = models.CharField(
        max_length=100,
        help_text="Human-readable chart name (e.g. Top Podcasts, Trending, Comedy)"
    )
    apple_genre_id = models.IntegerField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Official Apple Podcasts genre/category ID (e.g. 1303, 1321, 1412)"
    )
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="subcategories",
        help_text="Parent category (e.g. 'business' for 'investing')"
    )
    description = models.TextField(
        blank=True,
        help_text="Brief description of the chart category"
    )
    platform = models.CharField(
        max_length=30,
        choices=Platform.choices,
        default=Platform.ALL,
        help_text="Supported platform ('all', 'spotify', 'apple')"
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Whether chart scraping is enabled for this category"
    )
    display_order = models.PositiveIntegerField(
        default=0,
        help_text="Display ordering in UI/navigation"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Chart Category"
        verbose_name_plural = "Chart Categories"
        ordering = ["display_order", "name"]

    def __str__(self):
        return f"{self.name} ({self.slug})"
