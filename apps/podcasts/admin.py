from django.contrib import admin
from django.utils.html import format_html
from django.core.paginator import Paginator
from django.utils.functional import cached_property
from django.db import connection
from django.db.models import Count, OuterRef, Subquery, IntegerField, Prefetch
from django.db.models.functions import Coalesce

from .models import PodcastCategory, Category, Podcast, Episode, ChartRanking, PodcastRating, Country, ChartCategory


class LargeTablePaginator(Paginator):
    """
    Optimized paginator for large tables (Episode, ChartRanking) using PostgreSQL
    'pg_class' statistics table to get estimated row counts quickly.
    Eliminates slow 'SELECT COUNT(*)' queries when no filtering or search is applied.
    """
    @cached_property
    def count(self):
        if self.object_list.query.where:
            return super().count
        try:
            table_name = self.object_list.model._meta.db_table
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT reltuples::bigint FROM pg_class WHERE relname = %s;",
                    [table_name]
                )
                row = cursor.fetchone()
                if row and row[0] is not None and row[0] >= 0:
                    return int(row[0])
        except Exception:
            pass
        return super().count


class PodcastRatingInline(admin.TabularInline):
    model = PodcastRating
    extra = 0
    can_delete = False
    show_change_link = True
    fields = ["source_badge", "rating_display", "rating_count", "url_link", "synced_at"]
    readonly_fields = ["source_badge", "rating_display", "rating_count", "url_link", "synced_at"]
    verbose_name = "Platform Rating"
    verbose_name_plural = "Platform Ratings (Spotify, Apple, etc.)"

    def has_add_permission(self, request, obj=None):
        return False

    def source_badge(self, obj):
        if obj.source == "spotify":
            return format_html('<span style="background: #1DB954; color: white; padding: 3px 8px; border-radius: 4px; font-weight: bold;">Spotify</span>')
        elif obj.source == "apple":
            return format_html('<span style="background: #872996; color: white; padding: 3px 8px; border-radius: 4px; font-weight: bold;">Apple Podcasts</span>')
        return obj.get_source_display()
    source_badge.short_description = "Platform"

    def rating_display(self, obj):
        return format_html('<span style="font-weight: bold; color: #d97706; font-size: 14px;">★ {}</span>', obj.rating)
    rating_display.short_description = "Rating"

    def url_link(self, obj):
        if obj.url:
            return format_html('<a href="{}" target="_blank" style="color: #2563eb; font-weight: 500;">View Profile ↗</a>', obj.url)
        return "—"
    url_link.short_description = "Link"


