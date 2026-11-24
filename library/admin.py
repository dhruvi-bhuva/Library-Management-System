import logging
from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html
from .models import Author, Book, Member, BorrowRecord, Order, OrderItem
from .services import is_razorpay_configured, get_razorpay_client

logger = logging.getLogger(__name__)


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
        'author'
    )
    list_filter = ('available', 'author')
    search_fields = ('title', 'isbn_number')


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
    readonly_fields = ('book_title', 'book_image', 'price', 'quantity', 'subtotal')


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        'short_order_id',
        'customer_name',
        'mobile',
        'total_amount_display',
        'payment_method',
        'payment_status_badge',
        'order_status_badge',
        'refund_status_badge',
        'created_at'
    )
    list_filter = (
        'payment_method',
        'payment_status',
        'order_status',
        'refund_status',
        'created_at'
    )
    search_fields = (
        'order_id',
        'customer_name',
        'mobile',
        'customer_email',
        'razorpay_order_id',
        'razorpay_payment_id',
        'refund_id',
    )
    readonly_fields = ('order_id', 'created_at', 'updated_at', 'cancelled_at')
    fieldsets = (
        ('Order Info', {
            'fields': ('order_id', 'user', 'customer_name', 'customer_email', 'mobile', 'created_at', 'updated_at')
        }),
        ('Delivery Address', {
            'fields': ('address', 'city', 'state', 'pincode')
        }),
        ('Payment', {
            'fields': ('total_amount', 'payment_method', 'payment_status',
                       'razorpay_order_id', 'razorpay_payment_id', 'razorpay_signature')
        }),
        ('Order Status', {
            'fields': ('order_status',)
        }),
        ('Cancellation & Refund', {
            'fields': ('refund_status', 'refund_id', 'cancellation_reason', 'cancelled_at')
        }),
    )
    inlines = [OrderItemInline]
    actions = [
        'mark_processing',
        'mark_shipped',
        'mark_delivered',
        'approve_cancellation',
        'initiate_refund',
        'mark_refund_completed',
    ]
    list_per_page = 25

    def short_order_id(self, obj):
        return str(obj.order_id)[:8] + '...'
    short_order_id.short_description = 'Order ID'

    def total_amount_display(self, obj):
        return format_html('<strong>₹{}</strong>', obj.total_amount)
    total_amount_display.short_description = 'Total'

    def payment_status_badge(self, obj):
        colors = {
            'PENDING': '#ffc107',
            'PAID': '#198754',
            'FAILED': '#dc3545',
            'REFUND_PENDING': '#fd7e14',
            'REFUNDED': '#6c757d',
        }
        color = colors.get(obj.payment_status, '#6c757d')
        return format_html(
            '<span style="background:{}; color:white; padding:3px 8px; '
            'border-radius:12px; font-size:11px; font-weight:bold;">{}</span>',
            color, obj.get_payment_status_display()
        )
    payment_status_badge.short_description = 'Payment'

    def order_status_badge(self, obj):
        colors = {
            'PLACED': '#0d6efd',
            'PROCESSING': '#ffc107',
            'SHIPPED': '#0dcaf0',
            'DELIVERED': '#198754',
            'CANCELLATION_REQUESTED': '#fd7e14',
            'CANCELLED': '#dc3545',
        }
        color = colors.get(obj.order_status, '#6c757d')
        text_color = 'white' if obj.order_status != 'PROCESSING' else '#212529'
        return format_html(
            '<span style="background:{}; color:{}; padding:3px 8px; '
            'border-radius:12px; font-size:11px; font-weight:bold;">{}</span>',
            color, text_color, obj.get_order_status_display()
        )
    order_status_badge.short_description = 'Order Status'

    def refund_status_badge(self, obj):
        if obj.refund_status == 'NOT_APPLICABLE':
            return '-'
        colors = {
            'PENDING': '#ffc107',
            'PROCESSING': '#0dcaf0',
            'COMPLETED': '#198754',
            'FAILED': '#dc3545',
        }
        color = colors.get(obj.refund_status, '#6c757d')
        return format_html(
            '<span style="background:{}; color:white; padding:3px 8px; '
            'border-radius:12px; font-size:11px; font-weight:bold;">{}</span>',
            color, obj.get_refund_status_display()
        )
    refund_status_badge.short_description = 'Refund'

    @admin.action(description='Mark selected orders as Processing')
    def mark_processing(self, request, queryset):
        updated = queryset.filter(order_status='PLACED').update(
            order_status='PROCESSING'
        )
        self.message_user(request, f'{updated} order(s) marked as Processing.')

    @admin.action(description='Mark selected orders as Shipped')
    def mark_shipped(self, request, queryset):
        updated = queryset.filter(order_status__in=['PLACED', 'PROCESSING']).update(
            order_status='SHIPPED'
        )
        self.message_user(request, f'{updated} order(s) marked as Shipped.')

    @admin.action(description='Mark selected orders as Delivered')
    def mark_delivered(self, request, queryset):
        updated = queryset.filter(order_status='SHIPPED').update(
            order_status='DELIVERED'
        )
        self.message_user(request, f'{updated} order(s) marked as Delivered.')

    @admin.action(description='Approve cancellation for selected orders')
    def approve_cancellation(self, request, queryset):
        cancellable = queryset.filter(
            order_status__in=['PLACED', 'PROCESSING', 'CANCELLATION_REQUESTED']
        )
        count = 0
        for order in cancellable:
            order.order_status = 'CANCELLED'
            order.cancelled_at = timezone.now()
            if order.payment_method == 'ONLINE' and order.payment_status == 'PAID':
                order.payment_status = 'REFUND_PENDING'
                order.refund_status = 'PENDING'
            order.save()
            count += 1
        self.message_user(request, f'{count} order(s) cancellation approved.')

    @admin.action(description='Initiate Razorpay refund for selected orders')
    def initiate_refund(self, request, queryset):
        if not is_razorpay_configured():
            self.message_user(request, 'Razorpay is not configured. Cannot initiate refunds.', level='error')
            return

        client = get_razorpay_client()
        count = 0
        errors = 0
        for order in queryset.filter(
            payment_method='ONLINE',
            payment_status__in=['PAID', 'REFUND_PENDING'],
            refund_status__in=['NOT_APPLICABLE', 'PENDING', 'FAILED'],
            order_status='CANCELLED',
        ):
            if not order.razorpay_payment_id:
                continue
            # Idempotency: skip if refund already initiated
            if order.refund_id:
                continue
            try:
                refund = client.payment.refund(order.razorpay_payment_id, {
                    'amount': int(order.total_amount * 100),
                    'speed': 'normal',
                    'notes': {
                        'reason': order.cancellation_reason or 'Admin initiated refund',
                        'order_id': str(order.order_id),
                    }
                })
                order.refund_id = refund.get('id', '')
                order.refund_status = 'PROCESSING'
                order.payment_status = 'REFUND_PENDING'
                order.save()
                count += 1
                logger.info(f"Admin refund initiated: order={str(order.order_id)[:8]}, refund_id={refund.get('id')}")
            except Exception as e:
                errors += 1
                logger.error(f"Admin refund failed for order {str(order.order_id)[:8]}: {e}")

        msg = f'{count} refund(s) initiated.'
        if errors:
            msg += f' {errors} refund(s) failed — check logs.'
        self.message_user(request, msg)

    @admin.action(description='Mark refund as Completed (manual confirmation)')
    def mark_refund_completed(self, request, queryset):
        updated = queryset.filter(
            refund_status__in=['PENDING', 'PROCESSING'],
            order_status='CANCELLED',
        ).update(
            refund_status='COMPLETED',
            payment_status='REFUNDED',
        )
        self.message_user(
            request,
            f'{updated} order(s) refund marked as Completed. '
            f'Ensure the actual refund was confirmed before using this action.'
        )
