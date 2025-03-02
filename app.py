import os
import base64
import io
import logging
from flask import Flask, request, jsonify
import requests
import openai
from PIL import Image

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

openai.api_key = os.getenv("OPENAI_API_KEY")
whatsapp_token = os.getenv("WHATSAPP_TOKEN")
whatsapp_phone_id = os.getenv("PHONE_ID")
whatsapp_api_url = f"https://graph.facebook.com/v20.0/{whatsapp_phone_id}/messages"

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    logging.info(f"Получены данные: {data}")
    
    if not data or 'entry' not in data:
        return jsonify({"status": "error", "message": "Invalid webhook data"}), 400

    for entry in data['entry']:
        for change in entry['changes']:
            value = change['value']
            if 'messages' in value:
                message = value['messages'][0]
                from_number = message['from']
                msg_id = message['id']

                if message['type'] == 'text':
                    text = message['text']['body']
                    response = process_with_gpt(text=text)
                    send_whatsapp_response(from_number, response)

                elif message['type'] == 'image':
                    image_id = message['image']['id']
                    image_url = f"https://graph.facebook.com/v20.0/{image_id}/media?access_token={whatsapp_token}"
                    image_response = requests.get(image_url)
                    img_data = requests.get(image_response.json()['url']).content
                    image = Image.open(io.BytesIO(img_data))
                    response = process_with_gpt(image=image)
                    send_whatsapp_response(from_number, response)

    return jsonify({"status": "success"}), 200

def process_with_gpt(text=None, image=None):
    if image:
        img_byte_arr = io.BytesIO()
        image.save(img_byte_arr, format='PNG')
        img_bytes = img_byte_arr.getvalue()
        img_base64 = base64.b64encode(img_bytes).decode('utf-8')

        messages = [
            {"role": "user", "content": [
                {"type": "text", "text": "На фото есть варианты ответов (A, B, C, D). Определи правильный вариант и верни только букву."},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_base64}"}}
            ]}
        ]
    else:
        messages = [
            {"role": "user", "content": f"Обработай текст и дай ответ: {text}"}
        ]

    response = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=messages,
        max_tokens=100
    )
    return response.choices[0].message.content

def send_whatsapp_response(to, message):
    headers = {
        "Authorization": f"Bearer {whatsapp_token}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message}
    }
    response = requests.post(whatsapp_api_url, json=payload, headers=headers)
    if response.status_code != 200:
        logging.error(f"Ошибка отправки: {response.text}")

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8080)
