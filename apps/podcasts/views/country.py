from rest_framework import serializers
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from drf_spectacular.utils import extend_schema, OpenApiParameter, inline_serializer

from apps.podcasts.models import Country
from apps.podcasts.services.country_discovery import CountryDiscoveryService


@extend_schema(
    tags=["Countries"],
    summary="List of supported countries",
    description="Returns the list of countries supported across Apple Podcasts (175 storefronts) and Spotify Charts (26 markets). Supports platform and active-status filtering.",
    parameters=[
        OpenApiParameter(
            name="platform",
            description="Platform filter: 'apple' or 'spotify'",
            required=False,
            type=str,
            enum=["apple", "spotify"]
        ),
        OpenApiParameter(
            name="is_active",
            description="Filter by active status ('true' or 'false')",
            required=False,
            type=bool
        ),
        OpenApiParameter(
            name="refresh",
            description="When set to 'true', forces dynamic synchronization of country lists from official platforms.",
            required=False,
            type=bool
        )
    ],
    responses={
        200: inline_serializer(
            name="CountryListResponse",
            fields={
                "total": serializers.IntegerField(),
                "platform_filter": serializers.CharField(),
                "results": serializers.ListField(
                    child=inline_serializer(
                        name="CountryItem",
                        fields={
                            "code": serializers.CharField(),
                            "name": serializers.CharField(),
                            "is_active": serializers.BooleanField(),
                            "platforms": serializers.ListField(child=serializers.CharField()),
                        }
                    )
                ),
            }
        )
    }
)
class CountryListView(APIView):
    """
    Country List API: GET /api/v1/countries
    Returns internationally supported countries with platform availability flags.
    """
    def get(self, request):
        platform = request.query_params.get("platform")
        is_active_param = request.query_params.get("is_active")
        refresh = request.query_params.get("refresh", "").lower() in ["true", "1"]

        if refresh:
            CountryDiscoveryService.sync_countries_to_db(force_refresh=True)

        qs = Country.objects.all()

        if is_active_param is not None:
            is_act = is_active_param.lower() in ["true", "1"]
            qs = qs.filter(is_active=is_act)

        if platform:
            plat = platform.lower()
            if plat == "spotify":
                qs = qs.filter(supports_spotify=True)
            elif plat == "apple":
                qs = qs.filter(supports_apple=True)

        results = []
        for c in qs:
            plats = []
            if c.supports_apple:
                plats.append("apple")
            if c.supports_spotify:
                plats.append("spotify")
            results.append({
                "code": c.code,
                "name": c.name,
                "is_active": c.is_active,
                "platforms": plats,
            })

        # Fallback to service if database has not been populated yet
        if not results and not is_active_param:
            results = CountryDiscoveryService.get_all_supported_countries(platform=platform)

        return Response({
            "total": len(results),
            "platform_filter": platform or "all",
            "results": results
        }, status=status.HTTP_200_OK)