class PaginatedTabularInline(admin.TabularInline):
    """
    Base class providing dynamic pagination for Django Admin Inlines
    handling large related models (Episode, ChartRanking).
    - Prevents loading thousands of records on a single page, avoiding browser/server freezes.
    - Provides page navigation (« First, ‹ Previous, 1, 2, 3..., Next ›, Last »).
    - Includes a direct link in the header to view/manage records in the main changelist.
    """
    per_page = 20
    page_param = "p"
    template = "admin/podcasts/paginated_tabular_inline.html"
    external_changelist_url = None
    external_fk_field = "podcast__id__exact"

    def get_formset(self, request, obj=None, **kwargs):
        formset_class = super().get_formset(request, obj, **kwargs)
        inline_instance = self

        class BoundPaginatedInlineFormSet(formset_class):
            per_page = inline_instance.per_page
            page_param = inline_instance.page_param

            def __init__(fs_self, *args, **kwargs):
                fs_self.request = request
                super().__init__(*args, **kwargs)

            def get_queryset(fs_self):
                if not hasattr(fs_self, "_paginated_queryset"):
                    qs = super().get_queryset()

                    page_num = 1
                    if fs_self.request:
                        try:
                            page_num = int(fs_self.request.GET.get(fs_self.page_param, 1))
                        except (ValueError, TypeError):
                            page_num = 1

                    paginator = Paginator(qs, fs_self.per_page)
                    try:
                        fs_self.page_obj = paginator.get_page(page_num)
                    except Exception:
                        fs_self.page_obj = paginator.get_page(1)

                    fs_self.paginator = paginator
                    page_ids = list(fs_self.page_obj.object_list.values_list("id", flat=True))
                    ordering = inline_instance.get_ordering(request) or ["-id"]
                    fs_self._paginated_queryset = qs.filter(id__in=page_ids).order_by(*ordering)

                    fs_self.pagination = fs_self._build_pagination_data()

                return fs_self._paginated_queryset

            def _build_pagination_data(fs_self):
                page = fs_self.page_obj
                paginator = fs_self.paginator
                current = page.number
                total = paginator.num_pages

                base_params = fs_self.request.GET.copy() if fs_self.request else {}

                def make_url(num):
                    p = base_params.copy()
                    p[fs_self.page_param] = num
                    return f"?{p.urlencode()}#{fs_self.prefix}-group"

                window = 2
                start_page = max(1, current - window)
                end_page = min(total, current + window)

                pages = []
                for num in range(start_page, end_page + 1):
                    pages.append({
                        "number": num,
                        "is_current": num == current,
                        "url": make_url(num),
                    })

                return {
                    "has_previous": page.has_previous(),
                    "previous_url": make_url(page.previous_page_number()) if page.has_previous() else None,
                    "has_next": page.has_next(),
                    "next_url": make_url(page.next_page_number()) if page.has_next() else None,
                    "first_url": make_url(1) if current > 1 else None,
                    "last_url": make_url(total) if current < total else None,
                    "current_page": current,
                    "total_pages": total,
                    "total_count": paginator.count,
                    "start_index": page.start_index(),
                    "end_index": page.end_index(),
                    "pages": pages,
                    "show_first_ellipsis": start_page > 1,
                    "show_last_ellipsis": end_page < total,
                }

        return BoundPaginatedInlineFormSet


class ChartRankingInline(PaginatedTabularInline):
    model = ChartRanking
    extra = 0
    can_delete = False
    show_change_link = True
    fields = ["rank", "source", "country", "category", "episode", "date"]
    readonly_fields = ["rank", "source", "country", "category", "episode", "date"]
    ordering = ["-date", "rank"]
    per_page = 15
    page_param = "p_rank"
    verbose_name = "Chart Ranking History"
    verbose_name_plural = "Chart Ranking History"
    external_changelist_url = "/admin/podcasts/chartranking/"

    def has_add_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("country", "category", "episode")


class EpisodeInline(PaginatedTabularInline):
    model = Episode
    extra = 0
    can_delete = False
    show_change_link = True
    fields = ["title", "published_at", "duration", "guid"]
    readonly_fields = ["title", "published_at", "duration", "guid"]
    ordering = ["-published_at", "-id"]
    per_page = 20
    page_param = "p_ep"
    verbose_name = "Episode"
    verbose_name_plural = "Episodes"
    external_changelist_url = "/admin/podcasts/episode/"

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(PodcastCategory)
class PodcastCategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "parent", "podcasts_count", "podcasts_link"]
    list_filter = ["parent"]
    search_fields = ["name", "slug"]
    prepopulated_fields = {"slug": ("name",)}
    list_per_page = 50
    list_max_show_all = 250
    show_full_result_count = False

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_podcasts_count=Count("podcasts"))

    def podcasts_count(self, obj):
        count = getattr(obj, "_podcasts_count", None)
        if count is None:
            count = obj.podcasts.count()
        return count
    podcasts_count.admin_order_field = "_podcasts_count"
    podcasts_count.short_description = "Podcast Count"

    def podcasts_link(self, obj):
        count = self.podcasts_count(obj)
        if count > 0:
            return format_html('<a href="/admin/podcasts/podcast/?categories__id__exact={}" style="color: #2563eb; font-weight: 500;">View Podcasts ({}) ↗</a>', obj.id, count)
        return "—"
    podcasts_link.short_description = "Podcasts"


