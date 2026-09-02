from django.urls import path

from . import views

urlpatterns = [
    path("", views.ledamot_list, name="ledamot_list"),
    path("ledamoter/<str:intressent_id>/", views.ledamot_detail, name="ledamot_detail"),
    path("voteringar/", views.votering_list, name="votering_list"),
    path("voteringar/<str:votering_id>/", views.votering_detail, name="votering_detail"),
    path("kommande/", views.kommande_list, name="kommande_list"),
]
