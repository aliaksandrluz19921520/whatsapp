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
from concurrent.futures import ThreadPoolExecutor

app = Flask(__name__)
logging.basicConfig(level=logging.DEBUG)

# ENV variables
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER")

# Проверка переменных окружения
if not all([OPENAI_API_KEY, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_NUMBER]):
    raise ValueError("Missing required environment variables!")

# Клиенты
twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

# ID файла берётся из переменной окружения FILE_ID
FILE_ID = os.getenv("FILE_ID")
if not FILE_ID:
    raise ValueError("FILE_ID is not set in environment variables!")

# Оригинальный промпт для текста
TEXT_PROMPT = """
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

# Функция для стандартного запроса к GPT
def get_gpt_response(prompt):
    full_prompt = TEXT_PROMPT.replace("{input_text}", prompt) if isinstance(prompt, str) else prompt
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

# Функция для поиска по файлу (File Search)
def get_file_search_response(prompt):
    full_prompt = TEXT_PROMPT.replace("{input_text}", prompt) if isinstance(prompt, str) else prompt
    response = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a licensed California construction expert using a textbook."},
            {"role": "user", "content": full_prompt}
        ],
        tools=[{"type": "file_search", "file_id": FILE_ID}],
        temperature=0.2,
        max_tokens=1500
    )
    return response.choices[0].message.content.strip()

# Функция для выбора лучшего ответа
def select_best_response(question, gpt_response, file_search_response):
    selection_prompt = f"""
You are a licensed California construction expert and professional exam instructor. You have received a question and two potential answers. Your task is to analyze both answers and select the most accurate, complete, and legally compliant one according to California regulations (CBC, OSHA, ADA, CSLB practices). Provide reasoning for your choice.

Question: {question}

Answer 1 (from GPT-4o internal logic):
{gpt_response}

Answer 2 (from textbook search):
{file_search_response}

Instructions:
1. Compare both answers for accuracy, relevance, and adherence to California construction standards.
2. Check for completeness: does the answer fully address the question?
3. Prioritize safety, legal compliance, and precision in measurements or regulations.
4. If both are equally valid, choose the one that is more concise and practical.
5. Provide a brief reasoning for your choice.

Return your final answer in this format:
Reasoning: [Your reasoning here]
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
            # Загрузка изображения
            image_response = requests.get(media_url, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN), timeout=10)
            image_response.raise_for_status()
            image_content = image_response.content

            # Конвертация в base64
            image = Image.open(BytesIO(image_content)).convert("RGB")
            buffered = BytesIO()
            image.save(buffered, format="PNG")
            img_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")

            # Формирование сообщения для GPT
            messages = [
                {"role": "system", "content": "You are a licensed California construction expert."},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": TEXT_PROMPT.replace("{input_text}", "[Image data encoded as base64]")},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_base64}"}}
                    ]
                }
            ]

            # Параллельные запросы для изображений
            with ThreadPoolExecutor() as executor:
                gpt_future = executor.submit(get_gpt_response, messages)
                file_search_future = executor.submit(get_file_search_response, messages)

                gpt_response = gpt_future.result()
                file_search_response = file_search_future.result()
        else:
            # Параллельные запросы для текста
            with ThreadPoolExecutor() as executor:
                gpt_future = executor.submit(get_gpt_response, message_body)
                file_search_future = executor.submit(get_file_search_response, message_body)

                gpt_response = gpt_future.result()
                file_search_response = file_search_future.result()

        # Выбор лучшего ответа
        final_response = select_best_response(message_body or "Image-based question", gpt_response, file_search_response)
        final_answer = final_response.split("Final Answer:")[1].strip() if "Final Answer:" in final_response else final_response

        # Удаление буквы варианта, если есть
        final_answer = final_answer.split(".", 1)[1].strip() if final_answer.startswith(("A.", "B.", "C.", "D.")) else final_answer

        # Отправка ответа в WhatsApp
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
