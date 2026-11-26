import uuid
import logging
from decimal import Decimal
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.db import transaction
from django.conf import settings
from django.utils import timezone
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from .models import Book, Order, OrderItem, Review, Wishlist
from .forms import ReviewForm
from .services import (
    get_verified_cart,
    clear_cart,
    validate_delivery_form,
    is_razorpay_configured,
    is_razorpay_demo_mode,
    generate_demo_signature,
    verify_demo_signature,
    get_razorpay_client,
)

logger = logging.getLogger(__name__)


def book_list(request):
    books = Book.objects.filter(available=True)
    user_wishlist_ids = set()
    if request.user.is_authenticated:
        user_wishlist_ids = set(request.user.wishlist_items.values_list('book_id', flat=True))

    return render(
        request,
        'library/book_list.html',
        {
            'books': books,
            'user_wishlist_ids': user_wishlist_ids,
        }
    )


def add_to_cart(request, book_id):
    book = get_object_or_404(Book, id=book_id)

    cart_data = request.session.get('cart', {})
    book_id_str = str(book_id)

    if book_id_str in cart_data:
        cart_data[book_id_str] += 1
    else:
        cart_data[book_id_str] = 1

    request.session['cart'] = cart_data
    request.session.modified = True

    return redirect('cart')


def cart(request):
    verified_cart = get_verified_cart(request)

    return render(
        request,
        'library/cart.html',
        {
            'books': verified_cart['items'],
            'total': verified_cart['total_amount'],
            'total_quantity': verified_cart['total_quantity'],
            'is_empty': verified_cart['is_empty'],
        }
    )


def increase_quantity(request, book_id):
    cart_data = request.session.get('cart', {})
    book_id_str = str(book_id)

    if book_id_str in cart_data:
        cart_data[book_id_str] += 1

    request.session['cart'] = cart_data
    request.session.modified = True

    return redirect('cart')


def decrease_quantity(request, book_id):
    cart_data = request.session.get('cart', {})
    book_id_str = str(book_id)

    if book_id_str in cart_data and cart_data[book_id_str] > 1:
        cart_data[book_id_str] -= 1

    request.session['cart'] = cart_data
    request.session.modified = True

    return redirect('cart')


def remove_from_cart(request, book_id):
    cart_data = request.session.get('cart', {})
    book_id_str = str(book_id)

    if book_id_str in cart_data:
        del cart_data[book_id_str]

    request.session['cart'] = cart_data
    request.session.modified = True

    return redirect('cart')


