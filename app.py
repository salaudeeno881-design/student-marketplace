import json
import hmac
import hashlib
import os
import smtplib
import urllib.error
import urllib.request
from datetime import datetime
from email.message import EmailMessage
from urllib.parse import urljoin

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None
from flask import (Flask, flash, redirect, render_template, request, session,
                   url_for, abort)
from flask_login import (LoginManager, UserMixin, current_user, login_required,
                         login_user, logout_user)
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect, generate_csrf
from itsdangerous import URLSafeTimedSerializer
from sqlalchemy import text
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from models import ChatMessage, Listing, Order, User, db

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
if load_dotenv is not None:
    load_dotenv(os.path.join(BASE_DIR, ".env"))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp"}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this-secret")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL",
    f"sqlite:///{os.path.join(BASE_DIR, 'marketplace.db')}"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["PAYSTACK_SECRET_KEY"] = os.environ.get("PAYSTACK_SECRET_KEY", "sk_test_1234567890")
app.config["PAYSTACK_WEBHOOK_SECRET"] = os.environ.get("PAYSTACK_WEBHOOK_SECRET", "whsec_test_1234567890")
app.config["SECURITY_EMAIL_SENDER"] = os.environ.get("SECURITY_EMAIL_SENDER", "no-reply@student-marketplace.local")
app.config["MAIL_SERVER"] = os.environ.get("MAIL_SERVER")
app.config["MAIL_PORT"] = int(os.environ.get("MAIL_PORT", 587))
app.config["MAIL_USERNAME"] = os.environ.get("MAIL_USERNAME")
app.config["MAIL_PASSWORD"] = os.environ.get("MAIL_PASSWORD")
app.config["MAIL_USE_TLS"] = os.environ.get("MAIL_USE_TLS", "true").lower() in ["1", "true", "yes"]
app.config["MAIL_USE_SSL"] = os.environ.get("MAIL_USE_SSL", "false").lower() in ["1", "true", "yes"]

csrf = CSRFProtect(app)
db.init_app(app)

@app.context_processor
def inject_csrf_token():
    return dict(csrf_token=generate_csrf)

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message_category = "warning"

serializer = URLSafeTimedSerializer(app.config["SECRET_KEY"])


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# Flask 3 no longer supports before_first_request; create tables and migrate schema at startup instead.
with app.app_context():
    db.create_all()
    engine = db.engine
    with engine.connect() as connection:
        result = connection.execute(text("PRAGMA table_info(users)"))
        user_columns = [row[1] for row in result]
        if "department" not in user_columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN department TEXT"))
        if "matric_number" not in user_columns:
            connection.execute(text("ALTER TABLE users ADD COLUMN matric_number TEXT"))

        result = connection.execute(text("PRAGMA table_info(listings)"))
        listing_columns = [row[1] for row in result]
        if "image_filename" not in listing_columns:
            connection.execute(text("ALTER TABLE listings ADD COLUMN image_filename TEXT"))
        if "listing_type" not in listing_columns:
            connection.execute(text("ALTER TABLE listings ADD COLUMN listing_type TEXT NOT NULL DEFAULT 'sell'"))


def send_email(subject: str, recipient: str, body: str) -> bool:
    sender = app.config["SECURITY_EMAIL_SENDER"]
    smtp_server = app.config.get("MAIL_SERVER")
    port = app.config.get("MAIL_PORT")
    username = app.config.get("MAIL_USERNAME")
    password = app.config.get("MAIL_PASSWORD")
    use_tls = app.config.get("MAIL_USE_TLS")
    use_ssl = app.config.get("MAIL_USE_SSL")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.set_content(body)

    if not smtp_server:
        print("No SMTP server configured. Falling back to console output.")
        print(body)
        return False

    try:
        if use_ssl:
            server = smtplib.SMTP_SSL(smtp_server, port, timeout=10)
        else:
            server = smtplib.SMTP(smtp_server, port, timeout=10)
            if use_tls:
                server.starttls()

        if username and password:
            server.login(username, password)

        server.send_message(msg)
        server.quit()
        return True
    except Exception as exc:
        print("Failed to send verification email:", exc)
        print(body)
        return False


