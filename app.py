import os
import logging
from flask import Flask, request, jsonify
from openai import OpenAI
from twilio.rest import Client

# OpenAI
client_openai = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

# Twilio
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWILIO_WHATSAPP_NUMBER = os.getenv('TWILIO_WHATSAPP_NUMBER')
client_twilio = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.form
    from_number = data.get('From')
    message_body = data.get('Body')

    logging.info(f"Сообщение от {from_number}: {message_body}")

    if message_body:
        gpt_response = ask_gpt(message_body)
        send_whatsapp_message(from_number, gpt_response)

    return jsonify({"status": "success"}), 200

@app.route('/webhook', methods=['GET'])
def webhook_check():
    return jsonify({"status": "ok"}), 200

def ask_gpt(text):
    response = client_openai.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": text}],
        max_tokens=100
    )
    return response.choices[0].message.content

def send_whatsapp_message(to, message):
    client_twilio.messages.create(
        from_=TWILIO_WHATSAPP_NUMBER,
        body=message,
        to=to
    )
    logging.info(f"Отправлено сообщение на {to}")

if __name__ == '__main__':
    print("🚀 Бот работает и не спит...")
    app.run(host='0.0.0.0', port=8080)
