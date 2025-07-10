from telethon import TelegramClient, events
from telethon.tl.types import MessageMediaPhoto, MessageEntityTextUrl, PeerChannel
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from datetime import datetime, timedelta


import requests
import json
import re
import threading
import os
import time
import traceback
import tempfile
import random

from urllib.parse import urlparse, parse_qs, unquote
from collections import deque

import cloudinary
import cloudinary.uploader
from io import BytesIO


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
DELETE_CHANNEL_ID = int(os.getenv("DELETE_CHANNEL_ID"))
DELETE_CHANNEL_URL = os.getenv("DELETE_CHANNEL_URL")
POST_TO_TWITTER = os.getenv("POST_TO_TWITTER")
STOP_FLIPKART_LINKS = os.getenv("STOP_FLIPKART_LINKS")
TWITTER_MINS_TO_WAIT = int(os.getenv("TWITTER_MINS_TO_WAIT"))
TWITTER_ACCOUNTS = os.getenv("TWITTER_ACCOUNTS").split(",")
TG_WAIT = os.getenv("TG_WAIT")
WAIT_BEFORE_NEXT_DEAL = int(os.getenv("WAIT_BEFORE_NEXT_DEAL"))
TWITTER_REACTIONS = os.getenv("TWITTER_REACTIONS")
NO_OF_RETRIES = int(os.getenv("NO_OF_RETRIES"))
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_TEST_CHANNEL_ID = os.getenv("TG_TEST_CHANNEL_ID")
CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME")
CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY")
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET")




LOCAL_TEST_BYPASS = False
executor = ThreadPoolExecutor(max_workers=WORKERS)  # Adjust based on expected parallel jobs
processed_links = {}
url_regex = r'(https?://[^\s]+)'
deleted_ids_memory = {}
unshortened_link_cache = {}
data_pushed_to_db = {}
last_tweet_time = {"timestamp": None}
last_deal_time = {"timestamp": None}
SUCCESS = "success"
FAILED = "failed"
ACCOUNTS = TWITTER_ACCOUNTS
ACCOUNT_TO_URL_MAP = {
    "EmhDeals24": "https://frcp.onrender.com", #Oregon (US West)
    "jyotbaheti96": "https://offerzone-u7ik.onrender.com", #Oregon (US West) Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1
    "DealsJunction24": "https://thedealsjunction.webdev3211.workers.dev", # FrankFrut Mozilla/5.0 (Macintosh; Intel Mac OS X 13_3) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36
    "TheDealsValley": "https://dealsvalleyzone.webdev3211.workers.dev",
    "Yogeshbaheti94": "https://fastestlootdealsindia.webdev3211.workers.dev",
    "PuspaBaheti": "https://dealzwala.up.railway.app",
    "OfferZoneDaily": "https://offerzonedaily.onrender.com",
    "SastaDealsIndia": "https://sastadealshub.netlify.app"  



    # no creds added
    # "OfferBox": "https://dealsvalley.deno.dev" #some issue here please check later
    # "CouponHub": "https://couponhub-delta.vercel.app/api"
    # "LootDealsWorld": "https://fastestlootdeals.kiyagujral4128.workers.dev"
    # "C": "https://c.com",
    # "D": "https://d.com",
    # "E": "https://e.com"
}

ACCOUNT_TO_HAS_RETRY_FUNCTIONALITY_MAP = {
    "EmhDeals24": True,
}

scorecard = {item: 0 for item in ACCOUNTS}
# Step 1: Configure Cloudinary
cloudinary.config(
    cloud_name=CLOUDINARY_CLOUD_NAME,
    api_key=CLOUDINARY_API_KEY,
    api_secret=CLOUDINARY_API_SECRET,  # Replace this
    secure=True
)


executor_updates = ThreadPoolExecutor(max_workers=10)  # For update_messages API
executor_deletes = ThreadPoolExecutor(max_workers=5)    # For delayed deletes



