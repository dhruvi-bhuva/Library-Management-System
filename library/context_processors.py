from .models import Wishlist


def wishlist_count(request):
    """
    Context processor to make wishlist count globally available in all templates.
    """
    if hasattr(request, 'user') and request.user.is_authenticated:
        count = Wishlist.objects.filter(user=request.user).count()
    else:
        count = 0
    return {
        'wishlist_count': count
    }
