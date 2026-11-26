# 📚 Library Management System

A web-based Library Management System developed using **Python, Django, HTML, CSS, and JavaScript**. This project provides book management, user authentication, shopping cart, checkout, online payment, and order management features.

## 🚀 Features

- User Registration and Login
- User Authentication
- Book Listing and Management
- Shopping Cart
- Checkout System
- Cash on Delivery (COD)
- Razorpay Online Payment Integration
- Order History
- Order Cancellation
- Refund Management
- Admin Panel for Managing Library Data

## 🛠️ Technologies Used

- **Backend:** Python, Django
- **Frontend:** HTML, CSS, JavaScript
- **Database:** SQLite
- **Payment Gateway:** Razorpay
- **Tools:** VS Code, Git, GitHub

## 📂 Project Structure

```text
Library-Management-System/
│
├── accounts/
├── library/
├── studentproject/
├── templates/
├── manage.py
├── .env.example
├── .gitignore
└── README.md
```

## ⚙️ Installation and Setup

### 1. Clone the Repository

```bash
git clone https://github.com/dhruvi-bhuva/Library-Management-System.git
```

### 2. Open Project Folder

```bash
cd Library-Management-System
```

### 3. Create Virtual Environment

```bash
python -m venv venv
```

### 4. Activate Virtual Environment

Windows:

```bash
venv\Scripts\activate
```

### 5. Install Dependencies

```bash
pip install django
```

Install any additional packages required by the project and configure the environment variables using `.env.example`.

### 6. Apply Migrations

```bash
python manage.py makemigrations
python manage.py migrate
```

### 7. Create Superuser

```bash
python manage.py createsuperuser
```

### 8. Run the Development Server

```bash
python manage.py runserver
```


## 💳 Payment Integration

This project includes Razorpay online payment integration and Cash on Delivery functionality.

Razorpay test credentials and environment variables must be configured before testing online payments.

## 🎯 Project Objective

The main objective of this project is to provide an easy-to-use web application for managing books, user accounts, shopping cart operations, payments, and orders through a centralized system.

## 👩‍💻 Developer

**Dhruvi Bhuva**

GitHub: https://github.com/dhruvi-bhuva

---