def trigger_cron_v2(deal_id=None, tg_msg_id="", modified_text="", imageUrl=None):
    def run():
        try:
            url = BASE_URL + "/cron/v2"
            start = datetime.now().strftime("%H:%M:%S")
            print(f"🚀 Started cron/v2 for deal_id={deal_id} at {start}")

            payload = {
                "triggerTime": start
            }

            if deal_id:
                payload["deal_id"] = deal_id

            response = requests.post(url, json=payload, timeout=CRON_TIMEOUT)
            end = datetime.now().strftime("%H:%M:%S")
            print(f"🚀 Finished cron/v2 for deal_id={deal_id} at {end} with tg_msg_id={tg_msg_id}")
            data_pushed_to_db[tg_msg_id] = True

            # ✅ Post to Twitter only if there are 5+ words AND 1 hour has passed
            if (
                (POST_TO_TWITTER is True or POST_TO_TWITTER == "True") and
                len(modified_text.strip().split()) >= 5
            ):
                now = datetime.now()
                last_time = last_tweet_time.get("timestamp")

                if last_time is None or (now - last_time) >= timedelta(minutes=TWITTER_MINS_TO_WAIT):
                    post_deal_to_twitter(modified_text, imageUrl)
                    last_tweet_time["timestamp"] = now
                else:
                    print(f"⏳ Skipping Twitter post — {TWITTER_MINS_TO_WAIT} mins not yet passed since last post.")

        except requests.RequestException as e:
            print("⚠️ Error triggering cron/v2:", e)

    executor.submit(run)



def post_deal_to_twitter(text, imageUrl):
    if text is not None and len(text) > 0:
        url = BASE_URL + '/dealapi/fetch-enhanced-deal'
        payload = {
            "deal": text,
        }

        headers = {'Content-Type': 'application/json'}

        tweet_text = text  
        image_url = imageUrl  

        try:
            response = requests.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

            if data.get("success") and data.get("dealText"):
                tweet_text = data.get("dealText")

        except Exception as e:
            print("❌ Error from fetch-enhanced-deal API:", e)

        finally:
            save_to_tweet_db(tweet_text, image_url)



def save_to_tweet_db(text, image_url = None):
    url = BASE_URL + "/tweetapi"

    payload = {
        "deal": text,
        "imgurl": image_url,
        "action": "NO_ACTION"
    }

    headers = {'Content-Type': 'application/json'}

    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()

        response_data = response.json()
        deal_id = response_data.get("data", {}).get("_id", None)
        print("✅ Saved to Tweet DB with _id:", deal_id)
        check_all_twitter_apis_server_health()
        process_entries()
    except Exception as e:
        print("❌ Error saving to Tweet DB:", e)
        return None



def get_deal_by_id(deal_id):
    url = BASE_URL + f"/tweetapi/{deal_id}"  
    try:
        response = requests.get(url)
        if response.status_code == 200:
            json_data = response.json()
            if json_data.get("success"):
                return json_data["data"]
            else:
                return None
                print("Failed:", json_data.get("message"))
        else:
            return None
            print("HTTP error:", response.status_code)
    except Exception as e:
        print("Error occured while getting deal by id:", e)
        return None

def update_entry_action(deal_id, action, tweet_id=None, tweeted_by=None, tweet_action_taken_by= None, is_completed = False):
    payload = {"action": action}
    if tweet_id:
        payload["tweet_id"] = tweet_id
    if tweeted_by:
        payload["tweeted_by"] = tweeted_by
    if tweet_action_taken_by:
        payload["tweet_action_taken_by"] = tweet_action_taken_by
    if is_completed:
        payload["is_completed"] = is_completed
    try:
        response = requests.put(f"{BASE_URL}/tweetapi/{deal_id}", json=payload)
    except Exception as e:
        print(f"[ERROR] Failed to update action: {e}")


def delete_old_entries():
    url = BASE_URL + "/tweetapi" + "/cleanup"
    try:
        res = requests.delete(url)
        print("🗑️ Deleted old entries:", res.status_code)
    except Exception as e:
        print("❌ Error deleting old entries:", e)

def delete_entry(entry_id):
    try:
        url = f"{BASE_URL}/tweetapi/{entry_id}"
        response = requests.delete(url)
        print(f"🗑️ Deleted entry {entry_id}")
    except Exception as e:
        print(f"❌ Error deleting entry {entry_id}:", e)


def fetch_entries():
    try:
        response = requests.get(BASE_URL + "/tweetapi")
        response.raise_for_status()
        data = response.json().get("data", [])
        return data  # already sorted from backend
    except Exception as e:
        print("❌ Error fetching entries:", e)
        return []


def call_generate_quote_or_comment(deal, action):
    url = BASE_URL + "/tweetapi" + "/generate-quote-or-comment"
    try:
        res = requests.post(url, json={"deal": deal, "action": action})
        res.raise_for_status()
        return res.json().get("content", "")
    except Exception as e:
        print("❌ Error generating quote/comment:", e)
        return deal


