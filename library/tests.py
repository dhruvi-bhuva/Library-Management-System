import hmac
import hashlib
from decimal import Decimal
from unittest.mock import patch, MagicMock
from django.test import TestCase, Client
from django.urls import reverse
from django.conf import settings
from django.contrib.auth.models import User
from .models import Author, Book, Order, OrderItem
from .services import get_verified_cart, clear_cart, validate_delivery_form


class CheckoutAndPaymentTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Create test user
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            first_name='Aarav',
            last_name='Patel',
            email='aarav@example.com',
        )
        self.client.login(username='testuser', password='testpass123')

        # Create a second user for ownership tests
        self.other_user = User.objects.create_user(
            username='otheruser',
            password='otherpass123',
            first_name='Priya',
            last_name='Singh',
        )

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

    def _add_to_cart(self, book_id, qty=1):
        session = self.client.session
        cart = session.get('cart', {})
        cart[str(book_id)] = qty
        session['cart'] = cart
        session.save()

    # =========================================================================
    # 1. Cart Verification & DB Price Protection
    # =========================================================================
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

    # =========================================================================
    # 2. Empty cart cannot be checked out
    # =========================================================================
    def test_empty_cart_redirects_from_checkout(self):
        response = self.client.get(reverse('checkout'))
        self.assertRedirects(response, reverse('cart'))

    # =========================================================================
    # 3. Invalid delivery details are rejected
    # =========================================================================
    def test_delivery_form_validation_rejects_invalid_inputs(self):
        invalid_data = {
            'customer_name': '',
            'mobile': '12345',
            'address': 'Hi',
            'city': '',
            'state': '',
            'pincode': '123',
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

    # =========================================================================
    # 4. COD creates order with payment_status Pending and order_status Placed
    # =========================================================================
    def test_cash_on_delivery_creates_order_and_clears_cart(self):
        self._add_to_cart(self.book1.id, 2)

        response = self.client.post(reverse('checkout'), self.valid_delivery_data)

        self.assertEqual(Order.objects.count(), 1)
        order = Order.objects.first()

        self.assertEqual(order.customer_name, 'Aarav Patel')
        self.assertEqual(order.payment_method, 'COD')
        self.assertEqual(order.payment_status, 'PENDING')
        self.assertEqual(order.order_status, 'PLACED')
        self.assertEqual(order.total_amount, Decimal('998.00'))
        self.assertEqual(order.user, self.user)

        # 5. Order items and totals saved correctly
        self.assertEqual(order.items.count(), 1)
        item = order.items.first()
        self.assertEqual(item.book, self.book1)
        self.assertEqual(item.quantity, 2)
        self.assertEqual(item.price, Decimal('499.00'))
        self.assertEqual(item.subtotal, Decimal('998.00'))
        self.assertTrue(len(item.book_title) > 0)

        # Session cart should be empty
        self.assertEqual(self.client.session.get('cart'), {})

        # Should redirect to order_success
        self.assertRedirects(response, reverse('order_success', kwargs={'order_id': order.order_id}))

    def test_cod_order_success_page_renders(self):
        self._add_to_cart(self.book1.id, 2)
        self.client.post(reverse('checkout'), self.valid_delivery_data)
        order = Order.objects.first()

        success_response = self.client.get(reverse('order_success', kwargs={'order_id': order.order_id}))
        self.assertEqual(success_response.status_code, 200)
        self.assertContains(success_response, "Order Confirmed!")
        self.assertContains(success_response, "PENDING")
        self.assertContains(success_response, "998.00")

    # =========================================================================
    # 6. Razorpay order creation uses correct server-calculated amount
    # =========================================================================
    @patch('library.views.get_razorpay_client')
    @patch('library.views.is_razorpay_configured', return_value=True)
    def test_razorpay_checkout_initiation(self, mock_is_configured, mock_get_client):
        mock_client = MagicMock()
        mock_client.order.create.return_value = {
            'id': 'order_test_rzp_12345',
            'amount': 99800,
            'currency': 'INR',
            'status': 'created',
        }
        mock_get_client.return_value = mock_client

        self._add_to_cart(self.book1.id, 2)

        online_data = self.valid_delivery_data.copy()
        online_data['payment_method'] = 'ONLINE'

        response = self.client.post(reverse('checkout'), online_data)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'library/razorpay_checkout.html')
        self.assertContains(response, 'order_test_rzp_12345')

        mock_client.order.create.assert_called_once()
        args = mock_client.order.create.call_args[0][0]
        self.assertEqual(args['amount'], 99800)  # 499 * 2 * 100
        self.assertEqual(args['currency'], 'INR')

    # =========================================================================
    # 7. Valid payment signatures are accepted
    # =========================================================================
    @patch('library.views.get_razorpay_client')
    def test_razorpay_payment_verification_success(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.utility.verify_payment_signature.return_value = True
        mock_client.payment.fetch.return_value = {
            'id': 'pay_test_98765',
            'order_id': 'order_test_rzp_12345',
            'amount': 49900,
            'status': 'captured',
        }
        mock_get_client.return_value = mock_client

        self._add_to_cart(self.book1.id, 1)
        session = self.client.session
        session['pending_order_data'] = self.valid_delivery_data
        session['pending_razorpay_order_id'] = 'order_test_rzp_12345'
        session.save()

        verify_payload = {
            'razorpay_payment_id': 'pay_test_98765',
            'razorpay_order_id': 'order_test_rzp_12345',
            'razorpay_signature': 'valid_test_signature_hash',
        }

        response = self.client.post(reverse('payment_verify'), verify_payload)
        mock_client.utility.verify_payment_signature.assert_called_once_with(verify_payload)

        self.assertEqual(Order.objects.count(), 1)
        order = Order.objects.first()
        self.assertEqual(order.payment_method, 'ONLINE')
        self.assertEqual(order.payment_status, 'PAID')
        self.assertEqual(order.order_status, 'PLACED')
        self.assertEqual(order.razorpay_order_id, 'order_test_rzp_12345')
        self.assertEqual(order.razorpay_payment_id, 'pay_test_98765')
        self.assertEqual(order.total_amount, Decimal('499.00'))
        self.assertEqual(order.user, self.user)

        self.assertEqual(self.client.session.get('cart'), {})
        self.assertRedirects(response, reverse('order_success', kwargs={'order_id': order.order_id}))

    # =========================================================================
    # 8. Invalid payment signatures are rejected
    # =========================================================================
    @patch('library.views.get_razorpay_client')
    def test_razorpay_invalid_signature_rejects_order_and_preserves_cart(self, mock_get_client):
        import razorpay.errors
        mock_client = MagicMock()
        mock_client.utility.verify_payment_signature.side_effect = razorpay.errors.SignatureVerificationError("Invalid Signature")
        mock_get_client.return_value = mock_client

        self._add_to_cart(self.book1.id, 1)

        verify_payload = {
            'razorpay_payment_id': 'pay_fake_tampered',
            'razorpay_order_id': 'order_test_rzp_12345',
            'razorpay_signature': 'bad_tampered_signature',
        }

        response = self.client.post(reverse('payment_verify'), verify_payload)
        self.assertEqual(Order.objects.count(), 0)
        self.assertRedirects(response, f"{reverse('payment_failed')}?reason=signature_mismatch")
        self.assertEqual(self.client.session.get('cart'), {str(self.book1.id): 1})

    # =========================================================================
    # 9. Failed/cancelled payments do not create falsely paid orders
    # =========================================================================
    @patch('library.views.get_razorpay_client')
    def test_razorpay_mismatched_amount_rejects_order(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.utility.verify_payment_signature.return_value = True
        mock_client.payment.fetch.return_value = {
            'id': 'pay_test_tampered_amt',
            'order_id': 'order_test_rzp_12345',
            'amount': 10000,
            'status': 'captured',
        }
        mock_get_client.return_value = mock_client

        self._add_to_cart(self.book1.id, 1)

        verify_payload = {
            'razorpay_payment_id': 'pay_test_tampered_amt',
            'razorpay_order_id': 'order_test_rzp_12345',
            'razorpay_signature': 'valid_sig',
        }

        response = self.client.post(reverse('payment_verify'), verify_payload)
        self.assertEqual(Order.objects.count(), 0)
        self.assertRedirects(response, f"{reverse('payment_failed')}?reason=amount_mismatch")

    def test_missing_payment_parameters_rejected(self):
        response = self.client.post(reverse('payment_verify'), {
            'razorpay_payment_id': '',
            'razorpay_order_id': '',
            'razorpay_signature': '',
        })
        self.assertEqual(Order.objects.count(), 0)
        self.assertRedirects(response, f"{reverse('payment_failed')}?reason=missing_parameters")

    # =========================================================================
    # 10. Duplicate callbacks do not create duplicate orders
    # =========================================================================
    @patch('library.views.get_razorpay_client')
    def test_razorpay_idempotency_prevents_duplicate_orders(self, mock_get_client):
        existing_order = Order.objects.create(
            user=self.user,
            customer_name='Aarav Patel',
            mobile='9876543210',
            address='MG Road',
            city='Bengaluru',
            state='Karnataka',
            pincode='560001',
            total_amount=Decimal('499.00'),
            payment_method='ONLINE',
            payment_status='PAID',
            order_status='PLACED',
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

    # =========================================================================
    # 11. A customer cannot access another customer's order
    # =========================================================================
    def test_customer_cannot_view_another_customers_order(self):
        order = Order.objects.create(
            user=self.other_user,
            customer_name='Priya Singh',
            mobile='9123456789',
            address='MG Road',
            city='Mumbai',
            state='Maharashtra',
            pincode='400001',
            total_amount=Decimal('299.00'),
            payment_method='COD',
            payment_status='PENDING',
            order_status='PLACED',
        )
        # Try accessing other user's order detail
        response = self.client.get(reverse('order_detail', kwargs={'order_id': order.order_id}))
        self.assertRedirects(response, reverse('order_history'))

    def test_customer_cannot_cancel_another_customers_order(self):
        order = Order.objects.create(
            user=self.other_user,
            customer_name='Priya Singh',
            mobile='9123456789',
            address='MG Road',
            city='Mumbai',
            state='Maharashtra',
            pincode='400001',
            total_amount=Decimal('299.00'),
            payment_method='COD',
            payment_status='PENDING',
            order_status='PLACED',
        )
        response = self.client.post(
            reverse('cancel_order', kwargs={'order_id': order.order_id}),
            {'cancellation_reason': 'test'}
        )
        self.assertRedirects(response, reverse('order_history'))
        order.refresh_from_db()
        self.assertEqual(order.order_status, 'PLACED')  # Not cancelled

    # =========================================================================
    # 12. Eligible COD orders can be cancelled
    # =========================================================================
    def test_cod_order_cancellation(self):
        order = Order.objects.create(
            user=self.user,
            customer_name='Aarav Patel',
            mobile='9876543210',
            address='MG Road',
            city='Bengaluru',
            state='Karnataka',
            pincode='560001',
            total_amount=Decimal('499.00'),
            payment_method='COD',
            payment_status='PENDING',
            order_status='PLACED',
        )

        response = self.client.post(
            reverse('cancel_order', kwargs={'order_id': order.order_id}),
            {'cancellation_reason': 'Changed my mind'}
        )
        self.assertRedirects(response, reverse('cancellation_success', kwargs={'order_id': order.order_id}))

        order.refresh_from_db()
        self.assertEqual(order.order_status, 'CANCELLED')
        self.assertEqual(order.refund_status, 'NOT_APPLICABLE')
        self.assertEqual(order.cancellation_reason, 'Changed my mind')
        self.assertIsNotNone(order.cancelled_at)

    # =========================================================================
    # 13. Eligible paid Razorpay orders can be cancelled with refund_status Pending
    # =========================================================================
    @patch('library.views.is_razorpay_configured', return_value=False)
    def test_online_order_cancellation_sets_refund_pending(self, mock_config):
        order = Order.objects.create(
            user=self.user,
            customer_name='Aarav Patel',
            mobile='9876543210',
            address='MG Road',
            city='Bengaluru',
            state='Karnataka',
            pincode='560001',
            total_amount=Decimal('499.00'),
            payment_method='ONLINE',
            payment_status='PAID',
            order_status='PLACED',
            razorpay_order_id='order_rzp_test',
            razorpay_payment_id='pay_rzp_test',
        )

        response = self.client.post(
            reverse('cancel_order', kwargs={'order_id': order.order_id}),
            {'cancellation_reason': 'Found better price'}
        )
        self.assertRedirects(response, reverse('cancellation_success', kwargs={'order_id': order.order_id}))

        order.refresh_from_db()
        self.assertEqual(order.order_status, 'CANCELLED')
        self.assertEqual(order.payment_status, 'REFUND_PENDING')
        self.assertEqual(order.refund_status, 'PENDING')
        self.assertEqual(order.cancellation_reason, 'Found better price')
        self.assertIsNotNone(order.cancelled_at)

    @patch('library.views.get_razorpay_client')
    @patch('library.views.is_razorpay_configured', return_value=True)
    def test_online_order_cancellation_initiates_razorpay_refund(self, mock_config, mock_get_client):
        mock_client = MagicMock()
        mock_client.payment.refund.return_value = {
            'id': 'rfnd_test_12345',
            'payment_id': 'pay_rzp_refund_test',
            'amount': 49900,
            'status': 'processed',
        }
        mock_get_client.return_value = mock_client

        order = Order.objects.create(
            user=self.user,
            customer_name='Aarav Patel',
            mobile='9876543210',
            address='MG Road',
            city='Bengaluru',
            state='Karnataka',
            pincode='560001',
            total_amount=Decimal('499.00'),
            payment_method='ONLINE',
            payment_status='PAID',
            order_status='PLACED',
            razorpay_order_id='order_rzp_refund_test',
            razorpay_payment_id='pay_rzp_refund_test',
        )

        response = self.client.post(
            reverse('cancel_order', kwargs={'order_id': order.order_id}),
            {'cancellation_reason': 'Refund test'}
        )

        order.refresh_from_db()
        self.assertEqual(order.order_status, 'CANCELLED')
        self.assertEqual(order.refund_status, 'PROCESSING')
        self.assertEqual(order.refund_id, 'rfnd_test_12345')
        mock_client.payment.refund.assert_called_once()

    # =========================================================================
    # 14. Ineligible orders cannot be cancelled
    # =========================================================================
    def test_shipped_order_cannot_be_cancelled(self):
        order = Order.objects.create(
            user=self.user,
            customer_name='Aarav Patel',
            mobile='9876543210',
            address='MG Road',
            city='Bengaluru',
            state='Karnataka',
            pincode='560001',
            total_amount=Decimal('499.00'),
            payment_method='COD',
            payment_status='PENDING',
            order_status='SHIPPED',
        )

        response = self.client.post(
            reverse('cancel_order', kwargs={'order_id': order.order_id}),
            {'cancellation_reason': 'Changed mind'}
        )
        order.refresh_from_db()
        self.assertEqual(order.order_status, 'SHIPPED')  # Not cancelled

    def test_already_cancelled_order_cannot_be_cancelled_again(self):
        order = Order.objects.create(
            user=self.user,
            customer_name='Aarav Patel',
            mobile='9876543210',
            address='MG Road',
            city='Bengaluru',
            state='Karnataka',
            pincode='560001',
            total_amount=Decimal('499.00'),
            payment_method='COD',
            payment_status='PENDING',
            order_status='CANCELLED',
        )

        response = self.client.post(
            reverse('cancel_order', kwargs={'order_id': order.order_id}),
            {'cancellation_reason': 'Again'}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'cannot be cancelled')

    def test_delivered_order_cannot_be_cancelled(self):
        order = Order.objects.create(
            user=self.user,
            customer_name='Aarav Patel',
            mobile='9876543210',
            address='MG Road',
            city='Bengaluru',
            state='Karnataka',
            pincode='560001',
            total_amount=Decimal('499.00'),
            payment_method='COD',
            payment_status='PENDING',
            order_status='DELIVERED',
        )
        self.assertFalse(order.is_cancellable())

    # =========================================================================
    # 15. Duplicate refund attempts are prevented (idempotency via refund_id)
    # =========================================================================
    @patch('library.views.is_razorpay_configured', return_value=False)
    def test_double_cancellation_prevented_by_status_check(self, mock_config):
        order = Order.objects.create(
            user=self.user,
            customer_name='Aarav Patel',
            mobile='9876543210',
            address='MG Road',
            city='Bengaluru',
            state='Karnataka',
            pincode='560001',
            total_amount=Decimal('499.00'),
            payment_method='ONLINE',
            payment_status='PAID',
            order_status='PLACED',
            razorpay_payment_id='pay_dup_test',
        )

        # First cancel
        self.client.post(
            reverse('cancel_order', kwargs={'order_id': order.order_id}),
            {'cancellation_reason': 'First cancel'}
        )
        order.refresh_from_db()
        self.assertEqual(order.order_status, 'CANCELLED')

        # Second cancel attempt
        response = self.client.post(
            reverse('cancel_order', kwargs={'order_id': order.order_id}),
            {'cancellation_reason': 'Second cancel'}
        )
        # Should NOT re-cancel, the order is already cancelled
        order.refresh_from_db()
        self.assertEqual(order.cancellation_reason, 'First cancel')  # Unchanged

    # =========================================================================
    # 16. Refund status changes only through authorized operations
    # =========================================================================
    def test_unauthenticated_user_cannot_cancel(self):
        self.client.logout()
        order = Order.objects.create(
            user=self.user,
            customer_name='Aarav Patel',
            mobile='9876543210',
            address='MG Road',
            city='Bengaluru',
            state='Karnataka',
            pincode='560001',
            total_amount=Decimal('499.00'),
            payment_method='COD',
            payment_status='PENDING',
            order_status='PLACED',
        )
        response = self.client.post(
            reverse('cancel_order', kwargs={'order_id': order.order_id}),
            {'cancellation_reason': 'test'}
        )
        # Should redirect to login
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)
        order.refresh_from_db()
        self.assertEqual(order.order_status, 'PLACED')

    # =========================================================================
    # 17. Cart behavior after successful operations
    # =========================================================================
    def test_cart_cleared_after_cod_order(self):
        self._add_to_cart(self.book1.id, 1)
        self._add_to_cart(self.book2.id, 2)
        self.client.post(reverse('checkout'), self.valid_delivery_data)
        self.assertEqual(self.client.session.get('cart'), {})

    def test_cart_preserved_on_failed_payment(self):
        self._add_to_cart(self.book1.id, 1)
        response = self.client.get(f"{reverse('payment_failed')}?reason=cancelled")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.session.get('cart'), {str(self.book1.id): 1})

    # =========================================================================
    # 18. Existing functionality tests
    # =========================================================================
    def test_book_list_renders(self):
        response = self.client.get(reverse('book_list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Harry Potter')

    def test_add_to_cart_works(self):
        response = self.client.get(reverse('add_to_cart', kwargs={'book_id': self.book1.id}))
        self.assertRedirects(response, reverse('cart'))
        self.assertEqual(self.client.session['cart'], {str(self.book1.id): 1})

    def test_cart_view_renders(self):
        self._add_to_cart(self.book1.id, 1)
        response = self.client.get(reverse('cart'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Harry Potter')

    def test_increase_decrease_remove_from_cart(self):
        self._add_to_cart(self.book1.id, 1)

        self.client.get(reverse('increase_quantity', kwargs={'book_id': self.book1.id}))
        self.assertEqual(self.client.session['cart'][str(self.book1.id)], 2)

        self.client.get(reverse('decrease_quantity', kwargs={'book_id': self.book1.id}))
        self.assertEqual(self.client.session['cart'][str(self.book1.id)], 1)

        self.client.get(reverse('remove_from_cart', kwargs={'book_id': self.book1.id}))
        self.assertNotIn(str(self.book1.id), self.client.session['cart'])

    def test_order_history_shows_user_orders_only(self):
        Order.objects.create(
            user=self.user,
            customer_name='Aarav Patel',
            mobile='9876543210',
            address='MG Road',
            city='Bengaluru',
            state='Karnataka',
            pincode='560001',
            total_amount=Decimal('599.00'),
            payment_method='COD',
            payment_status='PENDING',
            order_status='PLACED',
        )
        Order.objects.create(
            user=self.other_user,
            customer_name='Priya Singh',
            mobile='9123456789',
            address='Other Road',
            city='Delhi',
            state='Delhi',
            pincode='110001',
            total_amount=Decimal('299.00'),
            payment_method='COD',
            payment_status='PENDING',
            order_status='PLACED',
        )

        response = self.client.get(reverse('order_history'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Aarav Patel')
        self.assertNotContains(response, 'Priya Singh')

    def test_checkout_page_displays_both_payment_options_and_defaults_to_cod(self):
        self._add_to_cart(self.book1.id, 1)

        response = self.client.get(reverse('checkout'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cash on Delivery (COD)")
        self.assertContains(response, "Online Payment (Razorpay Test Mode)")
        self.assertContains(response, 'name="customer_name"')
        self.assertContains(response, 'name="mobile"')
        self.assertContains(response, 'name="address"')

    @patch('library.views.is_razorpay_configured', return_value=False)
    def test_online_payment_disabled_when_credentials_unavailable(self, mock_is_configured):
        self._add_to_cart(self.book1.id, 1)

        online_data = self.valid_delivery_data.copy()
        online_data['payment_method'] = 'ONLINE'

        response = self.client.post(reverse('checkout'), online_data)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'library/checkout.html')
        self.assertContains(response, "Online payment is disabled")
        self.assertEqual(Order.objects.count(), 0)

    @patch('library.views.is_razorpay_configured', return_value=False)
    def test_cod_flow_succeeds_without_razorpay_credentials(self, mock_is_configured):
        self._add_to_cart(self.book2.id, 3)

        response = self.client.post(reverse('checkout'), self.valid_delivery_data)

        self.assertEqual(Order.objects.count(), 1)
        order = Order.objects.first()
        self.assertEqual(order.payment_method, 'COD')
        self.assertEqual(order.payment_status, 'PENDING')
        self.assertEqual(order.order_status, 'PLACED')
        self.assertEqual(order.total_amount, Decimal('897.00'))
        self.assertEqual(order.items.count(), 1)
        self.assertEqual(order.items.first().quantity, 3)
        self.assertEqual(self.client.session.get('cart'), {})
        self.assertRedirects(response, reverse('order_success', kwargs={'order_id': order.order_id}))

    def test_checkout_requires_login(self):
        self.client.logout()
        self._add_to_cart(self.book1.id, 1)
        response = self.client.get(reverse('checkout'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)

    def test_order_detail_page_renders(self):
        self._add_to_cart(self.book1.id, 1)
        self.client.post(reverse('checkout'), self.valid_delivery_data)
        order = Order.objects.first()

        response = self.client.get(reverse('order_detail', kwargs={'order_id': order.order_id}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Order Details')
        self.assertContains(response, order.customer_name)

    def test_cancel_confirm_page_renders_for_eligible_order(self):
        order = Order.objects.create(
            user=self.user,
            customer_name='Aarav Patel',
            mobile='9876543210',
            address='MG Road',
            city='Bengaluru',
            state='Karnataka',
            pincode='560001',
            total_amount=Decimal('499.00'),
            payment_method='COD',
            payment_status='PENDING',
            order_status='PLACED',
        )
        response = self.client.get(reverse('cancel_confirm', kwargs={'order_id': order.order_id}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Cancel Order')
        self.assertContains(response, 'Confirm Cancellation')

    def test_payment_failed_view_renders_cart_and_retry(self):
        self._add_to_cart(self.book1.id, 1)
        response = self.client.get(f"{reverse('payment_failed')}?reason=cancelled")
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'library/payment_failed.html')
        self.assertContains(response, "Payment Incomplete or Cancelled")
        self.assertContains(response, "Your Cart is Intact!")

    def test_cancellation_success_page_renders(self):
        order = Order.objects.create(
            user=self.user,
            customer_name='Aarav Patel',
            mobile='9876543210',
            address='MG Road',
            city='Bengaluru',
            state='Karnataka',
            pincode='560001',
            total_amount=Decimal('499.00'),
            payment_method='COD',
            payment_status='PENDING',
            order_status='CANCELLED',
            cancellation_reason='Test',
            cancelled_at='2026-10-24T12:00:00Z',
        )
        response = self.client.get(reverse('cancellation_success', kwargs={'order_id': order.order_id}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Order Cancelled')

    def test_model_is_cancellable_logic(self):
        """Test the is_cancellable method on the Order model."""
        order = Order(order_status='PLACED', payment_status='PENDING')
        self.assertTrue(order.is_cancellable())

        order = Order(order_status='PROCESSING', payment_status='PAID')
        self.assertTrue(order.is_cancellable())

        order = Order(order_status='SHIPPED', payment_status='PAID')
        self.assertFalse(order.is_cancellable())

        order = Order(order_status='DELIVERED', payment_status='PAID')
        self.assertFalse(order.is_cancellable())

        order = Order(order_status='CANCELLED', payment_status='PENDING')
        self.assertFalse(order.is_cancellable())
