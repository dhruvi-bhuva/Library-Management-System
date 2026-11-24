
from django.urls import path
from django.contrib.auth import views as auth_views

from . import views


urlpatterns = [
    # Book listing
    path(
        '',
        views.book_list,
        name='book_list',
    ),

    # Cart URLs
    path(
        'add-to-cart/<int:book_id>/',
        views.add_to_cart,
        name='add_to_cart',
    ),
    path(
        'cart/',
        views.cart,
        name='cart',
    ),
    path(
        'cart/increase/<int:book_id>/',
        views.increase_quantity,
        name='increase_quantity',
    ),
    path(
        'cart/decrease/<int:book_id>/',
        views.decrease_quantity,
        name='decrease_quantity',
    ),
    path(
        'cart/remove/<int:book_id>/',
        views.remove_from_cart,
        name='remove_from_cart',
    ),

    # Checkout and payment
    path(
        'checkout/',
        views.checkout,
        name='checkout',
    ),
    path(
        'payment/verify/',
        views.payment_verify,
        name='payment_verify',
    ),
    path(
        'payment/failed/',
        views.payment_failed,
        name='payment_failed',
    ),

    # Orders
    path(
        'order-success/<uuid:order_id>/',
        views.order_success,
        name='order_success',
    ),
    path(
        'orders/',
        views.order_history,
        name='order_history',
    ),
    path(
        'order/<uuid:order_id>/',
        views.order_detail,
        name='order_detail',
    ),

    # Order cancellation
    path(
        'order/<uuid:order_id>/cancel/',
        views.cancel_confirm,
        name='cancel_confirm',
    ),
    path(
        'order/<uuid:order_id>/cancel/confirm/',
        views.cancel_order,
        name='cancel_order',
    ),
    path(
        'order/<uuid:order_id>/cancelled/',
        views.cancellation_success,
        name='cancellation_success',
    ),

    # Razorpay webhook
    path(
        'webhook/razorpay/',
        views.razorpay_webhook,
        name='razorpay_webhook',
    ),

    # Authentication
    path(
        'login/',
        auth_views.LoginView.as_view(
            template_name='login.html',
        ),
        name='login',
    ),
    path(
        'logout/',
        auth_views.LogoutView.as_view(
            next_page='login',
        ),
        name='logout',
    ),
]
