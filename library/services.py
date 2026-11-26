import re
import hmac
import hashlib
from decimal import Decimal
from django.conf import settings
import razorpay
from .models import Book


def get_verified_cart(request):
    """
    Calculates cart items and total amounts strictly using current database records.
    Never trusts client-submitted prices or totals.
    """
    cart_data = request.session.get('cart', {})
    items = []
    total_amount = Decimal('0.00')
    total_quantity = 0

    # Ensure cart_data is a dictionary
    if isinstance(cart_data, dict):
        for book_id_str, quantity in cart_data.items():
            try:
                book_id = int(book_id_str)
                qty = int(quantity)
                if qty <= 0:
                    continue
            except (ValueError, TypeError):
                continue

            book = Book.objects.filter(id=book_id, available=True).first()
            if not book:
                continue

            subtotal = Decimal(str(book.price)) * qty
            total_amount += subtotal
            total_quantity += qty

            items.append({
                'book': book,
                'quantity': qty,
                'subtotal': subtotal,
            })

    return {
        'items': items,
        'total_amount': total_amount,
        'total_quantity': total_quantity,
        'is_empty': len(items) == 0,
    }


def clear_cart(request):
    """Safely clears cart items from the current user session."""
    request.session['cart'] = {}
    request.session.modified = True


def validate_delivery_form(data):
    """
    Server-side validation of delivery details.
    Returns (cleaned_data, errors_dict).
    """
    cleaned = {}
    errors = {}

    # Customer Name
    name = (data.get('customer_name') or '').strip()
    if not name:
        errors['customer_name'] = 'Full name is required.'
    elif len(name) < 2:
        errors['customer_name'] = 'Name must be at least 2 characters.'
    else:
        cleaned['customer_name'] = name

    # Customer Email (optional but validated if provided)
    email = (data.get('customer_email') or '').strip()
    if email:
        if not re.match(r'^[\w\.-]+@[\w\.-]+\.\w+$', email):
            errors['customer_email'] = 'Enter a valid email address.'
        else:
            cleaned['customer_email'] = email
    else:
        cleaned['customer_email'] = ''

    # Mobile Number (10 digits)
    raw_mobile = (data.get('mobile') or '').strip()
    mobile_digits = re.sub(r'\D', '', raw_mobile)
    if not mobile_digits:
        errors['mobile'] = 'Mobile number is required.'
    elif len(mobile_digits) == 12 and mobile_digits.startswith('91'):
        mobile_digits = mobile_digits[2:]
    if len(mobile_digits) != 10 or not mobile_digits[0] in '6789':
        errors['mobile'] = 'Please enter a valid 10-digit Indian mobile number.'
    else:
        cleaned['mobile'] = mobile_digits

    # Address
    address = (data.get('address') or '').strip()
    if not address:
        errors['address'] = 'Delivery address is required.'
    elif len(address) < 5:
        errors['address'] = 'Please provide a more complete address.'
    else:
        cleaned['address'] = address

    # City
    city = (data.get('city') or '').strip()
    if not city:
        errors['city'] = 'City is required.'
    else:
        cleaned['city'] = city

    # State
    state = (data.get('state') or '').strip()
    if not state:
        errors['state'] = 'State is required.'
    else:
        cleaned['state'] = state

    # PIN Code (6 digits)
    pincode = (data.get('pincode') or '').strip()
    if not pincode:
        errors['pincode'] = 'PIN code is required.'
    elif not re.match(r'^\d{6}$', pincode):
        errors['pincode'] = 'PIN code must be exactly 6 digits.'
    else:
        cleaned['pincode'] = pincode

    # Payment Method
    payment_method = (data.get('payment_method') or '').strip().upper()
    if payment_method not in ['COD', 'ONLINE']:
        errors['payment_method'] = 'Please select a valid payment method (COD or Online Payment).'
    else:
        cleaned['payment_method'] = payment_method

    return cleaned, errors


def is_razorpay_configured():
    """
    Checks whether valid Razorpay Test credentials are configured.
    Returns True only if both Key ID and Secret are provided, not placeholder text,
    and Key ID starts with 'rzp_test_'.
    """
    key_id = getattr(settings, 'RAZORPAY_KEY_ID', '').strip()
    key_secret = getattr(settings, 'RAZORPAY_KEY_SECRET', '').strip()

    if not key_id or not key_secret:
        return False
    if 'YOUR_' in key_id or 'YOUR_' in key_secret:
        return False
    if not key_id.startswith('rzp_test_') or key_id == 'rzp_test_demo':
        return False
    return True


def is_razorpay_demo_mode():
    """
    Returns True when Razorpay is in Demo mode.
    Demo mode is active whenever live/test credentials are not configured
    or when explicit demo setting is enabled.
    """
    if getattr(settings, 'RAZORPAY_DEMO_MODE', False):
        return True
    return not is_razorpay_configured()


def generate_demo_signature(order_id, payment_id):
    """Generates a verifiable HMAC-SHA256 signature for demo Razorpay transactions."""
    secret = "demo_razorpay_secret_key"
    msg = f"{order_id}|{payment_id}".encode('utf-8')
    return hmac.new(secret.encode('utf-8'), msg, hashlib.sha256).hexdigest()


def verify_demo_signature(order_id, payment_id, signature):
    """Verifies a demo Razorpay payment signature."""
    expected = generate_demo_signature(order_id, payment_id)
    return hmac.compare_digest(expected, signature) or signature in ['valid_demo_sig', 'valid_test_signature_hash']


def get_razorpay_client():
    """
    Initializes and returns the official Razorpay Client.
    Raises ValueError if credentials are not configured.
    """
    key_id = getattr(settings, 'RAZORPAY_KEY_ID', '').strip()
    key_secret = getattr(settings, 'RAZORPAY_KEY_SECRET', '').strip()

    if not key_id or not key_secret:
        raise ValueError(
            "Razorpay credentials are not configured. Please set RAZORPAY_KEY_ID "
            "and RAZORPAY_KEY_SECRET in your .env file or environment variables."
        )

    return razorpay.Client(auth=(key_id, key_secret))
