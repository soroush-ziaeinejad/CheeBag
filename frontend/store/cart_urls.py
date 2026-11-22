from django.urls import path

from . import cart

urlpatterns = [
    path("", cart.cart_page, name="cart"),
    path("add/<int:pk>/", cart.cart_add, name="cart_add"),
    path("add-json/<int:pk>/", cart.cart_add_json, name="cart_add_json"),   # from the chat's product cards
    path("update/<int:pk>/", cart.cart_update, name="cart_update"),
    path("submit/", cart.cart_submit, name="cart_submit"),
]
