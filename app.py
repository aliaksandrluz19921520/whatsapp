import os
from flask import Flask, request, jsonify
from twilio.rest import Client as TwilioClient
from openai import OpenAI
import logging

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
    try:
        # Получение данных из запроса
        data = request.form
        from_number = data.get('From')
        message_body = data.get('Body')

        logging.debug(f"Получено сообщение от {from_number}: {message_body}")

        if not message_body:
            return jsonify({"status": "error", "message": "Нет текста сообщения"}), 400

        # Получение ответа от GPT-4o
        gpt_response = ask_gpt(message_body)
        logging.debug(f"Ответ от GPT: {gpt_response}")

        # Отправка ответа через WhatsApp
        send_whatsapp_message(from_number, gpt_response)
        logging.debug(f"Сообщение отправлено пользователю {from_number}")

        return jsonify({"status": "success"}), 200

    except Exception as e:
        logging.error(f"Ошибка в webhook: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/webhook', methods=['GET'])
def webhook_check():
    return jsonify({"status": "ok"}), 200

def ask_gpt(text):
    try:
        logging.debug(f"Версия библиотеки OpenAI: {OpenAI.__version__}")
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": text}],
            max_tokens=100
        )
        return response.choices[0].message.content
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