@admin.register(Country)
class CountryAdmin(admin.ModelAdmin):
    list_display = ["code_badge", "name", "platforms_badge", "is_active", "rankings_count", "updated_at"]
    list_filter = ["is_active", "supports_apple", "supports_spotify"]
    search_fields = ["code", "name"]
    list_editable = ["is_active"]
    ordering = ["name"]
    list_per_page = 50
    list_max_show_all = 250
    show_full_result_count = False
    actions = ["activate_countries", "deactivate_countries", "sync_from_platforms"]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_rankings_count=Count("chart_rankings"))

    def code_badge(self, obj):
        return format_html('<span style="font-family: monospace; font-weight: bold; background: #e2e8f0; padding: 2px 6px; border-radius: 4px;">{}</span>', obj.code.upper())
    code_badge.short_description = "Code"

    def platforms_badge(self, obj):
        badges = []
        if obj.supports_apple:
            badges.append('<span style="background: #872996; color: white; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: bold; margin-right: 4px;">Apple</span>')
        if obj.supports_spotify:
            badges.append('<span style="background: #1DB954; color: white; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: bold;">Spotify</span>')
        return format_html("".join(badges)) if badges else "—"
    platforms_badge.short_description = "Supported Platforms"

    def rankings_count(self, obj):
        count = getattr(obj, "_rankings_count", None)
        if count is None:
            count = obj.chart_rankings.count()
        if count > 0:
            return format_html('<a href="/admin/podcasts/chartranking/?country__code__exact={}" style="color: #2563eb; font-weight: bold;">{} rankings ↗</a>', obj.code.lower(), count)
        return "0"
    rankings_count.admin_order_field = "_rankings_count"
    rankings_count.short_description = "Database Rankings"

    @admin.action(description="Activate selected countries")
    def activate_countries(self, request, queryset):
        count = queryset.update(is_active=True)
        self.message_user(request, f"{count} countries activated.")

    @admin.action(description="Deactivate selected countries")
    def deactivate_countries(self, request, queryset):
        count = queryset.update(is_active=False)
        self.message_user(request, f"{count} countries deactivated.")

    @admin.action(description="Sync latest country list from platforms")
    def sync_from_platforms(self, request, queryset):
        from apps.podcasts.services.country_discovery import CountryDiscoveryService
        count = CountryDiscoveryService.sync_countries_to_db(force_refresh=True)
        self.message_user(request, f"{count} countries successfully synced from platforms.")


@admin.register(ChartCategory)
class ChartCategoryAdmin(admin.ModelAdmin):
    list_display = ["slug", "name", "parent", "apple_genre_id", "platform_badge", "display_order", "is_active", "rankings_count"]
    list_filter = ["parent", "is_active", "platform"]
    search_fields = ["slug", "name"]
    list_editable = ["is_active", "display_order"]
    ordering = ["display_order", "name"]
    list_per_page = 50
    list_max_show_all = 250
    show_full_result_count = False

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_rankings_count=Count("chart_rankings"))

    def platform_badge(self, obj):
        if obj.platform == "spotify":
            return format_html('<span style="background: #1DB954; color: white; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: bold;">Spotify</span>')
        elif obj.platform == "apple":
            return format_html('<span style="background: #872996; color: white; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: bold;">Apple</span>')
        return format_html('<span style="background: #3b82f6; color: white; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: bold;">All Platforms</span>')
    platform_badge.short_description = "Platform"

    def rankings_count(self, obj):
        count = getattr(obj, "_rankings_count", None)
        if count is None:
            count = obj.chart_rankings.count()
        if count > 0:
            return format_html('<a href="/admin/podcasts/chartranking/?category__slug__exact={}" style="color: #2563eb; font-weight: bold;">{} rankings ↗</a>', obj.slug, count)
        return "0"
    rankings_count.admin_order_field = "_rankings_count"
    rankings_count.short_description = "Database Rankings"


class PodcastSourceFilter(admin.SimpleListFilter):
    title = "Ranking Source"
    parameter_name = "source"

    def lookups(self, request, model_admin):
        return ChartRanking.Source.choices

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(chart_rankings__source=self.value()).distinct()
        return queryset


