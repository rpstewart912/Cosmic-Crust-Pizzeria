import logging
# Import get_flashed_messages directly from flask
from flask import Flask, render_template, request, redirect, url_for, jsonify, session, flash, get_flashed_messages
from google.cloud import firestore
from werkzeug.security import generate_password_hash, check_password_hash

# Configure logging
logging.basicConfig(level=logging.INFO) # Set minimum logging level

app = Flask(__name__)
# TODO: Replace with a strong, unique secret key and manage securely (e.g., environment variable)
app.secret_key = "your_secret_key" # IMPORTANT: Change this to a real secret key!
# TODO: Ensure your Google Cloud project and Firestore database are correctly set up and authenticated
db = firestore.Client(database="ccpnosql01")

# Add a basic 500 error handler for better debugging
@app.errorhandler(500)
def internal_error(exception):
    # Log the exception traceback
    logging.exception('An internal server error occurred: %s', exception)
    # In production, you might render a custom 500.html template
    # return render_template('500.html'), 500
    # For debugging, return a simple message or the error details
    return f"<p>Internal Server Error: An unexpected error occurred.</p><p>Details have been logged.</p>", 500


# --- Helper function to get login status ---
def is_logged_in():
    return 'user_id' in session
# --- End Helper ---


@app.route('/')
def index():
    """Renders the home page."""
    # Pass login status to the template
    return render_template('index.html', logged_in=is_logged_in())

@app.route('/menu')
def menu():
    """
    Fetches menu items from Firestore and renders the menu page.
    Passes login status to the template.
    """
    menu_items_ref = db.collection('menuItems')
    # Fetch all documents from the menuItems collection
    docs = menu_items_ref.stream()

    menu_items_list = []
    for doc in docs:
        # Convert each document to a dictionary and add its ID
        item_data = doc.to_dict()
        item_data['id'] = doc.id # Include the Firestore document ID

        # --- Handle potential dietary label data issues ---
        if 'dietary' in item_data and isinstance(item_data['dietary'], list):
             processed_dietary = []
             for label_entry in item_data['dietary']:
                 if isinstance(label_entry, str):
                     processed_dietary.append(label_entry.strip()) # Strip whitespace
                 elif isinstance(label_entry, list):
                     try:
                         # Attempt to join list items, handle potential non-strings
                         joined_label = ''.join(map(str, label_entry)).strip()
                         if joined_label:
                             processed_dietary.append(joined_label)
                     except Exception as e:
                         logging.warning(f"Could not process dietary label list entry: {label_entry} for item {item_data.get('name', 'Unknown')}. Error: {e}")
             # Ensure processed_dietary is unique
             item_data['dietary'] = list(dict.fromkeys(processed_dietary))
        elif 'dietary' in item_data and isinstance(item_data['dietary'], str):
             # If dietary is a single string, put it in a list if not empty
             if item_data['dietary'].strip():
                 item_data['dietary'] = [item_data['dietary'].strip()]
             else:
                 item_data['dietary'] = []
        else:
             # If 'dietary' field doesn't exist or is of unexpected type, ensure it's an empty list
             item_data['dietary'] = []
        # --- END dietary label handling ---


        menu_items_list.append(item_data)

    # Pass the list of menu items AND the login status to the menu.html template
    return render_template('menu.html', menu_items=menu_items_list, logged_in=is_logged_in())

@app.route('/custom_pizza')
def customize_pizza():
    # Pass login status to the template
    return render_template('custom_pizza.html', logged_in=is_logged_in())

@app.route('/order')
def order():
    """Renders the order page."""
    # Pass login status to the template
    return render_template('order.html', logged_in=is_logged_in())

