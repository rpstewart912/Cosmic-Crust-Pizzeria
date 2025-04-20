from flask import Flask, render_template, request, redirect, url_for, jsonify, session
from google.cloud import firestore
from werkzeug.security import generate_password_hash, check_password_hash
import logging

app = Flask(__name__)
app.secret_key = "your_secret_key"
db = firestore.Client(database="ccpnosql01")

def user_exists(username, email):
    users_ref = db.collection('users')
    if list(users_ref.where('username', '==', username).limit(1).stream()):
        return True
    if list(users_ref.where('email', '==', email).limit(1).stream()):
        return True
    return False

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/menu')
def menu():
    return render_template('menu.html')

@app.route('/order')
def order():
    return render_template('order.html')

@app.route('/account', methods=['GET', 'POST'])
def account():
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

        if check_password_hash(password, user['password_hash']):
            session['user_id'] = user_id
            return redirect(url_for('account_dashboard'))
        else:
            return jsonify({'error': 'Invalid credentials'}), 401

    except Exception as e:
        logging.error(f"Login error: {e}")
        return jsonify({'error': f'Login failed: {str(e)}'}), 500

def register_user():
    username = request.form.get('username')
    email = request.form.get('email')
    password = request.form.get('password')
    first_name = request.form.get('first_name')
    last_name = request.form.get('last_name')
    address = request.form.get('address')
    phone_number = request.form.get('phone_number')

    if not username or not email or not password:
        return jsonify({'error': 'Missing required fields'}), 400

    if user_exists(username, email):
        return jsonify({'error': 'Username or email already exists'}), 409

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
        db.collection('users').add(user_data)
        return jsonify({'message': 'Registration successful'}), 201
    except Exception as e:
        logging.error(f"Registration error: {e}")
        return jsonify({'error': f'Registration failed: {str(e)}'}), 500

@app.route('/account_dashboard')
def account_dashboard():
    if 'user_id' in session:
        user_id = session['user_id']
        user_ref = db.collection('users').document(user_id)
        user_doc = user_ref.get()
        if user_doc.exists:
            user_data = user_doc.to_dict()
            return render_template('account_dashboard.html', user=user_data)
        else:
            return "User not found", 404
    else:
        return redirect(url_for('account'))

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('index'))

@app.route('/contact')
def contact():
    return render_template('contact.html')

@app.route('/disclaimer')
def disclaimer():
    return render_template('disclaimer.html')

@app.route('/privacy')
def privacy():
    return render_template('privacy.html')

if __name__ == '__main__':
    app.run(debug=True)