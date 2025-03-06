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

# Ручная инициализация клиента OpenAI
openai_client = OpenAI(
    api_key=OPENAI_API_KEY,
    # Убедитесь, что прокси не передаются, если они не нужны
    # Если нужны прокси, добавьте их явно, например:
    # http_client=SyncHttpxClientWrapper(proxies={"http": "http://proxy:port", "https": "http://proxy:port"})
)

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
                image.save(buffered, format="PNG", quality=95)
                img_base64 = base64.b64encode(buffered.getvalue()).decode("utf-8")

                # Новый промпт
                prompt = (
                    "You are an AI assistant designed to help with exam questions for contractors in California. Your task is to analyze the provided image, identify the exam question and answer choices, and select the most correct answer.\n\n"
                    "Follow these critical guidelines:\n\n"
                    "1. **Use only official California CSLB exam standards**. Prioritize CSLB codes, safety regulations, and licensing laws over real-world practices or assumptions.\n"
                    "2. **Pay close attention to precise wording** of the question (for example, distinguish between 'type of' and 'conditions where').\n"
                    "3. **For numerical values and standards** (such as measurements, sizes, slopes, and distances):\n"
                    "   - Always choose the exact numerical value that matches California construction codes.\n"
                    "   - Avoid estimates or rounding unless specified in the answer choices.\n"
                    "   - Use correct unit conversions (feet, inches, yards, etc.).\n"
                    "4. **For mathematical calculations** (areas, volumes, lengths):\n"
                    "   - Carefully apply the correct formulas.\n"
                    "   - Double-check units and conversions.\n"
                    "   - Select the answer closest to the exact calculation result, considering rounding only as necessary.\n"
                    "5. **When multiple options (e.g., A and C) are correct**, and there is a combined answer (like D = A and C), select the combined option as the most complete.\n"
                    "6. **For answers like 'All of the above' or 'None of the above'**, only choose them if ALL included statements are entirely correct or incorrect.\n"
                    "7. **For material selections**, choose the option that fully meets California building codes, environmental conditions, and safety standards.\n"
                    "8. **For safety-related questions**, select the answer that provides the highest level of safety and legal compliance, including health, insurance, and licensing topics.\n"
                    "9. **For accessibility and ADA compliance**, apply specific dimension requirements (e.g., hallway widths, landing sizes) accurately according to California code.\n"
                    "10. **For structural limits** (like cantilever lengths or anchor bolt spacing), use the exact values from California regulations.\n"
                    "11. **Ignore unrelated text** (such as system buttons, notes, or interface elements).\n"
                    "12. **If no valid question or answer choices are found, or if the image is unreadable**, respond with:\nAnswer: N/A\n\n"
                    "Respond strictly in this format: \nAnswer: [exact text of the correct answer]"
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

                # Получение ответа от GPT-4o
                start_gpt_time = time.time()
                gpt_response = ask_gpt(messages)
                gpt_time = time.time() - start_gpt_time
                logging.debug(f"GPT processing time: {gpt_time} seconds")

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

    except requests.exceptions.RequestError as e:
        logging.error(f"Request error: {str(e)}")
        return jsonify({"status": "error", "message": f"Request failed: {str(e)}"}), 500
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
