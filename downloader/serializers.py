from rest_framework import serializers
from .models import MediaStore

class MediaStoreSerializer(serializers.ModelSerializer):
    class Meta:
        model = MediaStore
        fields = '__all__'
