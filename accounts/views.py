from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib import messages


def register(request):
    if request.user.is_authenticated:
        return redirect('book_list')

    if request.method == "POST":
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        confirm_password = request.POST.get('confirm_password', '')

        if not username or not password:
            messages.error(request, "Username and password are required.")
            return render(request, 'register.html')

        if password != confirm_password:
            messages.error(request, "Passwords do not match!")
            return render(request, 'register.html')

        if User.objects.filter(username=username).exists():
            messages.error(request, "A user with this username already exists.")
            return render(request, 'register.html')

        if email and User.objects.filter(email=email).exists():
            messages.error(request, "A user with this email already exists.")
            return render(request, 'register.html')

        user = User.objects.create_user(
            first_name=first_name,
            last_name=last_name,
            username=username,
            email=email,
            password=password
        )
        login(request, user)
        messages.success(request, f"Welcome {username}! Your account has been registered.")
        return redirect('book_list')

    return render(request, 'register.html')


def user_login(request):
    if request.user.is_authenticated:
        return redirect('book_list')

    next_url = request.GET.get('next') or request.POST.get('next') or 'book_list'

    if request.method == "POST":
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            messages.success(request, f"Welcome back, {user.username}!")
            return redirect(next_url)
        else:
            messages.error(request, "Invalid username or password.")

    return render(request, 'login.html', {'next': next_url})


def user_logout(request):
    logout(request)
    messages.info(request, "You have been logged out successfully.")
    return redirect('book_list')