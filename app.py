import base64
import os
from flask import Flask, render_template, request, session
from openai import OpenAI
from dotenv import load_dotenv
from PIL import Image
import io
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL").replace("postgres://", "postgresql://")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# -------------------------
# DATABASE MODELS
# -------------------------

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    credits = db.Column(db.Integer, default=10)
    #is_generating = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Generation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    tokens_used = db.Column(db.Integer)


print("App starting...")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

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

#5 highly relevant hashtags in lowercase
"""

@app.route("/", methods=["GET", "POST"])
def index():
    listing = None

    if request.method == "POST":

        user = db.session.query(User).with_for_update().first()

        # If no user exists yet, create one automatically
        if not user:
            user = User(email="test@example.com", credits=100)
            db.session.add(user)
            db.session.commit()

            # Re-lock after creating
            user = db.session.query(User).with_for_update().first()


        # ---- HARD LOCK CHECK ----
        if user.is_generating:
            return render_template("index.html", listing="Generation already in progress. Please wait.")

        if user.credits <= 0:
            return render_template("index.html", listing="You have no credits remaining.")

        try:
            # ---- LOCK USER + DEDUCT CREDIT ATOMICALLY ----
            user.is_generating = True
            user.credits -= 1
            db.session.commit()

            images = request.files.getlist("images")

            if not images or images[0].filename == "":
                return render_template("index.html", listing="Please upload at least one image.")

            content = [
                {
                    "type": "text",
                    "text": "Carefully inspect ALL provided images for visible flaws such as holes, stains, fading, cracking, or damage. Then generate ONE Vinted listing for this clothing item using ALL provided images."
                }
            ]

            # ---- IMAGE PROCESSING ----
            for image in images:
                try:
                    img = Image.open(image)
                    max_size = (800, 800)
                    img.thumbnail(max_size)

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

                except Exception as e:
                    print(f"Image processing error: {e}")
                    continue

            if len(content) <= 1:
                return render_template("index.html", listing="No valid images were processed.")

            # ---- OPENAI CALL ----
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

            # ---- LOG GENERATION ----
            tokens_used = response.usage.total_tokens if response.usage else None

            generation = Generation(
                user_id=user.id,
                tokens_used=tokens_used
            )

            db.session.add(generation)
            db.session.commit()

        except Exception as e:
            print(f"Error during generation: {e}")

            db.session.rollback()

            # Refund credit if something failed
            user = User.query.get(user.id)
            user.credits += 1
            db.session.commit()

            listing = "Error generating listing. Please try again."

        finally:
            # ---- ALWAYS UNLOCK USER ----
            user = User.query.get(user.id)
            user.is_generating = False
            db.session.commit()

    return render_template("index.html", listing=listing)




with app.app_context():
    from sqlalchemy import text

    # Ensure tables exist first
    db.create_all()

    # Check if column exists before adding
    result = db.session.execute(text("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name='user' AND column_name='is_generating';
    """))

    column_exists = result.fetchone()

    if not column_exists:
        db.session.execute(text("""
            ALTER TABLE "user" 
            ADD COLUMN is_generating BOOLEAN DEFAULT FALSE;
        """))
        db.session.commit()
        print("is_generating column added.")
    else:
        print("is_generating column already exists.")


if __name__ == "__main__":
    app.run()
