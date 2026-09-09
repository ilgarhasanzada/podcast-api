from django.db.models import F, Max, Count, OuterRef, Subquery, IntegerField, Value, Exists
from django.db.models.functions import Coalesce
from rest_framework import generics, filters
from django_filters.rest_framework import DjangoFilterBackend
import django_filters
from drf_spectacular.utils import extend_schema, OpenApiParameter

from apps.podcasts.models import Podcast, ChartRanking, PodcastRating, Episode
from apps.podcasts.serializers import PodcastListSerializer, PodcastDetailSerializer
from .pagination import StandardResultsSetPagination


class PodcastFilter(django_filters.FilterSet):
    category = django_filters.CharFilter(field_name="categories__slug", lookup_expr="iexact", distinct=True)
    publisher = django_filters.CharFilter(lookup_expr="icontains")
    min_rating = django_filters.NumberFilter(
        method="filter_min_rating",
        help_text="Minimum rating score across platforms (e.g. 4.5)"
    )
    source = django_filters.ChoiceFilter(
        choices=ChartRanking.Source.choices,
        method="filter_source"
    )
    rating_source = django_filters.ChoiceFilter(
        choices=PodcastRating.Source.choices,
        method="filter_rating_source",
        help_text="Rating source platform (spotify, apple)"
    )

    class Meta:
        model = Podcast
        fields = ["category", "publisher", "min_rating", "source", "rating_source"]

    def filter_source(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(Exists(ChartRanking.objects.filter(podcast=OuterRef("pk"), source=value.lower())))

    def filter_min_rating(self, queryset, name, value):
        if value is None:
            return queryset
        return queryset.filter(Exists(PodcastRating.objects.filter(podcast=OuterRef("pk"), rating__gte=value)))

    def filter_rating_source(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(Exists(PodcastRating.objects.filter(podcast=OuterRef("pk"), source=value.lower())))


class PodcastOrderingFilter(filters.OrderingFilter):
    def filter_queryset(self, request, queryset, view):
        ordering = self.get_ordering(request, queryset, view)
        if ordering:
            new_ordering = []
            has_rating_ordering = False
            for field in ordering:
                if field == "-rating":
                    has_rating_ordering = True
                    new_ordering.append(F("max_rating").desc(nulls_last=True))
                elif field == "rating":
                    has_rating_ordering = True
                    new_ordering.append(F("max_rating").asc(nulls_last=True))
                else:
                    new_ordering.append(field)
            if has_rating_ordering:
                queryset = queryset.annotate(max_rating=Max("platform_ratings__rating"))
            return queryset.order_by(*new_ordering)
        return queryset


@extend_schema(
    tags=["Podcasts"],
    summary="Paginated podcast list and search",
    description="Returns a paginated list of podcasts. Supports search by title, publisher, or description (?search=...), category filtering (?category=...), minimum rating filtering (?min_rating=...), and ranking source filtering (?source=spotify/podchaser).",
    parameters=[
        OpenApiParameter(name="search", description="Search query across podcast title, publisher, and description", required=False, type=str),
        OpenApiParameter(name="category", description="Category slug (e.g. news, comedy, true-crime)", required=False, type=str),
        OpenApiParameter(name="publisher", description="Filter by publisher/creator name", required=False, type=str),
        OpenApiParameter(name="min_rating", description="Filter by minimum rating score (e.g. 4.5)", required=False, type=float),
        OpenApiParameter(name="source", description="Filter by ranking source: spotify or podchaser", required=False, type=str, enum=["spotify", "podchaser"]),
        OpenApiParameter(name="rating_source", description="Filter by rating platform source: spotify or apple", required=False, type=str, enum=["spotify", "apple"]),
    ]
)
class PodcastListAPIView(generics.ListAPIView):
    """
    Podcast List API: GET /api/v1/podcasts
    Paginated podcast list with full-text search and faceted filtering.
    """
    serializer_class = PodcastListSerializer
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, PodcastOrderingFilter]
    filterset_class = PodcastFilter
    search_fields = ["title", "publisher", "description"]
    ordering_fields = ["title", "rating", "updated_at"]
    ordering = ["-updated_at"]

    def get_queryset(self):
        episodes_subquery = Coalesce(
            Subquery(
                Episode.objects.filter(podcast_id=OuterRef("id"))
                .values("podcast_id")
                .annotate(cnt=Count("id"))
                .values("cnt")[:1],
                output_field=IntegerField()
            ),
            Value(0)
        )
        return (
            Podcast.objects
            .annotate(episodes_count=episodes_subquery)
            .prefetch_related("categories", "platform_ratings")
        )


@extend_schema(
    tags=["Podcasts"],
    summary="Detailed podcast metadata and recent episodes",
    description="Retrieves comprehensive metadata for a specific podcast by ID along with its recent episodes supporting limit/offset pagination.",
    parameters=[
        OpenApiParameter(name="limit", description="Number of recent episodes to return (default: 10, max: 100)", required=False, type=int),
        OpenApiParameter(name="offset", description="Starting offset index for recent episodes (default: 0)", required=False, type=int),
    ]
)
class PodcastDetailAPIView(generics.RetrieveAPIView):
    """
    Podcast Detail API: GET /api/v1/podcasts/{id}
    Detailed metadata and recent episodes for a specific podcast.
    """
    serializer_class = PodcastDetailSerializer
    lookup_field = "id"

    def get_queryset(self):
        return (
            Podcast.objects
            .annotate(episodes_count=Count("episodes", distinct=True))
            .prefetch_related("categories", "platform_ratings")
        )
