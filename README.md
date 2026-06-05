# Student Marketplace System

A secure student marketplace web application with user verification and Paystack payment integration.

## Features

- Student account registration with email validation and email verification flow
- Secure password hashing and safe session cookies
- Verified student-only listing creation
- Product browsing and Paystack checkout payment gateway integration
- Order recording with wallet-safe metadata
- Simple admin-style dashboard for buyers and sellers

## Architecture

- `Flask` backend with `Flask-Login` for authentication
- `SQLAlchemy` ORM backed by SQLite for local development
- Email verification using `itsdangerous` signed tokens
- Payment checkout via Paystack
- Templates for pages and simple form-based UI

## Setup

1. Create a Python virtual environment:

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
```

2. Install dependencies:

```powershell
pip install -r requirements.txt
```

3. Set environment variables (replace with your Paystack test keys and SMTP settings):

```powershell
$env:PAYSTACK_SECRET_KEY = "sk_test_..."
$env:PAYSTACK_WEBHOOK_SECRET = "whsec_test_..."
$env:SECRET_KEY = "your-secret-key"
$env:MAIL_SERVER = "smtp.example.com"
$env:MAIL_PORT = "587"
$env:MAIL_USERNAME = "smtp-user"
$env:MAIL_PASSWORD = "smtp-password"
$env:MAIL_USE_TLS = "true"
$env:MAIL_USE_SSL = "false"
$env:SECURITY_EMAIL_SENDER = "no-reply@student-marketplace.local"
```

4. Configure Paystack webhooks:
   - If you want Paystack to notify your app automatically, install ngrok and create a public tunnel to your local app.
   - Run ngrok:
     ```powershell
     ngrok http 5000
     ```
   - Use the generated HTTPS URL and set your webhook URL to:
     ```text
     https://<your-ngrok-id>.ngrok-free.app/paystack/webhook
     ```
   - In the Paystack webhook settings, use the same `PAYSTACK_WEBHOOK_SECRET` value as in your local `.env`.

5. Run the application:

```powershell
python app.py
```

6. Local callback testing (manual checkout only):
   - The app already uses Paystack's callback redirect to `/success`, so you can test checkout locally without a public webhook URL.
   - In this case, complete the Paystack payment in your browser and verify that you are redirected back to:
     ```text
     http://127.0.0.1:5000/success?reference=<reference>
     ```

Alternatively, create a `.env` file in the project root with the same keys, and the app will load them automatically.

```powershell
python app.py
```

5. Register a student account and follow the verification link printed to the console.

## Notes

- For production, replace console-based email output with a real email provider.
- Use HTTPS and secure cookie settings for deployment.
- Replace SQLite with PostgreSQL or MySQL for a production-ready database.