def try_action_with_multiple_accounts(action_fn, tweet_id, deal_text=None, username=None, post_owner_username=None,deal_id=None):
    attempted_accounts = set()
    if action_fn != "tweet":
        if post_owner_username is not None:
            attempted_accounts.add(post_owner_username)
    
    for _ in range(NO_OF_RETRIES):
        available_accounts = [a for a in ACCOUNTS if a not in attempted_accounts]
        if not available_accounts:
            break
        account = pick_item(allowed=available_accounts)
        base_url = ACCOUNT_TO_URL_MAP[account]
        attempted_accounts.add(account)

        if action_fn == "tweet":
            tweet_id_result, success = tweet_function_retry(tweet_id, deal_text, account, base_url)
            if success:
                return SUCCESS, tweet_id_result, account
        elif action_fn == "retweet":
            if retweet_function(tweet_id, username, base_url, account) == SUCCESS:
                return SUCCESS, None, account
            else:
                print(f"[RETRY] {action_fn.upper()} attempt failed by {account}")
        elif action_fn == "like":
            if like_function(tweet_id, username, base_url, account) == SUCCESS:
                return SUCCESS, None, account
            else:
                print(f"[RETRY] {action_fn.upper()} attempt failed by {account}")
        elif action_fn == "quote":
            content = call_generate_quote_or_comment(deal_text, "QUOTE")
            if quote_function(tweet_id, content, username, base_url, account) == SUCCESS:
                return SUCCESS, None, account
            else:
                print(f"[RETRY] {action_fn.upper()} attempt failed by {account}")
        elif action_fn == "comment":
            content = call_generate_quote_or_comment(deal_text, "COMMENT")
            if comment_function(tweet_id, content, base_url, post_owner_username, account) == SUCCESS:
                return SUCCESS, None, account
            else:
                print(f"[RETRY] {action_fn.upper()} attempt failed by {account}")

    # After 3 failed attempts
    if deal_id:
        delete_entry(deal_id)
    return FAILED, None, None



def tweet_function_retry(deal_id, deal_text, account, base_url):
    payload = {"text": deal_text}
    tweet_id = None
    try:
        res = requests.post(f"{base_url}/autotweet/tweet", json=payload, timeout=15)
        if res.ok and res.json().get("success"):
            tweet_id = res.json()["id"]
        else:
            raise Exception("Standard tweet failed")
    except Exception:
        if ACCOUNT_TO_HAS_RETRY_FUNCTIONALITY_MAP.get(account, False):
            try:
                res = requests.post(f"{base_url}/autotweet/browser-tweet", json=payload, timeout=15)
                if res.ok and res.json().get("success"):
                    tweet_id = res.json()["id"]
                else:
                    print(f"Both tweet apis failed by account = {account} and base_url={base_url}")
                    raise Exception("Both tweet apis failed")
            except Exception as e:
                print(f"[ERROR] Tweeting failed for {deal_id}: {e}")
                return None, False
        else:
            print(f"[ERROR] Tweeting failed for deal_id: {deal_id} by account={account} and base_url = {base_url}")
            return None, False

    return tweet_id, True if tweet_id else False


def retweet_function(tweet_id, username, base_url, account):
    payload = {"tweet_id": tweet_id, "post_owner_username": username}
    try:
        res = requests.post(f"{base_url}/autotweet/retweet", json=payload)
        if res.ok and res.json().get("success"):
            return SUCCESS
        else:
            raise Exception("Standard retweet failed")
    except Exception as e:
        if ACCOUNT_TO_HAS_RETRY_FUNCTIONALITY_MAP.get(account, False):
            try:
                res = requests.post(f"{base_url}/autotweet/browser-retweet", json=payload)
                if res.ok and res.json().get("success"):
                    return SUCCESS
                else:
                    raise Exception("Both retweet apis failed")
            except Exception as e:
                return FAILED
        else:
            print(f"[ERROR] Retweet failed for tweet_id={tweet_id} by account={account} and base_url = {base_url}")
            return FAILED

    return FAILED


