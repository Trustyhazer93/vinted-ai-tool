import base64
import os
import logging
from flask import Flask, render_template, request, redirect, url_for
from openai import OpenAI
from dotenv import load_dotenv
from PIL import Image
import io
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from flask_login import (
    LoginManager,
    login_user,
    login_required,
    logout_user,
    current_user,
    UserMixin,
)
from werkzeug.security import generate_password_hash, check_password_hash

# -------------------------
# CONFIG
# -------------------------

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL").replace(
    "postgres://", "postgresql://"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

logging.basicConfig(level=logging.INFO)

MAX_IMAGES = 5

# -------------------------
# SYSTEM PROMPT
# -------------------------

SYSTEM_PROMPT = """
You are an expert Vinted clothing reseller and SEO specialist.

Your job is to analyse clothing images and generate high-converting Vinted listings designed to maximise search visibility and buyer engagement.

STRICT RULES:
- Follow the exact format provided.
- If brand is unclear, leave blank.
- If size is unclear, leave blank.
- Do NOT guess brand or size.
- Condition must be one of: New, Excellent, Very Good, Good, Fair.
- Base condition ONLY on visible wear in the images.
- Carefully inspect ALL images for flaws before writing anything.
- If ANY visible flaws exist (stains, fading, cracking, holes, pulls, loose stitching, marks, distressing, discolouration, fabric thinning, repairs), you MUST list them in a separate "Flaws:" section.
- The Flaws section must appear directly after Condition.
- Each flaw must be described clearly and factually in one short sentence.
- If no visible flaws exist, DO NOT include a Flaws section.
- Accuracy is more important than making the item sound appealing.
- Do not exaggerate or invent damage.
- No emojis.
- No extra commentary.
- Optimise for Vinted search visibility using relevant fashion keywords.

TITLE RULES:
- Include brand (if known), fit style, colour, item type, size.
- Maximise relevant keywords naturally without repetition.
- Keep it clean and readable.

FORMAT:

Title: 

Brand: 
Size: 
Condition: 
Flaws: (only include if flaws are visible)

[2–4 sentence SEO-optimised description including style keywords, fit, wearability, aesthetic, and referencing any listed flaws if present.]

#[5 highly relevant hashtags in lowercase]
"""

# -------------------------
# DATABASE MODELS
# -------------------------

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    credits = db.Column(db.Integer, default=10)
    is_generating = db.Column(db.Boolean, default=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Generation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    tokens_used = db.Column(db.Integer)
    status = db.Column(db.String(20), default="completed")  # future-ready
    result = db.Column(db.Text)  # future-ready
    error = db.Column(db.Text)   # future-ready


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# -------------------------
# GENERATION LOGIC (UPGRADE READY)
# -------------------------

def generate_listing(images):
    """
    This function contains ALL heavy logic.
    When upgrading to background workers,
    only this function will be queued instead of called directly.
    """

    content = [
        {
            "type": "text",
            "text": "Carefully inspect ALL provided images for visible flaws such as holes, stains, fading, cracking, or damage. Then generate ONE Vinted listing for this clothing item using ALL provided images."
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
            "image_url": {
                "url": f"data:image/jpeg;base64,{encoded_image}"
            }
        })

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content}
        ],
        max_tokens=500,
        temperature=0.4
    )

    listing = response.choices[0].message.content
    tokens_used = response.usage.total_tokens if response.usage else None

    return listing, tokens_used


# -------------------------
# AUTH ROUTES
# -------------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email").lower().strip()
        password = request.form.get("password")

        user = User.query.filter_by(email=email).first()

        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for("index"))

        return render_template("login.html", error="Invalid email or password.")

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form.get("email").lower().strip()
        password = request.form.get("password")

        if User.query.filter_by(email=email).first():
            return render_template("register.html", error="Email already registered.")

        hashed_password = generate_password_hash(password)

        new_user = User(
            email=email,
            password_hash=hashed_password,
            credits=10,
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
# MAIN ROUTE
# -------------------------

@app.route("/", methods=["GET", "POST"])
@login_required
def index():
    listing = None

    if request.method == "POST":

        user = db.session.query(User).with_for_update().filter_by(id=current_user.id).first()

        if user.is_generating:
            return render_template("index.html", listing="Generation already in progress.")

        if not user.is_admin and user.credits <= 0:
            return render_template("index.html", listing="You have no credits remaining.")

        images = request.files.getlist("images")

        if not images or images[0].filename == "":
            return render_template("index.html", listing="Please upload at least one image.")

        if len(images) > MAX_IMAGES:
            return render_template("index.html", listing=f"Maximum {MAX_IMAGES} images allowed.")

        try:
            user.is_generating = True
            if not user.is_admin:
                user.credits -= 1
            db.session.commit()

            start_time = datetime.utcnow()

            listing, tokens_used = generate_listing(images)

            end_time = datetime.utcnow()
            logging.info(f"Generation took {(end_time - start_time).total_seconds()} seconds")

            generation = Generation(
                user_id=user.id,
                tokens_used=tokens_used,
                status="completed",
                result=listing
            )

            db.session.add(generation)
            db.session.commit()

        except Exception as e:
            logging.error(f"Generation error: {e}")
            db.session.rollback()

            user = User.query.get(current_user.id)
            if not user.is_admin:
                user.credits += 1
            db.session.commit()

            listing = "Error generating listing. Please try again."

        finally:
            user = User.query.get(current_user.id)
            user.is_generating = False
            db.session.commit()

    return render_template("index.html", listing=listing)
# -------------------------
# AUTO MIGRATION (SAFE)
# -------------------------

def run_safe_migration():
    with app.app_context():
        inspector = db.inspect(db.engine)
        columns = [col["name"] for col in inspector.get_columns("generation")]

        with db.engine.connect() as connection:

            if "status" not in columns:
                connection.execute(
                    db.text("ALTER TABLE generation ADD COLUMN status VARCHAR(20) DEFAULT 'completed'")
                )

            if "result" not in columns:
                connection.execute(
                    db.text("ALTER TABLE generation ADD COLUMN result TEXT")
                )

            if "error" not in columns:
                connection.execute(
                    db.text("ALTER TABLE generation ADD COLUMN error TEXT")
                )

        db.session.commit()



if __name__ == "__main__":
    run_safe_migration()
    app.run()
