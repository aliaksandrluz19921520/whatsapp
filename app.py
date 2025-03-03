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
    raise ValueError("Отсутствует одна или несколько обязательных переменных окружения!")

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

        logging.debug(f"Получено сообщение от {from_number}: текст={message_body}, media_url={media_url}")

        if not message_body and not media_url:
            return jsonify({"status": "error", "message": "Нет текста или изображения"}), 400

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

            # Уточненный prompt для экзаменационных вопросов
            prompt = (
                "Проанализируй изображение, найди вопрос и варианты ответов. "
                "Ответь на вопрос, выбрав правильный вариант согласно строительным законам Калифорнии для General Contractor (Class B). "
                "Ответь строго в формате: \nОтвет: [текст правильного варианта]  \n"
                "Если вопроса нет, напиши: \nОтвет: N/A"
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
        logging.debug(f"Время обработки GPT: {gpt_time} секунд")

        logging.debug(f"Ответ от GPT: {gpt_response}")

        # Отправка ответа через WhatsApp
        send_whatsapp_message(from_number, gpt_response)
        logging.debug(f"Сообщение отправлено пользователю {from_number}")

        total_time = time.time() - start_time
        logging.debug(f"Общее время ответа: {total_time} секунд")

        return jsonify({"status": "success"}), 200

    except requests.exceptions.RequestException as e:
        logging.error(f"Ошибка при загрузке изображения: {str(e)}")
        return jsonify({"status": "error", "message": f"Не удалось загрузить изображение: {str(e)}"}), 500
    except Exception as e:
        logging.error(f"Ошибка в webhook: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/webhook', methods=['GET'])
def webhook_check():
    return jsonify({"status": "ok"}), 200

def ask_gpt(messages):
    try:
        logging.debug(f"Версия библиотеки OpenAI: {openai_version}")
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            max_tokens=600
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logging.error(f"Ошибка в ask_gpt: {str(e)}")
        raise

def send_whatsapp_message(to, message):
    try:
        twilio_client.messages.create(
            from_=TWILIO_WHATSAPP_NUMBER,
            body=message,
            to=to
        )
    except Exception as e:
        logging.error(f"Ошибка в send_whatsapp_message: {str(e)}")
        raise

if __name__ == "__main__":
    print("🚀 Бот работает и не спит...")
    app.run(host="0.0.0.0", port=8080)
