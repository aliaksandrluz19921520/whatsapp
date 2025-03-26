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

# Проверка переменных окружения
if not all([OPENAI_API_KEY, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_NUMBER, FILE_ID]):
    raise ValueError("Missing required environment variables!")

# Клиенты
twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

TEXT_PROMPT = """
You are a licensed California construction expert and professional exam instructor. Analyze the following exam question and select the most accurate answer.
... [ПРОМПТ УКОРOЧЕН ДЛЯ ЧИТАЕМОСТИ] ...
Question:
{input_text}

Answer format:
Step 1: [Understanding of the question]
Step 2: [Analysis of the options]
Step 3: [Final answer with reasoning]
Answer: [exact text of the correct answer option]

If the question or options are unreadable, respond:
Step 1: [Unable to identify the question]
Step 2: [No options available]
Step 3: [Question unreadable]
Answer: N/A
"""

def get_gpt_response(prompt):
    if isinstance(prompt, list):
        messages = [
            {"role": "system", "content": "You are a licensed California construction expert."},
            {"role": "user", "content": prompt}
        ]
    else:
        full_prompt = TEXT_PROMPT.replace("{input_text}", prompt)
        messages = [
            {"role": "system", "content": "You are a licensed California construction expert."},
            {"role": "user", "content": full_prompt}
        ]

    response = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        temperature=0.2,
        max_tokens=1500
    )
    return response.choices[0].message.content.strip()

def get_file_search_response(prompt):
    if isinstance(prompt, list):
        messages = [
            {"role": "system", "content": "You are a licensed California construction expert using a textbook."},
            {"role": "user", "content": prompt}
        ]
    else:
        full_prompt = TEXT_PROMPT.replace("{input_text}", prompt)
        messages = [
            {"role": "system", "content": "You are a licensed California construction expert using a textbook."},
            {"role": "user", "content": full_prompt}
        ]

    response = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        tools=[{"type": "file_search", "file_id": FILE_ID}],
        temperature=0.2,
        max_tokens=1500
    )
    return response.choices[0].message.content.strip()

def select_best_response(question, gpt_response, file_search_response):
    selection_prompt = f"""
You are a licensed California construction expert and professional exam instructor... [УКОРОЧЕН] ...
Question: {question}

Answer 1 (from GPT-4o internal logic):
{gpt_response}

Answer 2 (from textbook search):
{file_search_response}

... [УКОРОЧЕН] ...
Final Answer: [The selected answer]
"""
    response = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are an expert decision-making AI."},
            {"role": "user", "content": selection_prompt}
        ],
        temperature=0.2,
        max_tokens=1500
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
            image_response.raise_for_status()
            image = Image.open(BytesIO(image_response.content)).convert("RGB")
            buffered = BytesIO()
            image.save(buffered, format="PNG")
            img_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")

            content = [
                {"type": "text", "text": TEXT_PROMPT.replace("{input_text}", "[Image data encoded as base64]")},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_base64}"}}
            ]

            with ThreadPoolExecutor() as executor:
                gpt_future = executor.submit(get_gpt_response, content)
                file_search_future = executor.submit(get_file_search_response, content)
                gpt_response = gpt_future.result()
                file_search_response = file_search_future.result()
        else:
            with ThreadPoolExecutor() as executor:
                gpt_future = executor.submit(get_gpt_response, message_body)
                file_search_future = executor.submit(get_file_search_response, message_body)
                gpt_response = gpt_future.result()
                file_search_response = file_search_future.result()

        final_response = select_best_response(message_body or "Image-based question", gpt_response, file_search_response)
        final_answer = final_response.split("Final Answer:")[-1].strip() if "Final Answer:" in final_response else final_response
        final_answer = final_answer.split(".", 1)[1].strip() if final_answer[:2] in ("A.", "B.", "C.", "D.") else final_answer

        send_whatsapp_message(from_number, final_answer)
        logging.debug(f"Total response time: {time.time() - start_time} seconds")

        return jsonify({"status": "success"}), 200

    except requests.exceptions.Timeout as e:
        logging.error(f"Timeout error: {str(e)}")
        return jsonify({"status": "error", "message": "Request timed out"}), 500
    except Exception as e:
        logging.error(f"Error in webhook: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

def send_whatsapp_message(to, message):
    try:
        twilio_client.messages.create(
            from_=TWILIO_WHATSAPP_NUMBER,
            body=message,
            to=to
        )
        logging.debug(f"Message sent to {to}")
    except Exception as e:
        logging.error(f"Error in send_whatsapp_message: {str(e)}")
        raise

if __name__ == "__main__":
    print("🚀 Bot is running...")
    app.run(host="0.0.0.0", port=8080)
