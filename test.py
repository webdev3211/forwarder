from telethon import TelegramClient, events
from telethon.tl.types import MessageMediaPhoto, MessageEntityTextUrl, PeerChannel
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from datetime import datetime


import requests
import json
import re
import threading
import os
import time
import traceback

from urllib.parse import urlparse, parse_qs, unquote
from collections import deque

api_id = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")
phone_number = os.getenv("PHONE_NUMBER")
IMGBB_API_KEY = os.getenv("IMGBB_API_KEY")
BASE_URL = os.getenv("BASE_URL")
BASE_URL_2 = os.getenv("BASE_URL_2")
TEST_CHANNEL = os.getenv("TEST_CHANNEL")
CRON_TIMEOUT = int(os.getenv("CRON_TIMEOUT"))
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
REMEMBER_TOKEN = os.getenv("REMEMBER_TOKEN")
channel_urls = os.getenv("SOURCE_CHANNELS").split(",")
USE_DEALAPI_V2 = int(os.getenv("USE_DEALAPI_V2"))
UNWANTED_KEYWORD = os.getenv("UNWANTED_KEYWORD").split(",")
private_channels = os.getenv("PRIVATE_CHANNELS").split(",")
TTL_SECONDS = int(os.getenv("TTL_SECONDS")) 
EXCLUDED_KEYWORDS = os.getenv("EXCLUDED_KEYWORDS").split(",")
DELETE_SLEEP_WAIT = int(os.getenv("DELETE_SLEEP_WAIT"))
WORKERS = int(os.getenv("WORKERS"))
DELETED_ID_TTL_SECONDS = int(os.getenv("DELETED_ID_TTL_SECONDS"))
HANDLE_DUPLICATES = os.getenv("HANDLE_DUPLICATES")
LINK_STORAGE_CACHE_DURATION = int(os.getenv("LINK_STORAGE_CACHE_DURATION"))
LINK_KEY_LENGTHS = json.loads(os.getenv("LINK_KEY_LENGTHS", "{}"))
UPDATE_WAIT_TIME = int(os.getenv("UPDATE_WAIT_TIME"))




LOCAL_TEST_BYPASS = False
executor = ThreadPoolExecutor(max_workers=WORKERS)  # Adjust based on expected parallel jobs
processed_links = {}
url_regex = r'(https?://[^\s]+)'
deleted_ids_memory = {}
unshortened_link_cache = {}
data_pushed_to_db = {}


executor_updates = ThreadPoolExecutor(max_workers=10)  # For update_messages API
executor_deletes = ThreadPoolExecutor(max_workers=5)    # For delayed deletes


def trigger_cron_v2(deal_id=None):
    def run():
        try:
            url = BASE_URL + "/cron/v2"
            start = datetime.now().strftime("%H:%M:%S")  # Current time in hh:mm:ss
            print(f"🚀 Started cron/v2 for deal_id={deal_id} at {start}")

            payload = {
                "triggerTime": start
            }

            if deal_id:
                payload["deal_id"] = deal_id

            response = requests.post(url, json=payload, timeout=CRON_TIMEOUT)
            end = datetime.now().strftime("%H:%M:%S")  # Current time in hh:mm:ss
            print(f"🚀 Finished cron/v2 for deal_id={deal_id} at {end} with tg_msg_id={tg_msg_id}")
            data_pushed_to_db[tg_msg_id] = True
        except requests.RequestException as e:
            print("⚠️ Error triggering cron/v2:", e)

    executor.submit(run)


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



def replace_text_links_with_urls(msg):
    if not msg.entities:
        return msg.message

    text = msg.message
    offset_adjustment = 0

    for entity in msg.entities:
        if isinstance(entity, MessageEntityTextUrl):
            start = entity.offset + offset_adjustment
            end = start + entity.length
            # Replace the anchor text with the raw URL
            text = text[:start] + entity.url + text[end:]
            # Adjust future offsets because replacement string length may differ
            offset_adjustment += len(entity.url) - entity.length

    return text



def modify_message(text, is_deal_over = False):
    if text is not None and len(text) > 0 and not is_deal_over:
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
            print("❌ Error from change-deal-aff API:", e)
            return text  # return original message in case of error
    else:
        return text

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



