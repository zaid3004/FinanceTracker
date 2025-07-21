import os
from flask import Flask, render_template, redirect, url_for, request, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import pandas as pd
import io

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key'

# Use DATABASE_URL environment variable, fallback to SQLite for local testing
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///instance/finance.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

# ======================= MODELS =======================

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True)
    password = db.Column(db.String(200))
    accounts = db.relationship('Account', backref='user', lazy=True)

class Account(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    transactions = db.relationship('Transaction', backref='account', lazy=True)

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.String(20))
    type = db.Column(db.String(10))
    category = db.Column(db.String(50))
    amount = db.Column(db.Float)
    description = db.Column(db.String(200))
    account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=False)

# ======================= LOGIN =======================

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.before_first_request
def create_tables():
    db.create_all()

# ======================= ROUTES =======================

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = generate_password_hash(request.form['password'])
        if User.query.filter_by(username=username).first():
            flash('Username already exists')
        else:
            user = User(username=username, password=password)
            db.session.add(user)
            db.session.commit()
            flash('Registration successful')
            return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid credentials')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# ======================= DASHBOARD =======================

@app.route('/dashboard', methods=['GET', 'POST'])
@login_required
def dashboard():
    selected_account_id = request.form.get('account_select') or request.args.get('account_id')
    if selected_account_id:
        selected_account = Account.query.filter_by(id=selected_account_id, user_id=current_user.id).first()
    else:
        selected_account = Account.query.filter_by(user_id=current_user.id).first()

    accounts = Account.query.filter_by(user_id=current_user.id).all()
    transactions = selected_account.transactions if selected_account else []

    filter_type = request.args.get('type')
    category = request.args.get('category')
    sort_by = request.args.get('sort_by')

    if filter_type:
        transactions = [t for t in transactions if t.type == filter_type]
    if category:
        transactions = [t for t in transactions if t.category == category]
    if sort_by:
        transactions = sorted(transactions, key=lambda t: getattr(t, sort_by))

    balance = sum(t.amount if t.type == 'Income' else -t.amount for t in transactions)

    return render_template('dashboard.html', accounts=accounts, transactions=transactions,
                           selected_account=selected_account, balance=balance)

# ======================= ACTIONS =======================

@app.route('/add_transaction', methods=['POST'])
@login_required
def add_transaction():
    account_id = request.form['account_id']
    date = datetime.strptime(request.form['date'], "%Y-%m-%d").strftime("%d-%m-%Y")
    type = request.form['type']
    category = request.form['category']
    amount = float(request.form['amount'].replace(",", ""))
    description = request.form['description']
    transaction = Transaction(date=date, type=type, category=category,
                              amount=amount, description=description, account_id=account_id)
    db.session.add(transaction)
    db.session.commit()
    return redirect(url_for('dashboard', account_id=account_id))

@app.route('/clear_transactions/<int:account_id>', methods=['POST'])
@login_required
def clear_transactions(account_id):
    Transaction.query.filter_by(account_id=account_id).delete()
    db.session.commit()
    return redirect(url_for('dashboard', account_id=account_id))

@app.route('/export/<int:account_id>')
@login_required
def export(account_id):
    transactions = Transaction.query.filter_by(account_id=account_id).all()
    df = pd.DataFrame([{
        'Date': t.date, 'Type': t.type, 'Category': t.category,
        'Amount': t.amount, 'Description': t.description
    } for t in transactions])
    stream = io.StringIO()
    df.to_csv(stream, index=False)
    stream.seek(0)
    return send_file(io.BytesIO(stream.read().encode()), mimetype='text/csv',
                     as_attachment=True, download_name='transactions.csv')

@app.route('/import/<int:account_id>', methods=['POST'])
@login_required
def import_excel(account_id):
    file = request.files['file']
    if file.filename.endswith('.xlsx'):
        df = pd.read_excel(file)
        for _, row in df.iterrows():
            transaction = Transaction(
                date=row['Date'],
                type=row['Type'],
                category=row['Category'],
                amount=float(row['Amount']),
                description=row.get('Description', ''),
                account_id=account_id
            )
            db.session.add(transaction)
        db.session.commit()
    return redirect(url_for('dashboard', account_id=account_id))

# ======================= ACCOUNT MGMT =======================

@app.route('/add_account', methods=['POST'])
@login_required
def add_account():
    name = request.form['name']
    if not Account.query.filter_by(user_id=current_user.id, name=name).first():
        account = Account(name=name, user_id=current_user.id)
        db.session.add(account)
        db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/rename_account/<int:account_id>', methods=['POST'])
@login_required
def rename_account(account_id):
    new_name = request.form['new_name']
    account = Account.query.get(account_id)
    if account and account.user_id == current_user.id:
        account.name = new_name
        db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/delete_account/<int:account_id>', methods=['POST'])
@login_required
def delete_account(account_id):
    account = Account.query.get(account_id)
    if account and account.user_id == current_user.id:
        Transaction.query.filter_by(account_id=account.id).delete()
        db.session.delete(account)
        db.session.commit()
    return redirect(url_for('dashboard'))

if __name__ == '__main__':
    app.run(debug=True)
