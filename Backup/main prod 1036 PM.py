import logging
from flask import (
    Flask, render_template, request, redirect,
    url_for, jsonify, session, flash
)
from google.cloud import firestore
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "your_secret_key"          # ← move to env var for production
db = firestore.Client(database="ccpnosql01")  # ← remove hard‑code in prod


# ────────────────────────────────────────────────────────────
# Helper
# ────────────────────────────────────────────────────────────
def user_exists(username: str, email: str) -> bool:
    """Return True if that username OR email is already in Firestore."""
    users_ref = db.collection("users")
    if list(users_ref.where("username", "==", username).limit(1).stream()):
        return True
    if list(users_ref.where("email", "==", email).limit(1).stream()):
        return True
    return False

# --- Helper function to get login status ---
def is_logged_in():
    return 'user_id' in session
# --- End Helper ---

# ────────────────────────────────────────────────────────────
# Public pages
# ────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html", logged_in=is_logged_in())


@app.route("/menu")
def menu():
    """
    Pull menuItems collection -> list[dict] with doc.id attached,
    massaging the 'dietary' field so templates never break.
    """
    docs = db.collection("menuItems").stream()
    items = []

    for doc in docs:
        data = doc.to_dict()
        data["id"] = doc.id

        # normalise 'dietary'
        if isinstance(data.get("dietary"), list):
            cleaned = []
            for d in data["dietary"]:
                if isinstance(d, str):
                    cleaned.append(d)
                elif isinstance(d, list):
                    try:
                        joined = "".join(map(str, d)).strip()
                        if joined:
                            cleaned.append(joined)
                    except Exception as exc:
                        logging.warning(
                            "Could not process dietary entry %s (%s)", d, exc
                        )
            data["dietary"] = list(dict.fromkeys(cleaned))
        elif isinstance(data.get("dietary"), str):
            data["dietary"] = [data["dietary"].strip()] if data["dietary"].strip() else []
        else:
            data["dietary"] = []

        items.append(data)

    return render_template("menu.html", menu_items=items, logged_in=is_logged_in())


@app.route("/custom_pizza")
def customize_pizza():
    return render_template("custom_pizza.html", logged_in=is_logged_in())


@app.route("/order")
def order():
    return render_template("order.html", logged_in=is_logged_in())


# ────────────────────────────────────────────────────────────
# Account / Auth
# ────────────────────────────────────────────────────────────
@app.route("/account", methods=["GET", "POST"])
def account():
    """
    GET  → show login form by default (or register form via ?form=register)
    POST → login  / register handlers.
    """
    form_type = request.args.get("form", "")
    if request.method == "POST":
        action = request.form.get("action")
        if action == "login":
            return login_user()
        if action == "register":
            return register_user()
        return jsonify({"error": "Invalid action"}), 400

    # GET
    return render_template("account.html", form_type=form_type, form_data=None, logged_in=is_logged_in())


def login_user():
    email = request.form.get("email")
    password = request.form.get("password")

    if not (email and password):
        return jsonify({"error": "Missing credentials"}), 400

    try:
        users = list(db.collection("users").where("email", "==", email).limit(1).stream())
        if not users:
            return jsonify({"error": "Invalid credentials"}), 401

        doc = users[0]
        user = doc.to_dict()
        if check_password_hash(user["password_hash"], password):
            session["user_id"] = doc.id
            return redirect(url_for("account_dashboard"))

        return jsonify({"error": "Invalid credentials"}), 401
    except Exception as exc:
        logging.error("Login error: %s", exc)
        return jsonify({"error": f"Login failed: {exc}"}), 500


def _sanitised_form_data(src):
    """Return a copy of request.form with password fields stripped."""
    data = src.to_dict(flat=True)
    data.pop("password", None)
    data.pop("confirm_password", None)
    return data