def checkIfCanUseDealApiV2(modified_text):
    try:
        word_count = len(modified_text.strip().split())

        excluded_keywords = EXCLUDED_KEYWORDS
        lower_text = modified_text.lower()

        # Block v2 if any excluded keyword is present
        if any(keyword in lower_text for keyword in excluded_keywords):
            print("Do not use V2 because keyword found")
            return False

        if "https://extp.in" in modified_text or "https://bitl.in" in modified_text:
            print("❌❌ Do not use V2 because Bitl/Extp link found ")
            return False

        if "grab" in modified_text or "fast" in modified_text:
            print("❌❌ Do not use V2 because grab/fast found ")
            return False

        # Allow v2 only if word count is >= 5
        return word_count >= 5

    except Exception as e:
        print("❌❌Some error in checkIfCanUseDealApiV2: ", e)

    return True

def save_to_db(modified_text, store, image_url="", tg_msg_id = ""):
    url = ""
    
    if USE_DEALAPI_V2 == 1 and checkIfCanUseDealApiV2(modified_text):
        url = BASE_URL + "/dealapi/v2"
    else:
        url = BASE_URL + "/dealapi"

    payload = {
        "deal": modified_text,
        "imgurl": image_url,
        "delay": "",
        "realmrp": "",
        "store": store,
        "tg_msg_id": tg_msg_id
    }

    headers = {'Content-Type': 'application/json'}

    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()

        response_data = response.json()
        deal_id = response_data.get("data", {}).get("_id", None)

        print("✅ Message saved to DB with _id:", deal_id)
        return deal_id
    except requests.RequestException as e:
        print("❌ Error saving to DB:", e)
        return None



def checkIfUnwantedText(text):
    try:
        text_lower = text.lower()

        # Check for unwanted keywords
        for keyword in UNWANTED_KEYWORD:
            if keyword.lower() in text_lower:
                print(f"🛑 Blocked message due to unwanted keyword: {keyword}")
                return True  # Early return if unwanted keyword found

        # Check for Telegram links
        if "https://t.me" in text_lower or "t.me/" in text_lower:
            print("❌ Telegram link found, skipping message:", text)
            return True

        if text_lower == "back" or text_lower == "loot":
            print("❌ Only back/loot msg no link:", text)
            return True 

        return False  # Clean message
    except Exception as e:
        print("Error occurred in checkIfUnwantedText:", e)
        return False


def checkIfDealIsOver(text):
    text_lower = text.lower()
    if "over" in text_lower:
        print("🗑️ Deal over revoke MSG")
        return True  
    unwanted_keywords_added_during_update =  checkIfUnwantedText(text)
    if unwanted_keywords_added_during_update:
        print("🗑️ Unwanted keyword added during update revoke MSG")
        return True
    return False


async def check_if_msg_has_image(msg):
    photo_media = None
    
    try:
        # Case 1: Photo in the main message
        if isinstance(msg.media, MessageMediaPhoto):
            photo_media = msg.media
        # Case 2: Photo in the replied-to message
        elif msg.reply_to_msg_id:
            try:
                replied_msg = await msg.get_reply_message()
                if isinstance(replied_msg.media, MessageMediaPhoto):
                    photo_media = replied_msg.media
            except Exception as e:
                print(f"⚠️ Could not fetch reply message media: {e}")

        if photo_media is None:
            return False
        else:
            return True
    except Exception as e:
        return False


async def upload_photo_get_url(msg):
    photo_media = None
    image_url = ""
    
    try:
        # Case 1: Photo in the main message
        if isinstance(msg.media, MessageMediaPhoto):
            photo_media = msg.media
        # Case 2: Photo in the replied-to message
        elif msg.reply_to_msg_id:
            try:
                replied_msg = await msg.get_reply_message()
                if isinstance(replied_msg.media, MessageMediaPhoto):
                    photo_media = replied_msg.media
            except Exception as e:
                print(f"⚠️ Could not fetch reply message media: {e}")

        # Step 2: Download photo if available
        if photo_media:
            print("✅ Photo found, downloading...")
            file_bytes = BytesIO()
            await client.download_media(photo_media, file=file_bytes)
            file_bytes.seek(0)
            image_url = upload_image_to_imgbb(file_bytes)
        else:
            image_url = ""
    except Exception as e:
        print("❌ Error Uploading Image to imgbb:", e)
    
    return image_url