def like_function(tweet_id, username, base_url, account):
    payload = {"tweet_id": tweet_id, "post_owner_username": username}
    try:
        res = requests.post(f"{base_url}/autotweet/like", json=payload)
        if res.ok and res.json().get("success"):
            return SUCCESS
        else:
            raise Exception("Standard retweet failed")
    except Exception as e:
        if ACCOUNT_TO_HAS_RETRY_FUNCTIONALITY_MAP.get(account, False):
            try:
                res = requests.post(f"{base_url}/autotweet/browser-like", json=payload)
                if res.ok and res.json().get("success"):
                    return SUCCESS
                else:
                    raise Exception("Both retweet apis failed")
            except Exception as e:
                return FAILED
        else:
            print(f"[ERROR] Like failed for tweet_id={tweet_id} by account={account} and base_url = {base_url}")
            return FAILED

    return FAILED


def quote_function(tweet_id, text, username, base_url, account):
    payload = {
        "text": text, 
        "attachment_url": f"https://x.com/{username}/status/{tweet_id}", 
        "tweet_id": tweet_id
    }
    try:
        res = requests.post(f"{base_url}/autotweet/quote", json=payload)
        if res.ok and res.json().get("success"):
            # print(res.json()["id"])
            return SUCCESS
        else:
            raise Exception("Standard quote failed")
    except Exception as e:
        if ACCOUNT_TO_HAS_RETRY_FUNCTIONALITY_MAP.get(account, False):
            try:
                res = requests.post(f"{base_url}/autotweet/browser-quote", json=payload)
                if res.ok and res.json().get("success"):
                    # print(res.json()["twitter_response"]["data"]["create_tweet"]["tweet_results"]["result"]["rest_id"])
                    return SUCCESS
                else:
                    raise Exception("Both type of quote apis failed")
            except Exception as e:
                return FAILED
        else:
            print(f"[ERROR] Quote failed for tweet_id={tweet_id} by account={account} and base_url = {base_url}")
            return FAILED

    return FAILED


def comment_function(tweet_id, text, base_url, post_owner_username, account):
    payload = {"tweet_id": tweet_id, "text": text, "post_owner_username": post_owner_username}
    try:
        res = requests.post(f"{base_url}/autotweet/comment", json=payload)
        if res.ok and res.json().get("success"):
            # print(res.json()["id"])
            return SUCCESS
        else:
            raise Exception("Standard comment failed")
    except Exception as e:
        if ACCOUNT_TO_HAS_RETRY_FUNCTIONALITY_MAP.get(account, False):
            try:
                res = requests.post(f"{base_url}/autotweet/browser-comment", json=payload)
                if res.ok and res.json().get("success"):
                    # print(res.json()["id"])
                    return SUCCESS
                else:
                    raise Exception("Both type of comment api failed")
            except:
                return FAILED
        else:
            return FAILED

    return FAILED


def mark_as_processed(deal_id, action, tweet_id, tweeted_by, tweet_action_taken_by, is_completed):
    try:
        update_entry_action(deal_id, action, tweet_id, tweeted_by, tweet_action_taken_by, is_completed)
    except Exception as e:
        print(f"[ERROR] Failed to mark as processed {deal_id}: {e}")

def process_entries():
    try:
        delete_old_entries()

        entries = fetch_entries()
        if not entries: 
            return
        
        entry = entries[0]
        deal_id = entry["_id"]
        if entry["action"] == "NO_ACTION":
            update_entry_action(deal_id, "PROCESSING")
            result, tweet_id, account = try_action_with_multiple_accounts(
                "tweet",
                entry["_id"],
                deal_text=entry["deal"],
                username=None, 
                post_owner_username=None,
                deal_id=deal_id
            )

            if result == SUCCESS:
                update_entry_action(deal_id, "TWEETED", tweet_id=tweet_id, tweeted_by=account)
                sendTgMsg(f"Deal with tweet_id = {tweet_id} and tweeted_by = {account}")

                if TWITTER_REACTIONS == True or TWITTER_REACTIONS == 'True':
                    # 🔀 Randomly decide if this entry should be discarded after tweeting
                    # if random.randint(1, 10) < 5:
                    #     print(f"🔁 Skipping engagement for {deal_id}, deleting...")
                    #     delete_entry(deal_id)
                    #     return  # Skip further actions and waiting

                    # 💤 Wait before further action
                    waittime = random.randint(180, 800)
                    print(f"Wait {waittime} seconds for reacting to tweet={tweet_id}")
                    time.sleep(waittime)
                else:
                    print("🔁 TWITTER REACTIONS OFF")
                    delete_entry(deal_id)
                    return
            else:
                return  # already deleted inside

        entries = fetch_entries()
        if not entries: 
            return
        
        temp_entry = get_deal_by_id(deal_id)
        if temp_entry:
            entry = temp_entry
        else:
            entry = entries[0]
        deal_id = entry["_id"]
        if entry["action"] == "TWEETED":
            next_action = random.choice(["QUOTE", "RETWEET", "COMMENT", "LIKE"])
            action_type = next_action.lower()
            tweeted_by = entry["tweeted_by"]
            tweet_id = entry["tweet_id"]
            deal_text = entry["deal"]
            username = tweeted_by

            result, _, action_account = try_action_with_multiple_accounts(action_type, tweet_id, deal_text=deal_text, username=username, post_owner_username=username, deal_id = deal_id)
            if result == SUCCESS:
                mark_as_processed(deal_id, next_action, tweet_id, tweeted_by, action_account, True)

            print(f"Tweet process completed with deal_id={deal_id}, tweeted_by={tweeted_by}, next_action=${next_action}, action_account={action_account}")
            sendTgMsg(f"TweetID: {tweet_id} tweeted by: {tweeted_by} and reacted as: {next_action} by {action_account}")
            delete_entry(deal_id)
        else:
            print("After wait current entry action is not 'TWEETED' so do not do anything")
            delete_entry(deal_id)
    except Exception as e:
        print("Error at process_entries: ", e)



