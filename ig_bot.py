#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Instagram Auto Account Creator + Pro Mode + Telegram Bot
Single-file build for Prime Hacker.

Install:
    pip install python-telegram-bot selenium undetected-chromedriver requests faker

Run:
    python ig_bot.py

Telegram commands:
    /start          - show help
    /create <N>     - spawn N IG accounts, enable pro mode, send txt file
    /accounts       - resend accounts.txt
"""

import os
import sys
import time
import random
import string
import asyncio
import logging

# ---------- CONFIG ----------
TELEGRAM_BOT_TOKEN = "8636780493:AAEPJG4IyDVrF3DFu_J6qkUzQt-Ra-RtEqU"
AUTHORIZED_ID      = 7422190601          # your Telegram user id
SMS_API_KEY        = "eyJhbGciOiJSUzUxMiIsInR5cCI6IkpXVCJ9.eyJleHAiOjE4MjI3NjEzNDMsImlhdCI6MTc5MTIyNTM0MywicmF5IjoiMjEyNjY4MTA4ZjVlODg1YjRlMTdhOTBhY2UxZmI4ZTEiLCJzdWIiOjQ1OTkyNTF9.ShicqXqkMKHfXQ6my4ocDDv3J5rvBRl-2VC9hZ7Klr9U5ZUJApeuavFnhW-XR9a5MgfrNK_fUhnvC8jK9-mzdNHXcyYLlZ4SM76iVXdV4oWVysKuwHjcnh_iC0NAAxMr32CaAJTedAUT3USvtWeqB7tecmao_hpamF8_z5UvXfOrjJIVY-egPpbVWM2jYqgU-EAN7qVnN9_IXpalK8PltbzBxeZvKt98LGDicZuRawajWKHicekUA8oxlUEsSYLxN3mCoTZaiJNrXUBfwA-Wxl6F8GyRmHr8oTERzXGNs_X1Y2TLl3RWVB7Vj6-gskJrHShaV-xWBOI6xaDE8pdVvA"
ACCOUNTS_FILE      = "accounts.txt"
HEADLESS           = False              # keep False; IG flags headless Chrome
PROXY              = None               # e.g. "http://user:pass@ip:port"
MAX_PER_BATCH      = 20
DELAY_BETWEEN      = 5                  # seconds between accounts

# ---------- LOGGING ----------
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("igbot")

# ---------- DEPENDENCY CHECK ----------
def _require(mod_name, pip_name=None):
    try:
        return __import__(mod_name)
    except ImportError:
        print(f"[!] Missing module '{mod_name}'. Install: pip install {pip_name or mod_name}")
        sys.exit(1)

requests = _require("requests")
faker_mod = _require("faker")
Faker = faker_mod.Faker
fake = Faker()

uc = _require("undetected_chromedriver")
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException, WebDriverException,
)

tg = _require("telegram", "python-telegram-bot")
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# =========================================================
#                   SMS SERVICE (5sim)
# =========================================================
SMS_BASE = "https://5sim.net/v1"
SMS_HEADERS = {
    "Authorization": f"Bearer {SMS_API_KEY}",
    "Accept": "application/json",
}

def sms_buy_instagram_number():
    """Buy a phone number for Instagram. Returns (order_id, phone) or (None, None)."""
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


def sms_poll_code(order_id, timeout=180):
    """Poll 5sim for SMS code."""
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
#                   ACCOUNT GENERATORS
# =========================================================
def gen_username():
    base = fake.user_name().replace(".", "").replace("_", "")[:12]
    if not base:
        base = "user"
    return f"{base}{random.randint(100, 999)}"


def gen_password():
    chars = string.ascii_letters + string.digits + "!@#$"
    return "".join(random.choice(chars) for _ in range(14))


def gen_email():
    return f"{fake.user_name()}{random.randint(1000, 9999)}@{fake.free_email_domain()}"


# =========================================================
#                   BROWSER HELPERS
# =========================================================
def build_driver():
    opts = uc.ChromeOptions()
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--window-size=1280,900")
    if PROXY:
        opts.add_argument(f"--proxy-server={PROXY}")
    if HEADLESS:
        opts.add_argument("--headless=new")

    driver = uc.Chrome(options=opts, version_main=None)
    driver.set_page_load_timeout(60)
    return driver


def safe_click(driver, by, value, timeout=15):
    try:
        el = WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((by, value))
        )
        el.click()
        return True
    except Exception:
        return False


def dismiss_popups(driver, rounds=3):
    """Click 'Not Now' / 'Cancel' popups if they appear."""
    xpaths = [
        "//button[contains(text(),'Not Now')]",
        "//button[contains(text(),'Not now')]",
        "//button[contains(text(),'Cancel')]",
    ]
    for _ in range(rounds):
        clicked = False
        for xp in xpaths:
            try:
                btns = driver.find_elements(By.XPATH, xp)
                if btns:
                    btns[0].click()
                    clicked = True
                    time.sleep(random.uniform(1.5, 3))
            except Exception:
                continue
        if not clicked:
            break


# =========================================================
#                   INSTAGRAM FLOW
# =========================================================
def create_instagram_account():
    """
    Returns (result_dict, driver).
    result: {username, password, email, phone, status, reason}
    """
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

    # --- buy phone first ---
    order_id, phone = sms_buy_instagram_number()
    if not phone:
        result["reason"] = "sms_buy_failed"
        return result, None

    phone_clean = phone.replace("+", "").strip()
    result["phone"] = phone_clean
    log.info(f"[ig] order={order_id} phone={phone_clean} user={username}")

    driver = None
    try:
        driver = build_driver()
        wait = WebDriverWait(driver, 25)

        # 1) signup page
        driver.get("https://www.instagram.com/accounts/emailsignup/")
        time.sleep(random.uniform(4, 7))

        # 2) email
        email_field = wait.until(
            EC.presence_of_element_located((By.NAME, "emailOrPhone"))
        )
        email_field.click()
        email_field.send_keys(email)
        time.sleep(random.uniform(0.8, 1.6))

        # 3) fullname
        name_field = driver.find_element(By.NAME, "fullName")
        name_field.click()
        name_field.send_keys(fullname)
        time.sleep(random.uniform(0.8, 1.6))

        # 4) username
        uname_field = driver.find_element(By.NAME, "username")
        uname_field.click()
        uname_field.send_keys(username)
        time.sleep(random.uniform(0.8, 1.6))

        # 5) password
        pwd_field = driver.find_element(By.NAME, "password")
        pwd_field.click()
        pwd_field.send_keys(password)
        time.sleep(random.uniform(0.8, 1.6))

        # 6) submit
        safe_click(driver, By.CSS_SELECTOR, "button[type='submit']", timeout=15)
        time.sleep(random.uniform(5, 8))

        # 7) birthdate (may appear)
        try:
            month_sel = wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "select[title='Month:']"))
            )
            Select(month_sel).select_by_value(str(random.randint(1, 12)))
            Select(driver.find_element(By.CSS_SELECTOR, "select[title='Day:']")
                   ).select_by_value(str(random.randint(1, 28)))
            Select(driver.find_element(By.CSS_SELECTOR, "select[title='Year:']")
                   ).select_by_value(str(random.randint(1990, 2000)))
            time.sleep(random.uniform(1, 2))
            safe_click(driver, By.XPATH, "//button[text()='Next']")
            time.sleep(random.uniform(4, 6))
        except TimeoutException:
            pass  # age gate skipped

        # 8) phone entry (may appear)
        try:
            phone_field = wait.until(
                EC.presence_of_element_located((By.NAME, "emailOrPhone"))
            )
            phone_field.clear()
            phone_field.click()
            phone_field.send_keys(phone_clean)
            time.sleep(random.uniform(1, 2))
            safe_click(driver, By.XPATH, "//button[text()='Next']")
            time.sleep(random.uniform(3, 5))
        except Exception as e:
            result["reason"] = f"phone_entry_failed: {e}"
            sms_cancel(order_id)
            return result, driver

        # 9) wait for SMS
        code = sms_poll_code(order_id, timeout=180)
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