from rest_framework import serializers
from apps.podcasts.models import Episode


class EpisodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Episode
        fields = [
            "id",
            "guid",
            "title",
            "description",
            "audio_url",
            "published_at",
            "duration",
            "cover_image_url",
        ]