@app.route('/account', methods=['GET', 'POST'])
def account():
    """Handles account login and registration."""
    logged_in = is_logged_in() # Check login status
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'login':
            # login_user will return a redirect or render on failure
            return login_user()
        elif action == 'register':
             # register_user will return a redirect or render on failure
            return register_user()
        else:
            # Handle unexpected action values - redirect back to account page with error
            flash('Invalid form action.')
            return redirect(url_for('account')) # Redirect to the GET /account route

    # If it's a GET request, render the account template and pass login status
    # Also check for flash messages to display errors/success
    # --- FIX: Call get_flashed_messages() directly ---
    messages = get_flashed_messages()
    # --- End FIX ---
    return render_template('account.html', logged_in=logged_in, messages=messages) # Pass messages

def login_user():
    """Handles user login."""
    # Ensure request is POST and form data is available
    if request.method != 'POST':
         flash('Invalid login request method.')
         return redirect(url_for('account')) # Redirect if not POST

    email = request.form.get('email')
    password = request.form.get('password')

    # Basic input validation
    if not email or not password:
        flash('Missing email or password') # Flash error message
        return redirect(url_for('account'))

    try:
        users_ref = db.collection('users')
        # Query by email (assuming email is unique for login)
        query = users_ref.where('email', '==', email).limit(1)
        results = list(query.stream())

        if not results:
            flash('Invalid email or password') # User not found or email incorrect
            return redirect(url_for('account'))

        user_doc = results[0]
        user_id = user_doc.id
        user = user_doc.to_dict() # Get user data as dict

        # Check if 'password_hash' field exists and is a string before comparison
        if 'password_hash' not in user or not isinstance(user['password_hash'], str):
             logging.error(f"User document {user_id} is missing or has invalid 'password_hash' field.")
             flash('Login failed due to missing or incorrect password data.')
             return redirect(url_for('account'))

        # Verify the password
        if check_password_hash(user['password_hash'], password): # Correct order is (password, hash)
            session['user_id'] = user_id
            logging.info(f"User {user_id} logged in successfully.")
            flash('Login successful!') # Optional success message
            # Redirect to the account dashboard page after successful login
            return redirect(url_for('account_dashboard'))
        else:
            flash('Invalid email or password') # Password did not match
            return redirect(url_for('account'))

    except Exception as e:
        # Catch any other unexpected errors during login
        logging.exception(f"Login error for email {email}:") # Use exception() to log traceback
        flash(f'An error occurred during login. Please try again.') # Generic error message for user
        return redirect(url_for('account'))


def register_user():
    """Handles user registration."""
    # Ensure request is POST and form data is available
    if request.method != 'POST':
         flash('Invalid registration request method.')
         return redirect(url_for('account')) # Redirect if not POST

    # Get registration data from request.form
    username = request.form.get('username')
    email = request.form.get('email')
    password = request.form.get('password')
    first_name = request.form.get('first_name')
    last_name = request.form.get('last_name')
    address = request.form.get('address')
    phone_number = request.form.get('phone_number')
    # Note: The 'action' field from the form is processed in the /account route, not here

    # Basic validation for all required fields
    if not username or not email or not password or not first_name or not last_name or not address or not phone_number:
        flash('Missing required fields. Please fill out all fields.') # Flash specific error message
        return redirect(url_for('account')) # Redirect back to account page

    # Check if user already exists
    if user_exists(username, email):
        flash('Username or email already exists. Please choose different ones or login.') # Flash specific error message
        return redirect(url_for('account')) # Redirect back to account page

    # Hash the password
    try:
        hashed_password = generate_password_hash(password)
    except Exception as e:
        logging.exception("Error hashing password during registration:")
        flash('An error occurred processing the password.')
        return redirect(url_for('account'))


    # Prepare user data for Firestore
    user_data = {
        'username': username,
        'email': email,
        'first_name': first_name,
        'last_name': last_name,
        'address': address,
        'phone_number': phone_number,
        'password_hash': hashed_password,
        'registration_date': firestore.SERVER_TIMESTAMP # Use server timestamp
    }

    try:
        # Add the new user document to the 'users' collection
        # db.collection('users').add returns a tuple (datetime, DocumentReference)
        update_time, doc_ref = db.collection('users').add(user_data)
        new_user_id = doc_ref.id
        logging.info(f"User {new_user_id} registered successfully.")

        # TODO: Implement automatic login after successful registration
        # If you want to log them in immediately:
        # session['user_id'] = new_user_id
        # flash('Registration successful and you are now logged in!') # Optional message

        # If NOT auto-logging in, redirect to the login page with success message
        flash('Registration successful! Please log in.') # Flash message to show on login page
        return redirect(url_for('account')) # Redirect to the GET /account route

    except Exception as e:
        # Catch any other unexpected errors during registration (e.g., Firestore write error)
        logging.exception("Registration error:") # Log traceback
        flash(f'An error occurred during registration. Please try again.') # Generic error message for user
        return redirect(url_for('account')) # Redirect back to the account page


