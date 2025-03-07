import os
import base64
import requests
from flask import Flask, request, jsonify
from twilio.rest import Client as TwilioClient
from openai import OpenAI, __version__ as openai_version
import logging
from io import BytesIO
from PIL import Image
import time

# Инициализация Flask приложения
app = Flask(__name__)

# Настройка логирования для отладки
logging.basicConfig(level=logging.DEBUG)

# Получение переменных окружения
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER")

# Проверка наличия обязательных переменных окружения
if not all([OPENAI_API_KEY, TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_NUMBER]):
    raise ValueError("Missing one or more required environment variables!")

# Инициализация клиента Twilio
twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# Инициализация клиента OpenAI
openai_client = OpenAI(
    api_key=OPENAI_API_KEY,
    # Прокси убраны, так как они вызывали ошибку
)

@app.route('/webhook', methods=['POST', 'GET'])
def webhook():
    start_time = time.time()
    try:
        if request.method == 'GET':
            return jsonify({"status": "ok"}), 200

        # Получение данных из запроса (только для POST)
        data = request.form
        from_number = data.get('From')
        message_body = data.get('Body')
        media_url = data.get('MediaUrl0')  # URL изображения от Twilio

        logging.debug(f"Received message from {from_number}: text={message_body}, media_url={media_url}")

        if not message_body and not media_url:
            return jsonify({"status": "error", "message": "No text or image provided"}), 400

        # Подготовка запроса к GPT
        if media_url:
            try:
                # Аутентифицированный запрос к Twilio для получения изображения
                response = requests.get(
                    media_url,
                    auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
                    timeout=10
                )
                response.raise_for_status()  # Проверка на ошибки (например, 401 или 404)
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 404:
                    logging.error(f"Image not found: {str(e)}")
                    gpt_response = "Answer: N/A"
                else:
                    raise  # Повторяем другие ошибки

            else:  # Если изображение успешно загружено
                # Загрузка изображения без обработки
                image = Image.open(BytesIO(response.content)).convert("RGB")
                buffered = BytesIO()
                image.save(buffered, format="PNG")  # Убрали quality=95
                img_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")

                # Новый промпт с уточнением
                prompt = """
You are a licensed California construction expert and professional exam instructor. Your task is to carefully analyze each question from the California General Building Contractor (Class B) license exam and select the most accurate answer.
Your answers must strictly follow California regulations, including the California Building Code (CBC), California OSHA standards, ADA guidelines, and CSLB exam practices.

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

Answer format:
Answer: [exact text of the correct answer option]

If the question or options are missing or unreadable, respond:
Answer: N/A
                """
                messages = [
                    {
                        "role": "system",
                        "content": prompt
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "Analyze the exam question in the provided image and select the correct answer based on California contractor standards."
                            },
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{img_base64}"}
                            }
                        ]
                    }
                ]

                # Получение ответа от GPT-4o
                start_gpt_time = time.time()
                gpt_response = ask_gpt(messages)
                gpt_time = time.time() - start_gpt_time
                logging.debug(f"GPT processing time: {gpt_time} seconds")

        else:
            # Для текстовых сообщений используем упрощенный промпт
            messages = [
                {
                    "role": "system",
                    "content": "You are an AI assistant designed to help with exam questions for contractors in California. Provide accurate answers based on California CSLB standards. Do NOT provide explanations; return only the answer in the format 'Answer: [exact text]' or 'Answer: N/A' if the question is invalid."
                },
                {
                    "role": "user",
                    "content": message_body
                }
            ]

            # Получение ответа от GPT-4o
            start_gpt_time = time.time()
            gpt_response = ask_gpt(messages)
            gpt_time = time.time() - start_gpt_time
            logging.debug(f"GPT processing time: {gpt_time} seconds")

        logging.debug(f"Answer from GPT: {gpt_response}")

        # Отправка ответа через WhatsApp
        send_whatsapp_message(from_number, gpt_response)
        logging.debug(f"Message sent to {from_number}")

        total_time = time.time() - start_time
        logging.debug(f"Total response time: {total_time} seconds")

        return jsonify({"status": "success"}), 200

    except requests.exceptions.RequestError as e:
        logging.error(f"Request error: {str(e)}")
        return jsonify({"status": "error", "message": f"Request failed: {str(e)}"}), 500
    except Exception as e:
        logging.error(f"Error in webhook: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

def ask_gpt(messages):
    try:
        logging.debug(f"OpenAI library version: {openai_version}")
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.2,  # Для максимальной точности
            max_tokens=1000,  # Оставляем 1000
            top_p=1.0,
            presence_penalty=0,
            frequency_penalty=0
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
    print("🚀 Bot is running and awake...")
    app.run(host="0.0.0.0", port=8080)
