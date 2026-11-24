
import razorpay
from django.conf import settings


def get_razorpay_client():
    key_id = settings.RAZORPAY_KEY_ID
    key_secret = settings.RAZORPAY_KEY_SECRET

    if not key_id or not key_secret:
        raise ValueError("Razorpay test credentials are not configured.")

    if not key_id.startswith("rzp_test_"):
        raise ValueError("Only Razorpay TEST MODE keys are allowed.")

    return razorpay.Client(auth=(key_id, key_secret))


def create_razorpay_order(amount_paise, receipt):
    client = get_razorpay_client()

    return client.order.create({
        "amount": int(amount_paise),
        "currency": "INR",
        "receipt": str(receipt),
    })


def verify_razorpay_signature(order_id, payment_id, signature):
    client = get_razorpay_client()

    client.utility.verify_payment_signature({
        "razorpay_order_id": order_id,
        "razorpay_payment_id": payment_id,
        "razorpay_signature": signature,
    })

    payment = client.payment.fetch(payment_id)

    if payment.get("order_id") != order_id:
        raise ValueError("Payment order mismatch.")

    if payment.get("status") != "captured":
        raise ValueError("Payment has not been captured.")

    return payment
