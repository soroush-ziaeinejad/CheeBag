from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("shop/", views.product_list, name="product_list"),
    path("products/<int:pk>/", views.product_detail, name="product_detail"),
    path("orders/", views.order_list, name="order_list"),
    path("orders/<int:pk>/", views.order_detail, name="order_detail"),
    path("switch-customer/", views.switch_customer, name="switch_customer"),
    path("assistant/chat/", views.assistant_chat, name="assistant_chat"),
    # the customer's click on a confirmation card (the only way an order gets cancelled)
    path("assistant/actions/confirm/", views.assistant_action, {"action": "confirm"}, name="assistant_confirm"),
    path("assistant/actions/discard/", views.assistant_action, {"action": "discard"}, name="assistant_discard"),
]