@admin.register(Podcast)
class PodcastAdmin(admin.ModelAdmin):
    list_display = [
        "cover_preview",
        "title",
        "publisher",
        "sources_badge",
        "rating_display",
        "frequency",
        "episodes_count",
        "rankings_count",
        "updated_at",
    ]
    list_display_links = ["cover_preview", "title"]
    search_fields = ["title", "publisher", "description"]
    list_filter = [PodcastSourceFilter, "categories", "frequency", "language"]
    filter_horizontal = ["categories"]
    readonly_fields = ["cover_preview_large", "platform_links", "created_at", "updated_at"]
    inlines = [PodcastRatingInline, ChartRankingInline, EpisodeInline]

    # Pagination & Performance optimization
    list_per_page = 25
    list_max_show_all = 100
    show_full_result_count = False
    show_facets = getattr(admin.ShowFacets, "NEVER", False)

    fieldsets = [
        ("General Information", {
            "fields": ("title", "publisher", "description", ("cover_image_url", "cover_preview_large")),
        }),
        ("Categories & Metrics", {
            "fields": ("categories", ("frequency", "language")),
        }),
        ("Links & External Identifiers", {
            "fields": ("feed_url", "website_url", "platform_links", ("spotify_id", "apple_id")),
        }),
        ("Timestamps", {
            "fields": (("created_at", "updated_at"),),
            "classes": ("collapse",),
        }),
    ]

    def get_queryset(self, request):
        ep_subquery = Subquery(
            Episode.objects.filter(podcast_id=OuterRef("pk"))
            .values("podcast_id")
            .annotate(c=Count("id"))
            .values("c")[:1],
            output_field=IntegerField(),
        )
        rank_subquery = Subquery(
            ChartRanking.objects.filter(podcast_id=OuterRef("pk"))
            .values("podcast_id")
            .annotate(c=Count("id"))
            .values("c")[:1],
            output_field=IntegerField(),
        )
        return (
            super()
            .get_queryset(request)
            .prefetch_related(
                "platform_ratings",
                "categories",
                Prefetch(
                    "chart_rankings",
                    queryset=ChartRanking.objects.only("id", "podcast_id", "source")
                )
            )
            .annotate(
                _episodes_count=Coalesce(ep_subquery, 0),
                _rankings_count=Coalesce(rank_subquery, 0),
            )
        )

    def sources_badge(self, obj):
        sources = set(r.source for r in obj.chart_rankings.all())
        if not sources:
            return "—"
        badges = []
        for s in sorted(sources):
            if s == "spotify":
                badges.append('<span style="background: #1DB954; color: white; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: bold; margin-right: 4px;">Spotify</span>')
            elif s == "podchaser":
                badges.append('<span style="background: #6366F1; color: white; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: bold; margin-right: 4px;">Podchaser</span>')
            else:
                badges.append(f'<span style="background: #6B7280; color: white; padding: 2px 6px; border-radius: 4px; font-size: 11px; margin-right: 4px;">{s.title()}</span>')
        return format_html("".join(badges))
    sources_badge.short_description = "Source"

    def platform_links(self, obj):
        links = []
        if obj.spotify_url:
            links.append(f'<a href="{obj.spotify_url}" target="_blank" style="background:#1DB954; color:white; padding:5px 12px; border-radius:4px; text-decoration:none; font-weight:bold; margin-right:8px; display:inline-block;">🎧 Open on Spotify ↗</a>')
        if obj.apple_url:
            links.append(f'<a href="{obj.apple_url}" target="_blank" style="background:#872996; color:white; padding:5px 12px; border-radius:4px; text-decoration:none; font-weight:bold; margin-right:8px; display:inline-block;">🍎 Open on Apple Podcasts ↗</a>')
        if not links:
            return "No external platform links available"
        return format_html("".join(links))
    platform_links.short_description = "Platform Links"

    def cover_preview(self, obj):
        if obj.cover_image_url:
            return format_html(
                '<img src="{}" style="width: 42px; height: 42px; object-fit: cover; border-radius: 6px; box-shadow: 0 1px 3px rgba(0,0,0,0.2);" />',
                obj.cover_image_url
            )
        return "—"
    cover_preview.short_description = "Cover"

    def cover_preview_large(self, obj):
        if obj.cover_image_url:
            return format_html(
                '<img src="{}" style="max-width: 180px; max-height: 180px; object-fit: cover; border-radius: 8px; box-shadow: 0 2px 6px rgba(0,0,0,0.3);" />',
                obj.cover_image_url
            )
        return "No image available"
    cover_preview_large.short_description = "Cover Image"

    def episodes_count(self, obj):
        count = getattr(obj, "_episodes_count", None)
        if count is None:
            count = obj.episodes.count()
        if count > 0:
            return format_html(
                '<a href="/admin/podcasts/episode/?podcast__id__exact={}" style="color: #2563eb; font-weight: bold;">{} episodes ↗</a>',
                obj.id,
                f"{count:,}"
            )
        return "0"
    episodes_count.admin_order_field = "_episodes_count"
    episodes_count.short_description = "Episodes"

    def rankings_count(self, obj):
        count = getattr(obj, "_rankings_count", None)
        if count is None:
            count = obj.chart_rankings.count()
        if count > 0:
            return format_html(
                '<a href="/admin/podcasts/chartranking/?podcast__id__exact={}" style="color: #2563eb; font-weight: bold;">{} rankings ↗</a>',
                obj.id,
                f"{count:,}"
            )
        return "0"
    rankings_count.admin_order_field = "_rankings_count"
    rankings_count.short_description = "Rankings"

    def rating_display(self, obj):
        ratings = obj.platform_ratings.all()
        if ratings:
            badges = []
            for r in ratings:
                color = "#1DB954" if r.source == "spotify" else ("#872996" if r.source == "apple" else "#4b5563")
                badges.append(
                    f'<span style="display: inline-block; margin: 1px 2px; padding: 2px 6px; border-radius: 4px; background: {color}; color: white; font-size: 11px; font-weight: 500;">'
                    f'{r.get_source_display()}: ★ {r.rating} <span style="opacity: 0.85;">({r.rating_count:,})</span></span>'
                )
            return format_html(" ".join(badges))
        return "—"
    rating_display.short_description = "Platform Ratings"


