from flask import Flask, render_template, request, redirect, url_for, make_response
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import date, timedelta
from flask import Flask, render_template, request, redirect, url_for, make_response
from translations import translations
import csv
import io

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret-key-goes-here'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///cards.db' 
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True)
    password = db.Column(db.String(100))
    cards = db.relationship('Card', backref='user', lazy=True)

class Card(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    question = db.Column(db.String(500))
    answer = db.Column(db.String(500))
    subject = db.Column(db.String(100), nullable=False, default='General')
    next_review_date = db.Column(db.Date, default=date.today)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
with app.app_context():
    db.create_all()

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if User.query.filter_by(username=username).first(): return "User exists!"       
        new_user = User(username=username, password=generate_password_hash(password))
        db.session.add(new_user)
        db.session.commit()
        login_user(new_user)
        return redirect(url_for('home'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password, request.form['password']):
            login_user(user)
            return redirect(url_for('home'))
        else: return "Invalid credentials"
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.context_processor
def inject_language():
    lang = request.cookies.get('lang', 'en')
    return dict(t=translations[lang], current_lang=lang)

@app.route('/set_lang/<lang_code>')
def set_lang(lang_code):
    if lang_code not in ['en', 'id']:
        lang_code = 'en'
    response = make_response(redirect(request.referrer or url_for('home')))
    response.set_cookie('lang', lang_code)
    return response

@app.route('/')
@login_required
def home():
    user_cards = Card.query.filter_by(user_id=current_user.id).all()
    subjects = {} 
    for c in user_cards:
        if c.subject not in subjects:
            subjects[c.subject] = {'total': 0, 'due': 0}
        subjects[c.subject]['total'] += 1
        if c.next_review_date <= date.today():
            subjects[c.subject]['due'] += 1
    return render_template('index.html', 
                           subjects=subjects, 
                           user=current_user, 
                           all_cards=user_cards)

@app.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    if request.method == 'POST':
        new_card = Card(
            question=request.form['question'], 
            answer=request.form['answer'],
            subject=request.form['subject'], # Save the subject
            user_id=current_user.id
        )
        db.session.add(new_card)
        db.session.commit()
        return redirect(url_for('home'))
    return render_template('add.html')

@app.route('/study')
@app.route('/study/<subject>')
@login_required
def study(subject=None):
    query = Card.query.filter_by(user_id=current_user.id).filter(Card.next_review_date <= date.today())
    if subject:
        query = query.filter_by(subject=subject)   
    card = query.first()   
    if not card: return redirect(url_for('home'))
    return render_template('study.html', card=card, current_subject=subject)

@app.route('/rate/<int:id>/<string:grade>')
@login_required
def rate_card(id, grade):
    card = Card.query.get_or_404(id)
    if card.user_id != current_user.id: return "Unauthorized", 403
    if grade == 'easy': card.next_review_date = date.today() + timedelta(days=3)
    else: card.next_review_date = date.today() + timedelta(days=1)
    db.session.commit()
    if request.args.get('subject'):
        return redirect(url_for('study', subject=request.args.get('subject')))
    return redirect(url_for('study'))

@app.route('/profile')
@login_required
def profile():
    cards = Card.query.filter_by(user_id=current_user.id).all()
    total = len(cards)
    mastered = len([c for c in cards if c.next_review_date > date.today() + timedelta(days=5)])
    accuracy = int((mastered / total) * 100) if total > 0 else 0
    return render_template('profile.html', user=current_user, total=total, mastered=mastered, accuracy=accuracy)

@app.route('/upload', methods=['POST'])
@login_required
def upload():
    file = request.files['file']
    if not file: return "No file uploaded"
    stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
    csv_input = csv.reader(stream)
    next(csv_input)
    
    for row in csv_input:
        if len(row) >= 3:
            new_card = Card(
                question=row[0],
                answer=row[1],
                subject=row[2],
                user_id=current_user.id
            )
            db.session.add(new_card)
    
    db.session.commit()
    return redirect(url_for('home'))

@app.route('/download')
@login_required
def download():
    user_cards = Card.query.filter_by(user_id=current_user.id).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Question', 'Answer', 'Subject'])
    for card in user_cards:
        writer.writerow([card.question, card.answer, card.subject])
    output.seek(0)
    response = make_response(output.getvalue())
    response.headers["Content-Disposition"] = "attachment; filename=my_flashcards.csv"
    response.headers["Content-type"] = "text/csv"
    return response

@app.route('/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit(id):
    card = Card.query.get_or_404(id)
    if card.user_id != current_user.id:
        return "Unauthorized", 403
    if request.method == 'POST':
        card.question = request.form['question']
        card.answer = request.form['answer']
        card.subject = request.form['subject']
        db.session.commit()
        return redirect(url_for('home'))
    return render_template('edit.html', card=card)

@app.route('/delete/<int:id>')
@login_required
def delete(id):
    card = Card.query.get_or_404(id)
    if card.user_id == current_user.id:
        db.session.delete(card)
        db.session.commit()
    return redirect(url_for('home'))

@app.route('/delete_bulk', methods=['POST'])
@login_required
def delete_bulk():
    card_ids = request.form.getlist('card_ids')   
    if card_ids:
        for c_id in card_ids:
            card = Card.query.get(int(c_id))
            if card and card.user_id == current_user.id:
                db.session.delete(card)
        db.session.commit()
    return redirect(url_for('home'))

if __name__ == '__main__':
    app.run(debug=True)