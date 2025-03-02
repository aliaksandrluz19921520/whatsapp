from flask import Flask, request, jsonify
import os
import requests
import threading
import time
import logging
from twilio.rest import Client
import openai

# Конфиг
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWILIO_WHATSAPP_NUMBER = os.getenv('TWILIO_WHATSAPP_NUMBER')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
openai.api_key = OPENAI_API_KEY

app = Flask(__name__)

# Keep-alive, чтобы Railway не засыпал
def keep_alive():
    while True:
        try:
            requests.get('https://web-production-a0d0.up.railway.app/webhook')
            logging.info("🔄 Keep-alive запрос отправлен.")
        except Exception as e:
            logging.error(f"❌ Ошибка keep-alive: {e}")
        time.sleep(300)  # Пинг каждые 5 минут

threading.Thread(target=keep_alive, daemon=True).start()


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
    logging.info(f"✅ Ответ отправлен {to}, SID: {message.sid}")


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