def send_verification_email(user):
    token = serializer.dumps(user.email, salt="email-confirm")
    confirm_url = url_for("confirm_email", token=token, _external=True)
    subject = "Confirm your student marketplace account"
    body = (
        f"Hello {user.name},\n\n"
        "Please confirm your account by visiting the link below:\n\n"
        f"{confirm_url}\n\n"
        "If you did not sign up, please ignore this message.\n"
    )
    was_sent = send_email(subject, user.email, body)
    if not was_sent:
        flash("Verification email could not be delivered automatically. The link is displayed below.", "warning")
    return confirm_url


def build_student_email_checker(email: str) -> bool:
    lower = email.lower()
    return lower.endswith(".edu") or lower.endswith("@student.university") or lower.endswith("@campus.edu")


def is_safe_url(target):
    ref_url = urljoin(request.host_url, "/")
    test_url = urljoin(request.host_url, target)
    return test_url.startswith(ref_url)


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_listing_image(file_obj, listing_id):
    if not file_obj or file_obj.filename == "":
        return None
    
    if not allowed_file(file_obj.filename):
        flash("Only image files (jpg, png, gif, webp) are allowed.", "danger")
        return None
    
    if len(file_obj.read()) > MAX_FILE_SIZE:
        file_obj.seek(0)
        flash("Image file is too large (max 5MB).", "danger")
        return None
    
    file_obj.seek(0)
    ext = file_obj.filename.rsplit(".", 1)[1].lower()
    filename = f"listing_{listing_id}.{ext}"
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file_obj.save(filepath)
    return filename


@app.route("/")
def index():
    listings = Listing.query.order_by(Listing.created_at.desc()).limit(20).all()
    return render_template("index.html", listings=listings)


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        department = request.form.get("department", "").strip()
        matric_number = request.form.get("matric_number", "").strip()

        if not name or not email or not password or not department or not matric_number:
            flash("All fields are required.", "danger")
            return render_template("register.html")

        if not build_student_email_checker(email):
            flash("Please register with a valid student email address.", "danger")
            return render_template("register.html")

        if User.query.filter_by(email=email).first():
            flash("Email is already registered.", "warning")
            return render_template("register.html")

        user = User(
            name=name,
            email=email,
            password_hash=generate_password_hash(password),
            student_id=matric_number,
            department=department,
            matric_number=matric_number,
            is_verified=False,
            verification_requested_at=datetime.utcnow(),
        )
        db.session.add(user)
        db.session.commit()

        confirm_url = send_verification_email(user)
        flash("Account created. Check the console log for the verification link.", "success")
        return render_template("verify.html", confirm_url=confirm_url)

    return render_template("register.html")


@app.route("/confirm/<token>")
def confirm_email(token):
    try:
        email = serializer.loads(token, salt="email-confirm", max_age=3600)
    except Exception:
        flash("Verification link is invalid or has expired.", "danger")
        return redirect(url_for("index"))

    user = User.query.filter_by(email=email).first()
    if not user:
        flash("Account not found.", "danger")
        return redirect(url_for("register"))

    if user.is_verified:
        flash("Your account is already verified.", "info")
    else:
        user.is_verified = True
        user.verified_at = datetime.utcnow()
        db.session.commit()
        flash("Email verified! You can now log in.", "success")

    return redirect(url_for("login"))


@app.route("/chat", methods=["GET", "POST"])
def chat():
    if request.method == "POST":
        if not current_user.is_authenticated:
            flash("Please log in to post in the student chat.", "warning")
            return redirect(url_for("login"))

        content = request.form.get("message", "").strip()
        if not content:
            flash("Please enter a message before sending.", "danger")
        else:
            chat_message = ChatMessage(user_id=current_user.id, content=content)
            db.session.add(chat_message)
            db.session.commit()
            return redirect(url_for("chat"))

    messages = ChatMessage.query.order_by(ChatMessage.created_at.asc()).limit(50).all()
    return render_template("chat.html", messages=messages)


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()

        if not user or not check_password_hash(user.password_hash, password):
            flash("Invalid credentials.", "danger")
            return render_template("login.html")

        if not user.is_verified:
            flash("Please verify your email before signing in.", "warning")
            return redirect(url_for("register"))

        login_user(user)
        flash("Signed in successfully.", "success")

        next_page = request.args.get("next")
        if next_page and is_safe_url(next_page):
            return redirect(next_page)
        return redirect(url_for("index"))

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("index"))


