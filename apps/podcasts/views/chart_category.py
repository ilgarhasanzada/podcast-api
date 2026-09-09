from rest_framework import serializers
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from drf_spectacular.utils import extend_schema, OpenApiParameter, inline_serializer

from apps.podcasts.models import ChartCategory
from apps.podcasts.services.category_discovery import CategoryDiscoveryService


@extend_schema(
    tags=["Charts & Rankings"],
    summary="List of chart categories (boards)",
    description="Returns available chart category boards (Top Podcasts, Trending, Comedy, News, etc.) supporting platform filtering and hierarchy traversal.",
    parameters=[
        OpenApiParameter(
            name="platform",
            description="Filter by platform: 'all', 'spotify', or 'apple'",
            required=False,
            type=str,
            enum=["all", "spotify", "apple"]
        ),
        OpenApiParameter(
            name="is_active",
            description="Filter by active status (default: true)",
            required=False,
            type=bool
        ),
        OpenApiParameter(
            name="refresh",
            description="When set to 'true', triggers dynamic re-synchronization of official categories from Apple iTunes.",
            required=False,
            type=bool
        ),
    ],
    responses={
        200: inline_serializer(
            name="ChartCategoryListResponse",
            fields={
                "total": serializers.IntegerField(),
                "results": serializers.ListField(
                    child=inline_serializer(
                        name="ChartCategoryItem",
                        fields={
                            "slug": serializers.CharField(),
                            "name": serializers.CharField(),
                            "description": serializers.CharField(allow_blank=True),
                            "platform": serializers.CharField(),
                            "display_order": serializers.IntegerField(),
                            "is_active": serializers.BooleanField(),
                            "apple_genre_id": serializers.IntegerField(allow_null=True),
                            "parent": serializers.CharField(allow_null=True),
                            "subcategories_count": serializers.IntegerField(),
                            "subcategories": serializers.ListField(child=serializers.DictField(), required=False),
                        }
                    )
                ),
            }
        )
    }
)
class ChartCategoryListView(APIView):
    """
    Chart Category List API: GET /api/v1/charts/categories
    Returns available chart categories and boards with optional hierarchical tree.
    """
    def get(self, request):
        platform = request.query_params.get("platform")
        is_active_param = request.query_params.get("is_active")
        refresh = request.query_params.get("refresh", "").lower() in ["true", "1"]

        if refresh:
            CategoryDiscoveryService.sync_categories_to_db()

        parent_param = request.query_params.get("parent")
        top_level_param = request.query_params.get("top_level")

        qs = ChartCategory.objects.select_related("parent").prefetch_related("subcategories").all()

        if is_active_param is not None:
            is_act = is_active_param.lower() in ["true", "1"]
            qs = qs.filter(is_active=is_act)
        elif not parent_param:
            # Default to active chart boards if no specific parent is requested
            qs = qs.filter(is_active=True)

        if parent_param:
            qs = qs.filter(parent__slug=parent_param.lower().strip())
        elif top_level_param and top_level_param.lower() in ["true", "1"]:
            qs = qs.filter(parent__isnull=True)

        if platform and platform.lower() != "all":
            qs = qs.filter(platform__in=[platform.lower(), "all"])

        results = []
        for c in qs:
            item = {
                "slug": c.slug,
                "name": c.name,
                "description": c.description,
                "platform": c.platform,
                "display_order": c.display_order,
                "is_active": c.is_active,
                "apple_genre_id": c.apple_genre_id,
                "parent": c.parent.slug if c.parent else None,
                "subcategories_count": c.subcategories.count(),
            }
            if not c.parent:
                item["subcategories"] = [
                    {
                        "slug": sub.slug,
                        "name": sub.name,
                        "apple_genre_id": sub.apple_genre_id,
                        "is_active": sub.is_active,
                    }
                    for sub in c.subcategories.all()
                ]
            results.append(item)

        return Response({
            "total": len(results),
            "results": results
        }, status=status.HTTP_200_OK)
