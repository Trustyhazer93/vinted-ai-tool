import base64
import os
from flask import Flask, render_template, request
from openai import OpenAI
from dotenv import load_dotenv

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
- Base condition only on visible wear.
- No emojis.
- No extra commentary.
- Optimise for Vinted search visibility using relevant fashion keywords.

TITLE RULES:
- Include brand (if known), item type, colour, graphic/theme, fit style, era/style vibe.
- Maximise relevant keywords naturally without repetition.
- Keep it clean and readable.

FORMAT:

Title: 

Brand: 
Size: 
Condition: 

[2–4 sentence SEO-optimised description including style keywords, fit, wearability, and aesthetic.]

#[5 highly relevant hashtags in lowercase]
"""

@app.route("/", methods=["GET", "POST"])
def index():
    listings = []

    if request.method == "POST":
        images = request.files.getlist("images")

        for image in images:
            image_bytes = image.read()
            encoded_image = base64.b64encode(image_bytes).decode("utf-8")

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Generate a Vinted listing for this clothing item."},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{encoded_image}"
                                }
                            }
                        ]
                    }
                ],
                max_tokens=600
            )

            listings.append(response.choices[0].message.content)

    return render_template("index.html", listings=listings)

if __name__ == "__main__":
    app.run(debug=True)
