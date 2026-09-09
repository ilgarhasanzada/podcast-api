from rest_framework.pagination import PageNumberPagination, LimitOffsetPagination


class StandardResultsSetPagination(PageNumberPagination):
    """Standard page-number pagination (page=1, page_size=20, max=250)."""
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 250


class EpisodeOffsetPagination(LimitOffsetPagination):
    """Offset-based pagination for high-volume datasets (limit=20, offset=0, max=250)."""
    default_limit = 20
    max_limit = 250

