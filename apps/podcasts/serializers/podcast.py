from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field
from apps.podcasts.models import Podcast, PodcastRating
from .category import CategorySerializer
from .episode import EpisodeSerializer


class PodcastRatingSerializer(serializers.ModelSerializer):
    class Meta:
        model = PodcastRating
        fields = [
            "source",
            "rating",
            "rating_count",
            "url",
            "synced_at",
        ]


class PodcastListSerializer(serializers.ModelSerializer):
    categories = CategorySerializer(many=True, read_only=True)
    episodes_count = serializers.SerializerMethodField()
    platform_ratings = PodcastRatingSerializer(many=True, read_only=True)

    class Meta:
        model = Podcast
        fields = [
            "id",
            "title",
            "publisher",
            "cover_image_url",
            "platform_ratings",
            "frequency",
            "categories",
            "episodes_count",
            "updated_at",
        ]

    @extend_schema_field(serializers.IntegerField())
    def get_episodes_count(self, obj) -> int:
        if hasattr(obj, "episodes_count") and obj.episodes_count is not None:
            return obj.episodes_count
        return obj.episodes.count()


class PodcastDetailSerializer(serializers.ModelSerializer):
    categories = CategorySerializer(many=True, read_only=True)
    episodes_count = serializers.SerializerMethodField()
    recent_episodes = serializers.SerializerMethodField()
    platform_ratings = PodcastRatingSerializer(many=True, read_only=True)

    spotify_url = serializers.CharField(read_only=True)
    apple_url = serializers.CharField(read_only=True)

    class Meta:
        model = Podcast
        fields = [
            "id",
            "title",
            "publisher",
            "description",
            "cover_image_url",
            "feed_url",
            "website_url",
            "spotify_url",
            "apple_url",
            "platform_ratings",
            "frequency",
            "language",
            "categories",
            "episodes_count",
            "recent_episodes",
            "created_at",
            "updated_at",
        ]

    @extend_schema_field(serializers.IntegerField())
    def get_episodes_count(self, obj) -> int:
        if hasattr(obj, "episodes_count") and obj.episodes_count is not None:
            return obj.episodes_count
        return obj.episodes.count()

    @extend_schema_field(EpisodeSerializer(many=True))
    def get_recent_episodes(self, obj):
        request = self.context.get("request")
        limit = 10
        offset = 0
        if request:
            try:
                if "limit" in request.query_params:
                    limit = min(max(int(request.query_params["limit"]), 1), 100)
                if "offset" in request.query_params:
                    offset = max(int(request.query_params["offset"]), 0)
            except (ValueError, TypeError):
                pass
        episodes = obj.episodes.all().order_by("-published_at", "-id")[offset:offset + limit]
        return EpisodeSerializer(episodes, many=True).data
