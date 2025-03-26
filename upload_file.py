import os
from openai import OpenAI

# Инициализация клиента
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Функция для загрузки файла
def upload_file(file_path):
    try:
        with open(file_path, "rb") as file:
            response = openai_client.files.create(file=file, purpose="assistants")
        print(f"Файл загружен! ID: {response.id}")
        return response.id
    except Exception as e:
        print(f"Ошибка при загрузке: {e}")
        return None

# Загрузка файла
if __name__ == "__main__":
    file_id = upload_file("structured_output.txt")
    if file_id:
        print(f"Сохраните этот ID для использования: {file_id}")
    else:
        print("Не удалось загрузить файл. Проверьте путь и API ключ.")
