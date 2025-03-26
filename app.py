import os
import base64
import requests
import logging
import time
from flask import Flask, request, jsonify
from twilio.rest import Client as TwilioClient
from openai import OpenAI
from io import BytesIO
from PIL import Image
from concurrent.futures import ThreadPoolExecutor

app = Flask(__name__)
logging.basicConfig(level=logging.DEBUG)

# ENV variables
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER")
FILE_ID = os.getenv("FILE_ID")

if not all([OPENAI_API_KEY, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_NUMBER, FILE_ID]):
    raise ValueError("One or more required environment variables are missing!")

# Clients
twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

TEXT_PROMPT = """
You are a licensed California construction expert and professional exam instructor. Analyze the following exam question and select the most accurate answer...
Question:
{input_text}

Answer format:
Step 1: [Understanding of the question]
Step 2: [Analysis of the options]
Step 3: [Final answer with reasoning]
Answer: [exact text of the correct answer option]
"""

# Request to GPT with internal logic
def get_gpt_response(prompt):
    full_prompt = TEXT_PROMPT.replace("{input_text}", prompt)
    response = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a licensed California construction expert."},
            {"role": "user", "content": full_prompt}
        ],
        temperature=0.2,
        max_tokens=1500
    )
    return response.choices[0].message.content.strip()

# Request to GPT using file search
def get_file_search_response(prompt):
    full_prompt = TEXT_PROMPT.replace("{input_text}", prompt)
    response = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a licensed California construction expert using a textbook."},
            {"role": "user", "content": full_prompt}
        ],
        file_ids=[FILE_ID],
        temperature=0.2,
        max_tokens=1500
    )
    return response.choices[0].message.content.strip()

# Compare both and select the best response
def select_best_response(question, gpt_response, file_response):
    compare_prompt = f"""
You are a licensed California construction expert. Analyze the two answers below and select the best.

Question: {question}

Answer 1 (GPT):
{gpt_response}

Answer 2 (File):
{file_response}

Return only:
Reasoning: ...
Final Answer: ...
"""
    response = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are an expert decision-making AI."},
            {"role": "user", "content": compare_prompt}
        ],
        temperature=0.2,
        max_tokens=1000
    )
    return response.choices[0].message.content.strip()

@app.route('/webhook', methods=['POST', 'GET'])
def webhook():
    if request.method == 'GET':
        return jsonify({"status": "ok"}), 200

    start_time = time.time()
    data = request.form
    from_number = data.get('From')
    message_body = data.get('Body')
    media_url = data.get('MediaUrl0')

    logging.debug(f"Received from {from_number}: text={message_body[:10] if message_body else 'None'}..., media_url={media_url}")

    if not message_body and not media_url:
        return jsonify({"status": "error", "message": "No image or text provided"}), 400

    try:
        if media_url:
            image_response = requests.get(media_url, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN), timeout=10)
            image = Image.open(BytesIO(image_response.content)).convert("RGB")
            buf = BytesIO()
            image.save(buf, format="PNG")
            img_base64 = base64.b64encode(buf.getvalue()).decode("utf-8")

            messages = [
                {"role": "system", "content": "You are a licensed California construction expert."},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": TEXT_PROMPT.replace("{input_text}", "[Image base64]")},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_base64}"}}
                    ]
                }
            ]
            with ThreadPoolExecutor() as executor:
                gpt_fut = executor.submit(get_gpt_response, messages)
                file_fut = executor.submit(get_file_search_response, messages)
                gpt_res = gpt_fut.result()
                file_res = file_fut.result()
        else:
            with ThreadPoolExecutor() as executor:
                gpt_fut = executor.submit(get_gpt_response, message_body)
                file_fut = executor.submit(get_file_search_response, message_body)
                gpt_res = gpt_fut.result()
                file_res = file_fut.result()

        final = select_best_response(message_body or "Image question", gpt_res, file_res)
        final_answer = final.split("Final Answer:")[-1].strip()
        if final_answer.startswith(("A.", "B.", "C.", "D.")):
            final_answer = final_answer.split(".", 1)[1].strip()

        send_whatsapp_message(from_number, final_answer)
        logging.debug(f"✅ Done in {time.time() - start_time:.2f}s")
        return jsonify({"status": "success"}), 200

    except Exception as e:
        logging.error(f"❌ Error: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

def send_whatsapp_message(to, message):
    try:
        twilio_client.messages.create(from_=TWILIO_WHATSAPP_NUMBER, body=message, to=to)
        logging.debug(f"📤 Sent to {to}")
    except Exception as e:
        logging.error(f"Failed to send: {str(e)}")

if __name__ == '__main__':
    print("🚀 Bot is running...")
    app.run(host="0.0.0.0", port=8080)
