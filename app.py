import os
from flask import Flask, request, jsonify
from twilio.rest import Client
import openai

app = Flask(__name__)

# Настройки переменных окружения
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER")

# Инициализация клиента Twilio
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# Настройка API-ключа OpenAI
openai.api_key = OPENAI_API_KEY


@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.form
    from_number = data.get('From')
    message_body = data.get('Body')

    if message_body:
        gpt_response = ask_gpt(message_body)
        send_whatsapp_message(from_number, gpt_response)

    return jsonify({"status": "success"}), 200


@app.route('/webhook', methods=['GET'])
def webhook_check():
    return jsonify({"status": "ok"}), 200


def ask_gpt(text):
    response = openai.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": text}],
        max_tokens=100
    )
    return response.choices[0].message.content


def send_whatsapp_message(to, message):
    twilio_client.messages.create(
        from_=TWILIO_WHATSAPP_NUMBER,
        body=message,
        to=to
    )


if __name__ == "__main__":
    print("🚀 Бот работает и не спит...")
    app.run(host="0.0.0.0", port=8080)
