import os
import base64
import requests
import logging
import time
import json
from flask import Flask, request, jsonify
from twilio.rest import Client as TwilioClient
from openai import OpenAI
from io import BytesIO
from PIL import Image

app = Flask(__name__)
logging.basicConfig(level=logging.DEBUG)

# ENV variables
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER")

# Логирование для диагностики
logging.debug(f"OPENAI_API_KEY: {'Set' if OPENAI_API_KEY else 'Not set'}")
logging.debug(f"TWILIO_ACCOUNT_SID: {'Set' if TWILIO_ACCOUNT_SID else 'Not set'}")
logging.debug(f"TWILIO_AUTH_TOKEN: {'Set' if TWILIO_AUTH_TOKEN else 'Not set'}")
logging.debug(f"TWILIO_WHATSAPP_NUMBER: {'Set' if TWILIO_WHATSAPP_NUMBER else 'Not set'}")

if not all([OPENAI_API_KEY, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_NUMBER]):
    raise ValueError("Missing required environment variables!")

# Clients
twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

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
            # Загрузка изображения
            image_response = requests.get(media_url, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN), timeout=10)
            image_response.raise_for_status()
            image_content = image_response.content

            # Конвертация изображения в base64
            image = Image.open(BytesIO(image_content)).convert("RGB")
            buffered = BytesIO()
            image.save(buffered, format="PNG")
            img_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")

            # Промт с пошаговым анализом
            gpt_prompt = f"""
You are a licensed California construction expert and professional exam instructor. Analyze the following exam question from the provided image and select the most accurate answer.
Your answers must strictly follow California regulations, including the California Building Code (CBC), California OSHA standards, ADA guidelines, and CSLB exam practices.

Important clarification about symbols and fractions:
In construction questions:
    • The symbol ' (single quote) means feet.
    • The symbol " (double quote) means inches.
    • Fractions such as 1/8”, 3/4”, 5-1/2” must be read and calculated accurately as inches.
    • Always consider fractions as exact values for precise measurements.
    • If symbols appear unclear, missing, or distorted in the image, assume standard notation and apply common construction measurement logic.

Analyze the provided exam question carefully. Follow these steps and provide your reasoning:
    1. Extract the text from the image:
    – Identify the question number, the question text, and all answer options (e.g., A, B, C, D).
    – Ignore irrelevant text such as UI elements (e.g., "TOOLS", "CONTRAST", "KEYBOARD SHORTCUTS", "MENU", "EXAM", "OPTIONS", browser tabs, dates, times, student names, or system messages like "I think there is a technical or content error").
    – Focus only on the question and its answer options.
    2. Understand the question:
    – Note key details such as specific words (e.g., “minimum,” “maximum,” “required,” “residential,” “commercial”).
    – Pay close attention to numerical values, measurements, and calculation requirements.
    3. Analyze the answer options:
    – List all options (e.g., A, B, C, D).
    – Compare each option carefully against the question and California regulations.
    – Check for combined options (like D = A and C), and prioritize them if they represent the most complete answer.
    – If multiple answers seem correct, choose the most comprehensive, safest, and legally compliant option, but prioritize the minimum requirement if specified.
    4. Check numerical accuracy:
    – If the question involves calculations, perform them step-by-step.
    – Reconfirm the correctness of dimensions, percentages, distances, and other critical measurements according to California codes.
    5. Consider legal context:
    – Apply official California standards (CBC, OSHA, ADA).
    – Do not use general or international construction practices.
    – Include knowledge from safety regulations, insurance, health standards, and licensing laws.
    6. Clarify ambiguous cases:
    – If there’s uncertainty, choose the option that best aligns with California contractor legal practices and prioritizes safety and compliance.
    7. Provide the final answer:
    – Summarize your reasoning and select the best option.
    – Include the text you extracted from the image for verification.

Critical rules:
    – Double-check calculations and reasoning before giving the final answer.
    – Be as precise as possible with numbers and measurements.
    – If the question specifies “minimum,” prioritize the smallest sufficient size that meets safety standards.
    – If the question mentions “all of the above” or combination answers (A and C), prioritize those if they are valid.
    – Return the answer in the specified format with reasoning and extracted text.

Question (from image):
[Image data encoded as base64]

Answer format:
Extracted text: [Text extracted from the image by GPT]
Step 1: [Understanding of the question]
Step 2: [Analysis of the options]
Step 3: [Final answer with reasoning]
Answer: [exact text of the correct answer option]

If the question or options are unreadable, respond:
Extracted text: [Unable to extract text from image]
Step 1: [Unable to identify the question]
Step 2: [No options available]
Step 3: [Question unreadable]
Answer: N/A
"""

            messages = [
                {
                    "role": "system",
                    "content": "You are an AI assistant for California contractor exam questions."
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": gpt_prompt
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{img_base64}"}
                        }
                    ]
                }
            ]

            start_gpt_time = time.time()
            gpt_response = ask_gpt(messages)
            gpt_time = time.time() - start_gpt_time
            logging.debug(f"Full GPT response: {gpt_response}")  # Логируем полный ответ
            logging.debug(f"GPT processing time: {gpt_time} seconds")
        else:
            input_text = message_body
            gpt_prompt = f"""
You are a licensed California construction expert and professional exam instructor. Analyze the following exam question and select the most accurate answer.
Your answers must strictly follow California regulations, including the California Building Code (CBC), California OSHA standards, ADA guidelines, and CSLB exam practices.

Important clarification about symbols and fractions:
In construction questions:
    • The symbol ' (single quote) means feet.
    • The symbol " (double quote) means inches.
    • Fractions such as 1/8”, 3/4”, 5-1/2” must be read and calculated accurately as inches.
    • Always consider fractions as exact values for precise measurements.
    • If symbols appear unclear, missing, or distorted, assume standard notation and apply common construction measurement logic.

Analyze the provided exam question carefully. Follow these steps and provide your reasoning:
    1. Understand the question:
    – Identify the question number and text.
    – Note key details such as specific words (e.g., “minimum,” “maximum,” “required,” “residential,” “commercial”).
    – Pay close attention to numerical values, measurements, and calculation requirements.
    2. Analyze the answer options:
    – List all options (e.g., A, B, C, D).
    – Compare each option carefully against the question and California regulations.
    – Check for combined options (like D = A and C), and prioritize them if they represent the most complete answer.
    – If multiple answers seem correct, choose the most comprehensive, safest, and legally compliant option, but prioritize the minimum requirement if specified.
    3. Check numerical accuracy:
    – If the question involves calculations, perform them step-by-step.
    – Reconfirm the correctness of dimensions, percentages, distances, and other critical measurements according to California codes.
    4. Consider legal context:
    – Apply official California standards (CBC, OSHA, ADA).
    – Do not use general or international construction practices.
    – Include knowledge from safety regulations, insurance, health standards, and licensing laws.
    5. Clarify ambiguous cases:
    – If there’s uncertainty, choose the option that best aligns with California contractor legal practices and prioritizes safety and compliance.
    6. Provide the final answer:
    – Summarize your reasoning and select the best option.

Critical rules:
    – Double-check calculations and reasoning before giving the final answer.
    – Be as precise as possible with numbers and measurements.
    – If the question specifies “minimum,” prioritize the smallest sufficient size that meets safety standards.
    – If the question mentions “all of the above” or combination answers (A and C), prioritize those if they are valid.
    – Ignore irrelevant text (UI elements, notes, system messages, dates, times, or interface labels like TOOLS, CONTRAST, KEYBOARD SHORTCUTS, MENU, EXAM, OPTIONS).
    – Prioritize universal rules over specific exceptions unless the question specifies otherwise.
    – Return the answer in the specified format with reasoning.

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

            start_gpt_time = time.time()
            gpt_response = ask_gpt(gpt_prompt)
            gpt_time = time.time() - start_gpt_time
            logging.debug(f"Full GPT response: {gpt_response}")  # Логируем полный ответ
            logging.debug(f"GPT processing time: {gpt_time} seconds")

        # Извлечение только финального ответа (после "Answer:")
        final_answer = gpt_response.split("Answer:")[1].strip() if "Answer:" in gpt_response else gpt_response
        # Удаляем букву варианта (A., B., C., D.) из ответа, если она есть
        final_answer = final_answer.split(".", 1)[1].strip() if final_answer.startswith(("A.", "B.", "C.", "D.")) else final_answer

        # Отправка только финального ответа в WhatsApp
        send_whatsapp_message(from_number, final_answer)
        total_time = time.time() - start_time
        logging.debug(f"Total response time: {total_time} seconds")

        return jsonify({"status": "success"}), 200

    except requests.exceptions.Timeout as e:
        logging.error(f"Timeout error: {str(e)}")
        return jsonify({"status": "error", "message": "Request timed out"}), 500
    except Exception as e:
        logging.error(f"Error in webhook: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

def ask_gpt(messages_or_prompt):
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=messages_or_prompt if isinstance(messages_or_prompt, list) else [
                {"role": "system", "content": "You are an AI assistant for California contractor exam questions."},
                {"role": "user", "content": messages_or_prompt}
            ],
            temperature=0.2,
            max_tokens=1500  # Увеличим лимит для пошагового анализа
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
        logging.debug(f"Message sent to {to}")
    except Exception as e:
        logging.error(f"Error in send_whatsapp_message: {str(e)}")
        raise

if __name__ == "__main__":
    print("🚀 Bot is running...")
    app.run(host="0.0.0.0", port=8080)