def get_chat_and_msg_ids_from_db(msg_id):
    url = BASE_URL_2 + f"/alldeals/get-chatids/{msg_id}"  # <-- make sure the URL matches your Express route

    try:
        response = requests.get(url)
        response.raise_for_status() 
        data = response.json()

        if data.get("success"):
            return data
        else:
            print("⚠️ Failed to fetch chat and msg ids:", data.get("message"))
            return None

        return None
    except requests.exceptions.RequestException as e:
        print("❌ Error fetching chatandmsgids:", e)
        return None
    except ValueError:
        print("❌ Response is not valid JSON.")
        return None


def update_forwarded_messages_sync(chat_and_msg_ids, modified_text, imgUrl):
    def run():
        print("Doing update for text = ", modified_text)
        api_url = BASE_URL + "/cron/update-messages"
        payload = {
            "chatandmsgids": chat_and_msg_ids,
            "text": modified_text,
            "imgUrl": imgUrl
        }

        print("Hitting: ", api_url)

        try:
            response = requests.post(api_url, json=payload, timeout=CRON_TIMEOUT)
            if response.status_code == 200:
                data = response.json()
                if data.get("success"):
                    print(f"✅ Successfully updated all messages: {data.get('message')}")
                else:
                    print(f"⚠️ Partial failure: {data.get('message')}")
            else:
                print(f"❌ Failed to update messages, HTTP status: {response.status_code}")
        except Exception as e:
            print(f"❌ Exception during update request: {e}")

    executor_updates.submit(run)


