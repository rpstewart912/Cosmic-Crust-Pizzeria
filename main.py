import logging
import random
import json # Added for parsing order data
from datetime import datetime, timedelta
from functools import wraps # Added for decorator

# Make sure all necessary Flask components are imported
from flask import Flask, render_template, request, redirect, url_for, jsonify, session, flash, g
from google.cloud import firestore
from werkzeug.security import generate_password_hash, check_password_hash
# Optional: If converting timezone for display
# import pytz

app = Flask(__name__)
# IMPORTANT: Replace with a strong, environment-variable-based secret key in production
app.secret_key = "your_secret_key_replace_me" # <-- CHANGE THIS!
# Initialize Firestore client - ensure your environment is authenticated
# Consider removing hardcoded database name in production if using default
db = firestore.Client(database="ccpnosql01")

# Configure logging
logging.basicConfig(level=logging.INFO) # Log INFO level messages and above

# ────────────────────────────────────────────────────────────
# Helper Functions
# ────────────────────────────────────────────────────────────

def user_exists(username: str, email: str) -> bool:
    """Return True if that username OR email is already in Firestore."""
    users_ref = db.collection("users")
    try:
        # Check for existing username (case-sensitive)
        username_query = users_ref.where("username", "==", username).limit(1).stream()
        if next(username_query, None):
            logging.info(f"Username '{username}' already exists.")
            return True
        # Check for existing email (case-sensitive)
        email_query = users_ref.where("email", "==", email).limit(1).stream()
        if next(email_query, None):
            logging.info(f"Email '{email}' already exists.")
            return True
    except Exception as e:
        logging.error(f"Error checking user existence for {username}/{email}: {e}")
        # Decide how to handle DB errors during check - maybe treat as exists?
        # For now, assume not exists on error
    return False


def is_logged_in():
    """Checks if a user ID exists in the session."""
    return 'user_id' in session

def generate_order_id():
    """Generates a random 6-digit order ID prefixed with #."""
    return f"#{random.randint(100000, 999999)}"

def get_order_status(order_stage):
    """Returns the order status string based on the stage number."""
    statuses = [
        "Order Received", # Stage 0
        "Preparing",      # Stage 1
        "Baking",         # Stage 2
        "Quality Check",  # Stage 3
        "On Route",       # Stage 4
        "Delivered"       # Stage 5
    ]
    if not isinstance(order_stage, int) or order_stage < 0:
        order_stage = 0 # Default to first stage if invalid
    return statuses[min(order_stage, len(statuses) - 1)]


def get_ready_by_time():
    """Calculates an estimated ready time (e.g., 45 minutes from now)."""
    now = datetime.now()
    ready_by = now + timedelta(minutes=45)
    # Consider using a timezone-aware calculation if needed
    return ready_by.strftime("%I:%M %p") # Format as HH:MM AM/PM

def get_order_time():
    """Gets the current time formatted for display."""
    now = datetime.now()
    # Consider using a timezone-aware calculation if needed
    return now.strftime("%Y-%m-%d %I:%M %p") # Format as YYYY-MM-DD HH:MM AM/PM

# --- Helper to parse sizes from form (NEW) ---
def parse_sizes_from_form(request_form):
    """Parses size names and prices from form fields like size_name_0, size_price_0."""
    sizes = {}
    i = 0
    while True:
        size_name_key = f'size_name_{i}'
        size_price_key = f'size_price_{i}'
        if size_name_key in request_form and size_price_key in request_form:
            name = request_form[size_name_key].strip()
            price_str = request_form[size_price_key].strip()
            if name and price_str: # Only process if both name and price are provided
                try:
                    # Attempt to convert price to float
                    price = float(price_str)
                    if price < 0: # Basic validation for non-negative price
                         flash(f"Price for size '{name}' cannot be negative.", "error")
                         # Skip this size if price is negative
                    else:
                         sizes[name] = price
                except ValueError:
                    # Handle cases where price is not a valid number
                    flash(f"Invalid price format for size '{name}'. Please enter a number.", "error")
                    # Skip this size entry if price format is invalid
                    logging.warning(f"Invalid price format '{price_str}' for size '{name}' submitted.")
            elif name or price_str: # Warn if only one of name/price is provided
                 logging.warning(f"Incomplete size entry found at index {i}. Both name and price are required.")

            i += 1
        else:
            break # Stop when no more sequential size fields are found
    return sizes

