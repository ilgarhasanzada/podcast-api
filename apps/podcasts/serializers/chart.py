from rest_framework import serializers
from apps.podcasts.models import ChartRanking, Country, ChartCategory
from .podcast import PodcastListSerializer
from .episode import EpisodeSerializer


class ChartCountrySerializer(serializers.ModelSerializer):
    class Meta:
        model = Country
        fields = ["code", "name"]


class ChartCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ChartCategory
        fields = ["slug", "name"]


class ChartRankingSerializer(serializers.ModelSerializer):
    podcast = PodcastListSerializer(read_only=True)
    episode = EpisodeSerializer(read_only=True)
    country = ChartCountrySerializer(read_only=True)
    category = ChartCategorySerializer(read_only=True)

    class Meta:
        model = ChartRanking
        fields = [
            "rank",
            "source",
            "country",
            "category",
            "date",
            "podcast",
            "episode",
        ]

