# from django.db import models


# class Category(models.Model):
#     name = models.CharField(max_length=100, unique=True)
#     description = models.TextField(blank=True)
#     created_at = models.DateTimeField(auto_now_add=True)
#     is_active = models.BooleanField(default=True)

#     def __str__(self):
#         return self.name


# class Book(models.Model):
#     title = models.CharField(max_length=200)
#     author = models.CharField(max_length=150)
#     ISBN = models.CharField(max_length=13, unique=True)
    
#     category = models.ForeignKey(
#         Category,
#         on_delete=models.CASCADE,
#         related_name='books'
#     )

#     description = models.TextField(blank=True)
#     publisher = models.CharField(max_length=150, blank=True)
#     publication_date = models.DateField(null=True, blank=True)
#     price = models.DecimalField(
#         max_digits=10,
#         decimal_places=2,
#         default=0
#     )
#     quantity = models.PositiveIntegerField(default=1)
#     language = models.CharField(max_length=50, default='English')
#     pages = models.PositiveIntegerField(null=True, blank=True)
#     is_available = models.BooleanField(default=True)
#     created_at = models.DateTimeField(auto_now_add=True)

#     def __str__(self):
#         return self.title

import uuid
from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator


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

    # Book image
    image = models.ImageField(
        upload_to="books/",
        blank=True,
        null=True
    )

    def __str__(self):
        return self.title

    def average_rating(self):
        """Returns the average rating for this book rounded to 1 decimal place."""
        avg = self.reviews.aggregate(models.Avg('rating'))['rating__avg']
        return round(float(avg), 1) if avg is not None else 0.0

    def total_reviews(self):
        """Returns total number of reviews for this book."""
        return self.reviews.count()

    def rating_percentage(self):
        """Returns the average rating as a percentage out of 5 stars (0 - 100)."""
        avg = self.average_rating()
        return round((avg / 5.0) * 100, 1) if avg else 0

    def star_breakdown(self):
        """Returns a breakdown of review counts and percentages for each star rating 5 down to 1."""
        total = self.total_reviews()
        breakdown = []
        for star in range(5, 0, -1):
            count = self.reviews.filter(rating=star).count()
            percent = round((count / total) * 100, 1) if total > 0 else 0
            breakdown.append({
                'star': star,
                'count': count,
                'percent': percent,
            })
        return breakdown

    def is_purchased_by(self, user):
        """
        Check if the given user has purchased this book.
        A user has purchased if:
        1. User is authenticated
        2. An Order exists linked to this user (or user's email) containing this book
        3. The order is not cancelled
        """
        if not user or not user.is_authenticated:
            return False

        order_filter = models.Q(user=user)
        if user.email:
            order_filter |= models.Q(customer_email__iexact=user.email)

        return Order.objects.filter(
            order_filter,
            items__book=self
        ).exclude(
            cancellation_status='CANCELLED'
        ).exclude(
            order_status='CANCELLED'
        ).exists()

    def is_in_wishlist(self, user):
        """Returns True if this book is in the user's wishlist."""
        if not user or not user.is_authenticated:
            return False
        return self.wishlisted_by.filter(user=user).exists()



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



# Order and OrderItem models
class Order(models.Model):
    ORDER_STATUSES = [
        ('PLACED', 'Placed'),
        ('PROCESSING', 'Processing'),
        ('SHIPPED', 'Shipped'),
        ('DELIVERED', 'Delivered'),
        ('CANCELLED', 'Cancelled'),
    ]

    PAYMENT_METHODS = [
        ('COD', 'Cash on Delivery'),
        ('ONLINE', 'Online Payment'),
    ]

    PAYMENT_STATUSES = [
        ('PENDING', 'Pending'),
        ('PAID', 'Paid'),
        ('FAILED', 'Failed'),
        ('CANCELLED', 'Cancelled'),
        ('REFUNDED', 'Refunded'),
    ]

    CANCELLATION_STATUSES = [
        ('NOT_CANCELLED', 'Not Cancelled'),
        ('CANCELLATION_REQUESTED', 'Cancellation Requested'),
        ('CANCELLED', 'Cancelled'),
    ]

    REFUND_STATUSES = [
        ('NOT_APPLICABLE', 'Not Applicable'),
        ('REFUND_PENDING', 'Refund Pending'),
        ('REFUNDED', 'Refunded'),
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

    order_status = models.CharField(
        max_length=20,
        choices=ORDER_STATUSES,
        default='PLACED'
    )

    payment_method = models.CharField(
        max_length=10,
        choices=PAYMENT_METHODS
    )

    payment_status = models.CharField(
        max_length=10,
        choices=PAYMENT_STATUSES,
        default='PENDING'
    )

    # Cancellation fields
    cancellation_status = models.CharField(
        max_length=30,
        choices=CANCELLATION_STATUSES,
        default='NOT_CANCELLED'
    )
    refund_status = models.CharField(
        max_length=20,
        choices=REFUND_STATUSES,
        default='NOT_APPLICABLE'
    )
    cancellation_reason = models.TextField(blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

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

    def __str__(self):
        return f"Order {str(self.order_id)[:8]} - {self.customer_name}"

    def is_cancellable(self):
        """
        Returns True if this order is eligible for cancellation.
        Eligible only when:
        1. order_status is 'PLACED' or 'PROCESSING' (not shipped/delivered)
        2. cancellation_status is 'NOT_CANCELLED'
        3. payment_status is 'PENDING' (COD) or 'PAID' (Online)
        """
        return (
            self.order_status in ['PLACED', 'PROCESSING'] and
            self.cancellation_status == 'NOT_CANCELLED' and
            self.payment_status in ['PENDING', 'PAID']
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
    price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField(default=1)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"{self.book_title} x {self.quantity}"


class Review(models.Model):
    RATING_CHOICES = [
        (1, '1 Star - Poor'),
        (2, '2 Stars - Fair'),
        (3, '3 Stars - Good'),
        (4, '4 Stars - Very Good'),
        (5, '5 Stars - Excellent'),
    ]

    book = models.ForeignKey(
        Book,
        on_delete=models.CASCADE,
        related_name='reviews'
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='reviews'
    )
    rating = models.PositiveSmallIntegerField(
        choices=RATING_CHOICES,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
        help_text="Rating must be between 1 and 5 stars"
    )
    review = models.TextField(
        blank=True,
        help_text="Write your review here"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = ('book', 'user')

    def __str__(self):
        return f"{self.user.username} - {self.book.title} ({self.rating}★)"

    @property
    def comment(self):
        """Alias for review text"""
        return self.review

    @property
    def filled_stars(self):
        return range(self.rating)

    @property
    def empty_stars(self):
        return range(5 - self.rating)

    @property
    def star_display(self):
        return '★' * self.rating + '☆' * (5 - self.rating)


class Wishlist(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='wishlist_items'
    )
    book = models.ForeignKey(
        Book,
        on_delete=models.CASCADE,
        related_name='wishlisted_by'
    )
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-added_at']
        unique_together = ('user', 'book')
        verbose_name = 'Wishlist Item'
        verbose_name_plural = 'Wishlist Items'

    def __str__(self):
        return f"{self.user.username} - {self.book.title}"


