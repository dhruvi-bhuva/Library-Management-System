
import hashlib
import hmac
import json
import logging
import uuid
from decimal import Decimal

import razorpay

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponseNotAllowed, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import Book, Order

logger = logging.getLogger(__name__)


# ---------------- RAZORPAY HELPERS ----------------

def is_razorpay_configured():
    return bool(
        getattr(settings, 'RAZORPAY_KEY_ID', '')
        and getattr(settings, 'RAZORPAY_KEY_SECRET', '')
    )


def get_razorpay_client():
    if not is_razorpay_configured():
        raise ValueError('Razorpay is not configured.')

    return razorpay.Client(
        auth=(
            settings.RAZORPAY_KEY_ID,
            settings.RAZORPAY_KEY_SECRET,
        )
    )


# ---------------- BOOK LIST ----------------

def book_list(request):
    books = Book.objects.all()

    return render(
        request,
        'library/book_list.html',
        {'books': books},
    )


# ---------------- CART HELPERS ----------------

def get_cart_items(request):
    cart_data = request.session.get('cart', {})
    items = []
    total = Decimal('0.00')

    if not isinstance(cart_data, dict):
        return items, total

    for book_id, quantity in cart_data.items():
        try:
            book = Book.objects.get(pk=book_id)
            quantity = int(quantity)

            if quantity < 1:
                continue

            price = Decimal(str(book.price))
            subtotal = price * quantity

            items.append({
                'book': book,
                'quantity': quantity,
                'price': price,
                'subtotal': subtotal,
            })

            total += subtotal

        except (Book.DoesNotExist, ValueError, TypeError):
            continue

    return items, total


# ---------------- ADD TO CART ----------------

@login_required
@require_POST
def add_to_cart(request, book_id):
    book = get_object_or_404(Book, pk=book_id)

    cart_data = request.session.get('cart', {})

    if not isinstance(cart_data, dict):
        cart_data = {}

    key = str(book.pk)

    try:
        quantity = int(cart_data.get(key, 0))
    except (ValueError, TypeError):
        quantity = 0

    cart_data[key] = max(quantity, 0) + 1

    request.session['cart'] = cart_data
    request.session.modified = True

    messages.success(
        request,
        f'{book.title} added to cart.'
    )

    return redirect('cart')


# ---------------- CART PAGE ----------------

@login_required
def cart(request):
    items, total = get_cart_items(request)

    return render(
        request,
        'library/cart.html',
        {
            'items': items,
            'cart_items': items,
            'total': total,
        },
    )


# ---------------- INCREASE QUANTITY ----------------

@login_required
@require_POST
def increase_quantity(request, book_id):
    cart_data = request.session.get('cart', {})
    key = str(book_id)

    if not isinstance(cart_data, dict):
        cart_data = {}

    if Book.objects.filter(pk=book_id).exists():
        try:
            cart_data[key] = int(cart_data.get(key, 0)) + 1
        except (ValueError, TypeError):
            cart_data[key] = 1

    request.session['cart'] = cart_data
    request.session.modified = True

    return redirect('cart')


# ---------------- DECREASE QUANTITY ----------------

@login_required
@require_POST
def decrease_quantity(request, book_id):
    cart_data = request.session.get('cart', {})
    key = str(book_id)

    if not isinstance(cart_data, dict):
        cart_data = {}

    if key in cart_data:
        try:
            quantity = int(cart_data[key]) - 1
        except (ValueError, TypeError):
            quantity = 0

        if quantity <= 0:
            cart_data.pop(key, None)
        else:
            cart_data[key] = quantity

    request.session['cart'] = cart_data
    request.session.modified = True

    return redirect('cart')


# ---------------- REMOVE FROM CART ----------------

@login_required
@require_POST
def remove_from_cart(request, book_id):
    cart_data = request.session.get('cart', {})

    if not isinstance(cart_data, dict):
        cart_data = {}

    cart_data.pop(str(book_id), None)

    request.session['cart'] = cart_data
    request.session.modified = True

    messages.success(request, 'Book removed from cart.')

    return redirect('cart')

# ---------------- CHECKOUT ----------------

