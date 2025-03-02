import os
import logging
from flask import Flask, request, jsonify
from twilio.rest import Client
import openai

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

# Проверяем переменные окружения
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWILIO_WHATSAPP_NUMBER = os.getenv('TWILIO_WHATSAPP_NUMBER')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_NUMBER, OPENAI_API_KEY]):
    raise Exception("❌ ERROR: Одна из переменных окружения не указана!")

# Инициализация клиентов
client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
openai.api_key = OPENAI_API_KEY

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.form
    from_number = data.get('From')
    message_body = data.get('Body')

    logging.info(f"📩 Сообщение от {from_number}: {message_body}")

    if message_body:
        gpt_response = ask_gpt(message_body)
        send_whatsapp_message(from_number, gpt_response)

    return jsonify({"status": "success"}), 200


def ask_gpt(text):
    response = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": text}],
        max_tokens=100
    )
    return response.choices[0].message.content


def send_whatsapp_message(to, message):
    message = client.messages.create(
        from_=TWILIO_WHATSAPP_NUMBER,
        body=message,
        to=to
    )
    logging.info(f"✅ Отправлено сообщение {message.sid} на {to}")


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
