from rest_framework import generics
from drf_spectacular.utils import extend_schema, OpenApiParameter

from apps.podcasts.models import Episode
from apps.podcasts.serializers import EpisodeSerializer
from .pagination import EpisodeOffsetPagination


@extend_schema(
    tags=["Episodes"],
    summary="Paginated episode list for a podcast",
    description="Returns offset-based paginated episode listings for a podcast (limit & offset) for optimal handling of large archives.",
    parameters=[
        OpenApiParameter(name="limit", description="Number of episodes per page (default: 20, max: 250)", required=False, type=int),
        OpenApiParameter(name="offset", description="Starting offset index (default: 0)", required=False, type=int),
    ]
)
class PodcastEpisodesListAPIView(generics.ListAPIView):
    """
    Offset-based paginated episode list for a podcast:
    GET /api/v1/podcasts/{id}/episodes?limit=20&offset=0
    """
    serializer_class = EpisodeSerializer
    pagination_class = EpisodeOffsetPagination

    def get_queryset(self):
        podcast_id = self.kwargs.get("id")
        return Episode.objects.filter(podcast_id=podcast_id).order_by("-published_at", "-id")