def checkout(request):
    """
    Renders checkout page and handles COD and Razorpay initiation.
    Recalculates all cart items and subtotals directly from the database.
    Supports both Razorpay Test Mode and Razorpay Demo Simulation.
    """
    verified_cart = get_verified_cart(request)

    # If cart is empty, redirect back to cart
    if verified_cart['is_empty']:
        return redirect('cart')

    errors = {}
    form_data = {
        'payment_method': 'COD',
    }

    # Pre-fill user data if authenticated
    if request.user.is_authenticated and request.method == 'GET':
        full_name = f"{request.user.first_name} {request.user.last_name}".strip() or request.user.username
        form_data['customer_name'] = full_name
        form_data['customer_email'] = request.user.email or ''

    if request.method == 'POST':
        cleaned, form_errors = validate_delivery_form(request.POST)
        form_data = request.POST.dict()

        if form_errors:
            errors = form_errors
        else:
            # 1. CASH ON DELIVERY (COD)
            if cleaned['payment_method'] == 'COD':
                with transaction.atomic():
                    order = Order.objects.create(
                        user=request.user if request.user.is_authenticated else None,
                        customer_name=cleaned['customer_name'],
                        customer_email=cleaned['customer_email'],
                        mobile=cleaned['mobile'],
                        address=cleaned['address'],
                        city=cleaned['city'],
                        state=cleaned['state'],
                        pincode=cleaned['pincode'],
                        total_amount=verified_cart['total_amount'],
                        order_status='PLACED',
                        payment_method='COD',
                        payment_status='PENDING',
                        cancellation_status='NOT_CANCELLED',
                        refund_status='NOT_APPLICABLE',
                    )
                    for item in verified_cart['items']:
                        OrderItem.objects.create(
                            order=order,
                            book=item['book'],
                            book_title=item['book'].title,
                            price=item['book'].price,
                            quantity=item['quantity'],
                            subtotal=item['subtotal'],
                        )

                    # Clear cart only after successful order placement
                    clear_cart(request)

                return redirect('order_success', order_id=order.order_id)

            # 2. ONLINE PAYMENT (RAZORPAY TEST / DEMO MODE)
            elif cleaned['payment_method'] == 'ONLINE':
                amount_in_paise = int(verified_cart['total_amount'] * 100)
                is_demo = is_razorpay_demo_mode()
                razorpay_order_id = ''
                key_id = getattr(settings, 'RAZORPAY_KEY_ID', '').strip() or 'rzp_test_demo'

                # If Razorpay keys are configured and valid
                if is_razorpay_configured():
                    try:
                        client = get_razorpay_client()
                        razorpay_order = client.order.create({
                            'amount': amount_in_paise,
                            'currency': 'INR',
                            'payment_capture': '1',
                            'notes': {
                                'customer_name': cleaned['customer_name'],
                                'mobile': cleaned['mobile'],
                                'items_count': str(verified_cart['total_quantity']),
                            }
                        })
                        razorpay_order_id = razorpay_order['id']
                        is_demo = False
                    except Exception as e:
                        logger.error(f"Error creating Razorpay order: {e}")
                        if getattr(settings, 'RAZORPAY_DEMO_MODE', True):
                            is_demo = True
                            razorpay_order_id = f"order_demo_{uuid.uuid4().hex[:14]}"
                        else:
                            errors['general'] = (
                                f"Unable to initiate Razorpay payment: {str(e)}. "
                                "Please check your Razorpay Test keys or choose Cash on Delivery."
                            )
                else:
                    if getattr(settings, 'RAZORPAY_DEMO_MODE', True):
                        is_demo = True
                        razorpay_order_id = f"order_demo_{uuid.uuid4().hex[:14]}"
                    else:
                        errors['payment_method'] = (
                            "Razorpay Test API Keys are not configured in your .env file. "
                            "Online payment is disabled. Please select Cash on Delivery to place your order."
                        )
                        form_data['payment_method'] = 'COD'

                if not errors:
                    # Save pending order data in session for verification
                    request.session['pending_order_data'] = cleaned
                    request.session['pending_razorpay_order_id'] = razorpay_order_id
                    request.session.modified = True

                    demo_payment_id = f"pay_demo_{uuid.uuid4().hex[:14]}"
                    demo_signature = generate_demo_signature(razorpay_order_id, demo_payment_id)

                    context = {
                        'razorpay_order_id': razorpay_order_id,
                        'razorpay_key_id': key_id,
                        'amount_in_paise': amount_in_paise,
                        'total_amount': verified_cart['total_amount'],
                        'cart': verified_cart,
                        'delivery': cleaned,
                        'is_demo': is_demo,
                        'demo_payment_id': demo_payment_id,
                        'demo_signature': demo_signature,
                        'verify_url': reverse('payment_verify'),
                        'failed_url': reverse('payment_failed'),
                    }
                    return render(request, 'library/razorpay_checkout.html', context)

    return render(
        request,
        'library/checkout.html',
        {
            'cart': verified_cart,
            'form_data': form_data,
            'errors': errors,
            'razorpay_configured': is_razorpay_configured(),
            'razorpay_demo': getattr(settings, 'RAZORPAY_DEMO_MODE', True),
        }
    )