# ────────────────────────────────────────────────────────────
# Decorators
# ────────────────────────────────────────────────────────────

# --- Staff Check Decorator (NEW) ---
def staff_required(f):
    """
    Decorator to ensure the user is logged in and has 'staff' privileges.
    Redirects to login or index page if conditions are not met.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_id = session.get('user_id')
        if not user_id:
            flash("Please log in to access this page.", "error")
            return redirect(url_for('account', next=request.url)) # Redirect to login, preserving next URL

        # Check staff status stored in session first (set during login)
        if session.get('is_staff') is True:
             return f(*args, **kwargs) # Proceed if session indicates staff

        # If not in session (e.g., session expired, direct access attempt), verify from DB
        user_ref = db.collection("users").document(user_id)
        try:
            user_doc = user_ref.get()
            if not user_doc.exists:
                flash("User not found. Please log in again.", "error")
                session.clear() # Clear invalid session
                return redirect(url_for('account'))

            user_data = user_doc.to_dict()
            # Check if 'staff' field exists and is explicitly True
            is_staff_db = user_data.get('staff') is True
            session['is_staff'] = is_staff_db # Update session status

            if not is_staff_db:
                flash("You do not have permission to access this page.", "error")
                return redirect(url_for('index')) # Redirect non-staff users to homepage

            # Optional: Store user data in g for easier access in the route if needed
            # g.user = user_data
            return f(*args, **kwargs) # Proceed to the original route function

        except Exception as e:
            logging.error(f"Error checking staff status for user {user_id}: {e}")
            flash("An error occurred while verifying your permissions.", "error")
            return redirect(url_for('index')) # Redirect on error

    return decorated_function


# ────────────────────────────────────────────────────────────
# Public Pages
# ────────────────────────────────────────────────────────────
@app.route("/")
def index():
    """Renders the homepage."""
    # Pass staff status to the template
    return render_template("index.html",
                           logged_in=is_logged_in(),
                           is_staff=session.get('is_staff', False))

@app.route("/menu")
def menu():
    """Fetches menu items from Firestore and renders the menu page."""
    try:
        docs = db.collection("menuItems").order_by("category").order_by("name").stream() # Order for consistency
        items = []
        for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id # Add document ID to the data

            # Normalize 'dietary' field to always be a list of strings
            dietary_raw = data.get("dietary")
            cleaned_dietary = []
            if isinstance(dietary_raw, list):
                for d in dietary_raw:
                    if isinstance(d, str) and d.strip():
                        cleaned_dietary.append(d.strip())
                    elif d is not None:
                         logging.warning(f"Unexpected type '{type(d)}' found in dietary list for item {data['id']}: {d}")
            elif isinstance(dietary_raw, str) and dietary_raw.strip():
                cleaned_dietary.extend([d_item.strip() for d_item in dietary_raw.split(',') if d_item.strip()])
            data["dietary"] = list(dict.fromkeys(cleaned_dietary))

            # Normalize 'sizes' field
            if not isinstance(data.get("sizes"), dict):
                 data["sizes"] = {}

            # Ensure base price exists and is float for non-pizza or pizza without sizes
            if data.get("category") != 'pizza' or not data.get("sizes"):
                 try:
                     data["price"] = float(data.get("price", 0.0))
                 except (ValueError, TypeError):
                     logging.warning(f"Invalid base price format for item {data['id']}. Setting to 0.0.")
                     data["price"] = 0.0
            else:
                 data["price"] = None # Ensure price is None for pizzas with sizes

            items.append(data)
    except Exception as e:
        logging.error(f"Error fetching menu items from Firestore: {e}")
        flash("Could not load menu items. Please try again later.", "error")
        items = [] # Return empty list on error

    # Pass staff status to the template
    return render_template("menu.html",
                           menu_items=items,
                           logged_in=is_logged_in(),
                           is_staff=session.get('is_staff', False))


@app.route("/custom_pizza")
def customize_pizza():
    """Renders the custom pizza builder page."""
    # Pass staff status to the template
    return render_template("custom_pizza.html",
                           logged_in=is_logged_in(),
                           is_staff=session.get('is_staff', False))


@app.route("/order")
def order():
    """Renders the order summary/cart page."""
    # Pass staff status to the template
    return render_template("order.html",
                           logged_in=is_logged_in(),
                           is_staff=session.get('is_staff', False))


# ────────────────────────────────────────────────────────────
# Checkout
# ────────────────────────────────────────────────────────────
@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    """
    GET -> Shows the checkout form.
    POST -> Processes the order and saves to Firestore.
    """
    if request.method == "POST":
        # 1. Get Order Data from the hidden input
        order_data_json = request.form.get('order_data')
        order_items = []
        order_total = 0.0

        if not order_data_json:
            flash("No order data received. Your cart might be empty.", "error")
            return redirect(url_for('order'))

        try:
            cart_items = json.loads(order_data_json)
            if not isinstance(cart_items, list):
                 raise ValueError("Order data is not in the expected format (list).")

            for item in cart_items:
                 if not isinstance(item, dict):
                     logging.warning(f"Skipping invalid item in cart data: {item}")
                     continue
                 try:
                     item_price = float(item.get('price', 0))
                     item_quantity = int(item.get('quantity', 1))
                 except (ValueError, TypeError):
                      logging.warning(f"Skipping item with invalid price/quantity format: {item}")
                      continue
                 if item_price < 0 or item_quantity <= 0:
                      logging.warning(f"Skipping item with invalid price/quantity values: {item}")
                      continue

                 order_total += item_price * item_quantity
                 order_items.append({
                     'id': item.get('id'),
                     'cartId': item.get('cartId'),
                     'baseId': item.get('baseId'),
                     'name': item.get('name', 'Unknown Item'),
                     'quantity': item_quantity,
                     'price': item_price,
                     'selectedSize': item.get('selectedSize'),
                     'customizations': item.get('customizations', {})
                 })

        except (json.JSONDecodeError, TypeError, ValueError) as e:
            logging.error(f"Error decoding/processing order_data JSON: {e}")
            flash("There was an error processing your order items. Please check your cart and try again.", "error")
            return redirect(url_for('order'))

        if not order_items:
             flash("Your cart appears to be empty or contains invalid items.", "error")
             return redirect(url_for('order'))

        order_id = generate_order_id()
        order_doc = {
            'orderId': order_id,
            'userId': session.get('user_id'),
            'orderItems': order_items,
            'orderTotal': round(order_total, 2),
            'status': "Order Received",
            'orderStage': 0,
            'orderTime': firestore.SERVER_TIMESTAMP,
            'customerName': request.form.get('name_on_card', '').strip(),
            'billingAddress': {
                'addr1': request.form.get('addr1', '').strip(),
                'addr2': request.form.get('addr2', '').strip(),
                'city': request.form.get('city', '').strip(),
                'state': request.form.get('state', '').strip(),
                'zip': request.form.get('zip', '').strip(),
                'country': request.form.get('country', '').strip(),
            },
            'readyByTime': get_ready_by_time()
        }

        try:
            db.collection("orders").document(order_id).set(order_doc)
            logging.info(f"Order {order_id} successfully saved to Firestore.")
            flash("Payment successful! Your order is being processed.", "success")
            return redirect(url_for('order_tracking', order_id=order_id))

        except Exception as e:
            logging.error(f"Firestore save error for order {order_id}: {e}")
            flash(f"Failed to save your order due to a server error. Please contact support.", "error")
            # Pass staff status when re-rendering checkout on error
            return render_template("checkout.html",
                                   logged_in=is_logged_in(),
                                   is_staff=session.get('is_staff', False))

    # --- GET request ---
    # Pass staff status when showing the checkout form
    return render_template("checkout.html",
                           logged_in=is_logged_in(),
                           is_staff=session.get('is_staff', False))


# ────────────────────────────────────────────────────────────
# Account / Auth
# ────────────────────────────────────────────────────────────
@app.route("/account", methods=["GET", "POST"])
def account():
    """
    GET -> Shows login or register form based on query param.
    POST -> Handles login or registration attempt.
    """
    form_type = request.args.get("form", "login") # Default to login form
    form_data = None # Initialize form_data

    if request.method == "POST":
        action = request.form.get("action")
        if action == "login":
            return login_user() # Handles redirects/rendering
        elif action == "register":
            return register_user() # Handles redirects/rendering
        else:
            flash("Invalid form action.", "error")
            # Pass staff status on redirect
            return redirect(url_for('account',
                                    form=form_type, # Keep current form type on redirect
                                    logged_in=is_logged_in(),
                                    is_staff=session.get('is_staff', False)))

    # GET request: Render the account page
    # Pass staff status to the template
    return render_template("account.html",
                           form_type=form_type,
                           form_data=form_data,
                           logged_in=is_logged_in(),
                           is_staff=session.get('is_staff', False))

def login_user():
    """Handles the user login attempt."""
    email = request.form.get("email")
    password = request.form.get("password")

    if not email or not password:
        flash("Email and password are required.", "error")
        # Pass staff status on redirect
        return redirect(url_for('account', form='login'))

    try:
        users_ref = db.collection("users")
        query = users_ref.where("email", "==", email).limit(1)
        results = list(query.stream())

        if not results:
            flash("Invalid email or password.", "error")
            # Pass staff status on redirect
            return redirect(url_for('account', form='login'))

        user_doc = results[0]
        user_data = user_doc.to_dict()

        if check_password_hash(user_data.get("password_hash", ""), password):
            session["user_id"] = user_doc.id
            session["user_name"] = user_data.get("first_name", user_data.get("username"))
            # Set staff status in session
            session["is_staff"] = user_data.get('staff') is True
            flash(f"Welcome back, {session['user_name']}!", "success")

            next_url = request.args.get('next')
            # Validate next_url here if needed to prevent open redirect vulnerabilities
            if next_url:
                 return redirect(next_url)
            else:
                 return redirect(url_for("account_dashboard"))
        else:
            flash("Invalid email or password.", "error")
            # Pass staff status on redirect
            return redirect(url_for('account', form='login'))

    except Exception as e:
        logging.error(f"Login error for email {email}: {e}")
        flash(f"An error occurred during login. Please try again.", "error")
        # Pass staff status on redirect
        return redirect(url_for('account', form='login'))


def _sanitised_form_data(form_request):
    """Returns a copy of request.form with password fields removed."""
    data = form_request.to_dict(flat=True)
    data.pop("password", None)
    data.pop("confirm_password", None)
    return data


def register_user():
    """Handles the user registration attempt."""
    req = request.form
    username = req.get("username", "").strip()
    email = req.get("email", "").strip()
    password = req.get("password")
    confirm = req.get("confirm_password")
    first_name = req.get("first_name", "").strip()
    last_name = req.get("last_name", "").strip()
    address = req.get("address", "").strip()
    phone_number = req.get("phone_number", "").strip()

    errors = []
    if not all([username, email, password, confirm, first_name, last_name, address, phone_number]):
        errors.append("All fields are required.")
    if password != confirm:
        errors.append("Passwords do not match.")
    # Add more validation (e.g., password length, email format)
    if len(password) < 8: # Example: min length
         errors.append("Password must be at least 8 characters long.")

    if errors:
        for error in errors:
            flash(error, "error")
        # Pass staff status when re-rendering form on error
        return render_template("account.html",
                               form_type="register",
                               form_data=_sanitised_form_data(req),
                               logged_in=is_logged_in(),
                               is_staff=session.get('is_staff', False))

    if user_exists(username, email):
        flash("Username or email already exists. Please choose different ones or login.", "error")
        # Pass staff status when re-rendering form on error
        return render_template("account.html",
                               form_type="register",
                               form_data=_sanitised_form_data(req),
                               logged_in=is_logged_in(),
                               is_staff=session.get('is_staff', False))

    user_doc_data = {
        "username": username,
        "email": email,
        "first_name": first_name,
        "last_name": last_name,
        "address": address,
        "phone_number": phone_number,
        "password_hash": generate_password_hash(password),
        "registration_date": firestore.SERVER_TIMESTAMP,
        "staff": False # Default new users to not be staff
    }
    try:
        _timestamp, user_ref = db.collection("users").add(user_doc_data)
        session["user_id"] = user_ref.id
        session["user_name"] = first_name
        session["is_staff"] = False # Newly registered user is not staff
        flash("Account created successfully! Welcome!", "success")
        return redirect(url_for("account_dashboard"))
    except Exception as e:
        logging.error(f"Registration error for email {email}: {e}")
        flash(f"Registration failed due to a server error. Please try again.", "error")
        # Pass staff status when re-rendering form on error
        return render_template("account.html",
                               form_type="register",
                               form_data=_sanitised_form_data(req),
                               logged_in=is_logged_in(),
                               is_staff=session.get('is_staff', False))


@app.route("/account_dashboard")
def account_dashboard():
    """Displays the user's account dashboard, including order history."""
    if "user_id" not in session:
        flash("Please log in to view your account.", "info")
        return redirect(url_for("account"))

    try:
        user_ref = db.collection("users").document(session["user_id"])
        user_doc = user_ref.get()

        if not user_doc.exists:
            session.clear()
            flash("User not found. Please log in again.", "error")
            return redirect(url_for("account"))

        user_data = user_doc.to_dict()

        orders_ref = db.collection("orders")
        query = orders_ref.where("userId", "==", session["user_id"])\
                          .order_by("orderTime", direction=firestore.Query.DESCENDING)\
                          .limit(10)
        order_history_docs = list(query.stream())
        order_history = []
        for order_doc in order_history_docs:
             order_data_hist = order_doc.to_dict()
             order_data_hist['orderId'] = order_doc.id
             order_time_obj = order_data_hist.get('orderTime')
             if isinstance(order_time_obj, datetime):
                 order_data_hist['order_date_str'] = order_time_obj.strftime("%Y-%m-%d %I:%M %p")
             else:
                 order_data_hist['order_date_str'] = "N/A"
             if not isinstance(order_data_hist.get('orderTotal'), (int, float)):
                 order_data_hist['orderTotal'] = 0.0
             order_history.append(order_data_hist)

        # Pass staff status to the template
        return render_template("account_dashboard.html",
                               user=user_data,
                               orders=order_history,
                               logged_in=is_logged_in(),
                               is_staff=session.get('is_staff', False))

    except Exception as e:
        logging.error(f"Error fetching dashboard data for user {session.get('user_id')}: {e}")
        flash("Could not load account dashboard. Please try again later.", "error")
        return redirect(url_for('index'))


