from django.urls import include, path

urlpatterns = [
    path('', include('sitrep.inspection.api_urls')),
]
