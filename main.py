import logging
from flask import Flask, render_template, request, redirect, url_for, jsonify, session
from google.cloud import firestore
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
# TODO: Replace with a strong, unique secret key and manage securely (e.g., environment variable)
app.secret_key = "your_secret_key"
# TODO: Ensure your Google Cloud project and Firestore database are correctly set up and authenticated
db = firestore.Client(database="ccpnosql01")

def user_exists(username, email):
    """Checks if a user with the given username or email already exists."""
    users_ref = db.collection('users')
    if list(users_ref.where('username', '==', username).limit(1).stream()):
        return True
    if list(users_ref.where('email', '==', email).limit(1).stream()):
        return True
    return False

@app.route('/')
def index():
    """Renders the home page."""
    return render_template('index.html')

@app.route('/menu')
def menu():
    """
    Fetches menu items from Firestore and renders the menu page.
    """
    menu_items_ref = db.collection('menuItems')
    # Fetch all documents from the menuItems collection
    docs = menu_items_ref.stream()

    menu_items_list = []
    for doc in docs:
        # Convert each document to a dictionary and add its ID
        item_data = doc.to_dict()
        item_data['id'] = doc.id # Include the Firestore document ID

        # --- Retained MODIFICATION: Handle potential dietary label data issues ---
        # This logic remains to ensure dietary labels are processed correctly for the menu display
        if 'dietary' in item_data and isinstance(item_data['dietary'], list):
            processed_dietary = []
            for label_entry in item_data['dietary']:
                if isinstance(label_entry, str):
                    processed_dietary.append(label_entry)
                elif isinstance(label_entry, list):
                    try:
                        joined_label = ''.join(map(str, label_entry)).strip()
                        if joined_label:
                            processed_dietary.append(joined_label)
                    except Exception as e:
                        logging.warning(f"Could not process dietary label list: {label_entry} for item {item_data.get('name', 'Unknown')}. Error: {e}")
            # If raw_dietary was a list, ensure the processed_dietary is unique
            processed_dietary = list(dict.fromkeys(processed_dietary))
            item_data['dietary'] = processed_dietary
        elif 'dietary' in item_data and isinstance(item_data['dietary'], str):
             # If dietary is a single string, put it in a list for consistency with template logic
             if item_data['dietary'].strip():
                 item_data['dietary'] = [item_data['dietary'].strip()]
             else:
                 item_data['dietary'] = []
        else:
             # If 'dietary' field doesn't exist or is of unexpected type, ensure it's an empty list
             item_data['dietary'] = []
        # --- END Retained MODIFICATION ---


        menu_items_list.append(item_data)

    # Pass the list of menu items to the menu.html template
    return render_template('menu.html', menu_items=menu_items_list)

# --- ROUTE FOR CUSTOMIZE PIZZA (WITH DATA PLACEHOLDERS) ---
@app.route('/custom_pizza')
def customize_pizza():
    return render_template('custom_pizza.html')

@app.route('/order')
def order():
    """Renders the order page."""
    return render_template('order.html')

@app.route('/account', methods=['GET', 'POST'])
def account():
    """Handles account login and registration."""
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'login':
            return login_user()
        elif action == 'register':
            return register_user()
        else:
            return jsonify({'error': 'Invalid action'}), 400
    return render_template('account.html')

def login_user():
    """Handles user login."""
    email = request.form.get('email')
    password = request.form.get('password')

    if not email or not password:
        return jsonify({'error': 'Missing email or password'}), 400

    try:
        users_ref = db.collection('users')
        query = users_ref.where('email', '==', email).limit(1)
        results = list(query.stream())

        if not results:
            return jsonify({'error': 'Invalid credentials'}), 401

        user = results[0].to_dict()
        user_id = results[0].id

        # TODO: Use a more secure password comparison method if possible, though check_password_hash is generally safe
        if check_password_hash(user['password_hash'], password): # Note: check_password_hash(password, hash) is the correct order
            session['user_id'] = user_id
            # TODO: Redirect to a more appropriate page after login, maybe the menu or order page
            return redirect(url_for('account_dashboard'))
        else:
            return jsonify({'error': 'Invalid credentials'}), 401

    except Exception as e:
        logging.error(f"Login error: {e}")
        return jsonify({'error': f'Login failed: {str(e)}'}), 500