# ────────────────────────────────────────────────────────────
# Profile Management
# ────────────────────────────────────────────────────────────
@app.route("/edit_profile", methods=["GET", "POST"])
def edit_profile():
    """Allows logged-in users to edit their profile information."""
    if "user_id" not in session:
        flash("Please log in to edit your profile.", "info")
        return redirect(url_for("account"))

    user_ref = db.collection("users").document(session["user_id"])
    current_user_data = None # Initialize

    try:
         current_user_doc = user_ref.get()
         if not current_user_doc.exists:
             session.clear()
             flash("User not found. Please log in again.", "error")
             return redirect(url_for('account'))
         current_user_data = current_user_doc.to_dict()
    except Exception as e:
         logging.error(f"Error fetching user {session['user_id']} for profile edit: {e}")
         flash("Could not load profile data.", "error")
         return redirect(url_for('account_dashboard'))


    if request.method == "POST":
        new_username = request.form.get("username", "").strip()
        first_name = request.form.get("first_name", "").strip()
        last_name = request.form.get("last_name", "").strip()
        address = request.form.get("address", "").strip()
        phone_number = request.form.get("phone_number", "").strip()

        if not all([new_username, first_name, last_name, address, phone_number]):
             flash("All profile fields are required.", "error")
             # Pass staff status when re-rendering
             return render_template("edit_profile.html",
                                    user=current_user_data,
                                    logged_in=is_logged_in(),
                                    is_staff=session.get('is_staff', False))

        try:
            original_username = current_user_data.get('username')
            if new_username != original_username:
                 # Check if new username is taken ONLY if it changed
                 existing_user_query = db.collection("users").where("username", "==", new_username).limit(1).stream()
                 if next(existing_user_query, None): # Check if the query returned any documents
                      flash("Username already taken. Please choose another.", "error")
                      # Pass staff status when re-rendering
                      return render_template("edit_profile.html",
                                             user=current_user_data,
                                             logged_in=is_logged_in(),
                                             is_staff=session.get('is_staff', False))

            user_ref.update({
                "first_name": first_name,
                "last_name": last_name,
                "address": address,
                "phone_number": phone_number,
                "username": new_username,
                "profileLastUpdated": firestore.SERVER_TIMESTAMP
            })
            flash("Profile updated successfully!", "success")
            session["user_name"] = first_name # Update session name
            return redirect(url_for("account_dashboard"))

        except Exception as e:
            logging.error(f"Error updating profile for user {session['user_id']}: {e}")
            flash("Failed to update profile due to a server error.", "error")
            # Pass staff status when re-rendering
            return render_template("edit_profile.html",
                                   user=current_user_data,
                                   logged_in=is_logged_in(),
                                   is_staff=session.get('is_staff', False))

    # --- GET request ---
    # Pass staff status when rendering the edit form
    return render_template("edit_profile.html",
                           user=current_user_data,
                           logged_in=is_logged_in(),
                           is_staff=session.get('is_staff', False))


