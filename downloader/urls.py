

from django.urls import path
from .views import download_video, download_audio, progress_view

urlpatterns = [
    path('download_video/<str:unique_id>/', download_video, name='download_video'),
    path('download_audio/<str:unique_id>/', download_audio, name='download_audio'),
    path('progress/<str:unique_id>/', progress_view, name='progress'),
]












# #$6_syeuInno