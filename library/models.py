
import uuid

from django.db import models
from django.contrib.auth.models import User


class Author(models.Model):
    name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    biography = models.TextField(blank=True)
    date_of_birth = models.DateField(null=True, blank=True)

    def __str__(self):
        return self.name


class Book(models.Model):
    title = models.CharField(max_length=200)
    isbn_number = models.CharField(max_length=13, unique=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    published_date = models.DateField(null=True, blank=True)
    available = models.BooleanField(default=True)

    author = models.ForeignKey(
        Author,
        on_delete=models.CASCADE,
        related_name="books"
    )

    image = models.ImageField(
        upload_to="books/",
        blank=True,
        null=True
    )

    def __str__(self):
        return self.title


class Member(models.Model):
    name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    phone_number = models.CharField(max_length=15)
    join_date = models.DateField(auto_now_add=True)
    active_status = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class BorrowRecord(models.Model):
    book = models.ForeignKey(Book, on_delete=models.CASCADE)
    member = models.ForeignKey(Member, on_delete=models.CASCADE)
    borrow_date = models.DateField(auto_now_add=True)
    return_date = models.DateField(null=True, blank=True)
    returned_status = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.member.name} - {self.book.title}"


class Order(models.Model):
    PAYMENT_METHODS = [
        ('COD', 'Cash on Delivery'),
        ('ONLINE', 'Online Payment'),
    ]

    PAYMENT_STATUSES = [
        ('PENDING', 'Pending'),
        ('PAID', 'Paid'),
        ('FAILED', 'Failed'),
        ('REFUND_PENDING', 'Refund Pending'),
        ('REFUNDED', 'Refunded'),
    ]

    ORDER_STATUSES = [
        ('PLACED', 'Placed'),
        ('PROCESSING', 'Processing'),
        ('SHIPPED', 'Shipped'),
        ('DELIVERED', 'Delivered'),
        ('CANCELLATION_REQUESTED', 'Cancellation Requested'),
        ('CANCELLED', 'Cancelled'),
    ]

    REFUND_STATUSES = [
        ('NOT_APPLICABLE', 'Not Applicable'),
        ('PENDING', 'Pending'),
        ('PROCESSING', 'Processing'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
    ]

    order_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False
    )

    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='orders'
    )

    customer_name = models.CharField(max_length=100)
    customer_email = models.EmailField(blank=True)
    mobile = models.CharField(max_length=15)
    address = models.TextField()
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    pincode = models.CharField(max_length=10)

    total_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    payment_method = models.CharField(
        max_length=10,
        choices=PAYMENT_METHODS
    )

    payment_status = models.CharField(
        max_length=20,
        choices=PAYMENT_STATUSES,
        default='PENDING'
    )

    # Order status
    order_status = models.CharField(
        max_length=30,
        choices=ORDER_STATUSES,
        default='PLACED'
    )

    # Cancellation and refund fields
    refund_status = models.CharField(
        max_length=20,
        choices=REFUND_STATUSES,
        default='NOT_APPLICABLE'
    )

    cancellation_reason = models.TextField(blank=True)

    cancelled_at = models.DateTimeField(
        null=True,
        blank=True
    )

    refund_id = models.CharField(
        max_length=100,
        blank=True,
        help_text='Razorpay refund ID for tracking'
    )

    # Razorpay payment details
    razorpay_order_id = models.CharField(
        max_length=100,
        blank=True
    )

    razorpay_payment_id = models.CharField(
        max_length=100,
        blank=True
    )

    razorpay_signature = models.CharField(
        max_length=255,
        blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['order_status']),
            models.Index(fields=['payment_status']),
            models.Index(fields=['razorpay_order_id']),
            models.Index(fields=['razorpay_payment_id']),
        ]

    def __str__(self):
        return (
            f"Order {str(self.order_id)[:8]} "
            f"- {self.customer_name}"
        )

    def is_cancellable(self):
        """Check whether the order is eligible for cancellation."""
        return (
            self.order_status in ['PLACED', 'PROCESSING']
            and self.payment_status in ['PENDING', 'PAID']
        )

    @property
    def order_status_display_badge(self):
        """Return the CSS class for the order status badge."""
        badge_map = {
            'PLACED': 'badge-info',
            'PROCESSING': 'badge-warning',
            'SHIPPED': 'badge-primary',
            'DELIVERED': 'badge-success',
            'CANCELLATION_REQUESTED': 'badge-warning',
            'CANCELLED': 'badge-danger',
        }

        return badge_map.get(
            self.order_status,
            'badge-secondary'
        )


class OrderItem(models.Model):
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='items'
    )

    book = models.ForeignKey(
        Book,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    book_title = models.CharField(max_length=200)

    book_image = models.CharField(
        max_length=500,
        blank=True,
        help_text='Snapshot of book image path at time of purchase'
    )

    price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField(default=1)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"{self.book_title} x {self.quantity}"