@app.route("/change_password", methods=["GET", "POST"])
def change_password():
    """Allows logged-in users to change their password."""
    if "user_id" not in session:
        flash("Please log in to change your password.", "info")
        return redirect(url_for("account"))

    user_ref = db.collection("users").document(session["user_id"])

    if request.method == "POST":
        current_pw = request.form.get("current_password")
        new_pw = request.form.get("new_password")
        confirm_pw = request.form.get("confirm_password")

        if not all([current_pw, new_pw, confirm_pw]):
            flash("All password fields are required.", "error")
            return redirect(url_for("change_password"))

        if new_pw != confirm_pw:
            flash("New passwords do not match.", "error")
            return redirect(url_for("change_password"))

        if len(new_pw) < 8:
             flash("New password must be at least 8 characters long.", "error")
             return redirect(url_for("change_password"))

        try:
            user_doc = user_ref.get()
            if not user_doc.exists:
                session.clear()
                flash("User not found. Please log in again.", "error")
                return redirect(url_for("account"))

            user_data = user_doc.to_dict()

            if not check_password_hash(user_data.get("password_hash", ""), current_pw):
                flash("Current password is incorrect.", "error")
                return redirect(url_for("change_password"))

            user_ref.update({"password_hash": generate_password_hash(new_pw)})
            flash("Password updated successfully!", "success")
            return redirect(url_for("account_dashboard"))

        except Exception as e:
            logging.error(f"Error changing password for user {session['user_id']}: {e}")
            flash("Failed to change password due to a server error.", "error")
            return redirect(url_for("change_password"))

    # --- GET request ---
    # Pass staff status when rendering the change password form
    return render_template("change_password.html",
                           logged_in=is_logged_in(),
                           is_staff=session.get('is_staff', False))


