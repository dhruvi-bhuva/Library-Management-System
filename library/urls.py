from django.urls import path
from . import views

urlpatterns = [
    path('', views.book_list, name='book_list'),

    path(
        'add-to-cart/<int:book_id>/',
        views.add_to_cart,
        name='add_to_cart'
    ),

    path(
        'cart/',
        views.cart,
        name='cart'
    ),

    path(
        'cart/increase/<int:book_id>/',
        views.increase_quantity,
        name='increase_quantity'
    ),

    path(
        'cart/decrease/<int:book_id>/',
        views.decrease_quantity,
        name='decrease_quantity'
    ),

    path(
        'cart/remove/<int:book_id>/',
        views.remove_from_cart,
        name='remove_from_cart'
    ),
    path(
        'checkout/',
        views.checkout,
        name='checkout'
    ),
    path(
        'payment/verify/',
        views.payment_verify,
        name='payment_verify'
    ),
    path(
        'payment/failed/',
        views.payment_failed,
        name='payment_failed'
    ),
    path(
        'order-success/<uuid:order_id>/',
        views.order_success,
        name='order_success'
    ),
    path(
        'orders/',
        views.order_history,
        name='order_history'
    ),

    # Order Cancellation URLs
    path(
        'order/<uuid:order_id>/cancel/',
        views.cancel_confirm,
        name='cancel_confirm'
    ),
    path(
        'order/<uuid:order_id>/cancel/confirm/',
        views.cancel_order,
        name='cancel_order'
    ),
    path(
        'order/<uuid:order_id>/cancelled/',
        views.cancellation_success,
        name='cancellation_success'
    ),

    # Product Reviews & Ratings URLs
    path(
        'book/<int:book_id>/',
        views.book_detail,
        name='book_detail'
    ),
    path(
        'product/<int:book_id>/',
        views.book_detail,
        name='product_detail'
    ),
    path(
        'book/<int:book_id>/review/',
        views.add_or_update_review,
        name='add_review'
    ),
    path(
        'review/<int:review_id>/edit/',
        views.edit_review,
        name='edit_review'
    ),
    path(
        'review/<int:review_id>/delete/',
        views.delete_review,
        name='delete_review'
    ),

    # Wishlist Management URLs
    path(
        'wishlist/',
        views.wishlist_view,
        name='wishlist'
    ),
    path(
        'wishlist/add/<int:book_id>/',
        views.add_to_wishlist,
        name='add_to_wishlist'
    ),
    path(
        'wishlist/remove/<int:book_id>/',
        views.remove_from_wishlist,
        name='remove_from_wishlist'
    ),
    path(
        'wishlist/toggle/<int:book_id>/',
        views.toggle_wishlist,
        name='toggle_wishlist'
    ),
    path(
        'wishlist/move-to-cart/<int:book_id>/',
        views.move_to_cart,
        name='move_to_cart'
    ),
    path(
        'wishlist/move-all-to-cart/',
        views.move_all_to_cart,
        name='move_all_to_cart'
    ),
]