@app.route("/dashboard")
@login_required
def dashboard():
    listings = Listing.query.filter_by(owner_id=current_user.id).order_by(Listing.created_at.desc()).all()
    orders = Order.query.filter_by(buyer_id=current_user.id).order_by(Order.created_at.desc()).all()
    return render_template("dashboard.html", listings=listings, orders=orders)


@app.route("/listings/new", methods=["GET", "POST"])
@login_required
def create_listing():
    if not current_user.is_verified:
        flash("Your account must be verified before creating listings.", "warning")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        price = request.form.get("price", "").strip()
        listing_type = request.form.get("listing_type", "sell")
        image_file = request.files.get("image")

        if not title or not description or not price or not listing_type:
            flash("Title, description, price, and type are required.", "danger")
            return render_template("create_listing.html")

        try:
            amount = float(price)
            if amount <= 0:
                raise ValueError
        except ValueError:
            flash("Enter a valid price.", "danger")
            return render_template("create_listing.html")

        listing = Listing(
            owner=current_user,
            title=title,
            description=description,
            price=amount,
            listing_type=listing_type,
            created_at=datetime.utcnow(),
        )
        db.session.add(listing)
        db.session.commit()

        # Save image if provided
        if image_file and image_file.filename != "":
            image_filename = save_listing_image(image_file, listing.id)
            if image_filename:
                listing.image_filename = image_filename
                db.session.commit()

        flash("Listing published successfully.", "success")
        return redirect(url_for("dashboard"))

    return render_template("create_listing.html")


@app.route("/listing/<int:listing_id>")
def listing_detail(listing_id):
    listing = Listing.query.get_or_404(listing_id)
    return render_template("listing.html", listing=listing)


@app.route("/listings/<int:listing_id>/delete", methods=["POST"])
@login_required
def delete_listing(listing_id):
    listing = Listing.query.get_or_404(listing_id)
    if listing.owner_id != current_user.id:
        abort(403)

    Order.query.filter_by(listing_id=listing.id).delete()
    db.session.delete(listing)
    db.session.commit()

    flash("Listing deleted successfully.", "success")
    return redirect(url_for("dashboard"))


@app.route("/requests")
def requests_feed():
    wanted_posts = Listing.query.filter_by(listing_type="buy").order_by(Listing.created_at.desc()).all()
    sell_posts = Listing.query.filter_by(listing_type="sell").order_by(Listing.created_at.desc()).all()
    return render_template("requests.html", wanted_posts=wanted_posts, sell_posts=sell_posts)


