#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Instagram Auto Creator via instagrapi + Telegram Bot
Chrome nahi chahiye. Railway pe direct chalega.
"""

import os
import sys
import time
import random
import string
import asyncio
import logging

import requests
from faker import Faker
from instagrapi import Client
from instagrapi.exceptions import (
    ClientError,
    ChallengeRequired,
    PleaseWaitFewMinutes,
)
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TELEGRAM_BOT_TOKEN = os.getenv("8636780493:AAEPJG4IyDVrF3DFu_J6qkUzQt-Ra-RtEqU", "YOUR_TELEGRAM_BOT_TOKEN")
AUTHORIZED_ID = int(os.getenv("AUTHORIZED_ID", "7422190601"))
SMS_API_KEY = os.getenv("SMS_API_KEY", "eyJhbGciOiJSUzUxMiIsInR5cCI6IkpXVCJ9.eyJleHAiOjE4MjI3NjEzNDMsImlhdCI6MTc5MTIyNTM0MywicmF5IjoiMjEyNjY4MTA4ZjVlODg1YjRlMTdhOTBhY2UxZmI4ZTEiLCJzdWIiOjQ1OTkyNTF9.ShicqXqkMKHfXQ6my4ocDDv3J5rvBRl-2VC9hZ7Klr9U5ZUJApeuavFnhW-XR9a5MgfrNK_fUhnvC8jK9-mzdNHXcyYLlZ4SM76iVXdV4oWVysKuwHjcnh_iC0NAAxMr32CaAJTedAUT3USvtWeqB7tecmao_hpamF8_z5UvXfOrjJIVY-egPpbVWM2jYqgU-EAN7qVnN9_IXpalK8PltbzBxeZvKt98LGDicZuRawajWKHicekUA8oxlUEsSYLxN3mCoTZaiJNrXUBfwA-Wxl6F8GyRmHr8oTERzXGNs_X1Y2TLl3RWVB7Vj6-gskJrHShaV-xWBOI6xaDE8pdVvA")
ACCOUNTS_FILE = "accounts.txt"
MAX_PER_BATCH = 20
DELAY_BETWEEN = 8

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("igbot")
logging.getLogger("instagrapi").setLevel(logging.WARNING)

fake = Faker()

SMS_BASE = "https://5sim.net/v1"
SMS_HEADERS = {
    "Authorization": "Bearer " + SMS_API_KEY,
    "Accept": "application/json",
}


def sms_buy_instagram_number():
    url = SMS_BASE + "/user/buy/activation/any/any/instagram"
    try:
        r = requests.get(url, headers=SMS_HEADERS, timeout=30)
        if r.status_code != 200:
            log.error("[sms] buy failed: %s %s", r.status_code, r.text[:200])
            return None, None
        data = r.json()
        return data.get("id"), data.get("phone")
    except Exception as e:
        log.error("[sms] buy exception: %s", e)
        return None, None


def sms_poll_code(order_id, timeout=240):
    url = SMS_BASE + "/user/check/" + str(order_id)
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(url, headers=SMS_HEADERS, timeout=30)
            data = r.json()
            if data.get("sms"):
                return data["sms"][0]["code"]
        except Exception as e:
            log.warning("[sms] poll err: %s", e)
        time.sleep(5)
    return None


def sms_finish(order_id):
    try:
        requests.get(
            SMS_BASE + "/user/finish/" + str(order_id),
            headers=SMS_HEADERS,
            timeout=30,
        )
    except Exception:
        pass


def sms_cancel(order_id):
    try:
        requests.get(
            SMS_BASE + "/user/cancel/" + str(order_id),
            headers=SMS_HEADERS,
            timeout=30,
        )
    except Exception:
        pass


def gen_username():
    base = fake.user_name().replace(".", "").replace("_", "")[:12]
    if not base:
        base = "user"
    return base + str(random.randint(100, 999))


def gen_password():
    chars = string.ascii_letters + string.digits + "!@#$"
    return "".join(random.choice(chars) for _ in range(14))


def gen_email():
    return fake.user_name() + str(random.randint(1000, 9999)) + "@" + fake.free_email_domain()


def create_instagram_account():
    username = gen_username()
    password = gen_password()
    email = gen_email()
    fullname = fake.name()

    result = {
        "username": username,
        "password": password,
        "email": email,
        "phone": "",
        "status": "failed",
        "reason": "",
    }

    order_id, phone = sms_buy_instagram_number()
    if not phone:
        result["reason"] = "sms_buy_failed"
        return result

    phone_clean = phone.replace("+", "").strip()
    result["phone"] = phone_clean
    log.info("[ig] order=%s phone=%s user=%s", order_id, phone_clean, username)

    cl = Client()
    cl.set_device({
        "app_version": "269.0.0.18.75",
        "android_version": 26,
        "android_release": "8.0.0",
        "dpi": "480dpi",
        "resolution": "1080x1920",
        "manufacturer": "OnePlus",
        "device": "ONEPLUS A3003",
        "model": "ONEPLUS A3003",
        "cpu": "qcom",
        "version_code": "314665256",
    })

    try:
        cl.request_signup_code(username, phone_clean)
        log.info("[ig] signup code requested for %s", username)

        code = sms_poll_code(order_id, timeout=240)
        if not code:
            result["reason"] = "no_sms"
            sms_cancel(order_id)
            return result

        log.info("[ig] received code %s", code)

        cl.signup(username, password, email, phone_clean, code, fullname)
        time.sleep(random.uniform(3, 5))

        try:
            cl.login(username, password)
        except ChallengeRequired:
            result["reason"] = "challenge_on_login"
            result["status"] = "success"
            sms_finish(order_id)
            return result

        sms_finish(order_id)
        result["status"] = "success"
        return result

    except PleaseWaitFewMinutes:
        result["reason"] = "rate_limited"
    except ChallengeRequired:
        result["reason"] = "challenge_required"
    except ClientError as e:
        result["reason"] = "client_error: " + str(e)[:120]
    except Exception as e:
        result["reason"] = type(e).__name__ + ": " + str(e)[:120]

    try:
        sms_cancel(order_id)
    except Exception:
        pass

    return result


def save_account(result):
    line = (
        result.get("username", "") + ":" +
        result.get("password", "") + ":" +
        result.get("email", "") + ":" +
        result.get("phone", "") + ":" +
        result.get("status", "") + ":" +
        result.get("reason", "") + "\n"
    )
    with open(ACCOUNTS_FILE, "a", encoding="utf-8") as f:
        f.write(line)


def ensure_accounts_file():
    if not os.path.exists(ACCOUNTS_FILE):
        with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
            f.write("# username:password:email:phone:status:reason\n")


def is_authorized(update):
    if not update.effective_user:
        return False
    return update.effective_user.id == AUTHORIZED_ID


async def cmd_start(update, ctx):
    if not is_authorized(update):
        return
    await update.message.reply_text(
        "[K] Prime Hacker online.\n\n"
        "/create <N>   - N IG accounts banao\n"
        "/accounts     - accounts.txt bhejo\n"
        "/ping         - zinda ho?"
    )


async def cmd_ping(update, ctx):
    if not is_authorized(update):
        return
    await update.message.reply_text("[K] zinda hoon.")


async def cmd_accounts(update, ctx):
    if not is_authorized(update):
        return
    ensure_accounts_file()
    with open(ACCOUNTS_FILE, "rb") as f:
        await update.message.reply_document(
            document=f,
            filename=os.path.basename(ACCOUNTS_FILE),
        )


async def cmd_create(update, ctx):
    if not is_authorized(update):
        return

    try:
        count = int(ctx.args[0]) if ctx.args else 1
    except (ValueError, IndexError):
        await update.message.reply_text("usage: /create <count>")
        return

    if count < 1:
        count = 1
    if count > MAX_PER_BATCH:
        count = MAX_PER_BATCH

    ensure_accounts_file()
    await update.message.reply_text("[K] " + str(count) + " account bana raha hoon...")

    success = 0
    for i in range(count):
        await update.message.reply_text("[" + str(i + 1) + "/" + str(count) + "] shuru...")

        try:
            result = await asyncio.to_thread(create_instagram_account)
        except Exception as e:
            await update.message.reply_text("[" + str(i + 1) + "/" + str(count) + "] crash: " + str(e))
            continue

        if result["status"] == "success":
            success += 1

        save_account(result)

        msg = (
            "[" + str(i + 1) + "/" + str(count) + "] " +
            result["status"] + " | @" + result["username"] +
            " | " + result.get("reason", "-")
        )
        await update.message.reply_text(msg)

        if i < count - 1:
            await asyncio.sleep(DELAY_BETWEEN)

    await update.message.reply_text(
        "[K] ho gaya. " + str(success) + "/" + str(count) + " pass. file bhej raha hoon..."
    )

    with open(ACCOUNTS_FILE, "rb") as f:
        await update.message.reply_document(
            document=f,
            filename=os.path.basename(ACCOUNTS_FILE),
            caption="creds andar hain. format: username:password:email:phone:status:reason",
        )


def main():
    def main():
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        print("[!] TELEGRAM_BOT_TOKEN set kar.")
        sys.exit(1)
    if not SMS_API_KEY or SMS_API_KEY == "YOUR_5SIM_API_KEY":
        print("[!] SMS_API_KEY set kar.")
        sys.exit(1)
    if AUTHORIZED_ID == 123456789:
        print("[!] AUTHORIZED_ID set kar.")
        sys.exit(1)

    ensure_accounts_file()

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("ping", cmd_ping))
    app.add_handler(CommandHandler("create", cmd_create))
    app.add_handler(CommandHandler("accounts", cmd_accounts))

    log.info("[K] bot online. Prime Hacker ka wait kar raha hoon...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
