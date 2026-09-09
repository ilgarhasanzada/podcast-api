from django.urls import path
from apps.podcasts.views import (
    ChartAPIView,
    PodcastListAPIView,
    PodcastDetailAPIView,
    PodcastEpisodesListAPIView,
    CountryListView,
    ChartCategoryListView,
)

urlpatterns = [
    # Supported countries API: GET /api/v1/countries/ and /api/v1/countries
    path("countries/", CountryListView.as_view(), name="country-list"),
    path("countries", CountryListView.as_view()),

    # Chart Rankings and Categories: GET /api/v1/charts/ and /api/v1/charts
    path("charts/categories/", ChartCategoryListView.as_view(), name="chart-category-list"),
    path("charts/categories", ChartCategoryListView.as_view()),
    path("charts/", ChartAPIView.as_view(), name="chart-list"),
    path("charts", ChartAPIView.as_view()),

    # Podcast APIs: List, Detail, and Episodes (with and without trailing slash)
    path("podcasts/", PodcastListAPIView.as_view(), name="podcast-list"),
    path("podcasts", PodcastListAPIView.as_view()),
    path("podcasts/<int:id>/", PodcastDetailAPIView.as_view(), name="podcast-detail"),
    path("podcasts/<int:id>", PodcastDetailAPIView.as_view()),
    path("podcasts/<int:id>/episodes/", PodcastEpisodesListAPIView.as_view(), name="podcast-episodes"),
    path("podcasts/<int:id>/episodes", PodcastEpisodesListAPIView.as_view()),
]


