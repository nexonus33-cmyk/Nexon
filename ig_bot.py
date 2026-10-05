#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Instagram Auto Creator via instagrapi + Telegram Bot
Chrome nahi chahiye. Railway pe direct chalega.

Env vars (Railway -> Variables tab mein daal):
    TELEGRAM_BOT_TOKEN
    AUTHORIZED_ID
    SMS_API_KEY
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
    ClientError, ChallengeRequired, PleaseWaitFewMinutes,
)
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ---------- CONFIG ----------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8636780493:AAEPJG4IyDVrF3DFu_J6qkUzQt-Ra-RtEqU")
AUTHORIZED_ID      = int(os.getenv("AUTHORIZED_ID", "7422190601"))
SMS_API_KEY        = os.getenv("SMS_API_KEY", "eyJhbGciOiJSUzUxMiIsInR5cCI6IkpXVCJ9.eyJleHAiOjE4MjI3NjEzNDMsImlhdCI6MTc5MTIyNTM0MywicmF5IjoiMjEyNjY4MTA4ZjVlODg1YjRlMTdhOTBhY2UxZmI4ZTEiLCJzdWIiOjQ1OTkyNTF9.ShicqXqkMKHfXQ6my4ocDDv3J5rvBRl-2VC9hZ7Klr9U5ZUJApeuavFnhW-XR9a5MgfrNK_fUhnvC8jK9-mzdNHXcyYLlZ4SM76iVXdV4oWVysKuwHjcnh_iC0NAAxMr32CaAJTedAUT3USvtWeqB7tecmao_hpamF8_z5UvXfOrjJIVY-egPpbVWM2jYqgU-EAN7qVnN9_IXpalK8PltbzBxeZvKt98LGDicZuRawajWKHicekUA8oxlUEsSYLxN3mCoTZaiJNrXUBfwA-Wxl6F8GyRmHr8oTERzXGNs_X1Y2TLl3RWVB7Vj6-gskJrHShaV-xWBOI6xaDE8pdVvA")
ACCOUNTS_FILE      = "accounts.txt"
MAX_PER_BATCH      = 20
DELAY_BETWEEN      = 8

# ---------- LOGGING ----------
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("igbot")
logging.getLogger("instagrapi").setLevel(logging.WARNING)

fake = Faker()

# =========================================================
#                   SMS SERVICE (5sim)
# =========================================================
SMS_BASE = "https://5sim.net/v1"
SMS_HEADERS = {
    "Authorization": f"Bearer {SMS_API_KEY}",
    "Accept": "application/json",
}

def sms_buy_instagram_number():
    url = f"{SMS_BASE}/user/buy/activation/any/any/instagram"
    try:
        r = requests.get(url, headers=SMS_HEADERS, timeout=30)
        if r.status_code != 200:
            log.error(f"[sms] buy failed: {r.status_code} {r.text[:200]}")
            return None, None
        data = r.json()
        return data.get("id"), data.get("phone")
    except Exception as e:
        log.error(f"[sms] buy exception: {e}")
        return None, None


def sms_poll_code(order_id, timeout=240):
    url = f"{SMS_BASE}/user/check/{order_id}"
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(url, headers=SMS_HEADERS, timeout=30)
            data = r.json()
            if data.get("sms"):
                return data["sms"][0]["code"]
        except Exception as e:
            log.warning(f"[sms] poll err: {e}")
        time.sleep(5)
    return None


def sms_finish(order_id):
    try:
        requests.get(f"{SMS_BASE}/user/finish/{order_id}",
                     headers=SMS_HEADERS, timeout=30)
    except Exception:
        pass


def sms_cancel(order_id):
    try:
        requests.get(f"{SMS_BASE}/user/cancel/{order_id}",
                     headers=SMS_HEADERS, timeout=30)
    except Exception:
        pass


# =========================================================
#                   GENERATORS
# =========================================================
def gen_username():
    base = fake.user_name().replace(".", "").replace("_", "")[:12] or "user"
    return f"{base}{random.randint(100, 999)}"


def gen_password():
    chars = string.ascii_letters + string.digits + "!@#$"
    return "".join(random.choice(chars) for _ in range(14))


def gen_email():
    return f"{fake.user_name()}{random.randint(1000, 9999)}@{fake.free_email_domain()}"


# =========================================================
#                   ACCOUNT CREATION
# =========================================================
def create_instagram_account():
    username = gen_username()
    password = gen_password()
    email    = gen_email()
    fullname = fake.name()

    result = {
        "username": username,
        "password": password,
        "email":    email,
        "phone":    "",
        "status":   "failed",
        "reason":   "",
    }

    order_id, phone = sms_buy_instagram_number()
    if not phone:
        result["reason"] = "sms_buy_failed"
        return result

    phone_clean = phone.replace("+", "").strip()
    result["phone"] = phone_clean
    log.info(f"[ig] order={order_id} phone={phone_clean} user={username}")

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
        log.info(f"[ig] signup code requested for {username}")

        code = sms_poll_code(order_id, timeout=240)
        if not code:
            result["reason"] = "no_sms"
            sms_cancel(order_id)
            return result

        log.info(f"[ig] received code {code}")

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
        result["reason"] = f"client_error: {str(e)[:120]}"
    except Exception as e:
        result["reason"] = f"{type(e).__name__}: {str(e)[:120]}"

    try:
        sms_cancel(order_id)
    except Exception:
        pass

    return result