def sendTgMsg(msg):
    bot_token = TG_BOT_TOKEN
    chat_id = TG_TEST_CHANNEL_ID
    telegram_url = f'https://api.telegram.org/bot{bot_token}/sendMessage?chat_id={chat_id}&text={msg}'
    try:
        response = requests.get(telegram_url)
        response.raise_for_status()  # Raise an exception for HTTP errors
        print("Telegram message sent successfully.")
    except requests.exceptions.RequestException as e:
        print("Failed sending TG msg:", e)



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
        print("❌ Failed to upload image via imgbb: ")
        return upload_to_cloudinary(file_bytes)


def upload_to_cloudinary(file_bytes, public_id=None):
    try:
        file_bytes.seek(0)  # 👈 rewind the stream before reading
        # Upload file-like object (e.g. BytesIO)
        response = cloudinary.uploader.upload(
            file_bytes,
            resource_type="image"
        )
        print("✅ Uploaded via cloudinary:", response["secure_url"])
        return response["secure_url"]
    except Exception as e:
        print("❌ Upload failed:", e)
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

        if "https://extp.in" in modified_text or "https://bitl.in" in modified_text or "https://myntr" in modified_text:
            print("❌❌ Do not use V2 because Bitl/Extp/Myntr link found ")
            return False

        if "grab" in modified_text or "fast" in modified_text:
            print("❌❌ Do not use V2 because grab/fast found ")
            return False

        # Count number of links
        links = re.findall(r'https?://\S+', modified_text)
        if len(links) >= 3:
            print(f"❌❌ Do not use V2 because {len(links)} links found")
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

        if STOP_FLIPKART_LINKS == True or STOP_FLIPKART_LINKS == 'True':
            if "flipkart" in text_lower or "fkrt.it" in text_lower or "fkrt.to" in text_lower or "fkrt.co" in text_lower or "fkrt.in" in text_lower or "fkrt.cc" in text_lower:
                print("❌ Flipkart links ban for now :", text)
                return True

        if text_lower == "back" or text_lower == "loot" or text_lower == "grab":
            print("❌ Only back/loot/grab msg no link:", text)
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
        error_text = str(e)
        if "404 Client Error: Not Found for url" not in error_text:
            print("❌ Error fetching chatandmsgids:", error_text)
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



def check_all_twitter_apis_server_health():
    for account, base_url in ACCOUNT_TO_URL_MAP.items():
        url = f"{base_url.rstrip('/')}/healthcheck"
        try:
            response = requests.get(url, timeout=50)
            if response.status_code == 200:
                print(f"✅ {account} is healthy: {response.text}")
            else:
                print(f"⚠️ {account} responded with status {response.status_code}")
        except requests.RequestException as e:
            print(f"❌ {account} health check failed: {e}")


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




def pick_item(allowed=None):
    # Default: use all accounts
    if allowed is None:
        allowed = accounts

    # Filter scorecard based on allowed accounts
    filtered_scores = {item: score for item, score in scorecard.items() if item in allowed}

    if not filtered_scores:
        raise ValueError("Allowed list has no valid accounts.")

    min_score = min(filtered_scores.values())
    candidates = [item for item, score in filtered_scores.items() if score == min_score]

    chosen = random.choice(candidates)
    scorecard[chosen] += 1
    print("scorecard: " + str(scorecard) + " and chosen one is: " + chosen)
    return chosen


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
        print("❌ Exception in handle_deletes_after_delay:", traceback.format_exc())



