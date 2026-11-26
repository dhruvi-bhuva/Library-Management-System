from django import forms
from .models import Review


class ReviewForm(forms.ModelForm):
    rating = forms.ChoiceField(
        choices=Review.RATING_CHOICES,
        widget=forms.Select(attrs={
            'class': 'form-select rating-select',
            'id': 'rating-select',
            'required': 'required'
        }),
        help_text="Select your rating from 1 to 5 stars"
    )

    review = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 4,
            'placeholder': 'Share your experience with this book (e.g. content quality, storyline, printing, etc.)...',
            'required': 'required'
        }),
        required=True,
        help_text="Write your review"
    )

    class Meta:
        model = Review
        fields = ['rating', 'review']
