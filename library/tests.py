import hmac
import hashlib
from decimal import Decimal
from unittest.mock import patch, MagicMock
from django.test import TestCase, Client
from django.urls import reverse
from django.conf import settings
from django.utils import timezone
from django.contrib.admin.sites import site
from django.contrib.auth.models import User
from .models import Author, Book, Order, OrderItem, Review, Wishlist
from .services import (
    get_verified_cart,
    clear_cart,
    validate_delivery_form,
    generate_demo_signature,
    verify_demo_signature,
)
from .admin import OrderAdmin, ReviewAdmin, WishlistAdmin


class CheckoutAndPaymentTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Create test author and books
        self.author = Author.objects.create(
            name="J.K. Rowling",
            email="jk@example.com",
            biography="Author of Harry Potter"
        )
        self.book1 = Book.objects.create(
            title="Harry Potter and the Sorcerer's Stone",
            isbn_number="9780439708180",
            price=Decimal("499.00"),
            author=self.author,
            available=True
        )
        self.book2 = Book.objects.create(
            title="The Hobbit",
            isbn_number="9780547928227",
            price=Decimal("299.00"),
            author=self.author,
            available=True
        )

        self.valid_delivery_data = {
            'customer_name': 'Aarav Patel',
            'customer_email': 'aarav@example.com',
            'mobile': '9876543210',
            'address': '402 Sunrise Heights, MG Road',
            'city': 'Bengaluru',
            'state': 'Karnataka',
            'pincode': '560001',
            'payment_method': 'COD',
        }

    # 1. Cart Verification & DB Price Protection Tests
    def test_cart_prices_calculated_strictly_from_database(self):
        session = self.client.session
        session['cart'] = {
            str(self.book1.id): 2,
            str(self.book2.id): 1,
        }
        session.save()

        request = MagicMock()
        request.session = session
        verified = get_verified_cart(request)

        # 499 * 2 + 299 * 1 = 998 + 299 = 1297.00
        self.assertEqual(verified['total_amount'], Decimal('1297.00'))
        self.assertEqual(verified['total_quantity'], 3)
        self.assertEqual(len(verified['items']), 2)

    def test_empty_cart_redirects_from_checkout(self):
        response = self.client.get(reverse('checkout'))
        self.assertRedirects(response, reverse('cart'))

    # 2. Form Validation Tests
    def test_delivery_form_validation_rejects_invalid_inputs(self):
        invalid_data = {
            'customer_name': '',  # missing
            'mobile': '12345',    # invalid length
            'address': 'Hi',      # too short
            'city': '',
            'state': '',
            'pincode': '123',     # invalid pincode
            'payment_method': 'INVALID',
        }
        cleaned, errors = validate_delivery_form(invalid_data)
        self.assertIn('customer_name', errors)
        self.assertIn('mobile', errors)
        self.assertIn('address', errors)
        self.assertIn('city', errors)
        self.assertIn('state', errors)
        self.assertIn('pincode', errors)
        self.assertIn('payment_method', errors)

    def test_delivery_form_validation_accepts_valid_inputs(self):
        cleaned, errors = validate_delivery_form(self.valid_delivery_data)
        self.assertEqual(len(errors), 0)
        self.assertEqual(cleaned['customer_name'], 'Aarav Patel')
        self.assertEqual(cleaned['mobile'], '9876543210')
        self.assertEqual(cleaned['pincode'], '560001')
        self.assertEqual(cleaned['payment_method'], 'COD')

    # 3. Cash on Delivery (COD) Order Flow
    def test_cash_on_delivery_creates_order_and_clears_cart(self):
        session = self.client.session
        session['cart'] = {str(self.book1.id): 2}
        session.save()

        response = self.client.post(reverse('checkout'), self.valid_delivery_data)

        # Should create 1 order
        self.assertEqual(Order.objects.count(), 1)
        order = Order.objects.first()

        self.assertEqual(order.customer_name, 'Aarav Patel')
        self.assertEqual(order.payment_method, 'COD')
        self.assertEqual(order.payment_status, 'PENDING')
        self.assertEqual(order.order_status, 'PLACED')
        self.assertEqual(order.cancellation_status, 'NOT_CANCELLED')
        self.assertEqual(order.refund_status, 'NOT_APPLICABLE')
        self.assertEqual(order.total_amount, Decimal('998.00'))

        # Should create 1 order item
        self.assertEqual(order.items.count(), 1)
        item = order.items.first()
        self.assertEqual(item.book, self.book1)
        self.assertEqual(item.quantity, 2)
        self.assertEqual(item.price, Decimal('499.00'))
        self.assertEqual(item.subtotal, Decimal('998.00'))

        # Session cart should be empty
        self.assertEqual(self.client.session.get('cart'), {})

        # Should redirect to order_success
        self.assertRedirects(response, reverse('order_success', kwargs={'order_id': order.order_id}))

        # Verify confirmation page renders correctly
        success_response = self.client.get(reverse('order_success', kwargs={'order_id': order.order_id}))
        self.assertEqual(success_response.status_code, 200)
        self.assertContains(success_response, "Order Confirmed!")
        self.assertContains(success_response, "998.00")

    # 4. Razorpay Online Payment Flow (Demo Mode & Live Mode)
    @patch('library.views.is_razorpay_configured', return_value=False)
    def test_razorpay_demo_checkout_initiation(self, mock_is_configured):
        session = self.client.session
        session['cart'] = {str(self.book1.id): 2}
        session.save()

        online_data = self.valid_delivery_data.copy()
        online_data['payment_method'] = 'ONLINE'

        response = self.client.post(reverse('checkout'), online_data)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'library/razorpay_checkout.html')
        self.assertContains(response, 'order_demo_')
        self.assertContains(response, 'Razorpay Demo Gateway')

    def test_razorpay_demo_payment_verification_success(self):
        # Setup cart and pending session data
        session = self.client.session
        session['cart'] = {str(self.book1.id): 1}
        order_demo_id = 'order_demo_1234567890'
        session['pending_order_data'] = self.valid_delivery_data
        session['pending_razorpay_order_id'] = order_demo_id
        session.save()

        payment_demo_id = 'pay_demo_9876543210'
        demo_sig = generate_demo_signature(order_demo_id, payment_demo_id)

        verify_payload = {
            'razorpay_payment_id': payment_demo_id,
            'razorpay_order_id': order_demo_id,
            'razorpay_signature': demo_sig,
        }

        response = self.client.post(reverse('payment_verify'), verify_payload)

        # Order created as PAID
        self.assertEqual(Order.objects.count(), 1)
        order = Order.objects.first()
        self.assertEqual(order.payment_method, 'ONLINE')
        self.assertEqual(order.payment_status, 'PAID')
        self.assertEqual(order.order_status, 'PLACED')
        self.assertEqual(order.razorpay_order_id, order_demo_id)
        self.assertEqual(order.razorpay_payment_id, payment_demo_id)
        self.assertEqual(order.total_amount, Decimal('499.00'))

        # Cart cleared
        self.assertEqual(self.client.session.get('cart'), {})
        self.assertRedirects(response, reverse('order_success', kwargs={'order_id': order.order_id}))

    @patch('library.views.get_razorpay_client')
    @patch('library.views.is_razorpay_configured', return_value=True)
    def test_razorpay_live_sdk_initiation(self, mock_is_configured, mock_get_client):
        mock_client = MagicMock()
        mock_client.order.create.return_value = {
            'id': 'order_test_rzp_12345',
            'amount': 99800,
            'currency': 'INR',
            'status': 'created',
        }
        mock_get_client.return_value = mock_client

        session = self.client.session
        session['cart'] = {str(self.book1.id): 2}
        session.save()

        online_data = self.valid_delivery_data.copy()
        online_data['payment_method'] = 'ONLINE'

        response = self.client.post(reverse('checkout'), online_data)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'library/razorpay_checkout.html')
        self.assertContains(response, 'order_test_rzp_12345')

    @patch('library.views.get_razorpay_client')
    def test_razorpay_idempotency_prevents_duplicate_orders(self, mock_get_client):
        existing_order = Order.objects.create(
            customer_name='Aarav Patel',
            mobile='9876543210',
            address='MG Road',
            city='Bengaluru',
            state='Karnataka',
            pincode='560001',
            total_amount=Decimal('499.00'),
            payment_method='ONLINE',
            payment_status='PAID',
            razorpay_order_id='order_test_rzp_12345',
            razorpay_payment_id='pay_test_already_processed',
        )

        verify_payload = {
            'razorpay_payment_id': 'pay_test_already_processed',
            'razorpay_order_id': 'order_test_rzp_12345',
            'razorpay_signature': 'any_sig',
        }

        response = self.client.post(reverse('payment_verify'), verify_payload)
        self.assertEqual(Order.objects.count(), 1)
        self.assertRedirects(response, reverse('order_success', kwargs={'order_id': existing_order.order_id}))

    def test_razorpay_invalid_signature_rejects_order_and_preserves_cart(self):
        session = self.client.session
        session['cart'] = {str(self.book1.id): 1}
        session.save()

        verify_payload = {
            'razorpay_payment_id': 'pay_demo_tampered',
            'razorpay_order_id': 'order_demo_12345',
            'razorpay_signature': 'invalid_bad_sig',
        }

        response = self.client.post(reverse('payment_verify'), verify_payload)
        self.assertEqual(Order.objects.count(), 0)
        self.assertRedirects(response, f"{reverse('payment_failed')}?reason=signature_mismatch")
        self.assertEqual(self.client.session.get('cart'), {str(self.book1.id): 1})

    def test_payment_failed_view_renders_cart_and_retry_button(self):
        session = self.client.session
        session['cart'] = {str(self.book1.id): 1}
        session.save()

        response = self.client.get(f"{reverse('payment_failed')}?reason=cancelled")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'library/payment_failed.html')
        self.assertContains(response, "Payment Incomplete or Cancelled")
        self.assertContains(response, "Your Cart is Intact!")


class OrderCancellationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.author = Author.objects.create(name="George Orwell", email="george@example.com")
        self.book = Book.objects.create(
            title="1984",
            isbn_number="9780451524935",
            price=Decimal("350.00"),
            author=self.author,
            available=True
        )

    # Subtask 1: Cancellation Eligibility
    def test_cancellation_eligibility_for_different_statuses(self):
        # 1. Placed order with Pending (COD) -> Cancellable
        order_placed_cod = Order.objects.create(
            customer_name="Test User",
            mobile="9876543210",
            address="Test St",
            city="City",
            state="State",
            pincode="123456",
            total_amount=Decimal("350.00"),
            order_status="PLACED",
            payment_method="COD",
            payment_status="PENDING",
            cancellation_status="NOT_CANCELLED",
        )
        self.assertTrue(order_placed_cod.is_cancellable())

        # 2. Processing order with Paid (Online) -> Cancellable
        order_proc_online = Order.objects.create(
            customer_name="Test User",
            mobile="9876543210",
            address="Test St",
            city="City",
            state="State",
            pincode="123456",
            total_amount=Decimal("350.00"),
            order_status="PROCESSING",
            payment_method="ONLINE",
            payment_status="PAID",
            cancellation_status="NOT_CANCELLED",
        )
        self.assertTrue(order_proc_online.is_cancellable())

        # 3. Shipped order -> NOT cancellable
        order_shipped = Order.objects.create(
            customer_name="Test User",
            mobile="9876543210",
            address="Test St",
            city="City",
            state="State",
            pincode="123456",
            total_amount=Decimal("350.00"),
            order_status="SHIPPED",
            payment_method="COD",
            payment_status="PENDING",
            cancellation_status="NOT_CANCELLED",
        )
        self.assertFalse(order_shipped.is_cancellable())

        # 4. Delivered order -> NOT cancellable
        order_delivered = Order.objects.create(
            customer_name="Test User",
            mobile="9876543210",
            address="Test St",
            city="City",
            state="State",
            pincode="123456",
            total_amount=Decimal("350.00"),
            order_status="DELIVERED",
            payment_method="ONLINE",
            payment_status="PAID",
            cancellation_status="NOT_CANCELLED",
        )
        self.assertFalse(order_delivered.is_cancellable())

        # 5. Already cancelled order -> NOT cancellable
        order_cancelled = Order.objects.create(
            customer_name="Test User",
            mobile="9876543210",
            address="Test St",
            city="City",
            state="State",
            pincode="123456",
            total_amount=Decimal("350.00"),
            order_status="CANCELLED",
            payment_method="COD",
            payment_status="CANCELLED",
            cancellation_status="CANCELLED",
        )
        self.assertFalse(order_cancelled.is_cancellable())

    # Subtask 2: COD Cancellation
    def test_cod_order_cancellation(self):
        order = Order.objects.create(
            customer_name="Vikram Singh",
            mobile="9876543210",
            address="Station Road",
            city="Jaipur",
            state="Rajasthan",
            pincode="302001",
            total_amount=Decimal("350.00"),
            order_status="PLACED",
            payment_method="COD",
            payment_status="PENDING",
            cancellation_status="NOT_CANCELLED",
            refund_status="NOT_APPLICABLE",
        )

        response = self.client.post(
            reverse('cancel_order', kwargs={'order_id': order.order_id}),
            {'cancellation_reason': 'Changed mind'}
        )

        order.refresh_from_db()
        self.assertEqual(order.order_status, 'CANCELLED')
        self.assertEqual(order.cancellation_status, 'CANCELLED')
        self.assertEqual(order.payment_status, 'CANCELLED')
        self.assertEqual(order.refund_status, 'NOT_APPLICABLE')
        self.assertEqual(order.cancellation_reason, 'Changed mind')
        self.assertIsNotNone(order.cancelled_at)
        self.assertRedirects(response, reverse('cancellation_success', kwargs={'order_id': order.order_id}))

    # Subtask 3: Online Payment Cancellation & Refund Status
    def test_online_payment_order_cancellation_records_refund_pending(self):
        order = Order.objects.create(
            customer_name="Pooja Sharma",
            mobile="9876543210",
            address="Koramangala",
            city="Bengaluru",
            state="Karnataka",
            pincode="560034",
            total_amount=Decimal("350.00"),
            order_status="PLACED",
            payment_method="ONLINE",
            payment_status="PAID",
            cancellation_status="NOT_CANCELLED",
            refund_status="NOT_APPLICABLE",
            razorpay_order_id="order_demo_111",
            razorpay_payment_id="pay_demo_222",
        )

        response = self.client.post(
            reverse('cancel_order', kwargs={'order_id': order.order_id}),
            {'cancellation_reason': 'Book ordered accidentally'}
        )

        order.refresh_from_db()
        self.assertEqual(order.order_status, 'CANCELLED')
        self.assertEqual(order.cancellation_status, 'CANCELLED')
        self.assertEqual(order.payment_status, 'CANCELLED')
        self.assertEqual(order.refund_status, 'REFUND_PENDING')
        self.assertEqual(order.cancellation_reason, 'Book ordered accidentally')
        self.assertIsNotNone(order.cancelled_at)
        self.assertRedirects(response, reverse('cancellation_success', kwargs={'order_id': order.order_id}))

    # Subtask 4: Order History View with Cancel Button and Statuses
    def test_order_history_displays_cancel_button_for_eligible_orders(self):
        order = Order.objects.create(
            customer_name="Pooja Sharma",
            mobile="9876543210",
            address="Koramangala",
            city="Bengaluru",
            state="Karnataka",
            pincode="560034",
            total_amount=Decimal("350.00"),
            order_status="PLACED",
            payment_method="COD",
            payment_status="PENDING",
            cancellation_status="NOT_CANCELLED",
        )

        response = self.client.get(reverse('order_history'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cancel Order")
        self.assertContains(response, reverse('cancel_confirm', kwargs={'order_id': order.order_id}))

    def test_order_history_does_not_display_cancel_button_for_shipped_orders(self):
        order = Order.objects.create(
            customer_name="Pooja Sharma",
            mobile="9876543210",
            address="Koramangala",
            city="Bengaluru",
            state="Karnataka",
            pincode="560034",
            total_amount=Decimal("350.00"),
            order_status="SHIPPED",
            payment_method="COD",
            payment_status="PENDING",
            cancellation_status="NOT_CANCELLED",
        )

        response = self.client.get(reverse('order_history'))
        self.assertEqual(response.status_code, 200)
        # Cancel order link for this specific order shouldn't be present
        self.assertNotContains(response, reverse('cancel_confirm', kwargs={'order_id': order.order_id}))

    # Subtask 5: Admin Management
    def test_admin_approve_cancellation_action(self):
        order = Order.objects.create(
            customer_name="Admin Test User",
            mobile="9876543210",
            address="Admin Ave",
            city="Admin City",
            state="Admin State",
            pincode="123456",
            total_amount=Decimal("500.00"),
            order_status="PLACED",
            payment_method="ONLINE",
            payment_status="PAID",
            cancellation_status="NOT_CANCELLED",
        )

        order_admin = OrderAdmin(Order, site)
        request = MagicMock()

        order_admin.approve_cancellation(request, Order.objects.filter(id=order.id))

        order.refresh_from_db()
        self.assertEqual(order.order_status, 'CANCELLED')
        self.assertEqual(order.cancellation_status, 'CANCELLED')
        self.assertEqual(order.payment_status, 'CANCELLED')
        self.assertEqual(order.refund_status, 'REFUND_PENDING')

    def test_admin_process_refund_action(self):
        order = Order.objects.create(
            customer_name="Refund Test User",
            mobile="9876543210",
            address="Refund Ave",
            city="City",
            state="State",
            pincode="123456",
            total_amount=Decimal("500.00"),
            order_status="CANCELLED",
            payment_method="ONLINE",
            payment_status="CANCELLED",
            cancellation_status="CANCELLED",
            refund_status="REFUND_PENDING",
        )

        order_admin = OrderAdmin(Order, site)
        request = MagicMock()

        order_admin.process_refund_completed(request, Order.objects.filter(id=order.id))

        order.refresh_from_db()
        self.assertEqual(order.refund_status, 'REFUNDED')
        self.assertEqual(order.payment_status, 'REFUNDED')


class ProductReviewTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Create author and book
        self.author = Author.objects.create(
            name="George Orwell",
            email="orwell@example.com",
            biography="English novelist"
        )
        self.book = Book.objects.create(
            title="1984",
            isbn_number="9780451524935",
            price=Decimal("350.00"),
            author=self.author,
            available=True
        )

        # Create users
        self.buyer_user = User.objects.create_user(
            username="buyer1",
            email="buyer1@example.com",
            password="password123"
        )
        self.non_buyer_user = User.objects.create_user(
            username="nonbuyer",
            email="nonbuyer@example.com",
            password="password123"
        )
        self.admin_user = User.objects.create_superuser(
            username="superadmin",
            email="admin@example.com",
            password="adminpassword123"
        )

        # Create a completed/placed order for buyer_user containing self.book
        self.order = Order.objects.create(
            user=self.buyer_user,
            customer_name="Buyer One",
            customer_email="buyer1@example.com",
            mobile="9876543210",
            address="123 Test Street",
            city="Tech City",
            state="Karnataka",
            pincode="560001",
            total_amount=Decimal("350.00"),
            order_status="DELIVERED",
            payment_method="COD",
            payment_status="PAID",
            cancellation_status="NOT_CANCELLED"
        )
        self.order_item = OrderItem.objects.create(
            order=self.order,
            book=self.book,
            book_title=self.book.title,
            price=self.book.price,
            quantity=1,
            subtotal=self.book.price
        )

    def test_book_average_rating_and_counts(self):
        self.assertEqual(self.book.average_rating(), 0.0)
        self.assertEqual(self.book.total_reviews(), 0)

        # Create review 1 (5 stars)
        Review.objects.create(
            book=self.book,
            user=self.buyer_user,
            rating=5,
            review="Phenomenal read! Highly recommended."
        )
        self.assertEqual(self.book.average_rating(), 5.0)
        self.assertEqual(self.book.total_reviews(), 1)

        # Create review 2 (4 stars)
        Review.objects.create(
            book=self.book,
            user=self.admin_user,
            rating=4,
            review="Classic dystopian novel."
        )
        self.assertEqual(self.book.average_rating(), 4.5)
        self.assertEqual(self.book.total_reviews(), 2)
        breakdown = self.book.star_breakdown()
        self.assertEqual(len(breakdown), 5)

    def test_non_purchased_user_cannot_submit_review(self):
        self.client.login(username="nonbuyer", password="password123")
        response = self.client.post(
            reverse('add_review', kwargs={'book_id': self.book.id}),
            {'rating': 5, 'review': 'I have not bought this!'}
        )
        # Should redirect back to book detail
        self.assertRedirects(response, reverse('book_detail', kwargs={'book_id': self.book.id}))
        # Review should not have been created
        self.assertEqual(Review.objects.filter(book=self.book, user=self.non_buyer_user).count(), 0)

    def test_purchased_user_can_submit_review(self):
        self.client.login(username="buyer1", password="password123")
        response = self.client.post(
            reverse('add_review', kwargs={'book_id': self.book.id}),
            {'rating': 5, 'review': 'Excellent quality and gripping story!'}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Review.objects.filter(book=self.book, user=self.buyer_user).count(), 1)
        review = Review.objects.get(book=self.book, user=self.buyer_user)
        self.assertEqual(review.rating, 5)
        self.assertEqual(review.review, 'Excellent quality and gripping story!')

    def test_review_resubmission_updates_existing_review(self):
        self.client.login(username="buyer1", password="password123")
        # First submission
        self.client.post(
            reverse('add_review', kwargs={'book_id': self.book.id}),
            {'rating': 4, 'review': 'Good book.'}
        )
        self.assertEqual(Review.objects.filter(book=self.book, user=self.buyer_user).count(), 1)

        # Re-submit with update
        self.client.post(
            reverse('add_review', kwargs={'book_id': self.book.id}),
            {'rating': 5, 'review': 'Changed my mind, masterclass!'}
        )
        # Count remains 1
        self.assertEqual(Review.objects.filter(book=self.book, user=self.buyer_user).count(), 1)
        review = Review.objects.get(book=self.book, user=self.buyer_user)
        self.assertEqual(review.rating, 5)
        self.assertEqual(review.review, 'Changed my mind, masterclass!')

    def test_user_can_edit_own_review(self):
        review = Review.objects.create(
            book=self.book,
            user=self.buyer_user,
            rating=3,
            review="Average"
        )
        self.client.login(username="buyer1", password="password123")

        # GET edit page
        get_response = self.client.get(reverse('edit_review', kwargs={'review_id': review.id}))
        self.assertEqual(get_response.status_code, 200)
        self.assertTemplateUsed(get_response, 'library/edit_review.html')

        # POST edit
        post_response = self.client.post(
            reverse('edit_review', kwargs={'review_id': review.id}),
            {'rating': 5, 'review': 'Updated to 5 stars!'}
        )
        self.assertEqual(post_response.status_code, 302)
        review.refresh_from_db()
        self.assertEqual(review.rating, 5)
        self.assertEqual(review.review, 'Updated to 5 stars!')

    def test_user_cannot_edit_another_users_review(self):
        review = Review.objects.create(
            book=self.book,
            user=self.buyer_user,
            rating=5,
            review="Original review"
        )
        self.client.login(username="nonbuyer", password="password123")

        post_response = self.client.post(
            reverse('edit_review', kwargs={'review_id': review.id}),
            {'rating': 1, 'review': 'Malicious edit'}
        )
        # Should redirect without modifying
        self.assertRedirects(post_response, reverse('book_detail', kwargs={'book_id': self.book.id}))
        review.refresh_from_db()
        self.assertEqual(review.rating, 5)
        self.assertEqual(review.review, 'Original review')

    def test_user_can_delete_own_review(self):
        review = Review.objects.create(
            book=self.book,
            user=self.buyer_user,
            rating=4,
            review="Will delete this"
        )
        self.client.login(username="buyer1", password="password123")

        response = self.client.post(reverse('delete_review', kwargs={'review_id': review.id}))
        self.assertRedirects(response, f"{reverse('book_detail', kwargs={'book_id': self.book.id})}#reviews")
        self.assertFalse(Review.objects.filter(id=review.id).exists())

    def test_user_cannot_delete_another_users_review(self):
        review = Review.objects.create(
            book=self.book,
            user=self.buyer_user,
            rating=4,
            review="Buyer review"
        )
        self.client.login(username="nonbuyer", password="password123")

        response = self.client.post(reverse('delete_review', kwargs={'review_id': review.id}))
        self.assertRedirects(response, reverse('book_detail', kwargs={'book_id': self.book.id}))
        self.assertTrue(Review.objects.filter(id=review.id).exists())

    def test_admin_can_delete_any_review(self):
        review = Review.objects.create(
            book=self.book,
            user=self.buyer_user,
            rating=1,
            review="Spam review"
        )
        self.client.login(username="superadmin", password="adminpassword123")

        response = self.client.post(reverse('delete_review', kwargs={'review_id': review.id}))
        self.assertRedirects(response, f"{reverse('book_detail', kwargs={'book_id': self.book.id})}#reviews")
        self.assertFalse(Review.objects.filter(id=review.id).exists())

    def test_admin_panel_review_management(self):
        review = Review.objects.create(
            book=self.book,
            user=self.buyer_user,
            rating=5,
            review="Great book with durable binding."
        )
        review_admin = ReviewAdmin(Review, site)
        self.assertEqual(review_admin.star_display_badge(review), '★★★★★')
        self.assertIn("Great book", review_admin.short_review(review))

    def test_cancelled_order_cannot_review(self):
        # Cancel order
        self.order.cancellation_status = 'CANCELLED'
        self.order.order_status = 'CANCELLED'
        self.order.save()

        self.assertFalse(self.book.is_purchased_by(self.buyer_user))

        self.client.login(username="buyer1", password="password123")
        response = self.client.post(
            reverse('add_review', kwargs={'book_id': self.book.id}),
            {'rating': 5, 'review': 'Order was cancelled'}
        )
        self.assertRedirects(response, reverse('book_detail', kwargs={'book_id': self.book.id}))
        self.assertEqual(Review.objects.filter(book=self.book, user=self.buyer_user).count(), 0)

    def test_product_detail_page_renders_reviews_and_form(self):
        Review.objects.create(
            book=self.book,
            user=self.buyer_user,
            rating=5,
            review="Best dystopian book ever written!"
        )

        response = self.client.get(reverse('book_detail', kwargs={'book_id': self.book.id}))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'library/book_detail.html')
        self.assertContains(response, "1984")
        self.assertContains(response, "George Orwell")
        self.assertContains(response, "Best dystopian book ever written!")
        self.assertContains(response, "5.0 / 5")
        self.assertContains(response, "1 review")


class WishlistManagementTests(TestCase):
    def setUp(self):
        self.client = Client()

        self.author = Author.objects.create(
            name="Jane Austen",
            email="austen@example.com",
            biography="English novelist"
        )
        self.book1 = Book.objects.create(
            title="Pride and Prejudice",
            isbn_number="9780141439518",
            price=Decimal("250.00"),
            author=self.author,
            available=True
        )
        self.book2 = Book.objects.create(
            title="Sense and Sensibility",
            isbn_number="9780141439662",
            price=Decimal("280.00"),
            author=self.author,
            available=True
        )
        self.out_of_stock_book = Book.objects.create(
            title="Emma",
            isbn_number="9780141439587",
            price=Decimal("300.00"),
            author=self.author,
            available=False
        )

        self.user = User.objects.create_user(
            username="booklover",
            email="lover@example.com",
            password="password123"
        )
        self.admin_user = User.objects.create_superuser(
            username="adminuser",
            email="adminuser@example.com",
            password="adminpassword123"
        )

    def test_anonymous_user_redirected_to_login(self):
        # Accessing wishlist page anonymously
        response = self.client.get(reverse('wishlist'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('login'), response.url)

        # Trying to add to wishlist anonymously
        add_response = self.client.get(reverse('add_to_wishlist', kwargs={'book_id': self.book1.id}))
        self.assertEqual(add_response.status_code, 302)
        self.assertIn(reverse('login'), add_response.url)

    def test_add_to_wishlist(self):
        self.client.login(username="booklover", password="password123")
        response = self.client.get(reverse('add_to_wishlist', kwargs={'book_id': self.book1.id}))
        self.assertEqual(response.status_code, 302)

        self.assertTrue(Wishlist.objects.filter(user=self.user, book=self.book1).exists())
        self.assertTrue(self.book1.is_in_wishlist(self.user))
        self.assertEqual(self.user.wishlist_items.count(), 1)

    def test_duplicate_add_to_wishlist_handled(self):
        self.client.login(username="booklover", password="password123")
        # Add first time
        self.client.get(reverse('add_to_wishlist', kwargs={'book_id': self.book1.id}))
        # Add second time
        self.client.get(reverse('add_to_wishlist', kwargs={'book_id': self.book1.id}))

        # Count remains 1
        self.assertEqual(Wishlist.objects.filter(user=self.user, book=self.book1).count(), 1)

    def test_remove_from_wishlist(self):
        Wishlist.objects.create(user=self.user, book=self.book1)
        self.assertEqual(self.user.wishlist_items.count(), 1)

        self.client.login(username="booklover", password="password123")
        response = self.client.get(reverse('remove_from_wishlist', kwargs={'book_id': self.book1.id}))
        self.assertEqual(response.status_code, 302)

        self.assertFalse(Wishlist.objects.filter(user=self.user, book=self.book1).exists())
        self.assertFalse(self.book1.is_in_wishlist(self.user))
        self.assertEqual(self.user.wishlist_items.count(), 0)

    def test_toggle_wishlist_standard_and_ajax(self):
        self.client.login(username="booklover", password="password123")

        # Toggle ON
        self.client.get(reverse('toggle_wishlist', kwargs={'book_id': self.book1.id}))
        self.assertTrue(self.book1.is_in_wishlist(self.user))

        # Toggle OFF
        self.client.get(reverse('toggle_wishlist', kwargs={'book_id': self.book1.id}))
        self.assertFalse(self.book1.is_in_wishlist(self.user))

        # Toggle ON via AJAX
        ajax_resp = self.client.get(
            reverse('toggle_wishlist', kwargs={'book_id': self.book1.id}),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(ajax_resp.status_code, 200)
        data = ajax_resp.json()
        self.assertEqual(data['status'], 'ok')
        self.assertTrue(data['in_wishlist'])
        self.assertEqual(data['wishlist_count'], 1)

    def test_wishlist_page_renders_saved_products(self):
        Wishlist.objects.create(user=self.user, book=self.book1)
        Wishlist.objects.create(user=self.user, book=self.book2)

        self.client.login(username="booklover", password="password123")
        response = self.client.get(reverse('wishlist'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'library/wishlist.html')
        self.assertContains(response, "Pride and Prejudice")
        self.assertContains(response, "Sense and Sensibility")
        self.assertContains(response, "Move to Cart")
        self.assertContains(response, "Move All to Cart")

    def test_move_wishlist_item_to_cart(self):
        # Setup book in wishlist
        Wishlist.objects.create(user=self.user, book=self.book1)
        self.assertTrue(self.book1.is_in_wishlist(self.user))

        self.client.login(username="booklover", password="password123")
        response = self.client.get(reverse('move_to_cart', kwargs={'book_id': self.book1.id}))
        self.assertRedirects(response, reverse('wishlist'))

        # Check wishlist: item must be removed
        self.assertFalse(Wishlist.objects.filter(user=self.user, book=self.book1).exists())
        self.assertEqual(self.user.wishlist_items.count(), 0)

        # Check session cart: item must be added
        session = self.client.session
        self.assertIn(str(self.book1.id), session.get('cart', {}))
        self.assertEqual(session['cart'][str(self.book1.id)], 1)

    def test_move_out_of_stock_item_to_cart_fails_gracefully(self):
        Wishlist.objects.create(user=self.user, book=self.out_of_stock_book)
        self.client.login(username="booklover", password="password123")

        response = self.client.get(reverse('move_to_cart', kwargs={'book_id': self.out_of_stock_book.id}))
        self.assertRedirects(response, reverse('wishlist'))

        # Item should remain in wishlist because it's out of stock
        self.assertTrue(Wishlist.objects.filter(user=self.user, book=self.out_of_stock_book).exists())
        # Cart should not contain it
        self.assertNotIn(str(self.out_of_stock_book.id), self.client.session.get('cart', {}))

    def test_move_all_to_cart(self):
        Wishlist.objects.create(user=self.user, book=self.book1)
        Wishlist.objects.create(user=self.user, book=self.book2)

        self.client.login(username="booklover", password="password123")
        response = self.client.get(reverse('move_all_to_cart'))
        self.assertRedirects(response, reverse('cart'))

        # Wishlist should be cleared
        self.assertEqual(self.user.wishlist_items.count(), 0)

        # Cart should have both books
        session = self.client.session
        cart = session.get('cart', {})
        self.assertEqual(cart.get(str(self.book1.id)), 1)
        self.assertEqual(cart.get(str(self.book2.id)), 1)

    def test_admin_wishlist_management(self):
        item = Wishlist.objects.create(user=self.user, book=self.book1)
        wishlist_admin = WishlistAdmin(Wishlist, site)
        self.assertEqual(str(item), f"booklover - {self.book1.title}")
        self.assertEqual(wishlist_admin.list_display, ('user', 'book', 'added_at'))