@login_required
def checkout(request):
    items, total = get_cart_items(request)

    if not items:
        messages.error(request, 'Your cart is empty.')
        return redirect('cart')

    if request.method == 'GET':
        return render(
            request,
            'library/checkout.html',
            {
                'items': items,
                'cart_items': items,
                'total': total,
                'razorpay_key_id': getattr(
                    settings, 'RAZORPAY_KEY_ID', ''
                ),
            },
        )

    if request.method != 'POST':
        return HttpResponseNotAllowed(['GET', 'POST'])

    payment_method = request.POST.get(
        'payment_method', 'COD'
    ).upper()

    if payment_method not in ('COD', 'ONLINE'):
        messages.error(request, 'Invalid payment method.')
        return redirect('checkout')

    if payment_method == 'ONLINE' and not is_razorpay_configured():
        messages.error(request, 'Online payment is not configured.')
        return redirect('checkout')

    try:
        with transaction.atomic():
            items, total = get_cart_items(request)

            if not items or total <= 0:
                messages.error(request, 'Your cart is empty.')
                return redirect('cart')

            order = Order.objects.create(
                order_id=uuid.uuid4(),
                user=request.user,
                total_amount=total,
                payment_method=payment_method,
                payment_status='PENDING',
                order_status='PLACED',
            )

            # Save individual books in the order.
            # This assumes OrderItem has the fields described
            # in your existing project.
            from .models import OrderItem

            for item in items:
                OrderItem.objects.create(
                    order=order,
                    book=item['book'],
                    book_title=item['book'].title,
                    book_image=(
                        item['book'].image.name
                        if item['book'].image else ''
                    ),
                    price=item['price'],
                    quantity=item['quantity'],
                    subtotal=item['subtotal'],
                )

            if payment_method == 'ONLINE':
                rp_order = get_razorpay_client().order.create({
                    'amount': int(total * 100),
                    'currency': 'INR',
                    'receipt': str(order.order_id),
                })

                order.razorpay_order_id = rp_order['id']
                order.save(update_fields=['razorpay_order_id'])

        if payment_method == 'COD':
            request.session['cart'] = {}
            request.session.modified = True

            return redirect(
                'order_success',
                order_id=order.order_id,
            )

        return render(
            request,
            'library/payment.html',
            {
                'order': order,
                'razorpay_order_id': order.razorpay_order_id,
                'razorpay_key_id': settings.RAZORPAY_KEY_ID,
                'amount': int(total * 100),
            },
        )

    except Exception:
        logger.exception('Checkout failed.')
        messages.error(
            request,
            'Checkout failed. Please check the configuration and try again.',
        )
        return redirect('checkout')

# ---------------- PAYMENT VERIFICATION ----------------

@login_required
@require_POST
def payment_verify(request):
    try:
        data = json.loads(request.body or '{}')
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse(
            {'error': 'Invalid request.'},
            status=400,
        )

    rp_order_id = data.get('razorpay_order_id', '')
    payment_id = data.get('razorpay_payment_id', '')
    signature = data.get('razorpay_signature', '')

    if not all([rp_order_id, payment_id, signature]):
        return JsonResponse(
            {'error': 'Payment details are missing.'},
            status=400,
        )

    try:
        with transaction.atomic():
            order = get_object_or_404(
                Order.objects.select_for_update(),
                razorpay_order_id=rp_order_id,
                user=request.user,
            )

            if order.payment_status == 'PAID':
                return JsonResponse({
                    'status': 'success',
                    'redirect_url': (
                        f'/order-success/{order.order_id}/'
                    ),
                })

            client = get_razorpay_client()

            # Verify the payment signature.
            client.utility.verify_payment_signature({
                'razorpay_order_id': rp_order_id,
                'razorpay_payment_id': payment_id,
                'razorpay_signature': signature,
            })

            # Confirm payment status with Razorpay.
            payment = client.payment.fetch(payment_id)

            if payment.get('order_id') != rp_order_id:
                return JsonResponse(
                    {'error': 'Payment order mismatch.'},
                    status=400,
                )

            if payment.get('status') != 'captured':
                return JsonResponse(
                    {'error': 'Payment has not been captured.'},
                    status=400,
                )

            expected_amount = int(
                Decimal(str(order.total_amount)) * 100
            )

            if int(payment.get('amount', 0)) != expected_amount:
                return JsonResponse(
                    {'error': 'Payment amount mismatch.'},
                    status=400,
                )

            order.razorpay_payment_id = payment_id
            order.razorpay_signature = signature
            order.payment_status = 'PAID'
            order.save()

    except Exception:
        logger.exception('Payment verification failed.')
        return JsonResponse(
            {'error': 'Payment verification failed.'},
            status=400,
        )

    request.session['cart'] = {}
    request.session.modified = True

    return JsonResponse({
        'status': 'success',
        'redirect_url': f'/order-success/{order.order_id}/',
    })