# ────────────────────────────────────────────────────────────
# Misc Pages
# ────────────────────────────────────────────────────────────
@app.route("/logout")
def logout():
    """Logs the user out by clearing session data."""
    session.clear() # Clear all session data
    flash("You have been logged out.", "success")
    return redirect(url_for("index"))


@app.route("/contact")
def contact():
    """Renders the contact page."""
    # Pass staff status to the template
    return render_template("contact.html",
                           logged_in=is_logged_in(),
                           is_staff=session.get('is_staff', False))


@app.route("/disclaimer")
def disclaimer():
    """Renders the disclaimer page."""
    # Pass staff status to the template
    return render_template("disclaimer.html",
                           logged_in=is_logged_in(),
                           is_staff=session.get('is_staff', False))


@app.route("/privacy")
def privacy():
    """Renders the privacy policy page."""
    # Pass staff status to the template
    return render_template("privacy.html",
                           logged_in=is_logged_in(),
                           is_staff=session.get('is_staff', False))


# ────────────────────────────────────────────────────────────
# Order Tracking
# ────────────────────────────────────────────────────────────
@app.route("/order_tracking/<order_id>")
def order_tracking(order_id):
    """
    Displays tracking information for a specific order fetched from Firestore.
    """
    if not order_id:
         flash("No order ID provided for tracking.", "error")
         return redirect(url_for('index'))

    try:
        order_ref = db.collection('orders').document(order_id)
        order_doc = order_ref.get()

        if order_doc.exists:
            order_data = order_doc.to_dict()
            order_items = order_data.get('orderItems', [])
            order_stage = order_data.get('orderStage', 0)
            status = get_order_status(order_stage)
            order_time_obj = order_data.get('orderTime')
            ready_by_time = order_data.get('readyByTime', "Est. Pending")

            order_time_str = "Not Available"
            if isinstance(order_time_obj, datetime):
                 order_time_str = order_time_obj.strftime("%Y-%m-%d %I:%M %p")
            elif order_time_obj:
                 order_time_str = str(order_time_obj)

            order_total = order_data.get('orderTotal', 0.0)
            if not isinstance(order_total, (int, float)):
                 logging.warning(f"Invalid orderTotal format in DB for order {order_id}. Recalculating.")
                 order_total = sum(
                     float(item.get('price', 0)) * int(item.get('quantity', 1))
                     for item in order_items if isinstance(item, dict)
                 )

            all_statuses = [
                "Order Received", "Preparing", "Baking",
                "Quality Check", "On Route", "Delivered"
            ]

            # Pass staff status to the template
            return render_template('order_tracking.html',
                                   order_id=order_id,
                                   order_items=order_items,
                                   status=status,
                                   order_time=order_time_str,
                                   ready_by_time=ready_by_time,
                                   order_total=round(float(order_total), 2),
                                   status_updates=all_statuses,
                                   current_stage=order_stage,
                                   logged_in=is_logged_in(),
                                   is_staff=session.get('is_staff', False)) # Pass staff status
        else:
            flash(f"Order with ID {order_id} not found.", "error")
            return redirect(url_for('index'))

    except Exception as e:
        logging.error(f"Error fetching order {order_id}: {e}")
        flash("An error occurred while retrieving your order details.", "error")
        return redirect(url_for('index'))


