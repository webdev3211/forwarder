from telethon import TelegramClient, events
import requests
import json
from io import BytesIO
import re
import threading
import os


api_id = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")
phone_number = os.getenv("PHONE_NUMBER")
IMGBB_API_KEY = os.getenv("IMGBB_API_KEY")
BASE_URL = os.getenv("BASE_URL")
SOURCE_CHANNEL_URL = os.getenv("SOURCE_CHANNEL_URL")
TEST_CHANNEL = os.getenv("TEST_CHANNEL")
CRON_TIMEOUT = int(os.getenv("CRON_TIMEOUT"))
ACCESS_TOKEN = os.getenv("TEST_CHANNEL")
REMEMBER_TOKEN = os.getenv("TEST_CHANNEL")



def trigger_cron_v2():
    def run():
        try:
            requests.get(BASE_URL + "/cron/v2", timeout=CRON_TIMEOUT)
            print("🚀 Triggered cron/v2")
        except requests.exceptions.RequestException as e:
            print("⚠️ Error triggering cron/v2:", e)
    threading.Thread(target=run).start()


def upload_image_to_imgbb(file_bytes):
    url = f"https://api.imgbb.com/1/upload?key={IMGBB_API_KEY}"
    files = {
        "image": file_bytes
    }

    try:
        response = requests.post(url, files=files)
        response.raise_for_status()
        json_response = response.json()
        image_url = json_response['data']['url']
        print("✅ Image uploaded to ImgBB:", image_url)
        return image_url
    except Exception as e:
        print("❌ Failed to upload image:", e)
        return ""



def modify_message(text):
    url = BASE_URL + '/api/change-deal-aff'
    payload = {
        "message": text,
        "accessToken": ACCESS_TOKEN,
        "rememberMeToken": REMEMBER_TOKEN,
        "bitlyConvert": True,
        "imageUrl": ""
    }

    headers = {'Content-Type': 'application/json'}

    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        return data.get("message")  # fallback to original if no 'message' in response
    except requests.RequestException as e:
        print("❌ Error from API:", e)
        return text  # return original message in case of error

def getStore(text):
    text = text.lower()

    if re.search(r"(amzn\.to|amazon\.)", text):
        return "Amazon"
    elif re.search(r"(fkrt\.to|fkrt\.cc|flipkart\.com|fkrt\.co)", text):
        return "Flipkart"
    elif re.search(r"(myntra\.com|myntr\.it|myntr\.cc|myntr\.in)", text):
        return "Myntra"
    elif re.search(r"(ajio\.com|ajio\.in|ajiio\.in)", text):
        return "Ajio"
    else:
        return "Amazon"  # Default


def save_to_db(modified_text, store, image_url=""):
    url = BASE_URL + "/dealapi"
    payload = {
        "deal": modified_text,
        "imgurl": image_url,
        "delay": "",
        "realmrp": "",
        "store": store
    }

    headers = {'Content-Type': 'application/json'}

    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        print("✅ Message saved to DB")
    except requests.RequestException as e:
        print("❌ Error saving to DB:", e)


client = TelegramClient('forwarder_session2', api_id, api_hash)

async def main():
    await client.start(phone=phone_number)

    await client.send_message(TEST_CHANNEL, "Hey, I have started ✅")

    # 👇 Resolve the source channel properly here
    source = await client.get_entity(SOURCE_CHANNEL_URL)  # or invite link / username

    @client.on(events.NewMessage(chats=source))
    async def handler(event):
        msg = event.message
        text = msg.message or ""

         # Handle media (images)
        image_url = ""
        if msg.media and not msg.photo:
            file_bytes = BytesIO()
            await client.download_media(msg.media, file=file_bytes)
            file_bytes.seek(0)
            image_url = upload_image_to_imgbb(file_bytes)


        modified_text = modify_message(text)
        print("Modified message success✅✅")
        print(modified_text)
        store = getStore(modified_text)
        print("Store fetched success✅✅")
        save_to_db(modified_text, store, image_url)
        trigger_cron_v2()
        print("Everything done sucessfully✅✅")

    print("Listening for messages...")
    await client.run_until_disconnected()

client.loop.run_until_complete(main())
