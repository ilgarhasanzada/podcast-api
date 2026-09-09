from django.db import models


class PodcastCategory(models.Model):
    """Podcast content category / genre (e.g. Comedy, News, Technology, Business)."""
    name = models.CharField(max_length=150, unique=True, db_index=True)
    slug = models.SlugField(max_length=150, unique=True)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="subcategories",
        help_text="Parent category"
    )

    class Meta:
        db_table = "podcasts_category"
        verbose_name = "Podcast Category"
        verbose_name_plural = "Podcast Categories"
        ordering = ["name"]

    def __str__(self):
        return self.name


# Backward compatibility alias
Category = PodcastCategory