def payment_verify(request):
    """
    Secure server-side verification of Razorpay payment signature.
    Supports both official SDK verification and demo mode simulation.
    Prevents duplicate orders and repeated verifications.
    Marks order as PAID only after cryptographic signature verification.
    """
    if request.method != 'POST':
        return redirect('cart')

    rzp_payment_id = request.POST.get('razorpay_payment_id', '').strip()
    rzp_order_id = request.POST.get('razorpay_order_id', '').strip()
    rzp_signature = request.POST.get('razorpay_signature', '').strip()

    if not (rzp_payment_id and rzp_order_id and rzp_signature):
        return redirect(f"{reverse('payment_failed')}?reason=missing_parameters")

    # Idempotency check: If this payment ID was already processed, avoid duplicate order
    existing_order = Order.objects.filter(razorpay_payment_id=rzp_payment_id).first()
    if existing_order:
        clear_cart(request)
        return redirect('order_success', order_id=existing_order.order_id)

    # Determine if this is a demo order or live Razorpay order
    is_demo_order = (
        rzp_order_id.startswith('order_demo_') or
        rzp_payment_id.startswith('pay_demo_')
    )

    client = None

    if is_demo_order:
        # Cryptographic verification for demo payment
        if not verify_demo_signature(rzp_order_id, rzp_payment_id, rzp_signature):
            logger.warning(f"Demo signature verification failed for payment {rzp_payment_id}")
            return redirect(f"{reverse('payment_failed')}?reason=signature_mismatch")
    else:
        # Cryptographic signature verification using official Razorpay SDK
        try:
            client = get_razorpay_client()
            client.utility.verify_payment_signature({
                'razorpay_order_id': rzp_order_id,
                'razorpay_payment_id': rzp_payment_id,
                'razorpay_signature': rzp_signature,
            })
        except Exception as e:
            logger.warning(f"Razorpay signature verification failed for payment {rzp_payment_id}: {e}")
            return redirect(f"{reverse('payment_failed')}?reason=signature_mismatch")

    # Fetch verified cart total from database
    verified_cart = get_verified_cart(request)
    if verified_cart['is_empty']:
        # If cart is already empty, check if order exists for this razorpay_order_id
        order_for_rzp = Order.objects.filter(razorpay_order_id=rzp_order_id).first()
        if order_for_rzp:
            return redirect('order_success', order_id=order_for_rzp.order_id)
        return redirect(f"{reverse('payment_failed')}?reason=cart_empty")

    # Validate payment details with Razorpay API (for live SDK transactions)
    if client is not None and not is_demo_order:
        try:
            payment_details = client.payment.fetch(rzp_payment_id)
            expected_amount_paise = int(verified_cart['total_amount'] * 100)

            # Validate order ID matches
            if payment_details.get('order_id') and payment_details.get('order_id') != rzp_order_id:
                logger.warning(
                    f"Razorpay order_id mismatch: expected {rzp_order_id}, got {payment_details.get('order_id')}"
                )
                return redirect(f"{reverse('payment_failed')}?reason=order_mismatch")

            # Validate payment amount matches verified cart
            if payment_details.get('amount') and payment_details.get('amount') != expected_amount_paise:
                logger.warning(
                    f"Payment amount mismatch: expected {expected_amount_paise}, got {payment_details.get('amount')}"
                )
                return redirect(f"{reverse('payment_failed')}?reason=amount_mismatch")

            # Validate status is authorized or captured
            if payment_details.get('status') and payment_details.get('status') not in ['captured', 'authorized']:
                logger.warning(f"Payment status not captured/authorized: {payment_details.get('status')}")
                return redirect(f"{reverse('payment_failed')}?reason=payment_not_captured")
        except Exception as e:
            if "SignatureVerificationError" in str(type(e)):
                raise
            # If network/API check fails but signature was valid, log notice
            logger.warning(f"Razorpay payment fetch notice: {e}")

    # Retrieve pending delivery details from session or fallback to POST
    delivery = request.session.get('pending_order_data', {})
    customer_name = delivery.get('customer_name') or request.POST.get('customer_name', 'Library Customer')
    customer_email = delivery.get('customer_email') or request.POST.get('customer_email', '')
    mobile = delivery.get('mobile') or request.POST.get('mobile', '')
    address = delivery.get('address') or request.POST.get('address', '')
    city = delivery.get('city') or request.POST.get('city', '')
    state = delivery.get('state') or request.POST.get('state', '')
    pincode = delivery.get('pincode') or request.POST.get('pincode', '')

    with transaction.atomic():
        order = Order.objects.create(
            user=request.user if request.user.is_authenticated else None,
            customer_name=customer_name,
            customer_email=customer_email,
            mobile=mobile,
            address=address,
            city=city,
            state=state,
            pincode=pincode,
            total_amount=verified_cart['total_amount'],
            order_status='PLACED',
            payment_method='ONLINE',
            payment_status='PAID',
            cancellation_status='NOT_CANCELLED',
            refund_status='NOT_APPLICABLE',
            razorpay_order_id=rzp_order_id,
            razorpay_payment_id=rzp_payment_id,
            razorpay_signature=rzp_signature,
        )

        for item in verified_cart['items']:
            OrderItem.objects.create(
                order=order,
                book=item['book'],
                book_title=item['book'].title,
                price=item['book'].price,
                quantity=item['quantity'],
                subtotal=item['subtotal'],
            )

        # Clear cart and pending session data only after database transaction succeeds
        clear_cart(request)
        request.session.pop('pending_order_data', None)
        request.session.pop('pending_razorpay_order_id', None)
        request.session.modified = True

    return redirect('order_success', order_id=order.order_id)


