import base64
import os
from flask import Flask, render_template, request
from openai import OpenAI
from dotenv import load_dotenv
from PIL import Image
import io


# Load environment variables
load_dotenv()

app = Flask(__name__)
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
- If visible flaws exist (stains, fading, cracking, holes, pulls, loose stitching, marks, distressing, discolouration), they MUST be clearly described in the description.
- If no visible flaws exist, do NOT invent any.
- Prioritise flaw analysis if close-up images appear to show damage.
- Do not exaggerate flaws.
- Describe severity accurately (minor, light, moderate, noticeable).
- Be transparent and factual about flaws.
- No emojis.
- No extra commentary.
- Optimise for Vinted search visibility using relevant fashion keywords.

TITLE RULES:
- Include brand (if known) fit style colour item type - size.
- Maximise relevant keywords naturally without repetition.
- Keep it clean and readable.

FORMAT:

Title: 

Brand: 
Size: 
Condition: 

[2–4 sentence SEO-optimised description including style keywords, fit, wearability, aesthetic, and any visible flaws if present.]

#[5 highly relevant hashtags in lowercase]
"""

@app.route("/", methods=["GET", "POST"])
def index():
    listing = None

    if request.method == "POST":
        images = request.files.getlist("images")

        content = [
            {"type": "text", "text": "Generate ONE Vinted listing for this clothing item using ALL provided images."}
        ]

        for image in images:
    try:
        img = Image.open(image)

        max_size = (1000, 1000)
        img.thumbnail(max_size)

        buffer = io.BytesIO()
        img.convert("RGB").save(buffer, format="JPEG", quality=75)
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


        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": content
                }
            ],
            max_tokens=500
        )

        listing = response.choices[0].message.content

    return render_template("index.html", listing=listing)


if __name__ == "__main__":
    app.run()
