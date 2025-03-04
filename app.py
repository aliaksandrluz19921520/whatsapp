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
openai_client = OpenAI(api_key=OPENAI_API_KEY)

@app.route('/webhook', methods=['POST'])
def webhook():
    start_time = time.time()
    try:
        # Получение данных из запроса
        data = request.form
        from_number = data.get('From')
        message_body = data.get('Body')
        media_url = data.get('MediaUrl0')  # URL изображения от Twilio

        logging.debug(f"Received message from {from_number}: text={message_body}, media_url={media_url}")

        if not message_body and not media_url:
            return jsonify({"status": "error", "message": "No text or image provided"}), 400

        # Подготовка запроса к GPT
        if media_url:
            # Аутентифицированный запрос к Twilio для получения изображения
            response = requests.get(
                media_url,
                auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
                timeout=10
            )
            response.raise_for_status()  # Проверка на ошибки (например, 401)

            # Загрузка изображения без обработки
            image = Image.open(BytesIO(response.content)).convert("RGB")
            buffered = BytesIO()
            image.save(buffered, format="PNG", quality=95)
            img_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")

            # Ваш текущий улучшенный prompt
            prompt = (
                "You are an AI assistant designed to help with exam questions for contractors in California. Your task is to analyze the provided image, identify the question and answer choices, and select the correct answer. Be thorough: pay close attention to the exact wording of the question (for example, note the difference between 'type of' and 'conditions where'). Multiple choices may be correct (e.g., A and C). If an option combines these (e.g., D = A and C), choose it as the most complete and accurate answer. Use logical reasoning and base your decision on California contractor licensing standards, safety practices, and general construction knowledge. Ignore unrelated text (such as interface elements or notes). Respond strictly in the following format: \nAnswer: [text of correct choice] \nIf no question or answer choices are found, or if the text is unreadable, respond with: \nAnswer: N/A \nIn case of uncertainty, prioritize the option most aligned with California contractor practices."
            )
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{img_base64}"}
                        }
                    ]
                }
            ]

        else:
            messages = [{"role": "user", "content": message_body}]

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

    except requests.exceptions.RequestException as e:
        logging.error(f"Error loading image: {str(e)}")
        return jsonify({"status": "error", "message": f"Failed to load image: {str(e)}"}), 500
    except Exception as e:
        logging.error(f"Error in webhook: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/webhook', methods=['GET'])
def webhook_check():
    return jsonify({"status": "ok"}), 200

def ask_gpt(messages):
    try:
        logging.debug(f"OpenAI library version: {openai_version}")
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            max_tokens=600
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