def payment_failed(request):
    """
    Renders payment failure / cancellation page.
    The cart is preserved so the user can easily retry checkout.
    """
    reason = request.GET.get('reason', 'Payment could not be completed.')
    description = request.GET.get('description', '')
    error_code = request.GET.get('code', '')

    reason_messages = {
        'cancelled': 'You closed or cancelled the Razorpay payment window before completing the payment.',
        'signature_mismatch': 'Payment signature could not be verified securely. The transaction was rejected.',
        'order_mismatch': 'The Razorpay Order ID did not match the transaction records. Payment was rejected.',
        'amount_mismatch': 'The paid amount did not match the cart total. Payment was rejected.',
        'payment_not_captured': 'The payment could not be captured by the bank or gateway.',
        'missing_parameters': 'Required payment details were missing from the payment gateway response.',
        'cart_empty': 'Your cart is empty or this order has already been processed.',
        'failed': description or 'The payment attempt failed at the gateway/bank.',
    }

    friendly_message = reason_messages.get(reason, description or reason)
    verified_cart = get_verified_cart(request)

    return render(
        request,
        'library/payment_failed.html',
        {
            'reason': friendly_message,
            'error_code': error_code,
            'cart': verified_cart,
        }
    )


def order_success(request, order_id):
    """
    Displays order confirmation with complete order details and status.
    """
    order = get_object_or_404(Order, order_id=order_id)
    return render(
        request,
        'library/order_success.html',
        {
            'order': order,
            'items': order.items.all(),
        }
    )


def order_history(request):
    """
    Displays order history.
    If authenticated, shows current user's orders; otherwise shows recent orders.
    """
    if request.user.is_authenticated:
        orders = Order.objects.filter(user=request.user).prefetch_related('items')
    else:
        orders = Order.objects.all().prefetch_related('items')[:25]

    return render(
        request,
        'library/order_history.html',
        {'orders': orders}
    )


def cancel_confirm(request, order_id):
    """
    Shows a cancellation confirmation page for an eligible order.
    GET: Render the confirmation page.
    """
    order = get_object_or_404(Order, order_id=order_id)

    # Ownership check: if user is authenticated, ensure it's their order
    if request.user.is_authenticated and order.user and order.user != request.user:
        return redirect('order_history')

    if not order.is_cancellable():
        return render(
            request,
            'library/cancel_confirm.html',
            {
                'order': order,
                'not_eligible': True,
                'message': 'This order is not eligible for cancellation. '
                           'Only orders in Placed or Processing status with Pending (COD) '
                           'or Paid (Online) payment status can be cancelled.',
            }
        )

    return render(
        request,
        'library/cancel_confirm.html',
        {'order': order, 'not_eligible': False}
    )


def cancel_order(request, order_id):
    """
    Processes order cancellation. POST only.
    - Updates order_status to CANCELLED.
    - COD orders: cancellation_status CANCELLED, payment_status CANCELLED, refund_status NOT_APPLICABLE.
    - ONLINE/PAID orders: cancellation_status CANCELLED, payment_status CANCELLED, refund_status REFUND_PENDING (simulated).
    Cart is NOT cleared; database is NOT reset.
    """
    if request.method != 'POST':
        return redirect('order_history')

    order = get_object_or_404(Order, order_id=order_id)

    # Ownership check
    if request.user.is_authenticated and order.user and order.user != request.user:
        return redirect('order_history')

    if not order.is_cancellable():
        return render(
            request,
            'library/cancel_confirm.html',
            {
                'order': order,
                'not_eligible': True,
                'message': 'This order cannot be cancelled. '
                           'Only Placed or Processing orders that have not yet shipped are eligible.',
            }
        )

    cancellation_reason = request.POST.get('cancellation_reason', '').strip()

    with transaction.atomic():
        order.order_status = 'CANCELLED'
        order.cancellation_status = 'CANCELLED'
        order.cancellation_reason = cancellation_reason
        order.cancelled_at = timezone.now()

        if order.payment_method == 'ONLINE' and order.payment_status in ['PAID', 'CANCELLED']:
            # Online orders that were paid: record refund status as REFUND_PENDING
            order.payment_status = 'CANCELLED'
            order.refund_status = 'REFUND_PENDING'
        else:
            # COD orders: no refund required
            order.payment_status = 'CANCELLED'
            order.refund_status = 'NOT_APPLICABLE'

        order.save()

    logger.info(
        f"Order {str(order.order_id)[:8]} cancelled. "
        f"Method: {order.payment_method}, Refund: {order.refund_status}"
    )

    return redirect('cancellation_success', order_id=order.order_id)