def register_user():
    req = request.form
    username = req.get("username")
    email = req.get("email")
    password = req.get("password")
    confirm = req.get("confirm_password")

    # Basic required field check
    if not all([username, email, password, confirm]):
        flash("Missing required fields", "error")
        return render_template(
            "account.html", form_type="register", form_data=_sanitised_form_data(req), logged_in=is_logged_in()
        )

    if password != confirm:
        flash("Passwords do not match", "error")
        return render_template(
            "account.html", form_type="register", form_data=_sanitised_form_data(req), logged_in=is_logged_in()
        )

    if user_exists(username, email):
        flash("Username or email already exists", "error")
        return render_template(
            "account.html", form_type="register", form_data=_sanitised_form_data(req), logged_in=is_logged_in()
        )

    # create user
    user_doc = {
        "username": username,
        "email": email,
        "first_name": req.get("first_name", ""),
        "last_name": req.get("last_name", ""),
        "address": req.get("address", ""),
        "phone_number": req.get("phone_number", ""),
        "password_hash": generate_password_hash(password),
        "registration_date": firestore.SERVER_TIMESTAMP,
    }
    try:
        db.collection("users").add(user_doc)
        return redirect(url_for("account_dashboard"))
    except Exception as exc:
        logging.error("Registration error: %s", exc)
        flash(f"Registration failed: {exc}", "error")
        return render_template(
            "account.html", form_type="register", form_data=_sanitised_form_data(req), logged_in=is_logged_in()
        )


@app.route("/account_dashboard")
def account_dashboard():
    if "user_id" not in session:
        return redirect(url_for("account"))

    user_doc = db.collection("users").document(session["user_id"]).get()
    if not user_doc.exists:
        session.pop("user_id", None)
        return "User not found", 404

    return render_template("account_dashboard.html", user=user_doc.to_dict(), logged_in=is_logged_in())


# ────────────────────────────────────────────────────────────
# Profile management
# ────────────────────────────────────────────────────────────
@app.route("/edit_profile", methods=["GET", "POST"])
def edit_profile():
    if "user_id" not in session:
        return redirect(url_for("account"))

    ref = db.collection("users").document(session["user_id"])

    if request.method == "POST":
        ref.update(
            {
                "first_name": request.form.get("first_name"),
                "last_name": request.form.get("last_name"),
                "address": request.form.get("address"),
                "phone_number": request.form.get("phone_number"),
                "username": request.form.get("username"),
            }
        )
        flash("Profile updated successfully!", "success")
        return redirect(url_for("account_dashboard"))

    doc = ref.get()
    if not doc.exists:
        return "User not found", 404

    return render_template("edit_profile.html", user=doc.to_dict(), logged_in=is_logged_in())


@app.route("/change_password", methods=["GET", "POST"])
def change_password():
    if "user_id" not in session:
        return redirect(url_for("account"))

    ref = db.collection("users").document(session["user_id"])

    if request.method == "POST":
        current_pw = request.form.get("current_password")
        new_pw = request.form.get("new_password")
        confirm_pw = request.form.get("confirm_password")

        if not all([current_pw, new_pw, confirm_pw]):
            flash("All fields are required.", "error")
            return redirect(url_for("change_password"))

        doc = ref.get()
        if not doc.exists:
            flash("User not found.", "error")
            return redirect(url_for("account"))

        if not check_password_hash(doc.to_dict()["password_hash"], current_pw):
            flash("Current password is incorrect.", "error")
            return redirect(url_for("change_password"))

        if new_pw != confirm_pw:
            flash("New passwords do not match.", "error")
            return redirect(url_for("change_password"))

        ref.update({"password_hash": generate_password_hash(new_pw)})
        flash("Password updated successfully!", "success")
        return redirect(url_for("account_dashboard"))

    return render_template("change_password.html", logged_in=is_logged_in())


# ────────────────────────────────────────────────────────────
# Misc pages
# ────────────────────────────────────────────────────────────
@app.route("/logout")
def logout():
    session.pop("user_id", None)
    return redirect(url_for("index"), logged_in=is_logged_in())


@app.route("/contact")
def contact():
    return render_template("contact.html", logged_in=is_logged_in())


@app.route("/disclaimer")
def disclaimer():
    return render_template("disclaimer.html", logged_in=is_logged_in())


@app.route("/privacy")
def privacy():
    return render_template("privacy.html", logged_in=is_logged_in())


# ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=True)
