from django.urls import include, path

urlpatterns = [
    path('', include('sitrep.inspection.api_urls')),
    path('', include('sitrep.catalog.api_urls')),
    path('', include('sitrep.fleet.api_urls')),
]