@admin.register(Episode)
class EpisodeAdmin(admin.ModelAdmin):
    paginator = LargeTablePaginator
    list_display = ["title", "podcast", "published_at", "duration"]
    search_fields = ["title", "podcast__title", "guid"]
    list_filter = ["published_at"]
    autocomplete_fields = ["podcast"]
    readonly_fields = ["created_at", "updated_at"]
    list_select_related = ["podcast"]
    ordering = ["-published_at", "-id"]
    date_hierarchy = "published_at"

    # Pagination & Performance optimization
    list_per_page = 50
    list_max_show_all = 200
    show_full_result_count = False
    show_facets = getattr(admin.ShowFacets, "NEVER", False)


@admin.register(ChartRanking)
class ChartRankingAdmin(admin.ModelAdmin):
    paginator = LargeTablePaginator
    list_display = ["date", "source", "country", "category", "rank", "podcast", "episode_display"]
    list_filter = ["source", "country", "category", "date"]
    search_fields = ["podcast__title", "episode__title"]
    autocomplete_fields = ["podcast", "country", "category", "episode"]
    readonly_fields = ["created_at"]
    list_select_related = ["podcast", "country", "category", "episode"]
    date_hierarchy = "date"
    ordering = ["-date", "rank"]

    # Pagination & Performance optimization
    list_per_page = 50
    list_max_show_all = 200
    show_full_result_count = False
    show_facets = getattr(admin.ShowFacets, "NEVER", False)

    def episode_display(self, obj):
        if obj.episode:
            title = obj.episode.title
            if len(title) > 40:
                title = title[:40] + "..."
            return format_html(
                '<a href="/admin/podcasts/episode/{}/change/" style="color: #059669; font-weight: 500;" title="{}">'
                '🎙️ {}</a>',
                obj.episode.id,
                obj.episode.title,
                title
            )
        return format_html('<span style="color: #9ca3af;">— (Podcast)</span>')
    episode_display.short_description = "Ranked Episode"


@admin.register(PodcastRating)
class PodcastRatingAdmin(admin.ModelAdmin):
    list_display = ["podcast", "source", "rating", "rating_count", "synced_at"]
    list_filter = ["source"]
    search_fields = ["podcast__title"]
    autocomplete_fields = ["podcast"]
    readonly_fields = ["synced_at", "created_at", "updated_at"]
    list_select_related = ["podcast"]
    ordering = ["-synced_at", "-id"]

    # Pagination & Performance optimization
    list_per_page = 50
    list_max_show_all = 200
    show_full_result_count = False
    show_facets = getattr(admin.ShowFacets, "NEVER", False)