@app.route('/account_dashboard')
def account_dashboard():
    """Renders the account dashboard page."""
    # Check if user is logged in
    logged_in = is_logged_in()
    if logged_in: # Dashboard content only for logged in users
        user_id = session.get('user_id') # Use session.get to avoid KeyError if 'user_id' is somehow None or missing
        if not user_id: # Double-check user_id exists
             logging.warning("Session indicates logged in but 'user_id' is missing.")
             session.pop('user_id', None) # Clear invalid session
             flash('Invalid session. Please log in again.')
             return redirect(url_for('account'))

        try:
            user_ref = db.collection('users').document(user_id)
            user_doc = user_ref.get() # Get the user document

            if user_doc.exists:
                user_data = user_doc.to_dict()
                # Basic check for expected fields to prevent template errors
                # Add checks for other critical fields if needed
                if not user_data or 'username' not in user_data or 'email' not in user_data:
                     logging.warning(f"User document {user_id} found but missing critical fields.")
                     # You might still render the page but show warnings, or redirect
                     # For now, let's render but log the warning

                return render_template('account_dashboard.html', user=user_data, logged_in=logged_in) # Pass user data and logged_in
            else:
                # User ID in session but document not found in Firestore (e.g., user deleted from DB)
                logging.warning(f"User ID {user_id} in session but document not found in Firestore.")
                session.pop('user_id', None) # Clear invalid session
                flash('Your account was not found. Please log in again.') # Message for the user
                return redirect(url_for('account')) # Redirect to login with message

        except Exception as e:
            # Catch any errors during Firestore fetch for dashboard
            logging.exception(f"Error fetching user {user_id} for dashboard:") # Log traceback
            session.pop('user_id', None) # Clear session if error is related to user ID
            flash('Error loading dashboard. Please try logging in again.') # Generic error message for user
            return redirect(url_for('account'))

    else:
        # User not logged in, redirect to account page (login form) with a message
        flash('Please log in to view your dashboard.')
        return redirect(url_for('account'))


@app.route('/logout')
def logout():
    """Logs out the user."""
    # Ensure session exists before popping
    if 'user_id' in session:
        session.pop('user_id', None)

    logging.info("User logged out.")
    flash('You have been logged out.') # Optional message
    # Redirect to the home page (or login page, depending on desired flow)
    return redirect(url_for('index')) # Redirect to index route


@app.route('/contact')
def contact():
    # Pass login status to the template
    return render_template('contact.html', logged_in=is_logged_in())

@app.route('/disclaimer')
def disclaimer():
    # Pass login status to the template
    return render_template('disclaimer.html', logged_in=is_logged_in())

@app.route('/privacy')
def privacy():
    # Pass login status to the template
    return render_template('privacy.html', logged_in=is_logged_in())

# TODO: Add routes for order processing, payment handling, order tracking, etc.

# Ensure debug=True is ONLY for development. Use a production WSGI server like Gunicorn.
if __name__ == '__main__':
    # Use 0.0.0.0 to make the server accessible externally if needed (e.g., for testing on devices)
    # app.run(debug=True, host='0.0.0.0')
    app.run(debug=True)