@app.route("/checkout/<int:listing_id>", methods=["POST"])
@login_required
def checkout(listing_id):
    listing = Listing.query.get_or_404(listing_id)
    if listing.owner_id == current_user.id:
        flash("You cannot purchase your own listing.", "warning")
        return redirect(url_for("listing_detail", listing_id=listing.id))

    if not current_user.is_verified:
        flash("Verify your account before making purchases.", "warning")
        return redirect(url_for("dashboard"))

    if not app.config["PAYSTACK_SECRET_KEY"] or app.config["PAYSTACK_SECRET_KEY"] == "sk_test_1234567890":
        flash("Paystack is not configured. Please set PAYSTACK_SECRET_KEY to enable payments.", "danger")
        return redirect(url_for("listing_detail", listing_id=listing.id))

    paystack_url = "https://api.paystack.co/transaction/initialize"
    payload = {
        "email": current_user.email,
        "amount": int(listing.price * 100),
        "callback_url": url_for("payment_success", _external=True),
        "metadata": {
            "listing_id": str(listing.id),
            "buyer_id": str(current_user.id),
        },
    }
    request_data = json.dumps(payload).encode("utf-8")

    request_headers = {
        "Authorization": f"Bearer {app.config.get('PAYSTACK_SECRET_KEY')}",
        "Content-Type": "application/json",
    }

    # Debug log path
    debug_log = os.path.join(BASE_DIR, "paystack_debug.log")
    try:
        with open(debug_log, "a", encoding="utf-8") as lf:
            lf.write(f"\n--- {datetime.utcnow().isoformat()} CHECKOUT INIT for listing {listing.id} user {current_user.id}\n")
            lf.write("Request headers:\n")
            lf.write(json.dumps(request_headers) + "\n")
            lf.write("Request payload:\n")
            try:
                lf.write(request_data.decode("utf-8") + "\n")
            except Exception:
                lf.write(str(request_data) + "\n")
    except Exception:
        pass

    req = urllib.request.Request(paystack_url, data=request_data, headers=request_headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp_body = resp.read().decode("utf-8", errors="ignore")
            try:
                response_data = json.loads(resp_body)
            except Exception:
                response_data = {"raw": resp_body}

            try:
                with open(debug_log, "a", encoding="utf-8") as lf:
                    lf.write("Response status: %s\n" % getattr(resp, "status", "N/A"))
                    lf.write("Response body:\n")
                    lf.write(resp_body + "\n")
            except Exception:
                pass

    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        try:
            with open(debug_log, "a", encoding="utf-8") as lf:
                lf.write("HTTPError code: %s\n" % exc.code)
                lf.write("Error body:\n")
                lf.write(body + "\n")
        except Exception:
            pass
        flash(f"Unable to start payment checkout: {body}", "danger")
        return redirect(url_for("listing_detail", listing_id=listing.id))
    except Exception as exc:
        try:
            with open(debug_log, "a", encoding="utf-8") as lf:
                lf.write("Exception: %s\n" % str(exc))
        except Exception:
            pass
        flash(f"Payment gateway error: {exc}", "danger")
        return redirect(url_for("listing_detail", listing_id=listing.id))

    if not response_data.get("status") or not response_data.get("data", {}).get("authorization_url"):
        message = response_data.get("message", "Unable to initialize payment.")
        flash(f"Unable to start payment checkout: {message}", "danger")
        return redirect(url_for("listing_detail", listing_id=listing.id))

    return redirect(response_data["data"]["authorization_url"], code=303)


@app.route("/paystack/webhook", methods=["POST"])
@csrf.exempt
def paystack_webhook():
    body = request.get_data()
    signature = request.headers.get("x-paystack-signature", "")

    # Compute expected signature if webhook secret exists
    webhook_secret = app.config.get("PAYSTACK_WEBHOOK_SECRET") or ""
    expected_signature = ""
    if webhook_secret and webhook_secret != "whsec_test_1234567890":
        expected_signature = hmac.new(
            webhook_secret.encode("utf-8"),
            body,
            hashlib.sha512,
        ).hexdigest()

    try:
        webhook_payload = json.loads(body.decode("utf-8"))
    except Exception:
        return "Invalid payload", 400

    event = webhook_payload.get("event")
    data = webhook_payload.get("data", {})

    # Helper: verify a reference directly with Paystack (fallback if signature not available)
    def verify_reference(reference: str):
        if not reference:
            return None
        paystack_url = f"https://api.paystack.co/transaction/verify/{reference}"
        req = urllib.request.Request(
            paystack_url,
            headers={
                "Authorization": f"Bearer {app.config.get('PAYSTACK_SECRET_KEY')}",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.load(resp)
        except Exception:
            return None

    signature_ok = False
    if expected_signature:
        try:
            signature_ok = hmac.compare_digest(signature, expected_signature)
        except Exception:
            signature_ok = False

    # If signature not OK, attempt to validate the event by verifying the transaction reference
    if not signature_ok:
        reference = data.get("reference") or (webhook_payload.get("data") or {}).get("reference")
        if not reference:
            return "Invalid signature", 400

        ver = verify_reference(reference)
        if not ver or not ver.get("status") or ver.get("data", {}).get("status") != "success":
            return "Unverified", 400

        # replace data with verified data from Paystack
        data = ver.get("data", {})

    # Process successful charge events
    if event == "charge.success" and data.get("status") == "success":
        reference = data.get("reference")
        metadata = data.get("metadata", {})
        try:
            listing_id = int(metadata.get("listing_id", 0))
            buyer_id = int(metadata.get("buyer_id", 0))
        except Exception:
            listing_id = 0
            buyer_id = 0

        if reference and not Order.query.filter_by(stripe_session_id=reference).first():
            listing = Listing.query.get(listing_id)
            buyer = User.query.get(buyer_id)
            if listing and buyer:
                order = Order(
                    listing=listing,
                    buyer=buyer,
                    seller=listing.owner,
                    amount=listing.price,
                    stripe_session_id=reference,
                    created_at=datetime.utcnow(),
                )
                db.session.add(order)
                db.session.commit()

    return "", 200


@app.route("/success")
@login_required
def payment_success():
    reference = request.args.get("reference")
    if not reference:
        flash("Missing checkout reference.", "danger")
        return redirect(url_for("index"))

    paystack_url = f"https://api.paystack.co/transaction/verify/{reference}"
    req = urllib.request.Request(
        paystack_url,
        headers={
            "Authorization": f"Bearer {app.config['PAYSTACK_SECRET_KEY']}",
        },
        method="GET",
    )

    try:
        with urllib.request.urlopen(req) as response:
            response_data = json.load(response)
    except urllib.error.HTTPError as exc:
        error_message = exc.read().decode("utf-8", errors="ignore")
        flash(f"Unable to verify payment: {error_message}", "danger")
        return redirect(url_for("index"))
    except Exception as exc:
        flash(f"Payment verification failed: {exc}", "danger")
        return redirect(url_for("index"))

    if not response_data.get("status") or response_data.get("data", {}).get("status") != "success":
        flash("Payment was not completed.", "danger")
        return redirect(url_for("index"))

    data = response_data["data"]
    metadata = data.get("metadata", {})
    listing_id = int(metadata.get("listing_id", 0))
    buyer_id = int(metadata.get("buyer_id", 0))
    listing = Listing.query.get(listing_id)
    buyer = User.query.get(buyer_id)

    if not listing or not buyer or buyer.id != current_user.id:
        flash("Cannot confirm payment for this order.", "danger")
        return redirect(url_for("index"))

    existing_order = Order.query.filter_by(stripe_session_id=reference).first()
    if existing_order:
        flash("Order already confirmed.", "info")
        return redirect(url_for("dashboard"))

    order = Order(
        listing=listing,
        buyer=current_user,
        seller=listing.owner,
        amount=listing.price,
        stripe_session_id=reference,
        created_at=datetime.utcnow(),
    )
    db.session.add(order)
    db.session.commit()

    flash("Payment successful! Order recorded.", "success")
    return render_template("success.html", listing=listing)


@app.errorhandler(404)
def page_not_found(error):
    return render_template("404.html"), 404


@app.route("/admin/paystack", methods=["GET", "POST"])
@login_required
def admin_paystack():
    # Non-production admin page to inspect loaded Paystack config and test verification
    paystack_key = app.config.get("PAYSTACK_SECRET_KEY")
    webhook_secret = app.config.get("PAYSTACK_WEBHOOK_SECRET")

    masked_key = None
    if paystack_key:
        if len(paystack_key) > 8:
            masked_key = paystack_key[:6] + "..." + paystack_key[-4:]
        else:
            masked_key = paystack_key

    masked_webhook = None
    if webhook_secret:
        if len(webhook_secret) > 8:
            masked_webhook = webhook_secret[:6] + "..." + webhook_secret[-4:]
        else:
            masked_webhook = webhook_secret

    verify_result = None
    if request.method == "POST":
        reference = request.form.get("reference", "").strip()
        if reference:
            paystack_url = f"https://api.paystack.co/transaction/verify/{reference}"
            req = urllib.request.Request(
                paystack_url,
                headers={"Authorization": f"Bearer {app.config.get('PAYSTACK_SECRET_KEY')}"},
                method="GET",
            )
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    verify_result = json.load(resp)
            except Exception as exc:
                verify_result = {"error": str(exc)}

    return render_template(
        "admin_paystack.html",
        paystack_key_masked=masked_key,
        webhook_masked=masked_webhook,
        verify_result=verify_result,
    )

if __name__ == "__main__":
    app.run(debug=True)
