
from django.shortcuts import render, redirect
from django.contrib.auth.models import User
from django.contrib import messages
from django.db import IntegrityError


def register(request):

    if request.method == "POST":

        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        confirm_password = request.POST.get('confirm_password', '')

        # Check required fields
        if not all([first_name, last_name, username, email,
                    password, confirm_password]):
            messages.error(request, "Please fill in all fields.")
            return render(request, 'register.html')

        # Check whether username already exists
        if User.objects.filter(username=username).exists():
            messages.error(
                request,
                "Username already exists. Please choose another username."
            )
            return render(request, 'register.html')

        # Check whether email already exists
        if User.objects.filter(email=email).exists():
            messages.error(
                request,
                "Email is already registered. Please use another email."
            )
            return render(request, 'register.html')

        # Check password confirmation
        if password != confirm_password:
            messages.error(request, "Passwords do not match.")
            return render(request, 'register.html')

        try:
            User.objects.create_user(
                first_name=first_name,
                last_name=last_name,
                username=username,
                email=email,
                password=password
            )

            messages.success(
                request,
                "Registration successful! Please log in."
            )
            return redirect('login')

        except IntegrityError:
            messages.error(
                request,
                "Registration failed. Please try another username or email."
            )
            return render(request, 'register.html')

    return render(request, 'register.html')
