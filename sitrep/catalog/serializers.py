from rest_framework import serializers

from .models import CatalogoVersion, Recurso


class RecursoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Recurso
        fields = [
            "id", "nombre", "codigo", "descripcion", "area", "categoria", "tipo", "periodicidad",
            "requerimientos", "regla_aplicacion", "naviera", "nave",
            "catalogo_version", "linaje_raiz", "activo", "created_at",
        ]


class CatalogoVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = CatalogoVersion
        fields = ["id", "naviera", "nave", "numero", "creado_en", "creado_por", "nota"]


class FilaPublicarSerializer(serializers.Serializer):
    base = serializers.PrimaryKeyRelatedField(queryset=Recurso.objects.all(), required=False, allow_null=True, default=None)
    cambios = serializers.DictField(required=False, default=dict)


class PublicarSerializer(serializers.Serializer):
    naviera_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    nave_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    nota = serializers.CharField(required=False, allow_blank=True, default="")
    filas = FilaPublicarSerializer(many=True)


class RevertirSerializer(serializers.Serializer):
    naviera_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    nave_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    numero_objetivo = serializers.IntegerField()
    nota = serializers.CharField(required=False, allow_blank=True, default="")
