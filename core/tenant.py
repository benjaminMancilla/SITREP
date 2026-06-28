from django.db import models


class TenantQuerySet(models.QuerySet):
    def for_naviera(self, naviera):
        """Scope to a single tenant. Always call before any further filtering."""
        return self.filter(naviera=naviera)


class TenantManager(models.Manager):
    def get_queryset(self):
        return TenantQuerySet(self.model, using=self._db)

    def for_naviera(self, naviera):
        return self.get_queryset().for_naviera(naviera)
