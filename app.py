import os
import base64
import requests
import logging
import time
from flask import Flask, request, jsonify
from twilio.rest import Client as TwilioClient
from openai import OpenAI
from google.cloud import vision
from io import BytesIO
from PIL import Image

app = Flask(__name__)
logging.basicConfig(level=logging.DEBUG)

# ENV variables
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER")
GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

if not all([OPENAI_API_KEY, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_NUMBER, GOOGLE_APPLICATION_CREDENTIALS]):
    raise ValueError("Missing required environment variables!")

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = GOOGLE_APPLICATION_CREDENTIALS

# Clients
twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
openai_client = OpenAI(api_key=OPENAI_API_KEY)
vision_client = vision.ImageAnnotatorClient()

@app.route('/webhook', methods=['POST', 'GET'])
def webhook():
    if request.method == 'GET':
        return jsonify({"status": "ok"}), 200

    start_time = time.time()
    data = request.form
    from_number = data.get('From')
    message_body = data.get('Body')
    media_url = data.get('MediaUrl0')

    logging.debug(f"Received from {from_number}: text={message_body[:10]}... (hidden), media_url={media_url}")

    if not media_url and not message_body:
        return jsonify({"status": "error", "message": "No image or text provided"}), 400

    try:
        if media_url:
            # Обработка изображения
            image_response = requests.get(media_url, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN), timeout=10)
            image_response.raise_for_status()
            image_content = image_response.content
            start_ocr_time = time.time()
            vision_image = vision.Image(content=image_content)
            vision_response = vision_client.text_detection(image=vision_image)
            ocr_time = time.time() - start_ocr_time
            logging.debug(f"OCR processing time: {ocr_time} seconds")

            if not vision_response.text_annotations:
                logging.warning("No text detected by Google Vision")
                gpt_response = "Answer: N/A"
            else:
                extracted_text = vision_response.text_annotations[0].description
                filtered_text = filter_text(extracted_text)
                input_text = filtered_text if filtered_text else "No valid question found"
                logging.debug(f"Extracted and filtered text: {input_text}")
        else:
            # Обработка текста
            input_text = message_body

        # Усиленный промт
        gpt_prompt = f"""
You are a licensed California construction expert and professional exam instructor. Analyze the following exam question and select the most accurate answer.
Your answers must strictly follow California regulations, including the California Building Code (CBC), California OSHA standards, ADA guidelines, and CSLB exam practices.

Important clarification about symbols and fractions:
In construction questions:
    • The symbol ' (single quote) means feet.
    • The symbol " (double quote) means inches.
    • Fractions such as 1/8”, 3/4”, 5-1/2” must be read and calculated accurately as inches.
    • Always consider fractions as exact values for precise measurements.
    • If symbols appear unclear, missing, or distorted in the image, assume standard notation and apply common construction measurement logic.

Analyze the provided exam question carefully. Follow these steps to ensure maximum accuracy:
    1. Understand the question:
    – Identify key details such as specific words (e.g., “minimum,” “maximum,” “required,” “residential,” “commercial”).
    – Pay close attention to numerical values, measurements, and calculation requirements.
    2. Analyze the answer options:
    – Compare each option carefully.
    – Check for combined options (like D = A and C), and prioritize them if they represent the most complete answer.
    – If multiple answers seem correct, choose the most comprehensive, safest, and legally compliant option.
    3. Check numerical accuracy:
    – If the question involves calculations, perform them step-by-step.
    – Reconfirm the correctness of dimensions, percentages, distances, and other critical measurements according to California codes.
    4. Consider legal context:
    – Apply official California standards (CBC, OSHA, ADA).
    – Do not use general or international construction practices.
    – Include knowledge from safety regulations, insurance, health standards, and licensing laws.
    5. Clarify ambiguous cases:
    – If there’s uncertainty, choose the option that best aligns with California contractor legal practices and prioritizes safety and compliance.
    6. Avoid common mistakes:
    – Do NOT ignore numerical differences, even if they seem small (e.g., 1/8 inch, ½ inch).
    – Do NOT select options outside the provided list.
    – Do NOT guess without analysis.

Critical rules:
    – Always double-check calculations and reasoning before giving the final answer.
    – Be as precise as possible with numbers and measurements.
    – If the question mentions “all of the above” or combination answers (A and C), prioritize those if they are valid.
    – Ignore irrelevant text (UI elements, notes, system messages).
    – Prioritize universal rules over specific exceptions unless the question specifies otherwise.
    – Do NOT provide any explanations or reasoning; return only the answer in the specified format.

Question:
{input_text}

Answer format:
Answer: [exact text of the correct answer option]

If the question or options are unreadable, respond:
Answer: N/A
"""

        start_gpt_time = time.time()
        gpt_response = ask_gpt(gpt_prompt)
        gpt_time = time.time() - start_gpt_time
        logging.debug(f"GPT processing time: {gpt_time} seconds")

        send_whatsapp_message(from_number, gpt_response)
        total_time = time.time() - start_time
        logging.debug(f"Total time: {total_time} seconds")

        return jsonify({"status": "success"}), 200

    except requests.exceptions.Timeout as e:
        logging.error(f"Timeout error: {str(e)}")
        return jsonify({"status": "error", "message": "Request timed out"}), 500
    except google.cloud.exceptions.GoogleCloudError as e:
        logging.error(f"Google Vision error: {str(e)}")
        return jsonify({"status": "error", "message": "Vision API failed"}), 500
    except Exception as e:
        logging.error(f"Error in webhook: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

def filter_text(text):
    lines = text.split('\n')
    filtered = []
    for line in lines:
        line = line.strip()
        if line and (line.startswith(('A.', 'B.', 'C.', 'D.', 'Which', 'How', 'Given')) or '?' in line or any(c.isdigit() for c in line)):
            filtered.append(line)
    return '\n'.join(filtered) if filtered else "No valid question found"

def ask_gpt(prompt):
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are an AI assistant for California contractor exam questions."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
            max_tokens=1000
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logging.error(f"Error in ask_gpt: {str(e)}")
        raise

def send_whatsapp_message(to, message):
    try:
        twilio_client.messages.create(
            from_=TWILIO_WHATSAPP_NUMBER,
            body=message,
            to=to
        )
    except Exception as e:
        logging.error(f"Error in send_whatsapp_message: {str(e)}")
        raise

if __name__ == "__main__":
    print("🚀 Bot is running...")
    app.run(host="0.0.0.0", port=8080)
