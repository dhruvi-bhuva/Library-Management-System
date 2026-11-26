from django.contrib import admin
from django.utils import timezone
from .models import Author, Book, Member, BorrowRecord, Order, OrderItem, Review, Wishlist


class ReviewInline(admin.TabularInline):
    model = Review
    extra = 0
    fields = ('user', 'rating', 'review', 'created_at')
    readonly_fields = ('created_at',)


@admin.register(Author)
class AuthorAdmin(admin.ModelAdmin):
    list_display = ('name', 'email', 'date_of_birth')


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = (
        'title',
        'isbn_number',
        'price',
        'available',
        'author',
        'average_rating_display',
        'total_reviews_count',
    )
    list_filter = ('available', 'author')
    search_fields = ('title', 'isbn_number')
    inlines = [ReviewInline]

    def average_rating_display(self, obj):
        avg = obj.average_rating()
        return f"{avg} ★" if avg > 0 else "No reviews"
    average_rating_display.short_description = 'Avg Rating'

    def total_reviews_count(self, obj):
        return obj.total_reviews()
    total_reviews_count.short_description = 'Reviews'


@admin.register(Member)
class MemberAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'email',
        'phone_number',
        'join_date',
        'active_status'
    )
    list_filter = ('active_status',)
    search_fields = ('name', 'email')


@admin.register(BorrowRecord)
class BorrowRecordAdmin(admin.ModelAdmin):
    list_display = (
        'book',
        'member',
        'borrow_date',
        'return_date',
        'returned_status'
    )
    list_filter = ('returned_status',)


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ('book_title', 'price', 'quantity', 'subtotal')


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        'order_id',
        'customer_name',
        'mobile',
        'total_amount',
        'payment_method',
        'payment_status',
        'order_status',
        'cancellation_status',
        'refund_status',
        'created_at'
    )
    list_filter = (
        'order_status',
        'cancellation_status',
        'refund_status',
        'payment_method',
        'payment_status',
        'created_at'
    )
    search_fields = (
        'order_id',
        'customer_name',
        'mobile',
        'razorpay_order_id',
        'razorpay_payment_id'
    )
    readonly_fields = ('order_id', 'created_at', 'updated_at', 'cancelled_at')
    fieldsets = (
        ('Order Info', {
            'fields': ('order_id', 'user', 'customer_name', 'customer_email', 'mobile', 'created_at', 'updated_at')
        }),
        ('Delivery Address', {
            'fields': ('address', 'city', 'state', 'pincode')
        }),
        ('Status & Tracking', {
            'fields': ('order_status',)
        }),
        ('Payment', {
            'fields': ('total_amount', 'payment_method', 'payment_status',
                       'razorpay_order_id', 'razorpay_payment_id', 'razorpay_signature')
        }),
        ('Cancellation & Refund Management', {
            'fields': ('cancellation_status', 'refund_status', 'cancellation_reason', 'cancelled_at')
        }),
    )
    inlines = [OrderItemInline]
    actions = [
        'approve_cancellation',
        'process_refund_completed',
        'mark_as_processing',
        'mark_as_shipped',
        'mark_as_delivered',
    ]

    @admin.action(description="Cancel selected orders (Approve Cancellation)")
    def approve_cancellation(self, request, queryset):
        count = 0
        now = timezone.now()
        for order in queryset:
            if order.cancellation_status != 'CANCELLED':
                order.order_status = 'CANCELLED'
                order.cancellation_status = 'CANCELLED'
                order.payment_status = 'CANCELLED'
                order.cancelled_at = now
                if order.payment_method == 'ONLINE':
                    order.refund_status = 'REFUND_PENDING'
                else:
                    order.refund_status = 'NOT_APPLICABLE'
                order.save()
                count += 1
        self.message_user(request, f"{count} order(s) successfully marked as CANCELLED.")

    @admin.action(description="Mark selected orders as REFUNDED (Simulate/Complete Refund)")
    def process_refund_completed(self, request, queryset):
        updated = queryset.filter(refund_status='REFUND_PENDING').update(
            refund_status='REFUNDED',
            payment_status='REFUNDED'
        )
        self.message_user(request, f"{updated} order(s) marked as REFUNDED.")

    @admin.action(description="Set order status to PROCESSING")
    def mark_as_processing(self, request, queryset):
        updated = queryset.exclude(order_status='CANCELLED').update(order_status='PROCESSING')
        self.message_user(request, f"{updated} order(s) updated to PROCESSING.")

    @admin.action(description="Set order status to SHIPPED")
    def mark_as_shipped(self, request, queryset):
        updated = queryset.exclude(order_status='CANCELLED').update(order_status='SHIPPED')
        self.message_user(request, f"{updated} order(s) updated to SHIPPED.")

    @admin.action(description="Set order status to DELIVERED")
    def mark_as_delivered(self, request, queryset):
        updated = queryset.exclude(order_status='CANCELLED').update(order_status='DELIVERED')
        self.message_user(request, f"{updated} order(s) updated to DELIVERED.")


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = (
        'book',
        'user',
        'rating',
        'star_display_badge',
        'short_review',
        'created_at',
        'updated_at',
    )
    list_filter = (
        'rating',
        'created_at',
        'book',
    )
    search_fields = (
        'user__username',
        'user__email',
        'book__title',
        'review',
    )
    readonly_fields = ('created_at', 'updated_at')
    ordering = ('-created_at',)

    def star_display_badge(self, obj):
        return obj.star_display
    star_display_badge.short_description = 'Stars'

    def short_review(self, obj):
        if not obj.review:
            return "(No text)"
        return obj.review[:60] + ('...' if len(obj.review) > 60 else '')
    short_review.short_description = 'Review Text'


@admin.register(Wishlist)
class WishlistAdmin(admin.ModelAdmin):
    list_display = ('user', 'book', 'added_at')
    list_filter = ('added_at',)
    search_fields = ('user__username', 'user__email', 'book__title', 'book__isbn_number')
    readonly_fields = ('added_at',)
    ordering = ('-added_at',)