def register_user():
    """Handles user registration."""
    username = request.form.get('username')
    email = request.form.get('email')
    password = request.form.get('password')
    first_name = request.form.get('first_name')
    last_name = request.form.get('last_name')
    address = request.form.get('address')
    phone_number = request.form.get('phone_number')

    if not username or not email or not password:
        # It's often better UX to flash a message and redirect back to the form
        # than returning JSON for validation errors in a server-rendered app
        # from flask import flash # Need to import flash
        # flash('Missing required fields')
        # return redirect(url_for('account'))
         return jsonify({'error': 'Missing required fields'}), 400 # Keep jsonify for API-like behavior if preferred


    if user_exists(username, email):
        # Similar to above, flashing a message and redirecting might be better UX
        # flash('Username or email already exists')
        # return redirect(url_for('account'))
        return jsonify({'error': 'Username or email already exists'}), 409 # Keep jsonify if preferred

    hashed_password = generate_password_hash(password)

    user_data = {
        'username': username,
        'email': email,
        'first_name': first_name,
        'last_name': last_name,
        'address': address,
        'phone_number': phone_number,
        'password_hash': hashed_password,
        'registration_date': firestore.SERVER_TIMESTAMP
    }
    try:
        # Add the new user document to the 'users' collection
        db.collection('users').add(user_data)

        # TODO: Consider automatically logging in the user after successful registration
        # If you automatically log them in, redirecting to the dashboard is perfect.
        # If you DON'T automatically log them in, you might redirect them to the login form
        # return redirect(url_for('account', login_message='Registration successful. Please log in.')) # Example passing message via URL or flash

        # --- REPLACE the jsonify return with a redirect ---
        print("Registration successful, redirecting to account dashboard.") # Log success
        return redirect(url_for('account_dashboard')) # Redirect to the account dashboard page


    except Exception as e:
        logging.error(f"Registration error: {e}")
        # Flash an error message and redirect back to the registration form
        # flash(f'Registration failed: {str(e)}')
        # return redirect(url_for('account', show_register_form=True)) # Example redirecting back to account page

        return jsonify({'error': f'Registration failed: {str(e)}'}), 500 # Keep jsonify if preferred for errors

@app.route('/account_dashboard')
def account_dashboard():
    """Renders the account dashboard page."""
    if 'user_id' in session:
        user_id = session['user_id']
        user_ref = db.collection('users').document(user_id)
        user_doc = user_ref.get()
        if user_doc.exists:
            user_data = user_doc.to_dict()
            return render_template('account_dashboard.html', user=user_data)
        else:
            # User ID in session but document not found (e.g., deleted user)
            session.pop('user_id', None) # Clear invalid session
            return "User not found", 404 # Or redirect to login with an error message
    else:
        # User not logged in, redirect to account page
        return redirect(url_for('account'))

@app.route('/logout')
def logout():
    """Logs out the user."""
    session.pop('user_id', None)
    # TODO: Redirect to a confirmation page or the home page
    return redirect(url_for('index'))

@app.route('/contact')
def contact():
    """Renders the contact page."""
    return render_template('contact.html')

@app.route('/disclaimer')
def disclaimer():
    """Renders the disclaimer page."""
    return render_template('disclaimer.html')

@app.route('/privacy')
def privacy():
    """Renders the privacy policy page."""
    return render_template('privacy.html')

# TODO: Add routes for order processing, payment handling, order tracking, etc.

if __name__ == '__main__':
    # In production, use a production WSGI server like Gunicorn
    # For local development, debug=True is fine
    app.run(debug=True)