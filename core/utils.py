from django.core.paginator import Paginator


def paginate(queryset, page, per_page):
    return Paginator(queryset, per_page).get_page(page)
