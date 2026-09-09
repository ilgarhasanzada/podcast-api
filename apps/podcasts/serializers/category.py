from rest_framework import serializers
from apps.podcasts.models import PodcastCategory, Category


class PodcastCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = PodcastCategory
        fields = ["id", "name", "slug"]


CategorySerializer = PodcastCategorySerializer