# =========================================================
#                   SAVE
# =========================================================
def save_account(result):
    line = (
        f"{result.get('username','')}:{result.get('password','')}:"
        f"{result.get('email','')}:{result.get('phone','')}:"
        f"{result.get('status','')}:{result.get('reason','')}\n"
    )
    with open(ACCOUNTS_FILE, "a", encoding="utf-8") as f:
        f.write(line)


def ensure_accounts_file():
    if not os.path.exists(ACCOUNTS_FILE):
        with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
            f.write("# username:password:email:phone:status:reason\n")


# =========================================================
#                   TELEGRAM BOT
# =========================================================
def is_authorized(update: Update) -> bool:
    return update.effective_user and update.effective_user.id == AUTHORIZED_ID


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    await update.message.reply_text(
        "[K] Prime Hacker online.\n\n"
        "/create <N>   - N IG accounts banao\n"
        "/accounts     - accounts.txt bhejo\n"
        "/ping         - zinda ho?"
    )


async def cmd_ping(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    await update.message.reply_text("[K] zinda hoon.")


async def cmd_accounts(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    ensure_accounts_file()
    await update.message.reply_document(
        document=open(ACCOUNTS_FILE, "rb"),
        filename=os.path.basename(ACCOUNTS_FILE),
    )


async def cmd_create(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return

    try:
        count = int(ctx.args[0]) if ctx.args else 1
    except (ValueError, IndexError):
        await update.message.reply_text("usage: /create <count>")
        return

    count = max(1, min(count, MAX_PER_BATCH))
    ensure_accounts_file()
    await update.message.reply_text(f"[K] {count} account bana raha hoon...")

    success = 0
    for i in range(count):
        await update.message.reply_text(f"[{i+1}/{count}] shuru...")

        try:
            result = await asyncio.to_thread(create_instagram_account)
        except Exception as e:
            await update.message.reply_text(f"[{i+1}/{count}] crash: {e}")
            continue

        if result["status"] == "success":
            success += 1

        save_account(result)
        await update.message.reply_text(
            f"[{i+1}/{count}] {result['status']} | @{result['username']} "
            f"| {result.get('reason','-')}"
        )

        if i < count - 1:
            await asyncio.sleep(DELAY_BETWEEN)

    await update.message.reply_text(
        f"[K] ho gaya. {success}/{count} pass. file bhej raha hoon..."
    )
    await update.message.reply_document(
        document=open(ACCOUNTS_FILE, "rb"),
        filename=os.path.basename(ACCOUNTS_FILE),
        caption="creds andar hain. format: username:password:email:phone:status:reason",
    )


# =========================================================
#                   MAIN
# =========================================================
def main():
    if TELEGRAM_BOT_TOKEN.startswith("YOUR_"):
        print("[!] TELEGRAM_BOT_TOKEN set kar.")
        sys.exit(1)
    if SMS_API_KEY.startswith("YOUR_"):
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
    main()AM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("ping", cmd_ping))
    app.add_handler(CommandHandler("create", cmd_create))
    app.add_handler(CommandHandler("accounts", cmd_accounts))

    log.info("[K] bot online. Prime Hacker ka wait kar raha hoon...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
        if not code:
            result["reason"] = "no_sms"
            sms_cancel(order_id)
            return result, driver

        log.info(f"[ig] received code {code}")

        # 10) type code into 6 boxes
        code_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='text']")
        if len(code_inputs) < len(code):
            # fallback: single input
            code_inputs = driver.find_elements(By.NAME, "emailOrPhone")
        for i, digit in enumerate(code):
            if i < len(code_inputs):
                code_inputs[i].click()
                code_inputs[i].send_keys(digit)
                time.sleep(random.uniform(0.3, 0.6))
        time.sleep(random.uniform(4, 7))

        sms_finish(order_id)

        # 11) dismiss popups (notifications, save login)
        time.sleep(random.uniform(2, 4))
        dismiss_popups(driver, rounds=3)

        result["status"] = "success"
        return result, driver

    except Exception as e:
        log.error(f"[ig] create exception: {e}")
        result["reason"] = f"{type(e).__name__}: {e}"
        if order_id:
            sms_cancel(order_id)
        return result, driver


# =========================================================
#                   ENABLE PRO (CREATOR) MODE
# =========================================================
def enable_pro_mode(driver):
    """Switch account to Professional (Creator) mode via settings UI."""
    if driver is None:
        return False

    try:
        driver.get("https://www.instagram.com/accounts/settings/")
        time.sleep(random.uniform(4, 6))

        # Try direct URL first (more stable than menu clicking)
        driver.get("https://www.instagram.com/accounts/convert_to_professional_account/")
        time.sleep(random.uniform(4, 6))

        # click "Continue"/"Next" through wizard
        for _ in range(8):
            clicked = False
            for label in ("Continue", "Next", "Done", "Switch"):
                try:
                    btns = driver.find_elements(
                        By.XPATH, f"//button[contains(text(),'{label}')]"
                    )
                    for b in btns:
                        if b.is_displayed() and b.is_enabled():
                            b.click()
                            clicked = True
                            time.sleep(random.uniform(2, 4))
                            break
                    if clicked:
                        break
                except Exception:
                    continue
            if not clicked:
                break

        # pick "Creator" if asked
        for label in ("Creator", "Digital creator", "Artist"):
            try:
                opts = driver.find_elements(
                    By.XPATH, f"//*[contains(text(),'{label}')]"
                )
                for o in opts:
                    if o.is_displayed():
                        o.click()
                        time.sleep(random.uniform(1.5, 3))
                        break
            except Exception:
                continue

        # finalize
        for label in ("Done", "Next", "Continue"):
            try:
                btns = driver.find_elements(
                    By.XPATH, f"//button[contains(text(),'{label}')]"
                )
                for b in btns:
                    if b.is_displayed() and b.is_enabled():
                        b.click()
                        time.sleep(random.uniform(2, 4))
                        break
            except Exception:
                continue

        return True

    except Exception as e:
        log.warning(f"[pro] failed: {e}")
        return False


# =========================================================
#                   SAVE ACCOUNT
# =========================================================
def save_account(result):
    line = (
        f"{result.get('username','')}:{result.get('password','')}:"
        f"{result.get('email','')}:{result.get('phone','')}:"
        f"{result.get('status','')}:{result.get('reason','')}\n"
    )
    with open(ACCOUNTS_FILE, "a", encoding="utf-8") as f:
        f.write(line)


def ensure_accounts_file():
    if not os.path.exists(ACCOUNTS_FILE):
        with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
            f.write("# username:password:email:phone:status:reason\n")


# =========================================================
#                   TELEGRAM BOT
# =========================================================
def is_authorized(update: Update) -> bool:
    return update.effective_user and update.effective_user.id == AUTHORIZED_ID


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    await update.message.reply_text(
        "[K] Prime Hacker online.\n\n"
        "/create <N>   - spawn N IG accounts (max {})\n"
        "/accounts     - resend accounts.txt\n"
        "/ping         - alive check".format(MAX_PER_BATCH)
    )


async def cmd_ping(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    await update.message.reply_text("[K] alive.")


async def cmd_accounts(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    ensure_accounts_file()
    await update.message.reply_document(
        document=open(ACCOUNTS_FILE, "rb"),
        filename=os.path.basename(ACCOUNTS_FILE),
    )


async def cmd_create(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return

    try:
        count = int(ctx.args[0]) if ctx.args else 1
    except (ValueError, IndexError):
        await update.message.reply_text("usage: /create <count>")
        return

    count = max(1, min(count, MAX_PER_BATCH))
    ensure_accounts_file()
    await update.message.reply_text(f"[K] spawning {count} account(s)...")

    success = 0
    for i in range(count):
        await update.message.reply_text(f"[{i+1}/{count}] starting...")

        # run selenium in thread (blocking)
        try:
            result, driver = await asyncio.to_thread(create_instagram_account)
        except Exception as e:
            await update.message.reply_text(f"[{i+1}/{count}] crash: {e}")
            continue

        # pro mode
        if result["status"] == "success" and driver is not None:
            await update.message.reply_text(
                f"[{i+1}/{count}] @{result['username']} created. enabling pro mode..."
            )
            try:
                ok = await asyncio.to_thread(enable_pro_mode, driver)
                result["reason"] = "pro_mode_on" if ok else "pro_mode_failed"
            except Exception as e:
                result["reason"] = f"pro_mode_err:{e}"

        save_account(result)
        if result["status"] == "success":
            success += 1

        await update.message.reply_text(
            f"[{i+1}/{count}] {result['status']} | @{result['username']} "
            f"| {result.get('reason','-')}"
        )

        # close browser
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass

        if i < count - 1:
            await asyncio.sleep(DELAY_BETWEEN)

    await update.message.reply_text(
        f"[K] done. {success}/{count} succeeded. sending file..."
    )
    await update.message.reply_document(
        document=open(ACCOUNTS_FILE, "rb"),
        filename=os.path.basename(ACCOUNTS_FILE),
        caption="creds inside. username:password:email:phone:status:reason",
    )


# =========================================================
#                   MAIN
# =========================================================
def main():
    if TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        print("[!] Set TELEGRAM_BOT_TOKEN in the config section.")
        sys.exit(1)
    if SMS_API_KEY == "YOUR_5SIM_API_KEY":
        print("[!] Set SMS_API_KEY in the config section.")
        sys.exit(1)
    if AUTHORIZED_ID == 123456789:
        print("[!] Set AUTHORIZED_ID (your Telegram user id) in config.")
        sys.exit(1)

    ensure_accounts_file()

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("ping", cmd_ping))
    app.add_handler(CommandHandler("create", cmd_create))
    app.add_handler(CommandHandler("accounts", cmd_accounts))

    log.info("[K] bot online. waiting for Prime Hacker...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