def cancellation_success(request, order_id):
    """Renders the cancellation confirmation/success page."""
    order = get_object_or_404(Order, order_id=order_id)
    return render(
        request,
        'library/cancellation_success.html',
        {'order': order}
    )


def book_detail(request, book_id):
    """
    Product Detail Page:
    - Displays full product information.
    - Shows overall rating stats (average rating, review count, star distribution).
    - Lists all customer reviews.
    - Determines if the currently logged-in user has purchased this product.
    - If purchased: allows adding a review, or editing/deleting their existing review.
    """
    book = get_object_or_404(Book, id=book_id)
    reviews = book.reviews.select_related('user').all()
    avg_rating = book.average_rating()
    total_reviews = book.total_reviews()
    star_breakdown = book.star_breakdown()

    has_purchased = False
    user_review = None
    is_in_wishlist = False

    if request.user.is_authenticated:
        has_purchased = book.is_purchased_by(request.user)
        user_review = book.reviews.filter(user=request.user).first()
        is_in_wishlist = book.is_in_wishlist(request.user)

    review_form = ReviewForm(instance=user_review) if user_review else ReviewForm()

    context = {
        'book': book,
        'reviews': reviews,
        'avg_rating': avg_rating,
        'total_reviews': total_reviews,
        'star_breakdown': star_breakdown,
        'has_purchased': has_purchased,
        'user_review': user_review,
        'review_form': review_form,
        'is_in_wishlist': is_in_wishlist,
    }
    return render(request, 'library/book_detail.html', context)


@login_required
def add_or_update_review(request, book_id):
    """
    Handles creating or updating a review for a book.
    Enforces rule: Only users who have purchased the product can submit a review.
    """
    if request.method != 'POST':
        return redirect('book_detail', book_id=book_id)

    book = get_object_or_404(Book, id=book_id)

    # Check verified purchase
    if not book.is_purchased_by(request.user):
        messages.error(
            request,
            "Only customers who have purchased this product can submit a rating and review."
        )
        return redirect('book_detail', book_id=book.id)

    # Validate rating
    try:
        rating_val = int(request.POST.get('rating', 5))
        if rating_val < 1 or rating_val > 5:
            rating_val = 5
    except (ValueError, TypeError):
        rating_val = 5

    review_text = request.POST.get('review', '').strip()

    review_obj, created = Review.objects.update_or_create(
        book=book,
        user=request.user,
        defaults={
            'rating': rating_val,
            'review': review_text,
        }
    )

    if created:
        messages.success(request, "Thank you! Your review and rating have been posted.")
    else:
        messages.success(request, "Your review has been updated successfully.")

    return redirect(f"{reverse('book_detail', kwargs={'book_id': book.id})}#reviews")


@login_required
def edit_review(request, review_id):
    """
    Allows a user to edit their own review.
    Superusers can also edit any review.
    """
    review = get_object_or_404(Review, id=review_id)

    if review.user != request.user and not request.user.is_superuser:
        messages.error(request, "You are only permitted to edit your own review.")
        return redirect('book_detail', book_id=review.book.id)

    if request.method == 'POST':
        try:
            rating_val = int(request.POST.get('rating', review.rating))
            if rating_val < 1 or rating_val > 5:
                rating_val = 5
        except (ValueError, TypeError):
            rating_val = review.rating

        review_text = request.POST.get('review', '').strip()
        review.rating = rating_val
        review.review = review_text
        review.save()

        messages.success(request, "Your review was updated successfully.")
        return redirect(f"{reverse('book_detail', kwargs={'book_id': review.book.id})}#reviews")

    form = ReviewForm(instance=review)
    return render(
        request,
        'library/edit_review.html',
        {
            'review': review,
            'book': review.book,
            'form': form,
        }
    )


@login_required
def delete_review(request, review_id):
    """
    Allows a user to delete their own review.
    Staff and superusers can delete any review.
    """
    review = get_object_or_404(Review, id=review_id)
    book_id = review.book.id

    if review.user != request.user and not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "You are only permitted to delete your own review.")
        return redirect('book_detail', book_id=book_id)

    review.delete()
    messages.success(request, "The review has been deleted successfully.")
    return redirect(f"{reverse('book_detail', kwargs={'book_id': book_id})}#reviews")