# ────────────────────────────────────────────────────────────
# Admin Routes
# ────────────────────────────────────────────────────────────

# --- Menu Management Route (NEW) ---
@app.route("/admin/menu", methods=["GET", "POST"])
@staff_required # Apply the decorator to restrict access
def admin_menu():
    """
    Handles viewing and modifying menu items for staff.
    GET: Displays the menu items and forms.
    POST: Handles add, edit, delete actions.
    """
    menu_ref = db.collection("menuItems")

    # --- Handle POST requests (Add, Edit, Delete) ---
    if request.method == "POST":
        action = request.form.get("action")
        item_id = request.form.get("item_id") # Used for edit/delete

        try:
            # --- ADD ITEM ---
            if action == "add":
                name = request.form.get("name", "").strip()
                description = request.form.get("description", "").strip()
                price_str = request.form.get("price", "").strip()
                category = request.form.get("category", "").strip()
                image_link = request.form.get("imageLink", "").strip()
                dietary_str = request.form.get("dietary", "").strip()
                dietary_list = [d.strip() for d in dietary_str.split(',') if d.strip()]
                sizes = {}
                if category == 'pizza':
                    sizes = parse_sizes_from_form(request.form) # Use helper

                # Validation
                if not name or not category:
                    flash("Item Name and Category are required.", "error")
                elif category != 'pizza' and not price_str:
                     flash("Price is required for non-pizza items.", "error")
                elif category == 'pizza' and not sizes:
                     flash("At least one size is required for pizza items.", "error")
                else:
                    new_item_data = {
                        "name": name, "description": description, "category": category,
                        "imageLink": image_link or None, "dietary": dietary_list,
                        "customizable": request.form.get("customizable") == "on",
                        "sizes": sizes, "price": None,
                    }
                    if category != 'pizza':
                         try:
                             new_item_data["price"] = float(price_str)
                         except (ValueError, TypeError):
                             flash("Invalid format for Price. Please enter a number.", "error")
                             return redirect(url_for('admin_menu')) # Stay on page

                    menu_ref.add(new_item_data)
                    flash(f"Menu item '{name}' added successfully!", "success")

            # --- EDIT ITEM ---
            elif action == "edit" and item_id:
                doc_ref = menu_ref.document(item_id)
                if not doc_ref.get().exists:
                     flash(f"Item with ID {item_id} not found for editing.", "error")
                     return redirect(url_for('admin_menu'))

                name = request.form.get("name", "").strip()
                description = request.form.get("description", "").strip()
                price_str = request.form.get("price", "").strip()
                category = request.form.get("category", "").strip()
                image_link = request.form.get("imageLink", "").strip()
                dietary_str = request.form.get("dietary", "").strip()
                dietary_list = [d.strip() for d in dietary_str.split(',') if d.strip()]
                sizes = {}
                if category == 'pizza':
                    sizes = parse_sizes_from_form(request.form) # Use helper

                # Validation similar to Add
                if not name or not category:
                    flash("Item Name and Category are required.", "error")
                elif category != 'pizza' and not price_str:
                     flash("Price is required for non-pizza items.", "error")
                elif category == 'pizza' and not sizes:
                     flash("At least one size is required for pizza items.", "error")
                else:
                     update_data = {
                         "name": name, "description": description, "category": category,
                         "imageLink": image_link or None, "dietary": dietary_list,
                         "customizable": request.form.get("customizable") == "on",
                         "sizes": sizes, "price": None,
                     }
                     if category != 'pizza':
                          try:
                              update_data["price"] = float(price_str)
                          except (ValueError, TypeError):
                              flash("Invalid format for Price. Please enter a number.", "error")
                              return redirect(url_for('admin_menu')) # Stay on page

                     doc_ref.update(update_data)
                     flash(f"Menu item '{name}' (ID: {item_id}) updated successfully!", "success")

            # --- DELETE ITEM ---
            elif action == "delete" and item_id:
                doc_ref = menu_ref.document(item_id)
                item_snapshot = doc_ref.get()
                if item_snapshot.exists:
                     item_name = item_snapshot.to_dict().get('name', f'ID: {item_id}')
                     doc_ref.delete()
                     flash(f"Menu item '{item_name}' deleted successfully!", "success")
                else:
                     flash(f"Item with ID {item_id} not found for deletion.", "error")

            else:
                flash("Invalid action or missing item ID.", "error")

        except Exception as e:
            logging.error(f"Error processing menu management action '{action}' for item '{item_id}': {e}")
            flash(f"An error occurred: {e}", "error")

        return redirect(url_for('admin_menu'))

    # --- Handle GET requests ---
    try:
        docs = menu_ref.order_by("category").order_by("name").stream()
        items = []
        for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id
            # Normalize dietary
            if isinstance(data.get("dietary"), str):
                 data["dietary"] = [d.strip() for d in data["dietary"].split(',') if d.strip()]
            elif not isinstance(data.get("dietary"), list):
                 data["dietary"] = []
             # Normalize sizes
            if not isinstance(data.get("sizes"), dict):
                 data["sizes"] = {}
             # Normalize price
            if data.get("category") != 'pizza' or not data.get("sizes"):
                 try:
                     data["price"] = float(data.get("price", 0.0))
                 except (ValueError, TypeError):
                     data["price"] = 0.0
            else:
                 data["price"] = None
            items.append(data)
    except Exception as e:
        logging.error(f"Error fetching menu items for admin: {e}")
        flash("Could not load menu items.", "error")
        items = []

    # Pass staff status to the admin template
    return render_template("admin_menu.html",
                           menu_items=items,
                           logged_in=is_logged_in(),
                           is_staff=session.get('is_staff', False)) # Pass staff status


# ────────────────────────────────────────────────────────────
# Main execution block (for local development)
# ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Set debug=True for development (provides detailed error pages)
    # Set debug=False for production
    # Use host='0.0.0.0' to make it accessible on your network if needed
    app.run(debug=True, host='127.0.0.1', port=8080)
