from django.db.models import Prefetch, Count
from django.core.cache import cache
from rest_framework import generics, filters
from django_filters.rest_framework import DjangoFilterBackend
import django_filters
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes

from apps.podcasts.models import ChartRanking, Podcast
from apps.podcasts.serializers import ChartRankingSerializer
from .pagination import StandardResultsSetPagination


class ChartRankingFilter(django_filters.FilterSet):
    country = django_filters.CharFilter(field_name="country__code", lookup_expr="iexact")
    category = django_filters.CharFilter(field_name="category__slug", lookup_expr="icontains")
    source = django_filters.ChoiceFilter(choices=ChartRanking.Source.choices)
    date = django_filters.DateFilter()

    class Meta:
        model = ChartRanking
        fields = ["country", "category", "source", "date"]


@extend_schema(
    tags=["Charts & Rankings"],
    summary="International podcast chart rankings",
    description="Returns ordered podcast rankings from Spotify and Podchaser filtered by country, category, source, and date. If no date is specified, defaults to the latest available chart date.",
    parameters=[
        OpenApiParameter(name="country", description="Two-letter ISO country code (e.g. us, gb)", required=False, type=str),
        OpenApiParameter(name="category", description="Chart category slug (e.g. top-podcasts, news, comedy)", required=False, type=str),
        OpenApiParameter(
            name="source",
            description="Ranking source platform",
            required=False,
            type=str,
            enum=ChartRanking.Source.values,
        ),
        OpenApiParameter(name="date", description="Chart recording date (format: YYYY-MM-DD)", required=False, type=OpenApiTypes.DATE),
    ]
)
class ChartAPIView(generics.ListAPIView):
    """
    Chart API: GET /api/v1/charts
    Parameters: country, category, date (default: latest date), source (spotify or podchaser).
    Returns ranked podcasts in order.
    """
    serializer_class = ChartRankingSerializer
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = ChartRankingFilter
    ordering = ["rank"]

    def get_queryset(self):
        podcast_prefetch = Prefetch(
            "podcast",
            queryset=Podcast.objects.annotate(
                episodes_count=Count("episodes")
            ).prefetch_related("categories", "platform_ratings")
        )
        queryset = (
            ChartRanking.objects
            .select_related("country", "category", "episode")
            .prefetch_related(podcast_prefetch)
        )
        
        # If no explicit date is specified, default to the latest available date
        date_param = self.request.query_params.get("date")
        if not date_param:
            country_param = (self.request.query_params.get("country") or "").lower().strip()
            source_param = (self.request.query_params.get("source") or "").lower().strip()
            category_param = (self.request.query_params.get("category") or "").lower().strip()

            cache_key = f"latest_chart_date_{country_param}_{source_param}_{category_param}"
            latest_date = cache.get(cache_key)
            if not latest_date:
                date_qs = ChartRanking.objects.all()
                if country_param:
                    date_qs = date_qs.filter(country__code=country_param)
                if source_param:
                    date_qs = date_qs.filter(source=source_param)
                if category_param:
                    date_qs = date_qs.filter(category__slug__icontains=category_param)

                latest_date = date_qs.order_by("-date").values_list("date", flat=True).first()
                if latest_date:
                    cache.set(cache_key, latest_date, timeout=300)

            if latest_date:
                queryset = queryset.filter(date=latest_date)

        return queryset

