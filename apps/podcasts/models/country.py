from django.db import models


class Country(models.Model):
    """
    Supported countries and their platform availability status.
    """
    code = models.CharField(
        max_length=5,
        primary_key=True,
        help_text="ISO 3166-1 alpha-2 country code (e.g. us, az, gb)"
    )
    name = models.CharField(
        max_length=100,
        help_text="Official country name (e.g. Azerbaijan, United States)"
    )
    supports_apple = models.BooleanField(
        default=True,
        help_text="Whether Apple Podcasts charts are supported"
    )
    supports_spotify = models.BooleanField(
        default=False,
        help_text="Whether Spotify Charts are supported"
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Whether daily scraping is active for this country"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Country"
        verbose_name_plural = "Countries"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.code.upper()})"