# ==============================================================================
# WISHLIST MODULE
# ==============================================================================

@login_required
def wishlist_view(request):
    """
    Renders the dedicated Wishlist page displaying all saved products for the logged-in user.
    """
    wishlist_items = Wishlist.objects.filter(
        user=request.user
    ).select_related('book', 'book__author')

    return render(
        request,
        'library/wishlist.html',
        {
            'wishlist_items': wishlist_items,
            'total_items': wishlist_items.count(),
        }
    )


@login_required
def add_to_wishlist(request, book_id):
    """
    Adds a book to the user's wishlist.
    """
    book = get_object_or_404(Book, id=book_id)
    item, created = Wishlist.objects.get_or_create(user=request.user, book=book)

    if created:
        messages.success(request, f"'{book.title}' added to your Wishlist ❤️")
    else:
        messages.info(request, f"'{book.title}' is already in your Wishlist.")

    redirect_url = request.META.get('HTTP_REFERER') or reverse('book_detail', kwargs={'book_id': book.id})
    return redirect(redirect_url)


@login_required
def remove_from_wishlist(request, book_id):
    """
    Removes a book from the user's wishlist.
    """
    book = get_object_or_404(Book, id=book_id)
    deleted_count, _ = Wishlist.objects.filter(user=request.user, book=book).delete()

    if deleted_count > 0:
        messages.success(request, f"'{book.title}' removed from your Wishlist.")
    else:
        messages.info(request, f"'{book.title}' was not in your Wishlist.")

    redirect_url = request.META.get('HTTP_REFERER') or reverse('wishlist')
    return redirect(redirect_url)


@login_required
def toggle_wishlist(request, book_id):
    """
    Toggles a book in/out of the user's wishlist.
    Supports standard HTTP redirects and AJAX/JSON responses.
    """
    book = get_object_or_404(Book, id=book_id)
    existing = Wishlist.objects.filter(user=request.user, book=book).first()

    if existing:
        existing.delete()
        in_wishlist = False
        message = f"'{book.title}' removed from your Wishlist."
        messages.success(request, message)
    else:
        Wishlist.objects.create(user=request.user, book=book)
        in_wishlist = True
        message = f"'{book.title}' added to your Wishlist ❤️"
        messages.success(request, message)

    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', ''):
        return JsonResponse({
            'status': 'ok',
            'in_wishlist': in_wishlist,
            'message': message,
            'wishlist_count': request.user.wishlist_items.count()
        })

    redirect_url = request.META.get('HTTP_REFERER') or reverse('book_detail', kwargs={'book_id': book.id})
    return redirect(redirect_url)


@login_required
def move_to_cart(request, book_id):
    """
    Moves an item from Wishlist to the user's Cart:
    1. Adds the book to session cart.
    2. Removes the book from user's wishlist.
    """
    book = get_object_or_404(Book, id=book_id)

    if not book.available:
        messages.error(request, f"Sorry, '{book.title}' is currently out of stock and cannot be moved to cart.")
        return redirect('wishlist')

    # Add to session cart
    cart_data = request.session.get('cart', {})
    b_id = str(book.id)
    if b_id in cart_data:
        cart_data[b_id] += 1
    else:
        cart_data[b_id] = 1

    request.session['cart'] = cart_data
    request.session.modified = True

    # Remove from wishlist
    Wishlist.objects.filter(user=request.user, book=book).delete()

    messages.success(request, f"'{book.title}' moved to your Cart! 🛒")
    return redirect('wishlist')


@login_required
def move_all_to_cart(request):
    """
    Moves all available items from the user's Wishlist into the Cart.
    """
    wishlist_items = Wishlist.objects.filter(user=request.user).select_related('book')

    if not wishlist_items.exists():
        messages.info(request, "Your wishlist is empty.")
        return redirect('wishlist')

    cart_data = request.session.get('cart', {})
    moved_count = 0

    for item in wishlist_items:
        if item.book.available:
            b_id = str(item.book.id)
            cart_data[b_id] = cart_data.get(b_id, 0) + 1
            moved_count += 1
            item.delete()

    request.session['cart'] = cart_data
    request.session.modified = True

    if moved_count > 0:
        messages.success(request, f"Successfully moved {moved_count} book(s) from your Wishlist to Cart! 🛒")
    else:
        messages.warning(request, "No available books in your wishlist could be moved to cart.")

    return redirect('cart')


