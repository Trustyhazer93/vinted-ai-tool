import base64
import os
from flask import Flask, render_template, request, redirect, url_for
from openai import OpenAI
from dotenv import load_dotenv
from PIL import Image
import io
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from flask_login import LoginManager, login_user, login_required, logout_user, current_user, UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL").replace("postgres://", "postgresql://")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# -------------------------
# DATABASE MODELS
# -------------------------

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    credits = db.Column(db.Integer, default=10)
    is_generating = db.Column(db.Boolean, default=False)
    is_admin = db.Column(db.Boolean, default=False)  # ADD THIS
    created_at = db.Column(db.DateTime, default=datetime.utcnow)



class Generation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    tokens_used = db.Column(db.Integer)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# -------------------------
# AUTH ROUTES
# -------------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        user = User.query.filter_by(email=email).first()

        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for("index"))
        else:
            return render_template("login.html", error="Invalid email or password.")

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        if User.query.filter_by(email=email).first():
            return render_template("register.html", error="Email already registered.")

        hashed_password = generate_password_hash(password)

        new_user = User(
            email=email,
            password_hash=hashed_password,
            credits=10
        )

        db.session.add(new_user)
        db.session.commit()

        login_user(new_user)
        return redirect(url_for("index"))

    return render_template("register.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


# -------------------------
# GENERATOR ROUTE
# -------------------------

@app.route("/", methods=["GET", "POST"])
@login_required
def index():
    listing = None

    if request.method == "POST":

        user = db.session.query(User).with_for_update().filter_by(id=current_user.id).first()

        if user.is_generating:
            return render_template("index.html", listing="Generation already in progress. Please wait.")

        if not user.is_admin and user.credits <= 0:
            return render_template("index.html", listing="You have no credits remaining.")


        try:
            user.is_generating = True
            if not user.is_admin:
                user.credits -= 1
            db.session.commit()

            images = request.files.getlist("images")

            if not images or images[0].filename == "":
                return render_template("index.html", listing="Please upload at least one image.")

            content = [
                {
                    "type": "text",
                    "text": "Carefully inspect ALL provided images for visible flaws and generate ONE Vinted listing."
                }
            ]

            for image in images:
                img = Image.open(image)
                img.thumbnail((800, 800))

                buffer = io.BytesIO()
                img.convert("RGB").save(buffer, format="JPEG", quality=65)
                buffer.seek(0)

                encoded_image = base64.b64encode(buffer.read()).decode("utf-8")

                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{encoded_image}"}
                })

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a Vinted listing expert."},
                    {"role": "user", "content": content}
                ],
                max_tokens=500,
                temperature=0.4
            )

            listing = response.choices[0].message.content

            tokens_used = response.usage.total_tokens if response.usage else None

            generation = Generation(
                user_id=user.id,
                tokens_used=tokens_used
            )

            db.session.add(generation)
            db.session.commit()

        except Exception as e:
            db.session.rollback()
            user = User.query.get(current_user.id)
            user.credits += 1
            db.session.commit()
            listing = "Error generating listing. Please try again."

        finally:
            user = User.query.get(current_user.id)
            user.is_generating = False
            db.session.commit()

    return render_template("index.html", listing=listing)


from sqlalchemy import text

with app.app_context():
    try:
        db.session.execute(text('ALTER TABLE "user" ADD COLUMN is_admin BOOLEAN DEFAULT FALSE;'))
        db.session.commit()
        print("is_admin column added")
    except Exception:
        db.session.rollback()



if __name__ == "__main__":
    app.run()