def handle_delete_instant(deleted_ids, check_duplicate = True):
    if check_duplicate:
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
            return extracted_url
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
    if url is not None:
        if unwanted_tracking_trail_exists(url):
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
            print(f"🛑 Exact duplicates: {key}")
            return True

        # Fuzzy check
        for existing_key in unshortened_link_cache:
            if not existing_key or existing_key == key:
                continue
            if key in existing_key or existing_key in key:
                print(f"🛑 Fuzzy duplicates: {key} ~ matches {existing_key}")
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





def do_update_delete(msg_id, text):
    image_url = ""

    text = text + ' OVER '

    alldeals_data = get_chat_and_msg_ids_from_db(msg_id)

    if alldeals_data is not None:
        chat_and_msg_ids = alldeals_data.get("chatandmsgids")
        if not chat_and_msg_ids:
            print("⚠️ No forwarded message mapping found, skipping...")
            return
        BTDAILY_DEAL_ID = alldeals_data.get("id")
        image_url = alldeals_data.get("imgurl")
    else:
        return

    update_forwarded_messages_sync(chat_and_msg_ids, text, image_url)



def delete_msg_from_all_grps(event):
    edited_msg = event.message
    text = replace_text_links_with_urls(edited_msg)
    match = re.search(r"\[(\d+)\]", text)
    if match:
        msg_id = match.group(1)
        print(f"Deleting {msg_id} msg from all grps")
        do_update_delete(msg_id, text)
    else:
        print("No match found")



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


    update_sources = sources.copy()
    try:
        update_sources.append(await client.get_entity(DELETE_CHANNEL_URL.strip()))
    except Exception as e:
        print(f"Some error while adding delete_channel to update sources: {e}")


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


            if TG_WAIT == True or TG_WAIT == "True" or TG_WAIT is True:
                now = datetime.now()
                last_time = last_deal_time.get("timestamp")

                if last_time is None or (now - last_time) >= timedelta(minutes=WAIT_BEFORE_NEXT_DEAL):
                    last_deal_time["timestamp"] = now
                else:
                    print(f"⏳ Skipping sending deal — {WAIT_BEFORE_NEXT_DEAL} mins not yet passed since last post.")
                    return


            image_url = await upload_photo_get_url(msg)

            modified_text = modify_message(text, False)
            print("Modified message success✅✅ ")

            if checkIfUnwantedText(text):
                print("❌ Modified Msg contain unwanted things so dropping: " + text)
                return

            store = getStore(modified_text)

            deal_id = save_to_db(modified_text, store, image_url, tg_msg_id)
            if deal_id is not None:
                trigger_cron_v2(deal_id, tg_msg_id, modified_text, image_url)

            print("Everything done successfully ✅✅")

        except Exception as e:
            print("❌ Error in message handler:", e)


    @client.on(events.MessageEdited(chats=update_sources))
    async def edited_handler(event):
        try:
            checkServerHealth()

            try:
                channel_id = event.message.peer_id.channel_id
                if channel_id == DELETE_CHANNEL_ID:
                    delete_msg_from_all_grps(event)
                    return
            except Exception as e:
                print("Some error in deleting from all grps: ", e)

            edited_msg = event.message
            print("✏️ Message was edited!")

            text = replace_text_links_with_urls(edited_msg)
            is_deal_over = checkIfDealIsOver(text)

            if is_deal_over == True:
                if checkIfUnwantedText(text):
                    print("❌ Edited Msg contain unwanted things so dropping: " + text)
                    text = text + " OVER"
                print("Deal is over or unwanted keywords added so delete ❌")
            else:
                if checkIfUnwantedText(text):
                    print("❌ Edited Msg contain unwanted things so dropping: " + text)
                    return
            
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
                handle_delete_instant([deleted_id], False)
                print(f"⏳Data is stilL not pushed to db, wait {DELETE_SLEEP_WAIT}s before delete")
                executor_deletes.submit(handle_deletes_after_delay, [deleted_id])

        except Exception as e:
            print("❌ Error in delete_handler:", e)


    print("Listening for messages...")
    await client.run_until_disconnected()

client.loop.run_until_complete(main())
