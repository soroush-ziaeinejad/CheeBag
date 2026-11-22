from django.urls import path

from . import studio_views

# included under /studio/ by store/urls.py
urlpatterns = [
    path("", studio_views.studio_page, name="studio_page"),   # the studio on its own page (a bigger window)
    path("upload/", studio_views.studio_upload, name="studio_upload"),
    path("products/", studio_views.studio_products, name="studio_products"),
    path("shops/", studio_views.studio_shop_search, name="studio_shops"),
    path("rooms/<slug:room_id>/analyze/", studio_views.studio_analyze, name="studio_analyze"),
    path("rooms/<slug:room_id>/render/", studio_views.studio_render, name="studio_render"),
    path("rooms/<slug:room_id>/ask/", studio_views.studio_ask, name="studio_ask"),
    path("rooms/<slug:room_id>/plan/", studio_views.studio_plan, name="studio_plan"),
    path("rooms/<slug:room_id>/image/", studio_views.studio_image, name="studio_image"),
]
