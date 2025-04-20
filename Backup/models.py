from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'users'  # Explicitly set the table name

    id = db.Column(db.Integer, primary_key=True)  # Auto-incrementing primary key
    full_name = db.Column(db.String(255) , nullable=False)  # User's full name
    email = db.Column(db.String(255), unique=True, nullable=False)  # Unique email
    password_hash = db.Column(db.String(255), nullable=False)  # Hashed password

    def __repr__(self):
        return f"<User(email='{self.email}')>"  # Representation for debugging