def update_message_in_db(deal_id, modified_text):
    url = f"{BASE_URL_2}/alldeals/updatedealtext/{deal_id}"
    payload = {
        "text": modified_text
    }
    headers = {
        'Content-Type': 'application/json'
    }

    try:
        response = requests.put(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        if data.get("success"):
            print(f"✅ Deal {deal_id} updated successfully in DB.")
        else:
            print(f"⚠️ Failed to update deal {deal_id}: {data.get('message')}")
    except requests.RequestException as e:
        print(f"❌ Error while updating deal {deal_id}: {e}")



def checkServerHealth():
    url = BASE_URL_2 + "/healthcheck"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            print("✅ Btdaily is healthy:", response.text)
            return True
        else:
            print(f"⚠️ Server responded with status code {response.status_code}")
            return False
    except requests.RequestException as e:
        print("❌ Server health check failed:", e)
        return False




def extract_first_url(text):
    match = re.search(url_regex, text)
    return match.group(1) if match else None

def is_already_processed_by_url(text):
    url = extract_first_url(text)
    now = time.time()

    # Cleanup expired entries
    expired_keys = [k for k, v in processed_links.items() if now - v > TTL_SECONDS]
    for k in expired_keys:
        del processed_links[k]

    if url and url in processed_links:
        return True

    if url:
        processed_links[url] = now
    
    return False


def get_unique_actual_deleted_ids(deleted_ids):
    try:
        now = time.time()

        # Cleanup old deleted IDs
        expired_ids = [msg_id for msg_id, ts in deleted_ids_memory.items() if now - ts > DELETED_ID_TTL_SECONDS]
        for msg_id in expired_ids:
            del deleted_ids_memory[msg_id]

        new_ids = []
        for msg_id in deleted_ids:
            if msg_id not in deleted_ids_memory:
                deleted_ids_memory[msg_id] = now
                new_ids.append(msg_id)
            else:
                print(f"🛑 Skipping duplicate deletion for msg_id: {msg_id}")

        if not new_ids:
            print("🚫 No new IDs to delete, skipping task.")
            return []
            
        return new_ids
    except Exception as e:
        print("❌❌ Some error while deleting from memory: ", e)
        return deleted_ids


def handle_deletes_after_delay(deleted_ids):
    try:
        print("⌛ Sleeping before deletion...")
        time.sleep(DELETE_SLEEP_WAIT)
        print("⏰ Awake! Now calling delete.")
        handle_delete_instant(deleted_ids)
    except Exception as e:
        import traceback
        print("❌ Exception in handle_deletes_after_delay:", traceback.format_exc())



def handle_delete_instant(deleted_ids):
    deleted_ids = get_unique_actual_deleted_ids(deleted_ids)
    print("🚀 Msg ID submitted for deletion: ", deleted_ids)

    for msg_id in deleted_ids:
        alldeals_data = get_chat_and_msg_ids_from_db(msg_id)

        if alldeals_data is not None:
            chat_and_msg_ids = alldeals_data.get("chatandmsgids")
            if not chat_and_msg_ids:
                print("⚠️ No message mapping found to be deleted, skipping...")
                continue
            else:
                BTDAILY_DEAL_ID = alldeals_data.get("id")
                text = alldeals_data.get("deal") + " OVER "

                update_forwarded_messages_sync(chat_and_msg_ids, text, "")
                print("DELETED MSG_ID: ", msg_id)
        else:
            print(f"❗No DB mapping for msg_id {msg_id} even after delay.")



def clean_old_links_cache():
    now = time.time()
    keys_to_remove = [k for k, v in unshortened_link_cache.items() if now - v[0] > LINK_STORAGE_CACHE_DURATION]
    for k in keys_to_remove:
        del unshortened_link_cache[k]


def unshorten_url(extracted_url):
    url = f"{BASE_URL}/api/unshortenafflink"
    payload = {
        "link": extracted_url
    }
    headers = {
        'Content-Type': 'application/json'
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout = 10)
        response.raise_for_status()
        data = response.json()

        if data.get("success"):
            return data.get("url")
        else:
            print("Failed unshortening url: ", extracted_url)
            return None
    except Exception as e:
        print("❌❌ Some error while unshortening url: ", e)
        return None



def extract_first_url(text):
    match = re.search(r'(https?://[^\s]+)', text)
    return match.group(1) if match else None



def unwanted_tracking_trail_exists(url):
    if "linksredirect" in url or "linkredirect" in url or "tracking.ajio.business" in url or "myntra.onelink.me" in url:
        return True
    return False


def extract_real_url_if_wrapped(url):
    if unwanted_tracking_trail_exists(url):
        print("it is either linkredirect or ajio or myntra link")
        parsed = urlparse(url)
        query_params = parse_qs(parsed.query)

        # Check for known redirect parameters
        for param in ["dl", "redirect", "u", "url", "target", "af_ios_url"]:
            if param in query_params:
                # Return the first occurrence, decoded
                return unquote(query_params[param][0])

        return url
    else:
        return url


def storeFirstLinkAndCheckIfDuplicate(text):
    try:
        clean_old_links_cache()

        url_extracted = extract_first_url(text)
        if not url_extracted:
            return False

        long_url = unshorten_url(url_extracted)
        long_url = extract_real_url_if_wrapped(long_url)

        print(f"url_extracted:  {url_extracted} and its long_url: {long_url}")

        if long_url is None or unwanted_tracking_trail_exists(long_url):
            return False

        key = None

        AMAZON_LENGTH = LINK_KEY_LENGTHS.get("amazon", 30)
        FLIPKART_LENGTH = LINK_KEY_LENGTHS.get("flipkart", 30)
        MYNTRA_LENGTH = LINK_KEY_LENGTHS.get("myntra", 40)
        AJIO_LENGTH = LINK_KEY_LENGTHS.get("ajio", 40)

        if "amazon" in long_url:
            match = re.search(r"(https?://[^ ]+/(?:dp|d)/[^/?]+)", long_url)
            if match:
                key = match.group(1)[:35]
            else:
                key = long_url[0:AMAZON_LENGTH]
        elif "flipkart" in long_url and "pid=" in long_url:
            match = re.search(r"pid=([A-Z0-9]{16})", long_url)
            if match:
                key = match.group(1)  # just the 16-char product ID
            else:
                key = long_url[0:FLIPKART_LENGTH]
        elif "myntra" in long_url:
            key = long_url[0:MYNTRA_LENGTH]
        elif "ajio" in long_url:
            key = long_url[0:AJIO_LENGTH]

        if key is None:
            return False

        # Fast check
        if key in unshortened_link_cache:
            print(f"🛑 Exact duplicate: {key}")
            return True

        # Fuzzy check
        for existing_key in unshortened_link_cache:
            if not existing_key or existing_key == key:
                continue
            if key in existing_key or existing_key in key:
                print(f"🛑 Fuzzy duplicate: {key} ~ matches {existing_key}")
                return True

        # Store new
        unshortened_link_cache[key] = (time.time(), long_url)
        print(f"✅ Stored new deal key: {key}")
        return False

    except Exception as e:
        print("❌❌ Some error at storeFirstLinkAndCheckIfDuplicate: ", e)
        return False





def do_update_operations_after_delay(edited_msg, text, is_deal_over):
    time.sleep(UPDATE_WAIT_TIME)
    do_update_operations(edited_msg, text, is_deal_over)



def do_update_operations(edited_msg, text, is_deal_over):
    image_url = ""

    BTDAILY_DEAL_ID = None

    modified_text = modify_message(text, is_deal_over)
    store = getStore(modified_text)

    alldeals_data = get_chat_and_msg_ids_from_db(edited_msg.id)

    if alldeals_data is not None:
        chat_and_msg_ids = alldeals_data.get("chatandmsgids")
        if not chat_and_msg_ids:
            print("⚠️ No forwarded message mapping found, skipping...")
            return
        BTDAILY_DEAL_ID = alldeals_data.get("id")
        image_url = alldeals_data.get("imgurl")
    else:
        return

    update_forwarded_messages_sync(chat_and_msg_ids, modified_text, image_url)
    update_message_in_db(BTDAILY_DEAL_ID, modified_text)




client = TelegramClient('forwarder_session2', api_id, api_hash)


async def main():
    await client.start(phone=phone_number)
    await client.send_message(TEST_CHANNEL, "PROD: Hey, I have started ✅")

    sources = []
    for url in channel_urls:
        try:
            entity = await client.get_entity(url.strip())
            sources.append(entity)
        except Exception as e:
            print(f"⚠️ Failed to fetch entity for {url.strip()}: {e}")


    for channel_id in private_channels:
        try:
            entity = await client.get_entity(PeerChannel(int(channel_id)))
            sources.append(entity)
        except Exception as e:
            print(f"⚠️ Failed to fetch private entity for ID {channel_id}: {e}")

    print("No of sources: ", len(sources))


    @client.on(events.NewMessage(chats=sources))
    async def handler(event):
        try:
            msg = event.message
            text = replace_text_links_with_urls(msg)
            tg_msg_id = msg.id

            checkServerHealth()

            if checkIfUnwantedText(text):
                print("❌ Msg contain unwanted things so dropping: " + text)
                return

            if not LOCAL_TEST_BYPASS:
                if is_already_processed_by_url(text):
                    print("⚠️ Duplicate message based on URL, skipping...")
                    return

            if HANDLE_DUPLICATES is True or HANDLE_DUPLICATES == "True":
                has_duplicate = storeFirstLinkAndCheckIfDuplicate(text)
                if has_duplicate:
                    print("⚠️ Duplicate message sent by diff sources, skipping..." + text)
                    return

            image_url = await upload_photo_get_url(msg)

            modified_text = modify_message(text, False)
            print("Modified message success✅✅ ", modified_text)

            if checkIfUnwantedText(text):
                print("❌ Modified Msg contain unwanted things so dropping: " + text)
                return

            store = getStore(modified_text)
            print("Store fetched success✅✅")

            deal_id = save_to_db(modified_text, store, image_url, tg_msg_id)
            if deal_id is not None:
                trigger_cron_v2(deal_id)

            print("Everything done successfully ✅✅")

        except Exception as e:
            print("❌ Error in message handler:", e)


    @client.on(events.MessageEdited(chats=sources))
    async def edited_handler(event):
        try:
            edited_msg = event.message
            print("✏️ Message was edited!")

            checkServerHealth()

            text = replace_text_links_with_urls(edited_msg)
            is_deal_over = checkIfDealIsOver(text)

            
            if data_pushed_to_db.get(edited_msg.id):
                do_update_operations(edited_msg, text, is_deal_over)
            else:
                print("Once trying update directly")
                do_update_operations(edited_msg, text, is_deal_over)
                print(f"⏳Data is stilL not pushed to db, wait {UPDATE_WAIT_TIME}s before updating")
                executor_updates.submit(do_update_operations_after_delay, edited_msg, text, is_deal_over)

        except Exception as e:
            print("❌ Error in edited_handler:", e)


    @client.on(events.MessageDeleted(chats=sources))
    async def delete_handler(event):
        try:
            deleted_id = event.deleted_id
            print(f"🗑️ Message(s) deleted: {deleted_id}")

            checkServerHealth()

            # Submit the delayed task to a thread
            if data_pushed_to_db.get(deleted_id):
                handle_delete_instant([deleted_id])
            else:
                print("Once trying delete directly")
                handle_delete_instant([deleted_id])
                print(f"⏳Data is stilL not pushed to db, wait {DELETE_SLEEP_WAIT}s before delete")
                executor_deletes.submit(handle_deletes_after_delay, [deleted_id])

        except Exception as e:
            print("❌ Error in delete_handler:", e)


    print("Listening for messages...")
    await client.run_until_disconnected()

client.loop.run_until_complete(main())
