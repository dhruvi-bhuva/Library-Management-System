

def cancel_confirm(request, order_id):
    """
    Shows a cancellation confirmation page for an eligible order.
    GET: Render the confirmation page.
    POST: Process the cancellation.
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
                           'Only orders that are Pending (COD) or Paid (Online) can be cancelled.',
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
    - COD orders: status set to CANCELLED, payment_status CANCELLED.
    - ONLINE/PAID orders: status CANCELLED, refund_status REFUND_PENDING (simulated).
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
                           'Only Pending (COD) or Paid (Online) orders that have not yet shipped are eligible.',
            }
        )

    cancellation_reason = request.POST.get('cancellation_reason', '').strip()

    with transaction.atomic():
        order.cancellation_status = 'CANCELLED'
        order.cancellation_reason = cancellation_reason
        order.cancelled_at = timezone.now()

        if order.payment_method == 'ONLINE' and order.payment_status == 'PAID':
            # Simulate refund — record refund as PENDING (no live Razorpay credentials)
            order.payment_status = 'CANCELLED'
            order.refund_status = 'REFUND_PENDING'
        else:
            # COD: just mark as cancelled
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
