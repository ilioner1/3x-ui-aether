#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🤖 VeloraBot — نسخه یکپارچه و بازنویسی‌شده (تک‌فایل)
ربات فروش کانفیگ/اشتراک با پردازش دستی سفارش‌ها توسط ادمین

✨ قابلیت‌ها:
- خرید پلن با موجودی یا کارت‌به‌کارت (پردازش دستی: ادمین با «ریپلای» کانفیگ را می‌فرستد)
- مدیریت گفت‌وگومحور پلن‌ها و بسته‌ها (افزودن متوالی بسته‌ها)
- مخزن دستی کانفیگ‌های تست (هر کاربر یک کانفیگ غیرتکراری دریافت می‌کند)
- مدیریت چند ادمین + مدیریت دکمه‌های شیشه‌ای از داخل پنل
- کیف پول، فیش واریزی، کوپن تخفیف، دعوت از دوستان، پیام همگانی، لیست سیاه، بکاپ
"""

import asyncio
import copy
import html
import json
import logging
import os
import re
import zipfile
import sqlite3
import uuid

from reseller_sales import InsufficientFunds, PlanUnavailable, SalesAPI, SalesError, WalletSales
from datetime import datetime
from io import BytesIO
from typing import Any, Dict, List, Optional

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton as _IKB,
    InlineKeyboardMarkup as _IKM,
    Message,
)


# =============== 🎨 دکمه‌های رنگی + ایموجی پرمیوم ===============
# رنگ‌بندی منظم سطری: همه‌ی دکمه‌های یک ردیف هم‌رنگ‌اند و ردیف‌ها الگوی ثابت سه‌رنگ دارند:
#   ردیف ۱ → 🔵 آبی، ردیف ۲ → 🟢 سبز، ردیف ۳ → 🔴 قرمز، ردیف ۴ → 🔵 آبی ... (چرخه‌ی سه‌تایی)
#   ردیف بازگشت/انصراف/بستن همیشه → 🔴 قرمز
# هیچ دکمه‌ای بی‌رنگ نمی‌ماند چون رنگ‌آمیزی روی خودِ InlineKeyboardMarkup انجام می‌شود.

_ROW_CYCLE = ("primary", "success", "danger")
_LAST_ROW_WORDS = ("بازگشت", "برگشت", "انصراف", "بستن", "صفحه اصلی", "منوی اصلی", "خروج", "لغو")

# 🌟 ایموجی‌های پرمیوم (متحرک) — شناسه‌های رسمی و رایگان تلگرام
PREMIUM_EMOJI = {
    "📁": "5357315181649076022", "🗃": "5357315181649076022",
    "🛒": "5431492767249342908", "🛡": "5431492767249342908",
    "🛍": "5350699789551935589", "📦": "5350699789551935589",
    "💰": "5350452584119279096", "💵": "5350452584119279096",
    "💸": "5309929258443874898", "💳": "5310107765874632305",
    "🪙": "5377690785674175481", "❕": "5379748062124056162",
    "❗️": "5379748062124056162", "‼️": "5377498341074542641",
    "❓": "5377316857231450742", "⁉️": "5377438129928020693",
    "👥": "5386435923204382258", "👤": "5418115271267197333",
    "🪪": "5418115271267197333", "🎟": "5377624166436445368",
    "🏷️": "5377624166436445368", "🧪": "5411138633765757782",
    "👑": "5357107601584693888", "📋": "5373251851074415873",
    "📝": "5373251851074415873", "📊": "5350305691942788490",
    "📈": "5350305691942788490", "📉": "5350713563512052787",
    "💎": "5309958691854754293", "✅": "5237699328843200968",
    "🎉": "5310228579009699834", "🎁": "5310228579009699834",
    "📢": "5309984423003823246", "📣": "5309984423003823246",
    "💻": "5350554349074391003", "💾": "5350554349074391003",
    "🤖": "5309832892262654231", "⚡️": "5312016608254762256",
    "🔥": "5312241539987020022", "🎨": "5310039132297242441",
    "💬": "5417915203100613993", "🏆": "5312315739842026755",
    "🗳": "5350387571199319521", "🔎": "5309965701241379366",
    "🔝": "5418085807791545980", "💡": "5312536423851630001",
    "📱": "5409357944619802453", "📅": "5433614043006903194",
    "📆": "5433614043006903194", "⭐️": "5235579393115438657",
    "✍️": "5238156910363950406", "🧠": "5237889595894414384",
    "🎂": "5310132165583840589", "🔮": "5350367161514732241",
    "⌨️": "5350554349074391003", "⚙️": "5355127101970194557",
    "🔙": "5418085807791545980", "🔔": "5309984423003823246",
    "🚀": "5312016608254762256", "🗑": "5379748062124056162",
    "🚫": "5420331611830886484", "🔴": "5377498341074542641",
    "🟢": "5237699328843200968", "🧾": "5373251851074415873",
    "⏳": "5433614043006903194", "🆔": "5418115271267197333",
    "🔗": "5309965701241379366", "🎯": "5312315739842026755",
}

_LEADING_EMOJI_RE = re.compile(
    r"^\s*(" + "|".join(re.escape(e) for e in sorted(PREMIUM_EMOJI, key=len, reverse=True)) + r")\s*"
)


def _premium_text(text):
    """جایگزینی ایموجی‌های استاندارد با نسخه‌ی پرمیوم (متحرک) در متن پیام‌ها.
    fallback استاندارد داخل تگ باقی می‌ماند تا برای کلاینت‌های قدیمی هم درست دیده شود."""
    if not text or "<tg-emoji" in text:
        return text
    out = text
    for emoji, eid in PREMIUM_EMOJI.items():
        if emoji in out:
            out = out.replace(emoji, f'<tg-emoji emoji-id="{eid}">{emoji}</tg-emoji>')
    return out


def InlineKeyboardButton(text=None, *, callback_data=None, url=None, style=None,
                         icon_custom_emoji_id=None, **kw):
    """دکمه‌ی شیشه‌ای: ایموجیِ ابتدای متن به ایموجی پرمیوم دکمه تبدیل می‌شود.
    رنگ (style) بعداً به‌صورت سطری توسط InlineKeyboardMarkup ست می‌شود."""
    if text and icon_custom_emoji_id is None:
        m = _LEADING_EMOJI_RE.match(text)
        if m:
            icon_custom_emoji_id = PREMIUM_EMOJI[m.group(1)]
            text = text[m.end():] or m.group(1)
    return _IKB(text=text, callback_data=callback_data, url=url, style=style,
                icon_custom_emoji_id=icon_custom_emoji_id, **kw)


def _is_nav_row(row):
    """ردیف‌های بازگشت/انصراف/بستن → قرمز."""
    if not row:
        return False
    return all(any(w in (b.text or "") for w in _LAST_ROW_WORDS) for b in row)


def InlineKeyboardMarkup(inline_keyboard=None, **kw):
    """کیبورد شیشه‌ای با رنگ‌بندی منظم سطری — همه‌ی دکمه‌های ربات را پوشش می‌دهد."""
    rows = inline_keyboard or []
    colored = []
    idx = 0
    for row in rows:
        if _is_nav_row(row):
            style = "danger"
        else:
            style = _ROW_CYCLE[idx % len(_ROW_CYCLE)]
            idx += 1
        new_row = []
        for b in row:
            data = b.model_dump(exclude_none=True) if hasattr(b, "model_dump") else dict(b)
            data["style"] = style
            new_row.append(_IKB(**data))
        colored.append(new_row)
    return _IKM(inline_keyboard=colored, **kw)


# ==================== ⚙️ تنظیمات اصلی (فقط همین‌جا را پر کنید) ====================
BOT_TOKEN = os.environ["BOT_TOKEN"]
SUPER_ADMIN_ID = int(os.environ["SUPER_ADMIN_ID"])
# =================================================================================

# 💳 تنظیمات کارت بانکی (برای پرداخت کارت‌به‌کارت)
BANK_CARD_NUMBER = os.getenv("BANK_CARD_NUMBER", "")
BANK_CARD_HOLDER = os.getenv("BANK_CARD_HOLDER", "")
BANK_NAME = os.getenv("BANK_NAME", "")

# 💬 پشتیبانی و تنظیمات فروشگاه
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "")

# 🦆 استیکر خوش‌آمدگویی /start — استیکر هفتم پک Duck X2 (t.me/addstickers/DMJDuckX2)
START_STICKER_ID = "CAACAgQAAxUAAWqZhTxlwPZq0EELWcv_JjHtMoELAAKZEgACdnlZUW2qPBOT3zBNPQQ"

# 📢 گروه لاگ — همه رویدادها (استارت، تست، خرید و...) به این گروه می‌روند (ربات باید عضو باشد)
# اگر با یوزرنیم کار نکرد، آیدی عددی گروه (مثل -1001234567890) را اینجا بگذارید
LOG_CHAT_ID = os.getenv("LOG_CHAT_ID", "")
MIN_CHARGE = 10_000          # حداقل مبلغ شارژ حساب (تومان)
MAX_CHARGE = 5_000_000       # حداکثر مبلغ شارژ حساب (تومان)
REFERRAL_BONUS = 5_000       # پاداش ثابت دعوت (بکاپ — پیش‌فرض: درصدی است)
REFERRAL_PERCENT = 10        # 🎁 پاداش دعوت: ۱۰٪ از مبلغ خرید دوست شما

# 🏆 پاداش پله‌ای دعوت — با رسیدن به تعداد رفرال، اعتبار یک‌جا هدیه می‌شود
DEFAULT_REFERRAL_TIERS = [
    {"count": 10, "reward": 100_000},
    {"count": 20, "reward": 200_000},
    {"count": 50, "reward": 500_000},
]
TEST_MAX_PER_USER = 1        # حداکثر دفعات دریافت تست رایگان برای هر کاربر

# ==================== پایان تنظیمات — بقیه فایل نیازی به تغییر ندارد ====================

try:
    SUPER_ADMIN_ID = int(SUPER_ADMIN_ID)
except (ValueError, TypeError):
    raise SystemExit("❌ SUPER_ADMIN_ID باید یک عدد باشد!")

try:
    import qrcode
    QR_AVAILABLE = True
except ImportError:
    QR_AVAILABLE = False

# =============== لاگینگ ===============
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("VeloraBot")

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


async def _premium_emoji_middleware(make_request, bot_obj, method):
    """میدل‌ور خروجی: ایموجی‌های متن و کپشن هر پیام را به ایموجی پرمیوم تبدیل می‌کند.
    این‌طور همه‌ی پیام‌های ربات (answer / reply / send_message / edit) پوشش داده می‌شوند."""
    for field in ("text", "caption"):
        value = getattr(method, field, None)
        if isinstance(value, str) and value:
            try:
                object.__setattr__(method, field, _premium_text(value))
            except Exception:
                pass
    return await make_request(bot_obj, method)


bot.session.middleware(_premium_emoji_middleware)
dp = Dispatcher()

# =============== مسیر فایل‌های دیتابیس ===============
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.getenv("BOT_DATA_DIR", os.path.join(BASE_DIR, "data"))
os.makedirs(DATA_DIR, exist_ok=True)

FILES = {
    "users": os.path.join(DATA_DIR, "users.json"),
    "orders": os.path.join(DATA_DIR, "orders.json"),
    "plans": os.path.join(DATA_DIR, "plans.json"),
    "settings": os.path.join(DATA_DIR, "settings.json"),
    "coupons": os.path.join(DATA_DIR, "coupons.json"),
    "blacklist": os.path.join(DATA_DIR, "blacklist.json"),
    "test_pool": os.path.join(DATA_DIR, "test_pool.json"),
    "config_pool": os.path.join(DATA_DIR, "config_pool.json"),
}

# =============== توابع خواندن/نوشتن JSON (امن و اتمیک) ===============
def save_json(file_path: str, data: Any) -> bool:
    """ذخیره امن JSON: ابتدا در فایل موقت می‌نویسد بعد جایگزین می‌کند تا فایل خراب نشود."""
    try:
        tmp_path = file_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, file_path)
        return True
    except Exception as e:
        logger.error(f"❌ خطا در ذخیره {file_path}: {e}")
        return False


def load_json(file_path: str, default: Any) -> Any:
    """خواندن JSON با مدیریت خطا؛ در صورت خرابی، بکاپ گرفته و مقدار پیش‌فرض برمی‌گردد."""
    if not os.path.exists(file_path):
        return default
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"❌ خطا در خواندن {file_path}: {e}")
        try:
            backup = file_path + ".corrupt_" + datetime.now().strftime("%Y%m%d_%H%M%S")
            os.replace(file_path, backup)
            logger.warning(f"⚠️ فایل خراب به {backup} منتقل شد")
        except Exception:
            pass
        return default


# =============== دیتای پیش‌فرض ===============
DEFAULT_KEYBOARD = {
    "buy_service":      {"visible": True, "text": "🛡 خرید سرویس"},
    "my_configs":       {"visible": True, "text": "🗃 کانفیگ های من"},
    "increase_balance": {"visible": True, "text": "💰 افزایش موجودی"},
    "my_account":       {"visible": True, "text": "❕ حساب کاربری"},
    "invite_friends":   {"visible": True, "text": "👥 دعوت از دوستان"},
    "apply_coupon":     {"visible": True, "text": "🏷️ اعمال کوپن"},
    "test_service":     {"visible": True, "text": "🧪 دریافت تست رایگان"},
}

DEFAULT_SETTINGS: Dict[str, Any] = {
    "admins": [],                    # آیدی عددی ادمین‌های اضافه (سوپر ادمین جداست)
    "shop_open": True,               # باز/بسته بودن فروشگاه
    "keyboard": DEFAULT_KEYBOARD,    # تنظیمات دکمه‌های شیشه‌ای منوی اصلی
    "price": {
        "min_charge": MIN_CHARGE,
        "max_charge": MAX_CHARGE,
        "referral_bonus": REFERRAL_BONUS,
        "referral_percent": REFERRAL_PERCENT,
    },
    "referral_milestones": {
        "enabled": True,             # روشن/خاموش بودن پاداش پله‌ای
        "require_purchase": False,   # آیا رفرال فقط وقتی حساب شود که خرید کرده باشد؟
        "tiers": DEFAULT_REFERRAL_TIERS,
    },
    "card": {
        "number": BANK_CARD_NUMBER,
        "holder": BANK_CARD_HOLDER,
        "bank": BANK_NAME,
    },
    "test_service": {
        "enabled": True,
        "max_per_user": TEST_MAX_PER_USER,
    },
    "support_username": SUPPORT_USERNAME,  # 💬 آیدی پشتیبانی (از پنل ادمین قابل ویرایش)
    "force_join_enabled": True,            # 📢 عضویت اجباری روشن/خاموش
    "force_join_channels": [],             # 📢 لیست کانال‌های عضویت اجباری
}


def _merge_defaults(saved: dict, default: dict) -> dict:
    """ادغام بازگشتی تنظیمات ذخیره‌شده با پیش‌فرض‌ها (تا کلید جدیدی جا نماند)."""
    result = copy.deepcopy(default)
    for key, value in (saved or {}).items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _merge_defaults(value, result[key])
        else:
            result[key] = value
    return result


# =============== بارگذاری دیتا در حافظه ===============
USERS: Dict[str, dict] = load_json(FILES["users"], {})
ORDERS: Dict[str, dict] = load_json(FILES["orders"], {})
PLANS: Dict[str, Any] = load_json(FILES["plans"], {"categories": []})
if not isinstance(PLANS, dict) or "categories" not in PLANS:
    PLANS = {"categories": []}
SETTINGS: Dict[str, Any] = _merge_defaults(load_json(FILES["settings"], {}), DEFAULT_SETTINGS)
COUPONS: Dict[str, dict] = load_json(FILES["coupons"], {})
BLACKLIST: set = set(load_json(FILES["blacklist"], []))
TEST_POOL: List[dict] = load_json(FILES["test_pool"], [])
if not isinstance(TEST_POOL, list):
    TEST_POOL = []

CONFIG_POOL: List[dict] = load_json(FILES["config_pool"], [])
if not isinstance(CONFIG_POOL, list):
    CONFIG_POOL = []

# وضعیت‌های موقت کاربران/ادمین (در حافظه)
user_states: Dict[int, dict] = {}

# نگاشت «پیام اعلان ادمین» → سفارش (برای قابلیت ریپلای کردن کانفیگ)
# کلید: "chat_id:message_id"  →  مقدار: order_id
NOTIF_MAP: Dict[str, int] = {}


def save_users() -> None:
    save_json(FILES["users"], USERS)


def save_orders() -> None:
    save_json(FILES["orders"], ORDERS)


def save_plans() -> None:
    save_json(FILES["plans"], PLANS)


def save_settings() -> None:
    save_json(FILES["settings"], SETTINGS)


def save_coupons() -> None:
    save_json(FILES["coupons"], COUPONS)


def save_blacklist() -> None:
    save_json(FILES["blacklist"], sorted(BLACKLIST))


def save_test_pool() -> None:
    save_json(FILES["test_pool"], TEST_POOL)


def save_config_pool() -> None:
    save_json(FILES["config_pool"], CONFIG_POOL)


def rebuild_notif_map() -> None:
    """بازسازی نگاشت پیام‌های اعلان از روی سفارش‌های در انتظار کانفیگ (بعد از ری‌استارت)."""
    NOTIF_MAP.clear()
    for order in ORDERS.values():
        if order.get("status") == "awaiting_config":
            for msg_ref in order.get("notif_msgs", []):
                key = f"{msg_ref.get('chat')}:{msg_ref.get('msg')}"
                NOTIF_MAP[key] = order.get("order_id")


rebuild_notif_map()


# =============== توابع کمکی عمومی ===============
def is_admin(user_id: int) -> bool:
    """سوپر ادمین یا یکی از ادمین‌های اضافه‌شده است؟"""
    return user_id == SUPER_ADMIN_ID or user_id in SETTINGS.get("admins", [])


def get_admin_ids() -> List[int]:
    """لیست همه ادمین‌ها (سوپر ادمین همیشه اول)."""
    ids = [SUPER_ADMIN_ID]
    for aid in SETTINGS.get("admins", []):
        if aid != SUPER_ADMIN_ID and aid not in ids:
            ids.append(aid)
    return ids

# =============== 🗃 مخزن کانفیگ + 📢 عضویت اجباری + 💬 پشتیبانی + 📊 لاگ ===============
def get_support() -> str:
    """آیدی پشتیبانی از تنظیمات (قابل ویرایش از پنل ادمین)."""
    return SETTINGS.get("support_username") or SUPPORT_USERNAME


def get_force_channels() -> List[str]:
    chans = SETTINGS.get("force_join_channels", [])
    return chans if isinstance(chans, list) else []


def get_sale_mode(plan: dict) -> str:
    """حالت فروش پلن: «pool» (از مخزن، خودکار) یا «manual» (دستی).
    اگر پلن حالت ذخیره‌شده نداشته باشد ولی برایش کانفیگ در مخزن باشد → «pool»."""
    plan = plan or {}
    mode = plan.get("sale_mode")
    if mode in ("pool", "manual"):
        return mode
    # پیش‌فرض هوشمند: اگر مخزن این پلن کانفیگ دارد، خودکار از مخزن تحویل بده
    if any(c.get("plan_id") == plan.get("id") for c in CONFIG_POOL):
        return "pool"
    return "manual"


def pool_configs(plan_id: int, package_id: int) -> List[dict]:
    return [c for c in CONFIG_POOL if c.get("plan_id") == plan_id and c.get("package_id") == package_id]


def pool_count(plan_id: int, package_id: int) -> int:
    return len(pool_configs(plan_id, package_id))


def pop_pool_config(plan_id: int, package_id: int) -> Optional[dict]:
    """برداشتن یک کانفیگ از مخزن یک پلن+بسته (غیرتکراری — از مخزن حذف می‌شود)."""
    for i, c in enumerate(CONFIG_POOL):
        if c.get("plan_id") == plan_id and c.get("package_id") == package_id:
            item = CONFIG_POOL.pop(i)
            save_config_pool()
            return item
    return None


async def log_event(text: str) -> None:
    """ارسال لاگ رویداد به گروه لاگ."""
    if not LOG_CHAT_ID:
        return
    try:
        await bot.send_message(LOG_CHAT_ID, text, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.warning(f"⚠️ ارسال لاگ به گروه ({LOG_CHAT_ID}) ناموفق بود: {e}")


async def check_force_join(user_id: int) -> List[str]:
    """لیست کانال‌هایی که کاربر هنوز عضوشان نیست (اگر عضویت اجباری فعال باشد)."""
    if not SETTINGS.get("force_join_enabled", True):
        return []
    missing = []
    for ch in get_force_channels():
        try:
            member = await bot.get_chat_member(ch, user_id)
            if getattr(member, "status", "left") in ("left", "kicked"):
                missing.append(ch)
        except Exception as e:
            logger.warning(f"⚠️ بررسی عضویت در {ch} ناموفق بود: {e}")
    return missing


def force_join_keyboard(missing: List[str], retry_data: str) -> InlineKeyboardMarkup:
    """کیبورد عضویت اجباری: لینک کانال‌ها + دکمه بررسی مجدد."""
    buttons = []
    for ch in missing:
        url = str(ch) if str(ch).startswith("http") else f"https://t.me/{str(ch).lstrip('@')}"
        buttons.append([InlineKeyboardButton(text=f"📢 عضویت در {ch}", url=url)])
    buttons.append([InlineKeyboardButton(text="✅ بررسی عضویت", callback_data=retry_data)])
    buttons.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data="back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def force_join_gate(callback: CallbackQuery, retry_data: str) -> bool:
    """اگر کاربر عضو کانال‌های اجباری نباشد، پیام عضویت را نشان می‌دهد و True برمی‌گرداند."""
    missing = await check_force_join(callback.from_user.id)
    if not missing:
        return False
    channels_text = "\n".join(f"• {esc(ch)}" for ch in missing)
    await safe_edit(
        callback,
        "🔒 <b>عضویت اجباری</b>\n\n"
        "برای خرید پنل، ابتدا در کانال(های) زیر عضو شوید:\n\n"
        f"{channels_text}\n\n"
        "✅ بعد از عضویت، دکمه «بررسی عضویت» را بزنید.",
        reply_markup=force_join_keyboard(missing, retry_data),
    )
    await safe_answer(callback)
    return True


def esc(text: Any) -> str:
    """Escape کردن متن برای HTML تا پیام خراب نشود."""
    return html.escape(str(text if text is not None else ""))


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_str() -> str:
    return datetime.now().strftime("%Y/%m/%d")


def parse_int(text: Any) -> Optional[int]:
    """تبدیل متن به عدد صحیح با پشتیبانی از اعداد فارسی/عربی و جداکننده‌ها."""
    if text is None:
        return None
    s = str(text).strip()
    fa_digits = "۰۱۲۳۴۵۶۷۸۹"
    ar_digits = "٠١٢٣٤٥٦٧٨٩"
    for i, d in enumerate(fa_digits):
        s = s.replace(d, str(i))
    for i, d in enumerate(ar_digits):
        s = s.replace(d, str(i))
    s = s.replace(",", "").replace("،", "").replace("٬", "").replace(" ", "").replace("تومان", "")
    if not re.fullmatch(r"-?\d+", s):
        return None
    try:
        return int(s)
    except (ValueError, TypeError):
        return None


def format_volume(volume: Any) -> str:
    """نمایش حجم؛ صفر یعنی نامحدود."""
    try:
        v = float(volume)
    except (ValueError, TypeError):
        return str(volume)
    if v == 0:
        return "♾️ نامحدود"
    if v == int(v):
        return f"{int(v)} GB"
    return f"{v:.2f} GB"


def next_numeric_id(container: Any, key: str = "id") -> int:
    """تولید آیدی عددی بعدی برای دیکشنری یا لیست."""
    max_id = 0
    if isinstance(container, dict):
        for k in container.keys():
            try:
                max_id = max(max_id, int(k))
            except (ValueError, TypeError):
                continue
    elif isinstance(container, list):
        for item in container:
            try:
                max_id = max(max_id, int(item.get(key, 0)))
            except (ValueError, TypeError, AttributeError):
                continue
    return max_id + 1


def get_user(user_id: int, name: str = None, username: str = None) -> dict:
    """دریافت رکورد کاربر؛ اگر نبود می‌سازد. نام/یوزرنیم تازه هم به‌روز می‌شود."""
    uid = str(user_id)
    created = False
    if uid not in USERS:
        USERS[uid] = {
            "id": user_id,
            "name": name or "کاربر",
            "username": username or "",
            "balance": 0,
            "join_date": today_str(),
            "referred_by": None,
            "has_purchased": False,
            "total_purchases": 0,
            "total_spent": 0,
            "coupon_code": None,
            "coupon_discount": 0,
            "coupon_applied": False,
            "test_count": 0,
            "created_at": now_str(),
        }
        created = True
    user = USERS[uid]
    changed = created
    if name and user.get("name") != name:
        user["name"] = name
        changed = True
    if username is not None and user.get("username") != username:
        user["username"] = username
        changed = True
    for field, default in (
        ("balance", 0), ("total_purchases", 0), ("total_spent", 0),
        ("coupon_code", None), ("coupon_discount", 0), ("coupon_applied", False),
        ("test_count", 0), ("referred_by", None), ("has_purchased", False),
        ("milestones_claimed", []),
    ):
        if field not in user:
            user[field] = default
            changed = True
    if changed:
        save_users()
    return user


def add_balance(user_id: int, amount: int) -> int:
    user = get_user(user_id)
    user["balance"] = user.get("balance", 0) + amount
    save_users()
    return user["balance"]


def reduce_balance(user_id: int, amount: int) -> int:
    user = get_user(user_id)
    user["balance"] = max(0, user.get("balance", 0) - amount)
    save_users()
    return user["balance"]


def create_order(user_id: int, order_type: str, volume: Any, days: int, price: int,
                 plan_id: int = None, plan_name: str = None, package_id: int = None,
                 payment_method: str = None, coupon_code: str = None,
                 discount_percent: int = 0) -> int:
    """ساخت سفارش جدید و بازگرداندن شماره آن."""
    order_id = next_numeric_id(ORDERS)
    ORDERS[str(order_id)] = {
        "order_id": order_id,
        "user_id": user_id,
        "type": order_type,               # purchase | balance_charge | test
        "plan_id": plan_id,
        "plan_name": plan_name,
        "package_id": package_id,
        "volume": volume,
        "days": days,
        "price": price,
        "status": "awaiting_payment",     # awaiting_payment | pending | awaiting_config | approved | rejected | cancelled
        "payment_method": payment_method, # balance | card | test
        "receipt_photo_id": None,
        "config_link": None,
        "coupon_code": coupon_code,
        "discount_percent": discount_percent,
        "notif_msgs": [],                 # پیام‌های اعلان ادمین برای ریپلای
        "date": now_str(),
        "created_at": now_str(),
        "approved_date": None,
    }
    save_orders()
    return order_id


def update_order(order_id: int, **kwargs) -> None:
    order = ORDERS.get(str(order_id))
    if not order:
        return
    order.update(kwargs)
    save_orders()


def get_order(order_id: int) -> Optional[dict]:
    return ORDERS.get(str(order_id))


def referral_bonus_for(price: int) -> int:
    """پاداش دعوت = درصدی از مبلغ خرید دوست (پیش‌فرض ۱۰٪). اگر درصد صفر بود، از مبلغ ثابت استفاده کن."""
    percent = SETTINGS.get("price", {}).get("referral_percent")
    if percent is None:
        # مهاجرت از نسخه قدیمی (فقط مبلغ ثابت)
        percent = 0
    if percent and percent > 0:
        return int(price * percent / 100)
    return SETTINGS.get("price", {}).get("referral_bonus", REFERRAL_BONUS)


def milestones_conf() -> dict:
    """تنظیمات پاداش پله‌ای با مقادیر پیش‌فرض."""
    conf = SETTINGS.setdefault("referral_milestones", {})
    conf.setdefault("enabled", True)
    conf.setdefault("require_purchase", False)
    conf.setdefault("tiers", [dict(t) for t in DEFAULT_REFERRAL_TIERS])
    return conf


def milestone_tiers() -> List[dict]:
    """پله‌ها به ترتیب صعودیِ تعداد رفرال."""
    tiers = [t for t in milestones_conf().get("tiers", []) if t.get("count") and t.get("reward")]
    return sorted(tiers, key=lambda t: int(t["count"]))


def count_referrals(user_id: int) -> int:
    """تعداد رفرال‌های یک کاربر (اگر require_purchase روشن باشد، فقط خریدکرده‌ها)."""
    only_paid = bool(milestones_conf().get("require_purchase"))
    total = 0
    for u in USERS.values():
        if u.get("referred_by") != user_id:
            continue
        if only_paid and not u.get("has_purchased"):
            continue
        total += 1
    return total


def next_milestone(user_id: int) -> Optional[dict]:
    """پله‌ی بعدی که کاربر هنوز نگرفته است."""
    user = get_user(user_id)
    claimed = set(int(c) for c in user.get("milestones_claimed", []))
    for tier in milestone_tiers():
        if int(tier["count"]) not in claimed:
            return tier
    return None


async def check_referral_milestones(user_id: int) -> None:
    """بررسی و پرداخت پاداش پله‌ای — هر پله فقط یک‌بار برای همیشه."""
    conf = milestones_conf()
    if not conf.get("enabled", True):
        return
    tiers = milestone_tiers()
    if not tiers:
        return

    user = get_user(user_id)
    claimed = set(int(c) for c in user.get("milestones_claimed", []))
    ref_count = count_referrals(user_id)

    for tier in tiers:
        need = int(tier["count"])
        reward = int(tier["reward"])
        if ref_count < need or need in claimed:
            continue

        new_balance = add_balance(user_id, reward)
        claimed.add(need)
        user["milestones_claimed"] = sorted(claimed)
        save_users()

        nxt = next_milestone(user_id)
        nxt_line = ""
        if nxt:
            remain = int(nxt["count"]) - ref_count
            if remain > 0:
                nxt_line = (f"\n\n🎯 پله بعدی: {int(nxt['count'])} دعوت → "
                            f"{int(nxt['reward']):,} تومان (فقط {remain} نفر دیگر!)")

        try:
            await bot.send_message(
                user_id,
                f"🏆 <b>تبریک! پله‌ی جدید فتح شد</b>\n\n"
                f"👥 شما {need} کاربر دعوت کرده‌اید.\n"
                f"🎁 پاداش این پله: <b>{reward:,} تومان</b>\n"
                f"💳 موجودی فعلی: {new_balance:,} تومان{nxt_line}",
            )
        except Exception as e:
            logger.warning(f"⚠️ ارسال پیام پاداش پله‌ای ناموفق: {e}")

        await log_event(
            f"🏆 <b>پاداش پله‌ای</b> — کاربر <code>{user_id}</code> با {need} دعوت "
            f"{reward:,} تومان دریافت کرد."
        )
        await notify_admins(
            f"🏆 <b>پاداش پله‌ای پرداخت شد</b>\n\n"
            f"👤 کاربر: <code>{user_id}</code>\n"
            f"👥 تعداد دعوت: {need}\n"
            f"🎁 مبلغ: {reward:,} تومان"
        )


def record_purchase(user_id: int, price: int) -> None:
    """ثبت خرید موفق + پاداش رفرال به دعوت‌کننده (۱۰٪ مبلغ خرید)."""
    user = get_user(user_id)
    user["has_purchased"] = True
    user["total_purchases"] = user.get("total_purchases", 0) + 1
    user["total_spent"] = user.get("total_spent", 0) + price
    save_users()

    referrer_id = user.get("referred_by")
    if referrer_id and price > 0:
        bonus = referral_bonus_for(price)
        if bonus > 0:
            new_balance = add_balance(int(referrer_id), bonus)
            try:
                percent = SETTINGS.get("price", {}).get("referral_percent") or 0
                src = f"({percent}٪ مبلغ خرید)" if percent else ""
                asyncio.create_task(bot.send_message(
                    int(referrer_id),
                    f"🎁 <b>هدیه دعوت از دوستان!</b>\n\n"
                    f"👤 دوست شما یک خرید انجام داد.\n"
                    f"💰 مبلغ {bonus:,} تومان {src} به موجودی شما اضافه شد.\n"
                    f"💳 موجودی فعلی: {new_balance:,} تومان",
                ))
            except Exception as e:
                logger.warning(f"خطا در ارسال پیام پاداش رفرال: {e}")
        # 🏆 بررسی پله‌های دعوت‌کننده (وقتی شرط «فقط خریدکرده‌ها» روشن است مهم می‌شود)
        try:
            asyncio.create_task(check_referral_milestones(int(referrer_id)))
        except Exception as e:
            logger.warning(f"خطا در بررسی پله‌های رفرال: {e}")


# =============== کوپن‌ها ===============
def get_coupon(code: str) -> Optional[dict]:
    if not code:
        return None
    return COUPONS.get(code.strip())


def coupon_is_usable(coupon: Optional[dict], user_id: int) -> bool:
    if not coupon:
        return False
    if coupon.get("status") != "active":
        return False
    used_by = coupon.get("used_by", [])
    if user_id in used_by:
        return False
    max_uses = coupon.get("max_uses", 0)
    if max_uses and len(used_by) >= max_uses:
        return False
    return True


def consume_coupon(user_id: int) -> None:
    """مصرف کوپن فعال کاربر بعد از خرید موفق."""
    user = get_user(user_id)
    code = user.get("coupon_code")
    if user.get("coupon_applied") and code and code in COUPONS:
        coupon = COUPONS[code]
        used_by = coupon.setdefault("used_by", [])
        if user_id not in used_by:
            used_by.append(user_id)
        save_coupons()
    user["coupon_code"] = None
    user["coupon_discount"] = 0
    user["coupon_applied"] = False
    save_users()


def release_coupon(user_id: int) -> None:
    """آزادسازی کوپن بدون مصرف (مثلاً وقتی سفارش رد/لغو شد)."""
    user = get_user(user_id)
    user["coupon_code"] = None
    user["coupon_discount"] = 0
    user["coupon_applied"] = False
    save_users()


def apply_discount(price: int, user_id: int) -> tuple:
    """محاسبه قیمت نهایی با کوپن کاربر. خروجی: (قیمت نهایی، درصد تخفیف، کد کوپن)."""
    user = get_user(user_id)
    if user.get("coupon_applied") and user.get("coupon_code"):
        coupon = get_coupon(user["coupon_code"])
        if coupon_is_usable(coupon, user_id):
            percent = coupon.get("percent", user.get("coupon_discount", 0))
            if percent > 0:
                final = price - (price * percent // 100)
                return max(final, 0), percent, user["coupon_code"]
    return price, 0, None


# =============== پلن‌ها (بسته‌های آماده) ===============
def get_plan(plan_id: int) -> Optional[dict]:
    for cat in PLANS.get("categories", []):
        if cat.get("id") == plan_id:
            return cat
    return None


def get_package(plan: dict, package_id: int) -> Optional[dict]:
    if not plan:
        return None
    for pkg in plan.get("packages", []):
        if pkg.get("id") == package_id:
            return pkg
    return None


def active_plans() -> List[dict]:
    plans = [c for c in PLANS.get("categories", []) if c.get("is_active", True)]
    return [c for c in plans if any(p.get("is_active", True) for p in c.get("packages", []))]


# =============== QR Code ===============
def make_qr_bytes(data: str) -> Optional[bytes]:
    if not QR_AVAILABLE:
        return None
    try:
        img = qrcode.make(data)
        buf = BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception as e:
        logger.warning(f"خطا در ساخت QR: {e}")
        return None


async def send_config_to_user(user_id: int, config_link: str, title: str = None,
                              extra: str = None) -> None:
    """ارسال کانفیگ به کاربر به صورت متن قابل‌کپی + QR (در صورت وجود کتابخانه)."""
    header = title or "🔑 <b>کانفیگ شما</b>"
    text = f"{header}\n\n<code>{esc(config_link)}</code>\n"
    if extra:
        text += f"\n{extra}"
    text += "\n💡 برای کپی، روی کانفیگ بزنید."

    qr_bytes = make_qr_bytes(config_link)
    if qr_bytes:
        try:
            caption = text if len(text) <= 1000 else None
            await bot.send_photo(
                user_id,
                BufferedInputFile(qr_bytes, filename="config_qr.png"),
                caption=caption,
                parse_mode=ParseMode.HTML if caption else None,
            )
            if caption is None:
                await bot.send_message(user_id, text, parse_mode=ParseMode.HTML)
            return
        except Exception as e:
            logger.warning(f"خطا در ارسال QR به {user_id}: {e}")
    await bot.send_message(user_id, text, parse_mode=ParseMode.HTML)


async def safe_edit(callback: CallbackQuery, text: str,
                    reply_markup: InlineKeyboardMarkup = None) -> None:
    """ویرایش امن پیام؛ اگر نشد، پیام جدید می‌فرستد. ایموجی‌های متن پرمیوم می‌شوند."""
    text = _premium_text(text)
    try:
        await callback.message.edit_text(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    except Exception as e:
        if "message is not modified" in str(e):
            pass
        else:
            try:
                await callback.message.delete()
            except Exception:
                pass
            await callback.message.answer(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)


async def safe_answer(callback: CallbackQuery, text: str = None, show_alert: bool = False) -> None:
    """پاسخ امن به کال‌بک؛ اگر قبلاً پاسخ داده شده یا کوئری قدیمی باشد، خطا نمی‌دهد."""
    try:
        await callback.answer(text, show_alert=show_alert)
    except Exception:
        pass


async def notify_admins(text: str, reply_markup: InlineKeyboardMarkup = None) -> List[dict]:
    """ارسال پیام به همه ادمین‌ها و برگرداندن مراجع پیام‌ها [{chat, msg}]."""
    refs = []
    for admin_id in get_admin_ids():
        try:
            msg = await bot.send_message(admin_id, text, reply_markup=reply_markup,
                                         parse_mode=ParseMode.HTML)
            refs.append({"chat": admin_id, "msg": msg.message_id})
        except Exception as e:
            logger.error(f"❌ خطا در ارسال اعلان به ادمین {admin_id}: {e}")
    return refs


async def send_order_config_request(order_id: int) -> None:
    """ارسال اعلان «در انتظار کانفیگ» به ادمین‌ها با قابلیت ریپلای برای ارسال کانفیگ."""
    order = get_order(order_id)
    if not order:
        return
    user = get_user(order["user_id"])
    username_display = f"@{esc(user.get('username'))}" if user.get("username") else "ندارد"

    plan_name = order.get("plan_name") or "خرید سرویس"
    method_fa = {"balance": "💰 پرداخت با موجودی", "card": "💳 کارت‌به‌کارت"}.get(
        order.get("payment_method"), "🛒 خرید")

    text = (
        f"🔔 <b>سفارش جدید — در انتظار ارسال کانفیگ</b>\n\n"
        f"👤 کاربر: {esc(user.get('name', 'کاربر'))}\n"
        f"🆔 آیدی: <code>{order['user_id']}</code>\n"
        f"📛 یوزرنیم: {username_display}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 پلن: {esc(plan_name)}\n"
        f"📊 بسته: {format_volume(order.get('volume', 0))} / {order.get('days', 0)} روز\n"
        f"💰 مبلغ: {order.get('price', 0):,} تومان\n"
        f"💳 روش پرداخت: {method_fa}\n"
        f"💵 موجودی فعلی کاربر: {user.get('balance', 0):,} تومان\n"
        f"🆔 شماره سفارش: #{order_id}\n"
        f"📅 زمان: {esc(order.get('date', now_str()))}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📤 <b>برای ارسال کانفیگ، همین پیام را «ریپلای» کنید و لینک/کانفیگ را بفرستید.</b>\n"
        f"ربات به صورت خودکار آن را برای خریدار ارسال می‌کند. ✅"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        styled_btn("❌ لغو سفارش و بازگشت وجه", f"ordcancel_{order_id}", "danger")
    ]])

    refs = await notify_admins(text, reply_markup=kb)
    order = get_order(order_id)  # تازه‌سازی
    if order:
        order["notif_msgs"] = refs
        save_orders()
        for ref in refs:
            NOTIF_MAP[f"{ref['chat']}:{ref['msg']}"] = order_id


async def close_order_notifications(order: dict, note: str) -> None:
    """الحاق وضعیت نهایی به پیام‌های اعلان و پاک‌سازی نگاشت ریپلای."""
    for ref in order.get("notif_msgs", []):
        # نگاشت عمداً نگه داشته می‌شود تا ریپلای مجدد پاسخ «قبلاً پردازش شده» بگیرد
        try:
            await bot.send_message(ref["chat"], note, reply_to_message_id=ref["msg"],
                                   parse_mode=ParseMode.HTML)
        except Exception:
            pass
    order["notif_msgs"] = []


# =============== کیبوردها ===============
def get_main_keyboard(is_admin_user: bool = False, user_id: int = None) -> InlineKeyboardMarkup:
    """کیبورد اصلی کاربر — دکمه‌ها از تنظیمات خوانده می‌شوند تا ادمین بتواند مدیریتشان کند."""
    kb_conf = SETTINGS.get("keyboard", {})

    def btn(key: str) -> Optional[InlineKeyboardButton]:
        conf = kb_conf.get(key, {})
        if not conf.get("visible", True):
            return None
        labels = {"my_configs": "📁 پنل‌های من", "buy_service": "🛒 خرید پنل نمایندگی"}
        return InlineKeyboardButton(text=labels.get(key, conf.get("text", key)), callback_data=key)

    buttons: List[List[InlineKeyboardButton]] = []

    row1 = [b for b in (btn("my_configs"), btn("buy_service")) if b]
    if row1:
        buttons.append(row1)

    row2 = [b for b in (btn("increase_balance"), btn("my_account")) if b]
    if row2:
        buttons.append(row2)

    if is_admin_user:
        buttons.append([InlineKeyboardButton(text="👑 پنل ادمین", callback_data="admin_panel")])

    if not buttons:
        buttons.append([InlineKeyboardButton(text="🚀 شروع", callback_data="back_to_main")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_back_only_keyboard(callback_data: str = "back_to_main") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔙 بازگشت", callback_data=callback_data)
    ]])


def get_cancel_keyboard(callback_data: str = "back_to_main") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="❌ انصراف", callback_data=callback_data)
    ]])


def styled_btn(text: str, callback_data: str, style=None):
    """سازگاری با کدهای قبلی — رنگ نهایی به‌صورت سطری روی کیبورد اعمال می‌شود."""
    return InlineKeyboardButton(text=text, callback_data=callback_data)


def get_admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        *admin_sales_launch(),
        [
            styled_btn("📋 سفارشات", "admin_orders", "primary"),
            InlineKeyboardButton(text="👥 کاربران", callback_data="admin_users"),
        ],
        [
            InlineKeyboardButton(text="📢 عضویت اجباری", callback_data="admin_forcejoin"),
        ],
        [
            InlineKeyboardButton(text="👑 مدیریت ادمین‌ها", callback_data="admin_admins"),
            InlineKeyboardButton(text="⌨️ مدیریت دکمه‌ها", callback_data="admin_keyboard"),
        ],
        [
            InlineKeyboardButton(text="🏷️ مدیریت کوپن‌ها", callback_data="admin_coupons"),
            styled_btn("🎁 هدیه موجودی", "admin_gift", "success"),
        ],
        [
            InlineKeyboardButton(text="🏆 پاداش پله‌ای دعوت", callback_data="admin_milestones"),
        ],
        [
            styled_btn("📢 پیام همگانی", "admin_broadcast", "danger"),
            styled_btn("🚫 لیست سیاه", "admin_blacklist", "danger"),
        ],
        [
            InlineKeyboardButton(text="📊 آمار", callback_data="admin_stats"),
            InlineKeyboardButton(text="⚙️ تنظیمات", callback_data="admin_settings"),
        ],
        [InlineKeyboardButton(text="💾 بکاپ", callback_data="admin_backup")],
        [InlineKeyboardButton(text="🔙 صفحه اصلی", callback_data="back_to_main")],
    ])


# =============== هندلر استارت ===============
@dp.message(CommandStart())
async def cmd_start(message: Message):
    user_id = message.from_user.id

    # ⛔ چک لیست سیاه
    if user_id in BLACKLIST:
        await message.answer("⛔ <b>دسترسی مسدود شده</b>\n\nشما در لیست سیاه قرار دارید.",
                             parse_mode=ParseMode.HTML)
        return

    user_name = message.from_user.first_name or message.from_user.username or "کاربر"
    if message.from_user.last_name:
        user_name += f" {message.from_user.last_name}"
    user_username = message.from_user.username or ""

    uid = str(user_id)
    is_new_user = uid not in USERS

    user = get_user(user_id, user_name, user_username)

    # =============== رفرال ===============
    args = message.text.split() if message.text else []
    if is_new_user and len(args) > 1 and args[1].isdigit():
        ref_id = int(args[1])
        if ref_id != user_id and str(ref_id) in USERS:
            user["referred_by"] = ref_id
            save_users()

            percent = SETTINGS.get("price", {}).get("referral_percent") or 0
            if percent:
                reward_line = f"🎁 با اولین خرید ایشان، {percent}٪ مبلغ خرید هدیه می‌گیرید."
            else:
                fixed = SETTINGS.get("price", {}).get("referral_bonus", REFERRAL_BONUS)
                reward_line = f"🎁 با اولین خرید ایشان، {fixed:,} تومان هدیه می‌گیرید."

            ref_count = count_referrals(ref_id)
            nxt = next_milestone(ref_id)
            tier_line = ""
            if milestones_conf().get("enabled", True) and nxt:
                remain = int(nxt["count"]) - ref_count
                if remain > 0:
                    tier_line = (f"\n🏆 پله بعدی: {int(nxt['count'])} دعوت → "
                                 f"{int(nxt['reward']):,} تومان ({remain} نفر دیگر)")

            try:
                await bot.send_message(
                    ref_id,
                    f"👥 <b>دعوت جدید!</b>\n\nکاربر {esc(user_name)} با لینک شما وارد ربات شد.\n"
                    f"{reward_line}\n"
                    f"📊 تعداد دعوت‌های شما: {ref_count}{tier_line}",
                )
            except Exception:
                pass

            # 🏆 بررسی پله‌های پاداش دعوت
            try:
                await check_referral_milestones(ref_id)
            except Exception as e:
                logger.warning(f"خطا در بررسی پله‌های رفرال: {e}")

    await log_event(
        f"🚀 <b>استارت</b> — {esc(user_name)} (<code>{user_id}</code>)"
        f"{' | @' + esc(user_username) if user_username else ''}"
        f"{' | 🆕 کاربر جدید' if is_new_user else ''}"
    )

    admin_flag = is_admin(user_id)

    # 🦆 استیکر خوش‌آمد (استیکر هفتم پک Duck X2) — قبل از منوی اصلی
    try:
        await message.answer_sticker(START_STICKER_ID)
    except Exception as e:
        logger.warning(f"⚠️ ارسال استیکر استارت ناموفق بود: {e}")

    if admin_flag:
        await message.answer("🚀 به پنل ادمین خوش آمدید!",
                             reply_markup=get_main_keyboard(True, user_id))
    else:
        await message.answer(f"🚀 سلام {esc(user_name)}! خوش آمدید",
                             reply_markup=get_main_keyboard(False, user_id))


@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("👑 <b>پنل مدیریت</b>\n\nیکی از بخش‌ها را انتخاب کنید:",
                         reply_markup=get_admin_keyboard(), parse_mode=ParseMode.HTML)


@dp.message(Command("id"))
async def cmd_id(message: Message):
    await message.answer(f"🆔 آیدی عددی شما: <code>{message.from_user.id}</code>",
                         parse_mode=ParseMode.HTML)


@dp.callback_query(F.data == "noop")
async def noop_handler(callback: CallbackQuery):
    await safe_answer(callback)


@dp.callback_query(F.data == "back_to_main")
async def back_to_main(callback: CallbackQuery):
    user_id = callback.from_user.id
    user_states.pop(user_id, None)
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(
        "🚀 منوی اصلی",
        reply_markup=get_main_keyboard(is_admin(user_id), user_id),
    )
    await safe_answer(callback)


@dp.callback_query(F.data == "admin_panel")
async def admin_panel(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    user_states.pop(callback.from_user.id, None)
    await safe_edit(
        callback,
        "👑 <b>پنل مدیریت</b>\n\nیکی از بخش‌ها را انتخاب کنید:",
        reply_markup=get_admin_keyboard(),
    )
    await safe_answer(callback)


# =============== 🛒 خرید سرویس ===============
async def buy_service(callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id in BLACKLIST:
        await safe_answer(callback, "⛔ دسترسی مسدود شده", show_alert=True)
        return

    if not SETTINGS.get("shop_open", True):
        await safe_answer(callback, "🛒 فروشگاه موقتاً بسته است. لطفاً بعداً مراجعه کنید.", show_alert=True)
        return

    # 🔒 عضویت اجباری برای خرید کانفیگ
    if await force_join_gate(callback, "buy_service"):
        return

    plans = active_plans()
    if not plans:
        await safe_edit(
            callback,
            "❌ <b>هیچ پلن فعالی موجود نیست.</b>\n\n💡 لطفاً بعداً سر بزنید یا با پشتیبانی در تماس باشید.",
            reply_markup=get_back_only_keyboard(),
        )
        await safe_answer(callback)
        return

    user = get_user(user_id)
    coupon_text = ""
    if user.get("coupon_applied") and user.get("coupon_code"):
        coupon_text = f"\n\n🏷️ <b>کوپن فعال:</b> {esc(user['coupon_code'])} ({user.get('coupon_discount', 0)}%)"

    text = f"📦 <b>انتخاب پلن</b>\n\nلطفاً پلن مورد نظر را انتخاب کنید:{coupon_text}"

    buttons = []
    for plan in plans:
        icon = plan.get("icon", "📦")
        pkg_count = len([p for p in plan.get("packages", []) if p.get("is_active", True)])
        plan_type = plan.get("type", "")
        type_badge = f" | {plan_type}" if plan_type else ""
        buttons.append([InlineKeyboardButton(
            text=f"{icon} {plan.get('name')}{type_badge} ({pkg_count} بسته)",
            callback_data=f"buyplan_{plan.get('id')}",
        )])
    buttons.append([InlineKeyboardButton(text="🔙 بازگشت به منوی اصلی", callback_data="back_to_main")])

    await safe_edit(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await safe_answer(callback)


@dp.callback_query(F.data.startswith("buyplan_"))
async def buy_plan_select(callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id in BLACKLIST:
        await safe_answer(callback, "⛔ دسترسی مسدود شده", show_alert=True)
        return

    plan_id = parse_int(callback.data.split("_", 1)[1])
    plan = get_plan(plan_id)
    if not plan:
        await safe_answer(callback, "❌ پلن یافت نشد", show_alert=True)
        return

    packages = [p for p in plan.get("packages", []) if p.get("is_active", True)]
    if not packages:
        await safe_answer(callback, "❌ این پلن فعلاً بسته فعالی ندارد", show_alert=True)
        return

    icon = plan.get("icon", "📦")
    text = f"{icon} <b>{esc(plan.get('name'))}</b>\n\nلطفاً بسته مورد نظر را انتخاب کنید:\n"

    buttons = []
    for idx, pkg in enumerate(packages, start=1):
        price, discount, _ = apply_discount(pkg.get("price", 0), user_id)
        price_text = f"{price:,} تومان"
        if discount > 0:
            price_text = f"{price:,} تومان 🔥 {discount}% تخفیف"
        buttons.append([InlineKeyboardButton(
            text=f"{idx} - {format_volume(pkg.get('volume', 0))} | {pkg.get('days', 30)} روز | {price_text}",
            callback_data=f"buypkg_{plan_id}_{pkg.get('id')}",
        )])
    buttons.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data="buy_service")])

    await safe_edit(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await safe_answer(callback)


@dp.callback_query(F.data.startswith("buypkg_"))
async def buy_package_select(callback: CallbackQuery):
    """نمایش خلاصه بسته و انتخاب روش پرداخت."""
    user_id = callback.from_user.id
    if user_id in BLACKLIST:
        await safe_answer(callback, "⛔ دسترسی مسدود شده", show_alert=True)
        return

    parts = callback.data.split("_")
    if len(parts) != 3:
        await safe_answer(callback, "❌ خطا", show_alert=True)
        return
    plan_id = parse_int(parts[1])
    package_id = parse_int(parts[2])
    plan = get_plan(plan_id)
    pkg = get_package(plan, package_id)
    if not plan or not pkg:
        await safe_answer(callback, "❌ بسته یافت نشد", show_alert=True)
        return

    price, discount, coupon_code = apply_discount(pkg.get("price", 0), user_id)
    balance = get_user(user_id).get("balance", 0)

    user_states[user_id] = {
        "selected_plan": plan_id,
        "selected_package": package_id,
        "selected_price": price,
        "selected_discount": discount,
        "selected_coupon": coupon_code,
    }

    icon = plan.get("icon", "📦")
    discount_text = ""
    if discount > 0:
        discount_text = f"\n🏷️ <b>تخفیف کوپن:</b> {discount}% (قیمت اصلی: {pkg.get('price', 0):,} تومان)"

    text = (
        f"{icon} <b>خرید بسته: {esc(plan.get('name'))}</b>\n\n"
        f"📦 حجم: {format_volume(pkg.get('volume', 0))}\n"
        f"⏱ مدت: {pkg.get('days', 30)} روز\n"
        f"💰 قیمت: {price:,} تومان{discount_text}\n\n"
        f"💳 موجودی شما: {balance:,} تومان\n\n"
        f"💡 روش پرداخت را انتخاب کنید:"
    )

    buttons = [
        [styled_btn("💰 پرداخت با موجودی", "pay_balance", "success")],
        [styled_btn("💳 پرداخت کارت‌به‌کارت", "pay_card", "primary")],
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"buyplan_{plan_id}")],
    ]

    await safe_edit(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await safe_answer(callback)


# =============== 💰 پرداخت با موجودی (پردازش دستی توسط ادمین) ===============
@dp.callback_query(F.data == "pay_balance")
async def pay_balance(callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id in BLACKLIST:
        await safe_answer(callback, "⛔ دسترسی مسدود شده", show_alert=True)
        return
    if not SETTINGS.get("shop_open", True):
        await safe_answer(callback, "🛒 فروشگاه موقتاً بسته است.", show_alert=True)
        return

    state = user_states.get(user_id, {})
    plan = get_plan(state.get("selected_plan"))
    pkg = get_package(plan, state.get("selected_package"))
    if not plan or not pkg:
        await safe_answer(callback, "❌ ابتدا یک بسته انتخاب کنید", show_alert=True)
        return

    price, discount, coupon_code = apply_discount(pkg.get("price", 0), user_id)
    balance = get_user(user_id).get("balance", 0)

    if balance < price:
        await safe_answer(callback, 
            f"⚠️ موجودی کافی نیست!\n💰 موجودی: {balance:,} تومان\n💵 قیمت: {price:,} تومان",
            show_alert=True,
        )
        return

    # =============== کسر موجودی و ثبت سفارش در انتظار کانفیگ ===============
    new_balance = reduce_balance(user_id, price)
    order_id = create_order(
        user_id, "purchase", pkg.get("volume", 0), pkg.get("days", 30), price,
        plan_id=plan.get("id"), plan_name=plan.get("name"), package_id=pkg.get("id"),
        payment_method="balance", coupon_code=coupon_code, discount_percent=discount,
    )
    update_order(order_id, status="awaiting_config")
    consume_coupon(user_id)
    record_purchase(user_id, price)
    user_states.pop(user_id, None)

    await safe_edit(
        callback,
        f"✅ <b>سفارش شما با موفقیت ثبت شد!</b>\n\n"
        f"🆔 شماره سفارش: #{order_id}\n"
        f"📦 پلن: {esc(plan.get('name'))}\n"
        f"📊 بسته: {format_volume(pkg.get('volume', 0))} / {pkg.get('days', 30)} روز\n"
        f"💰 مبلغ کسر شده: {price:,} تومان\n"
        f"💳 موجودی فعلی: {new_balance:,} تومان\n\n"
        f"⏳ سفارش شما در صف پردازش است.\n"
        f"به محض آماده شدن، کانفیگ همین‌جا برایتان ارسال می‌شود. 🌹",
        reply_markup=get_back_only_keyboard(),
    )
    await safe_answer(callback, "✅ سفارش ثبت شد")

    await log_event(
        f"🛒 <b>خرید (موجودی)</b> — کاربر <code>{user_id}</code> پلن «{esc(plan.get('name'))}» "
        f"بسته {format_volume(pkg.get('volume', 0))} / {pkg.get('days', 30)} روز "
        f"به {price:,} تومان خرید. سفارش #{order_id}"
    )

    # =============== تحویل کانفیگ (از مخزن یا دستی — بسته به حالت فروش پلن) ===============
    await deliver_order_config(order_id)


# =============== 💳 پرداخت کارت‌به‌کارت ===============
@dp.callback_query(F.data == "pay_card")
async def pay_card(callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id in BLACKLIST:
        await safe_answer(callback, "⛔ دسترسی مسدود شده", show_alert=True)
        return
    if not SETTINGS.get("shop_open", True):
        await safe_answer(callback, "🛒 فروشگاه موقتاً بسته است.", show_alert=True)
        return

    state = user_states.get(user_id, {})
    plan = get_plan(state.get("selected_plan"))
    pkg = get_package(plan, state.get("selected_package"))
    if not plan or not pkg:
        await safe_answer(callback, "❌ ابتدا یک بسته انتخاب کنید", show_alert=True)
        return

    price, discount, coupon_code = apply_discount(pkg.get("price", 0), user_id)

    order_id = create_order(
        user_id, "purchase", pkg.get("volume", 0), pkg.get("days", 30), price,
        plan_id=plan.get("id"), plan_name=plan.get("name"), package_id=pkg.get("id"),
        payment_method="card", coupon_code=coupon_code, discount_percent=discount,
    )

    user_states[user_id] = {"awaiting_receipt": order_id}

    card = SETTINGS.get("card", {})
    text = (
        f"💳 <b>پرداخت کارت‌به‌کارت</b>\n\n"
        f"🆔 شماره سفارش: #{order_id}\n"
        f"💰 مبلغ قابل پرداخت: <b>{price:,} تومان</b>\n\n"
        f"🏦 بانک: {esc(card.get('bank', ''))}\n"
        f"💳 شماره کارت:\n<code>{esc(card.get('number', ''))}</code>\n"
        f"👤 به نام: {esc(card.get('holder', ''))}\n\n"
        f"📝 لطفاً پس از واریز، <b>عکس فیش واریزی</b> را همین‌جا ارسال کنید.\n"
        f"⏳ پس از تایید فیش توسط ادمین، کانفیگ برایتان ارسال می‌شود."
    )

    await safe_edit(
        callback, text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="❌ انصراف از پرداخت", callback_data=f"cancel_order_{order_id}")
        ]]),
    )
    await safe_answer(callback)


@dp.callback_query(F.data.startswith("cancel_order_"))
async def cancel_order_direct(callback: CallbackQuery):
    """انصراف کاربر از سفارش در انتظار پرداخت."""
    user_id = callback.from_user.id
    order_id = parse_int(callback.data.split("_", 2)[2])
    order = get_order(order_id)
    if not order or order.get("user_id") != user_id:
        await safe_answer(callback, "❌ سفارش یافت نشد", show_alert=True)
        return
    if order.get("status") != "awaiting_payment":
        await safe_answer(callback, "⚠️ این سفارش دیگر قابل لغو نیست", show_alert=True)
        return
    update_order(order_id, status="cancelled")
    user_states.pop(user_id, None)
    await safe_edit(callback, f"❌ سفارش #{order_id} لغو شد.", reply_markup=get_back_only_keyboard())
    await safe_answer(callback, "لغو شد")


# =============== 📸 دریافت فیش واریزی ===============
@dp.message(F.photo, lambda m: user_states.get(m.from_user.id, {}).get("awaiting_receipt") is not None)
async def handle_receipt(message: Message):
    """دریافت عکس فیش از کاربر و ارسال آن به ادمین‌ها برای تایید/رد."""
    user_id = message.from_user.id
    state = user_states.get(user_id, {})
    order_id = state.get("awaiting_receipt")
    if not order_id:
        return  # کاربر در حالت ارسال فیش نیست

    if user_id in BLACKLIST:
        await message.reply("⛔ <b>دسترسی مسدود شده</b>", parse_mode=ParseMode.HTML)
        user_states.pop(user_id, None)
        return

    order = get_order(order_id)
    if not order or order.get("status") != "awaiting_payment":
        await message.reply("❌ سفارش معتبری برای این فیش یافت نشد.",
                            reply_markup=get_back_only_keyboard(), parse_mode=ParseMode.HTML)
        user_states.pop(user_id, None)
        return

    photo_id = message.photo[-1].file_id
    update_order(order_id, receipt_photo_id=photo_id, status="pending")
    user_states.pop(user_id, None)

    user = get_user(user_id)
    username_display = f"@{esc(user.get('username'))}" if user.get("username") else "ندارد"

    # =============== متن اعلان برای ادمین ===============
    if order.get("type") == "balance_charge":
        admin_text = (
            f"💰 <b>فیش جدید — شارژ حساب</b>\n\n"
            f"🆔 سفارش: #{order_id}\n"
            f"👤 کاربر: {esc(user.get('name', 'کاربر'))}\n"
            f"🆔 آیدی: <code>{user_id}</code>\n"
            f"📛 یوزرنیم: {username_display}\n"
            f"💵 مبلغ مورد انتظار: {order.get('price', 0):,} تومان\n"
            f"📅 {esc(order.get('date', ''))}\n\n"
            f"⏳ در انتظار تایید"
        )
    else:
        admin_text = (
            f"🛒 <b>فیش جدید — خرید سرویس</b>\n\n"
            f"🆔 سفارش: #{order_id}\n"
            f"👤 کاربر: {esc(user.get('name', 'کاربر'))}\n"
            f"🆔 آیدی: <code>{user_id}</code>\n"
            f"📛 یوزرنیم: {username_display}\n"
            f"📦 پلن: {esc(order.get('plan_name') or '-')}\n"
            f"📊 بسته: {format_volume(order.get('volume', 0))} / {order.get('days', 0)} روز\n"
            f"💵 مبلغ مورد انتظار: {order.get('price', 0):,} تومان\n"
            f"📅 {esc(order.get('date', ''))}\n\n"
            f"⏳ در انتظار تایید"
        )

    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            styled_btn("✅ تایید", f"rcpok_{order_id}", "success"),
            styled_btn("❌ رد", f"rcprej_{order_id}", "danger"),
        ],
        [InlineKeyboardButton(text="🔙 بستن", callback_data="admin_close_msg")],
    ])

    for admin_id in get_admin_ids():
        try:
            await bot.send_photo(admin_id, photo_id, caption=admin_text,
                                 reply_markup=admin_kb, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.error(f"خطا در ارسال فیش به ادمین {admin_id}: {e}")
            try:
                await bot.send_message(admin_id, admin_text, reply_markup=admin_kb,
                                       parse_mode=ParseMode.HTML)
            except Exception:
                pass

    await message.reply(
        f"✅ <b>فیش دریافت شد</b>\n\n"
        f"🆔 #{order_id}\n"
        f"💰 {order.get('price', 0):,} تومان\n"
        f"⏳ در انتظار تایید ادمین",
        parse_mode=ParseMode.HTML,
    )
    await message.answer("🚀 منوی اصلی",
                         reply_markup=get_main_keyboard(is_admin(user_id), user_id))


# =============== تایید/رد فیش توسط ادمین ===============
@dp.callback_query(F.data.startswith("rcpok_"))
async def approve_receipt(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    order_id = parse_int(callback.data.split("_", 1)[1])
    order = get_order(order_id)
    if not order:
        await safe_answer(callback, "❌ سفارش یافت نشد", show_alert=True)
        return
    if order.get("status") != "pending":
        await safe_answer(callback, "⚠️ این سفارش قبلاً پردازش شده است", show_alert=True)
        return

    user_id = order["user_id"]

    if order.get("type") == "balance_charge":
        # ✅ تایید شارژ حساب
        new_balance = add_balance(user_id, order.get("price", 0))
        update_order(order_id, status="approved", approved_date=now_str())
        try:
            await bot.send_message(
                user_id,
                f"✅ <b>شارژ حساب شما تایید شد!</b>\n\n"
                f"💰 مبلغ {order.get('price', 0):,} تومان به حساب شما اضافه شد.\n"
                f"💳 موجودی فعلی: {new_balance:,} تومان",
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            logger.error(f"خطا در اطلاع شارژ به کاربر {user_id}: {e}")
        await safe_answer(callback, "✅ شارژ تایید شد")
        try:
            await callback.message.edit_caption(
                caption=(callback.message.caption or "") + "\n\n✅ <b>تایید شد — شارژ انجام شد</b>",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
    else:
        # ✅ تایید خرید → سفارش می‌رود به صف «در انتظار کانفیگ»
        update_order(order_id, status="awaiting_config")
        consume_coupon(user_id)
        record_purchase(user_id, order.get("price", 0))
        try:
            await bot.send_message(
                user_id,
                f"✅ <b>فیش شما تایید شد!</b>\n\n"
                f"🆔 سفارش: #{order_id}\n"
                f"⏳ سفارش شما در صف پردازش است. به محض آماده شدن، کانفیگ همین‌جا ارسال می‌شود. 🌹",
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            logger.error(f"خطا در اطلاع تایید فیش به کاربر {user_id}: {e}")
        await safe_answer(callback, "✅ فیش تایید شد — در انتظار کانفیگ")
        try:
            await callback.message.edit_caption(
                caption=(callback.message.caption or "") + "\n\n✅ <b>تایید شد — در انتظار ارسال کانفیگ</b>",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        await log_event(
            f"💳 <b>خرید (کارت)</b> — کاربر <code>{order['user_id']}</code> سفارش #{order_id} "
            f"(«{esc(order.get('plan_name') or '-')}»، {format_volume(order.get('volume', 0))}) تایید شد."
        )
        # تحویل کانفیگ (از مخزن یا دستی — بسته به حالت فروش پلن)
        await deliver_order_config(order_id)


@dp.callback_query(F.data.startswith("rcprej_"))
async def reject_receipt(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    order_id = parse_int(callback.data.split("_", 1)[1])
    order = get_order(order_id)
    if not order:
        await safe_answer(callback, "❌ سفارش یافت نشد", show_alert=True)
        return
    if order.get("status") != "pending":
        await safe_answer(callback, "⚠️ این سفارش قبلاً پردازش شده است", show_alert=True)
        return

    update_order(order_id, status="rejected")
    user_id = order["user_id"]
    try:
        await bot.send_message(
            user_id,
            f"❌ <b>فیش شما رد شد</b>\n\n"
            f"🆔 سفارش: #{order_id}\n"
            f"💬 برای اطلاعات بیشتر با پشتیبانی در تماس باشید: {get_support()}",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        logger.error(f"خطا در اطلاع رد فیش به کاربر {user_id}: {e}")
    await safe_answer(callback, "❌ فیش رد شد")
    try:
        await callback.message.edit_caption(
            caption=(callback.message.caption or "") + "\n\n❌ <b>رد شد</b>",
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass


@dp.callback_query(F.data == "admin_close_msg")
async def admin_close_msg(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    try:
        await callback.message.delete()
    except Exception:
        pass
    await safe_answer(callback)


# =============== ❌ لغو سفارش توسط ادمین + بازگشت وجه ===============
@dp.callback_query(F.data.startswith("ordcancel_"))
async def admin_cancel_order(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    order_id = parse_int(callback.data.split("_", 1)[1])
    order = get_order(order_id)
    if not order:
        await safe_answer(callback, "❌ سفارش یافت نشد", show_alert=True)
        return
    if order.get("status") != "awaiting_config":
        await safe_answer(callback, "⚠️ فقط سفارش‌های در انتظار کانفیگ قابل لغو هستند", show_alert=True)
        return

    user_id = order["user_id"]
    refund = order.get("price", 0)

    # بازگشت وجه فقط اگر با موجودی پرداخت شده بود
    if order.get("payment_method") == "balance" and refund > 0:
        add_balance(user_id, refund)

    update_order(order_id, status="cancelled")
    await close_order_notifications(order, f"❌ سفارش #{order_id} توسط ادمین لغو شد.")
    save_orders()

    refund_text = ""
    if order.get("payment_method") == "balance" and refund > 0:
        refund_text = f"💰 مبلغ {refund:,} تومان به موجودی شما برگشت.\n"
    try:
        await bot.send_message(
            user_id,
            f"❌ <b>سفارش شما لغو شد</b>\n\n"
            f"🆔 سفارش: #{order_id}\n"
            f"{refund_text}"
            f"💬 برای اطلاعات بیشتر با پشتیبانی در تماس باشید: {get_support()}",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        logger.error(f"خطا در اطلاع لغو سفارش به کاربر {user_id}: {e}")
    await safe_answer(callback, "❌ سفارش لغو شد")


# =============== 📤 هندلر ریپلای ادمین → ارسال کانفیگ به خریدار ===============
@dp.message(lambda m: is_admin(m.from_user.id) and m.reply_to_message is not None and (
    not user_states.get(m.from_user.id)
    or f"{m.chat.id}:{m.reply_to_message.message_id}" in NOTIF_MAP
))
async def admin_config_reply(message: Message):
    """اگر ادمین به پیام اعلان سفارش ریپلای کند، متن همان کانفیگ است و برای خریدار فرستاده می‌شود."""
    admin_id = message.from_user.id

    key = f"{message.chat.id}:{message.reply_to_message.message_id}"
    order_id = NOTIF_MAP.get(key)
    if not order_id:
        return  # ریپلای روی پیام نامرتبط است

    order = get_order(order_id)
    if not order or order.get("status") != "awaiting_config":
        await message.reply("⚠️ این سفارش قبلاً پردازش شده است.")
        return

    config_text = (message.text or message.caption or "").strip()
    if not config_text:
        await message.reply("⚠️ لطفاً متن کانفیگ یا لینک اشتراک را ریپلای کنید.")
        return

    user_id = order["user_id"]
    plan_name = order.get("plan_name") or "سرویس"

    # =============== ارسال کانفیگ به خریدار ===============
    try:
        await send_config_to_user(
            user_id,
            config_text,
            title=(
                f"🎉 <b>سفارش شما آماده شد!</b>\n\n"
                f"🆔 سفارش: #{order_id}\n"
                f"📦 پلن: {esc(plan_name)}\n"
                f"📊 بسته: {format_volume(order.get('volume', 0))} / {order.get('days', 0)} روز"
            ),
        )
    except Exception as e:
        logger.error(f"❌ خطا در ارسال کانفیگ به {user_id}: {e}")
        await message.reply(f"❌ خطا در ارسال به کاربر: {e}")
        return

    update_order(order_id, status="approved", config_link=config_text, approved_date=now_str())
    await close_order_notifications(order, f"✅ سفارش #{order_id} تحویل داده شد.")
    save_orders()

    await message.reply(
        f"✅ <b>کانفیگ برای خریدار ارسال شد.</b>\n\n"
        f"🆔 سفارش: #{order_id}\n"
        f"👤 کاربر: <code>{user_id}</code>",
        parse_mode=ParseMode.HTML,
    )
    logger.info(f"📤 کانفیگ سفارش #{order_id} توسط ادمین {admin_id} برای کاربر {user_id} ارسال شد")


# =============== 💰 افزایش موجودی ===============
@dp.callback_query(F.data == "increase_balance")
async def increase_balance(callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id in BLACKLIST:
        await safe_answer(callback, "⛔ دسترسی مسدود شده", show_alert=True)
        return

    price_conf = SETTINGS.get("price", {})
    min_charge = price_conf.get("min_charge", MIN_CHARGE)
    max_charge = price_conf.get("max_charge", MAX_CHARGE)

    user_states[user_id] = {"awaiting_amount": True}

    text = (
        f"💰 <b>افزایش موجودی</b>\n\n"
        f"📝 لطفاً مبلغ را به تومان وارد کنید:\n\n"
        f"⚠️ حداقل: {min_charge:,} | حداکثر: {max_charge:,}"
    )
    await safe_edit(callback, text, reply_markup=get_cancel_keyboard("cancel_increase_balance"))
    await safe_answer(callback)


@dp.callback_query(F.data == "cancel_increase_balance")
async def cancel_increase_balance(callback: CallbackQuery):
    user_id = callback.from_user.id
    user_states.pop(user_id, None)
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer("🚀 منوی اصلی",
                                  reply_markup=get_main_keyboard(is_admin(user_id), user_id))
    await safe_answer(callback, "❌ عملیات لغو شد")


@dp.message(lambda m: user_states.get(m.from_user.id, {}).get("awaiting_amount") is True)
async def process_charge_amount(message: Message):
    user_id = message.from_user.id
    amount = parse_int(message.text)

    price_conf = SETTINGS.get("price", {})
    min_charge = price_conf.get("min_charge", MIN_CHARGE)
    max_charge = price_conf.get("max_charge", MAX_CHARGE)

    if amount is None or amount <= 0:
        await message.reply("❌ لطفاً یک عدد معتبر وارد کنید (به تو  ان):",
                            reply_markup=get_cancel_keyboard("cancel_increase_balance"))
        return
    if amount < min_charge or amount > max_charge:
        await message.reply(
            f"⚠️ مبلغ باید بین {min_charge:,} تا {max_charge:,} تومان باشد. دوباره وارد کنید:",
            reply_markup=get_cancel_keyboard("cancel_increase_balance"),
        )
        return

    order_id = create_order(user_id, "balance_charge", 0, 0, amount, payment_method="card")
    user_states[user_id] = {"awaiting_receipt": order_id}

    card = SETTINGS.get("card", {})
    await message.answer(
        f"💳 <b>پرداخت کارت‌به‌کارت</b>\n\n"
        f"🆔 شماره سفارش: #{order_id}\n"
        f"💰 مبلغ قابل پرداخت: <b>{amount:,} تومان</b>\n\n"
        f"🏦 بانک: {esc(card.get('bank', ''))}\n"
        f"💳 شماره کارت:\n<code>{esc(card.get('number', ''))}</code>\n"
        f"👤 به نام: {esc(card.get('holder', ''))}\n\n"
        f"📝 لطفاً پس از واریز، <b>عکس فیش واریزی</b> را همین‌جا ارسال کنید.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="❌ انصراف از پرداخت", callback_data=f"cancel_order_{order_id}")
        ]]),
        parse_mode=ParseMode.HTML,
    )


# =============== 📁 کانفیگ‌های من ===============
@dp.callback_query(F.data == "old_configs")
async def my_configs(callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id in BLACKLIST:
        await safe_answer(callback, "⛔ دسترسی مسدود شده", show_alert=True)
        return

    configs = [
        o for o in ORDERS.values()
        if o.get("user_id") == user_id and o.get("status") == "approved" and o.get("config_link")
    ]
    configs.sort(key=lambda x: x.get("date", ""), reverse=True)

    if not configs:
        await safe_edit(
            callback,
            "📁 <b>کانفیگ‌های شما</b>\n\n"
            "🚫 شما هیچ کانفیگ فعالی ندارید.\n\n"
            "💡 برای خرید کانفیگ از منوی اصلی اقدام کنید.",
            reply_markup=get_back_only_keyboard(),
        )
        await safe_answer(callback)
        return

    buttons = []
    for o in configs:
        is_test = o.get("type") == "test"
        label = f"{'🧪' if is_test else '📦'} #{o['order_id']} — {format_volume(o.get('volume', 0))} / {o.get('days', 0)} روز"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"view_config_{o['order_id']}")])
    buttons.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data="back_to_main")])

    await safe_edit(
        callback,
        f"📁 <b>کانفیگ‌های شما</b> ({len(configs)})\n\nبرای مشاهده، روی کانفیگ بزنید:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await safe_answer(callback)


@dp.callback_query(F.data.startswith("view_config_"))
async def view_single_config(callback: CallbackQuery):
    user_id = callback.from_user.id
    order_id = parse_int(callback.data.split("_", 2)[2])
    order = get_order(order_id)
    if not order or order.get("user_id") != user_id or not order.get("config_link"):
        await safe_answer(callback, "❌ کانفیگ یافت نشد", show_alert=True)
        return

    is_test = order.get("type") == "test"
    title = (
        f"{'🧪 <b>کانفیگ تست</b>' if is_test else '📦 <b>کانفیگ شما</b>'}\n\n"
        f"🆔 سفارش: #{order_id}\n"
        f"📊 {format_volume(order.get('volume', 0))} / {order.get('days', 0)} روز"
    )
    await safe_answer(callback)
    await send_config_to_user(user_id, order["config_link"], title=title)


# =============== 👤 حساب کاربری ===============
@dp.callback_query(F.data == "my_account")
async def my_account(callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id in BLACKLIST:
        await safe_answer(callback, "⛔ دسترسی مسدود شده", show_alert=True)
        return

    user = get_user(user_id)
    ref_count = len([u for u in USERS.values() if u.get("referred_by") == user_id])
    user_orders = [o for o in ORDERS.values()
                   if o.get("user_id") == user_id and o.get("type") != "balance_charge"]

    purchase_orders = [o for o in user_orders if o.get("type") == "purchase"]
    approved = [o for o in purchase_orders if o.get("status") == "approved"]
    pending = [o for o in purchase_orders if o.get("status") == "pending"]
    awaiting_config = [o for o in purchase_orders if o.get("status") == "awaiting_config"]
    cancelled = [o for o in purchase_orders if o.get("status") == "cancelled"]
    rejected = [o for o in purchase_orders if o.get("status") == "rejected"]
    active_configs = [o for o in approved if o.get("config_link")]
    test_orders = [o for o in user_orders if o.get("type") == "test"]

    coupon_info = ""
    if user.get("coupon_applied") and user.get("coupon_code"):
        coupon_info = f"\n🏷️ کوپن فعال: <code>{esc(user['coupon_code'])}</code> ({user.get('coupon_discount', 0)}%)"

    text = (
        f"👤 <b>حساب کاربری</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 <b>آیدی:</b> {user_id}\n"
        f"👤 <b>نام:</b> {esc(user.get('name', 'کاربر'))}\n"
        f"💰 <b>موجودی:</b> {user.get('balance', 0):,} تومان\n"
        f"👥 <b>تعداد دعوت:</b> {ref_count}\n"
        f"📦 <b>کل خریدها:</b> {len(approved)}\n"
        f"🟢 <b>کانفیگ فعال:</b> {len(active_configs)}\n"
        f"📅 <b>عضویت:</b> {esc(user.get('join_date', 'نامشخص'))}"
        f"{coupon_info}\n\n"
        f"📊 <b>وضعیت سفارشات:</b>\n"
        f"✅ <b>تایید شده:</b> {len(approved)}\n"
        f"⏳ <b>در انتظار تایید:</b> {len(pending)}\n"
        f"📤 <b>در انتظار کانفیگ:</b> {len(awaiting_config)}\n"
        f"❌ <b>لغو شده:</b> {len(cancelled)}\n"
        f"🚫 <b>رد شده:</b> {len(rejected)}\n\n"
        f"🧪 <b>تست‌های شما:</b> {len(test_orders)}"
    )

    buttons = []
    if user.get("coupon_applied") and user.get("coupon_code"):
        buttons.append([InlineKeyboardButton(text="❌ لغو کوپن", callback_data="cancel_coupon")])
    buttons.append([InlineKeyboardButton(text="🔙 برگشت", callback_data="back_to_main")])

    await safe_edit(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await safe_answer(callback)


# =============== 👥 دعوت از دوستان ===============
@dp.callback_query(F.data == "invite_friends")
async def invite_friends(callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id in BLACKLIST:
        await safe_answer(callback, "⛔ دسترسی مسدود شده", show_alert=True)
        return

    bot_info = await bot.get_me()
    link = "https://t.me/" + str(bot_info.username) + "?start=" + str(user_id)
    ref_count = count_referrals(user_id)
    percent = SETTINGS.get("price", {}).get("referral_percent") or 0

    if percent:
        reward_text = f"🎁 پاداش: <b>{percent}٪ از مبلغ هر خرید</b> دوست شما به موجودی شما اضافه می‌شود"
    else:
        bonus = SETTINGS.get("price", {}).get("referral_bonus", REFERRAL_BONUS)
        reward_text = f"🎁 پاداش: {bonus:,} تومان به ازای هر خرید دوست شما"

    text = (
        f"👥 <b>دعوت از دوستان</b>\n\n"
        f"🔗 لینک دعوت شما:\n<code>{link}</code>\n\n"
        f"{reward_text}\n"
        f"👥 دعوت موفق: <b>{ref_count}</b>\n"
    )

    # 🏆 جدول پاداش پله‌ای
    conf = milestones_conf()
    tiers = milestone_tiers()
    if conf.get("enabled", True) and tiers:
        user = get_user(user_id)
        claimed = [int(c) for c in user.get("milestones_claimed", [])]
        earned = sum(int(t["reward"]) for t in tiers if int(t["count"]) in claimed)

        text += "\n🏆 <b>پاداش پله‌ای دعوت</b>\n"
        for t in tiers:
            need, reward = int(t["count"]), int(t["reward"])
            if need in claimed:
                mark = "✅"
            elif ref_count >= need:
                mark = "⏳"
            else:
                mark = "🔒"
            text += f"{mark} {need} دعوت → {reward:,} تومان\n"

        if earned:
            text += f"\n💰 مجموع پاداش دریافتی شما: <b>{earned:,} تومان</b>\n"

        nxt = next_milestone(user_id)
        if nxt:
            remain = int(nxt["count"]) - ref_count
            if remain > 0:
                text += (f"\n🎯 تا پله بعدی فقط <b>{remain} نفر</b> مانده "
                         f"({int(nxt['reward']):,} تومان)")
        else:
            text += "\n🥇 همه‌ی پله‌ها را فتح کردید!"

        if conf.get("require_purchase"):
            text += "\n\n❕ توجه: فقط دعوت‌شده‌هایی که خرید کرده باشند شمرده می‌شوند."

    await safe_edit(callback, text, reply_markup=get_back_only_keyboard())
    await safe_answer(callback)


# =============== 🏷️ کوپن تخفیف ===============
@dp.callback_query(F.data == "apply_coupon")
async def apply_coupon(callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id in BLACKLIST:
        await safe_answer(callback, "⛔ دسترسی مسدود شده", show_alert=True)
        return

    user = get_user(user_id)
    if user.get("coupon_applied") and user.get("coupon_code"):
        await safe_answer(callback, 
            f"🏷️ کوپن {user['coupon_code']} ({user.get('coupon_discount', 0)}%) از قبل فعال است",
            show_alert=True,
        )
        return

    user_states[user_id] = {"awaiting_coupon": True}
    await safe_edit(
        callback,
        "🏷️ <b>اعمال کوپن تخفیف</b>\n\n📝 کد کوپن را وارد کنید:",
        reply_markup=get_cancel_keyboard("cancel_coupon"),
    )
    await safe_answer(callback)


@dp.callback_query(F.data == "cancel_coupon")
async def cancel_coupon(callback: CallbackQuery):
    user_id = callback.from_user.id
    state = user_states.get(user_id, {})
    if state.get("awaiting_coupon"):
        user_states.pop(user_id, None)
        await safe_edit(callback, "❌ اعمال کوپن لغو شد.", reply_markup=get_back_only_keyboard())
        await safe_answer(callback, "لغو شد")
        return
    # لغو کوپن فعال
    release_coupon(user_id)
    await safe_answer(callback, "🏷️ کوپن شما لغو شد", show_alert=True)
    await my_account(callback)


@dp.message(lambda m: user_states.get(m.from_user.id, {}).get("awaiting_coupon") is True)
async def process_coupon_code(message: Message):
    user_id = message.from_user.id
    code = (message.text or "").strip()
    user_states.pop(user_id, None)

    coupon = get_coupon(code)
    if not coupon:
        await message.reply("❌ کد کوپن نامعتبر است.", reply_markup=get_back_only_keyboard())
        return
    if not coupon_is_usable(coupon, user_id):
        await message.reply(
            "❌ این کوپن قابل استفاده نیست (منقضی شده، به سقف استفاده رسیده یا قبلاً استفاده کرده‌اید).",
            reply_markup=get_back_only_keyboard(),
        )
        return

    user = get_user(user_id)
    user["coupon_code"] = coupon["code"]
    user["coupon_discount"] = coupon.get("percent", 0)
    user["coupon_applied"] = True
    save_users()

    await message.reply(
        f"✅ <b>کوپن فعال شد!</b>\n\n"
        f"🏷️ کد: <code>{esc(coupon['code'])}</code>\n"
        f"💥 تخفیف: {coupon.get('percent', 0)}%\n\n"
        f"💡 این تخفیف روی خرید بعدی شما اعمال می‌شود.",
        reply_markup=get_back_only_keyboard(),
        parse_mode=ParseMode.HTML,
    )


# =============== 🧪 دریافت تست رایگان (از مخزن دستی) ===============
@dp.callback_query(F.data == "get_test_service")
async def get_test_service(callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id in BLACKLIST:
        await safe_answer(callback, "⛔ دسترسی مسدود شده", show_alert=True)
        return

    # 🔒 عضویت اجباری برای دریافت تست
    if await force_join_gate(callback, "get_test_service"):
        return

    test_conf = SETTINGS.get("test_service", {})
    if not test_conf.get("enabled", True):
        await safe_answer(callback, "❌ تست سرویس در حال حاضر غیرفعال است!", show_alert=True)
        return

    max_tests = test_conf.get("max_per_user", TEST_MAX_PER_USER)
    user = get_user(user_id)
    used = user.get("test_count", 0)

    if used >= max_tests:
        await safe_answer(callback, 
            f"⚠️ شما قبلاً از سقف تست مجاز ({max_tests} بار) استفاده کرده‌اید!",
            show_alert=True,
        )
        return

    if not TEST_POOL:
        await safe_answer(callback, 
            "❌ در حال حاضر کانفیگ تست موجود نیست. لطفاً بعداً تلاش کنید.",
            show_alert=True,
        )
        return

    # =============== برداشتن یک کانفیگ از مخزن (غیرقابل تکرار برای بقیه) ===============
    config_item = TEST_POOL.pop(0)
    save_test_pool()

    user["test_count"] = used + 1
    save_users()

    order_id = create_order(user_id, "test", 0, 0, 0, payment_method="test")
    update_order(order_id, status="approved", config_link=config_item.get("link", ""),
                 approved_date=now_str())

    await safe_answer(callback, "🧪 کانفیگ تست برا   شما ارسال شد")
    await send_config_to_user(
        user_id,
        config_item.get("link", ""),
        title="🧪 <b>کانفیگ تست رایگان شما</b>",
        extra="🎁 این یک سرویس تست رایگان است.\n💡 برای خرید سرویس کامل از منوی اصلی اقدام کنید.",
    )

    # اعلان ساده به ادمین‌ها
    await notify_admins(
        f"🧪 <b>تست رایگان جدید</b>\n\n"
        f"👤 کاربر: {esc(user.get('name', 'کاربر'))}\n"
        f"🆔 آیدی: <code>{user_id}</code>\n"
        f"🆔 سفارش: #{order_id}\n"
        f"📦 باقیمانده مخزن تست: {len(TEST_POOL)} عدد\n"
        f"📅 {now_str()}"
    )
    await log_event(
        f"🧪 <b>تست رایگان</b> — {esc(user.get('name', 'کاربر'))} (<code>{user_id}</code>)"
        f"{' | @' + esc(user.get('username')) if user.get('username') else ''}"
        f" یک کانفیگ تست گرفت. (سفارش #{order_id})"
    )


# ==================================================================
# 👑 بخش مدیریت (ادمین پنل)
# ==================================================================

# =============== 📋 سفارشات ===============
@dp.callback_query(F.data == "admin_orders")
async def admin_orders(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    user_states.pop(callback.from_user.id, None)

    pending_receipts = [o for o in ORDERS.values() if o.get("status") == "pending"]
    awaiting_config = [o for o in ORDERS.values() if o.get("status") == "awaiting_config"]
    awaiting_config.sort(key=lambda x: x.get("order_id", 0))
    pending_receipts.sort(key=lambda x: x.get("order_id", 0))

    text = (
        f"📋 <b>مدیریت سفارشات</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💳 فیش‌های در انتظار تایید: {len(pending_receipts)}\n"
        f"📤 سفارش‌های در انتظار کانفیگ: {len(awaiting_config)}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
    )

    if awaiting_config:
        text += "\n📤 <b>در انتظار کانفیگ</b> (به پیام اعلان ریپلای کنید):\n"
        for o in awaiting_config[:15]:
            text += f"  • #{o['order_id']} — {format_volume(o.get('volume', 0))} / {o.get('days', 0)} روز — {o.get('price', 0):,} تومان\n"
    if pending_receipts:
        text += "\n💳 <b>فیش‌های در انتظار تایید:</b>\n"
        for o in pending_receipts[:15]:
            kind = "شارژ حساب" if o.get("type") == "balance_charge" else "خرید سرویس"
            text += f"  • #{o['order_id']} — {kind} — {o.get('price', 0):,} تومان\n"
    if not awaiting_config and not pending_receipts:
        text += "\n✅ هیچ سفارش در انتظاری وجود ندارد."

    buttons = []
    for o in awaiting_config[:8]:
        buttons.append([InlineKeyboardButton(
            text=f"🔁 ارسال مجدد اعلان #{o['order_id']}",
            callback_data=f"ordresend_{o['order_id']}",
        )])
    buttons.append([InlineKeyboardButton(text="🔙 برگشت به پنل", callback_data="admin_panel")])

    await safe_edit(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await safe_answer(callback)


@dp.callback_query(F.data.startswith("ordresend_"))
async def admin_resend_order_notif(callback: CallbackQuery):
    """ارسال مجدد پیام اعلان «در انتظار کانفیگ» تا ادمین بتواند ریپلای کند."""
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    order_id = parse_int(callback.data.split("_", 1)[1])
    order = get_order(order_id)
    if not order or order.get("status") != "awaiting_config":
        await safe_answer(callback, "⚠️ این سفارش دیگر در انتظار کانفیگ نیست", show_alert=True)
        return
    await deliver_order_config(order_id)
    await safe_answer(callback, f"✅ اعلان سفارش #{order_id} دوباره ارسال شد", show_alert=True)


# =============== 👥 کاربران ===============
USERS_PER_PAGE = 8


@dp.callback_query(F.data == "admin_users")
async def admin_users(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    user_states.pop(callback.from_user.id, None)
    await _show_users_page(callback, 0)


@dp.callback_query(F.data.startswith("userspage_"))
async def admin_users_page(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    page = parse_int(callback.data.split("_", 1)[1]) or 0
    await _show_users_page(callback, page)


async def _show_users_page(callback: CallbackQuery, page: int):
    all_users = sorted(USERS.values(), key=lambda u: u.get("id", 0), reverse=True)
    total = len(all_users)
    max_page = max(0, (total - 1) // USERS_PER_PAGE)
    page = max(0, min(page, max_page))

    start = page * USERS_PER_PAGE
    chunk = all_users[start:start + USERS_PER_PAGE]

    text = (
        f"👥 <b>مدیریت کاربران</b>\n\n"
        f"📊 کل کاربران: {total}\n"
        f"📄 صفحه {page + 1} از {max_page + 1}\n\n"
        f"برای مدیریت، روی کاربر بزنید:"
    )

    buttons = []
    for u in chunk:
        name = (u.get("name") or "کاربر")[:20]
        balance = u.get("balance", 0)
        buttons.append([InlineKeyboardButton(
            text=f"👤 {name} | {balance:,}T | {u.get('id')}",
            callback_data=f"userview_{u.get('id')}",
        )])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️ قبلی", callback_data=f"userspage_{page - 1}"))
    if page < max_page:
        nav.append(InlineKeyboardButton(text="بعدی ▶️", callback_data=f"userspage_{page + 1}"))
    if nav:
        buttons.append(nav)

    buttons.append([InlineKeyboardButton(text="🔍 جستجوی کاربر (آیدی)", callback_data="usersearch")])
    buttons.append([InlineKeyboardButton(text="🔙 برگشت به پنل", callback_data="admin_panel")])

    await safe_edit(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await safe_answer(callback)


@dp.callback_query(F.data == "usersearch")
async def admin_user_search(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    user_states[callback.from_user.id] = {"awaiting_user_search": True}
    await safe_edit(
        callback,
        "🔍 <b>جستجوی کاربر</b>\n\nآیدی عددی کاربر را وارد کنید:",
        reply_markup=get_cancel_keyboard("admin_users"),
    )
    await safe_answer(callback)


@dp.callback_query(F.data.startswith("userview_"))
async def admin_user_view(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    uid = parse_int(callback.data.split("_", 1)[1])
    if uid is None or str(uid) not in USERS:
        await safe_answer(callback, "❌ کاربر یافت نشد", show_alert=True)
        return

    u = USERS[str(uid)]
    user_orders = [o for o in ORDERS.values() if o.get("user_id") == uid]
    purchases = [o for o in user_orders if o.get("type") == "purchase" and o.get("status") == "approved"]
    blocked = uid in BLACKLIST

    text = (
        f"👤 <b>جزئیات کاربر</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 آیدی: <code>{uid}</code>\n"
        f"👤 نام: {esc(u.get('name', 'کاربر'))}\n"
        f"📛 یوزرنیم: {'@' + esc(u.get('username')) if u.get('username') else 'ندارد'}\n"
        f"💰 موجودی: {u.get('balance', 0):,} تومان\n"
        f"📦 خریدهای موفق: {len(purchases)}\n"
        f"🧪 تست‌ها: {u.get('test_count', 0)}\n"
        f"📅 عضویت: {esc(u.get('join_date', '-'))}\n"
        f"🚫 وضعیت: {'لیست سیاه ⛔' if blocked else 'عادی ✅'}"
    )

    buttons = [
        [
            InlineKeyboardButton(text="➕ افزایش موجودی", callback_data=f"useradd_{uid}"),
            InlineKeyboardButton(text="➖ کاهش موجودی", callback_data=f"usersub_{uid}"),
        ],
        [InlineKeyboardButton(
            text="🚫 افزودن به لیست سیاه" if not blocked else "✅ خروج از لیست سیاه",
            callback_data=f"userblock_{uid}",
        )],
        [InlineKeyboardButton(text="🔙 برگشت", callback_data="admin_users")],
    ]

    await safe_edit(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await safe_answer(callback)


@dp.callback_query(F.data.startswith("useradd_") | F.data.startswith("usersub_"))
async def admin_user_balance_start(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    action, uid_str = callback.data.split("_", 1)
    uid = parse_int(uid_str)
    if uid is None or str(uid) not in USERS:
        await safe_answer(callback, "❌ کاربر یافت نشد", show_alert=True)
        return

    mode = "add" if action == "useradd" else "sub"
    user_states[callback.from_user.id] = {"balance_adjust": {"user_id": uid, "mode": mode}}

    label = "افزایش" if mode == "add" else "کاهش"
    await safe_edit(
        callback,
        f"💰 <b>{label} موجودی</b>\n\n"
        f"👤 کاربر: <code>{uid}</code>\n"
        f"💳 موجودی فعلی: {USERS[str(uid)].get('balance', 0):,} تومان\n\n"
        f"📝 مبلغ را به تومان وارد کنید:",
        reply_markup=get_cancel_keyboard(f"userview_{uid}"),
    )
    await safe_answer(callback)


@dp.callback_query(F.data.startswith("userblock_"))
async def admin_user_block_toggle(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    uid = parse_int(callback.data.split("_", 1)[1])
    if uid is None:
        await safe_answer(callback, "❌ خطا", show_alert=True)
        return
    if uid == SUPER_ADMIN_ID or uid in SETTINGS.get("admins", []):
        await safe_answer(callback, "⛔ نمی‌توانید ادمین را بلاک کنید", show_alert=True)
        return

    if uid in BLACKLIST:
        BLACKLIST.discard(uid)
        msg = "✅ کاربر از لیست سیاه خارج شد"
    else:
        BLACKLIST.add(uid)
        msg = "🚫 کاربر به لیست سیاه اضافه شد"
    save_blacklist()
    await safe_answer(callback, msg, show_alert=True)
    await admin_user_view(callback)


# ==================================================================
# 📦 مدیریت پلن‌ها — گفت‌وگومحور (قابلیت جدید)
# ==================================================================
PLAN_TYPES = [
    ("⭐️ ویژه", "⭐️"),
    ("📦 عادی", "📦"),
    ("💎 حرفه‌ای", "💎"),
    ("🔥 اقتصادی", "🔥"),
]


@dp.callback_query(F.data == "admin_plans")
async def admin_plans(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    user_states.pop(callback.from_user.id, None)

    categories = PLANS.get("categories", [])
    total_packages = sum(len(c.get("packages", [])) for c in categories)

    text = (
        f"📦 <b>مدیریت پلن‌ها</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 تعداد پلن‌ها: {len(categories)}\n"
        f"📦 تعداد کل بسته‌ها: {total_packages}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
    )

    if categories:
        text += "\n<b>لیست پلن‌ها:</b>\n"
        for cat in categories:
            status = "🟢" if cat.get("is_active", True) else "🔴"
            pkg_count = len(cat.get("packages", []))
            plan_type = cat.get("type", "")
            type_badge = f" | {esc(plan_type)}" if plan_type else ""
            text += f"\n{cat.get('icon', '📦')} <b>{esc(cat.get('name'))}</b>{type_badge} — {status} ({pkg_count} بسته)\n"
            for idx, pkg in enumerate(cat.get("packages", []), start=1):
                pkg_status = "✅" if pkg.get("is_active", True) else "❌"
                text += (
                    f"   {pkg_status} بسته {idx}: {format_volume(pkg.get('volume', 0))}"
                    f" | {pkg.get('days', 30)} روز | {pkg.get('price', 0):,} تومان\n"
                )
    else:
        text += "\n❌ هنوز هیچ پلنی تعریف نشده است.\nبرای شروع، روی «➕ افزودن پلن جدید» بزنید."

    buttons = [[InlineKeyboardButton(text="➕ افزودن پلن جدید", callback_data="planadd")]]
    for cat in categories:
        status_icon = "🟢" if cat.get("is_active", True) else "🔴"
        buttons.append([InlineKeyboardButton(
            text=f"{cat.get('icon', '📦')} {cat.get('name')} ({status_icon})",
            callback_data=f"planview_{cat.get('id')}",
        )])
    buttons.append([InlineKeyboardButton(text="🔙 برگشت به پنل", callback_data="admin_panel")])

    await safe_edit(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await safe_answer(callback)


@dp.callback_query(F.data.startswith("planview_"))
async def admin_plan_view(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    plan_id = parse_int(callback.data.split("_", 1)[1])
    plan = get_plan(plan_id)
    if not plan:
        await safe_answer(callback, "❌ پلن یافت نشد", show_alert=True)
        return

    status = "🟢 فعال" if plan.get("is_active", True) else "🔴 غیرفعال"
    sale_fa = "🗃 از مخزن (خودکار)" if get_sale_mode(plan) == "pool" else "✋ دستی (ادمین)"
    text = (
        f"{plan.get('icon', '📦')} <b>{esc(plan.get('name'))}</b>\n\n"
        f"🏷 نوع: {esc(plan.get('type', '-'))}\n"
        f"⚙️ وضعیت: {status}\n"
        f"🛒 حالت فروش: {sale_fa}\n"
        f"📦 تعداد بسته‌ها: {len(plan.get('packages', []))}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>بسته‌ها:</b>\n"
    )
    packages = plan.get("packages", [])
    if packages:
        for idx, pkg in enumerate(packages, start=1):
            pkg_status = "✅" if pkg.get("is_active", True) else "❌"
            text += (
                f"{pkg_status} <b>بسته {idx}</b>: {format_volume(pkg.get('volume', 0))}"
                f" | {pkg.get('days', 30)} روز | {pkg.get('price', 0):,} تومان\n"
            )
    else:
        text += "❌ بسته‌ای ندارد. روی «➕ افزودن بسته» بزنید.\n"

    buttons = [
        [InlineKeyboardButton(text="➕ افزودن بسته", callback_data=f"pkgadd_{plan_id}")],
        [InlineKeyboardButton(
            text=f"🛒 حالت فروش: {sale_fa} (بزن برای تغییر)",
            callback_data=f"plansale_{plan_id}",
        )],
    ]
    for idx, pkg in enumerate(packages, start=1):
        buttons.append([InlineKeyboardButton(
            text=f"🗑 حذف بسته {idx} ({format_volume(pkg.get('volume', 0))})",
            callback_data=f"pkgdel_{plan_id}_{pkg.get('id')}",
        )])
    buttons.append([InlineKeyboardButton(
        text="🔴 غیرفعال کردن پلن" if plan.get("is_active", True) else "🟢 فعال کردن پلن",
        callback_data=f"plantoggle_{plan_id}",
    )])
    buttons.append([InlineKeyboardButton(text="🗑 حذف کامل پلن", callback_data=f"plandel_{plan_id}")])
    buttons.append([InlineKeyboardButton(text="🔙 برگشت", callback_data="admin_plans")])

    await safe_edit(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await safe_answer(callback)


@dp.callback_query(F.data.startswith("plantoggle_"))
async def admin_plan_toggle(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    plan_id = parse_int(callback.data.split("_", 1)[1])
    plan = get_plan(plan_id)
    if not plan:
        await safe_answer(callback, "❌ پلن یافت نشد", show_alert=True)
        return
    plan["is_active"] = not plan.get("is_active", True)
    save_plans()
    await safe_answer(callback, "✅ وضعیت پلن تغییر کرد")
    await admin_plan_view(callback)


@dp.callback_query(F.data.startswith("plandel_"))
async def admin_plan_delete(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    plan_id = parse_int(callback.data.split("_", 1)[1])
    plan = get_plan(plan_id)
    if not plan:
        await safe_answer(callback, "❌ پلن یافت نشد", show_alert=True)
        return

    await safe_edit(
        callback,
        f"⚠️ <b>حذف پلن «{esc(plan.get('name'))}»</b>\n\n"
        f"این پلن و همه {len(plan.get('packages', []))} بسته آن برای همیشه حذف می‌شود. مطمئنید؟",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ بله، حذف کن", callback_data=f"plandelyes_{plan_id}")],
            [InlineKeyboardButton(text="❌ انصراف", callback_data=f"planview_{plan_id}")],
        ]),
    )
    await safe_answer(callback)


@dp.callback_query(F.data.startswith("plandelyes_"))
async def admin_plan_delete_confirm(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    plan_id = parse_int(callback.data.split("_", 1)[1])
    before = len(PLANS.get("categories", []))
    PLANS["categories"] = [c for c in PLANS.get("categories", []) if c.get("id") != plan_id]
    if len(PLANS["categories"]) < before:
        save_plans()
        await safe_answer(callback, "🗑 پلن حذف شد", show_alert=True)
    else:
        await safe_answer(callback, "❌ پلن یافت نشد", show_alert=True)
    await admin_plans(callback)


@dp.callback_query(F.data.startswith("pkgdel_"))
async def admin_package_delete(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    parts = callback.data.split("_")
    if len(parts) != 3:
        await safe_answer(callback, "❌ خطا", show_alert=True)
        return
    plan_id = parse_int(parts[1])
    pkg_id = parse_int(parts[2])
    plan = get_plan(plan_id)
    if not plan:
        await safe_answer(callback, "❌ پلن یافت نشد", show_alert=True)
        return
    before = len(plan.get("packages", []))
    plan["packages"] = [p for p in plan.get("packages", []) if p.get("id") != pkg_id]
    if len(plan["packages"]) < before:
        save_plans()
        await safe_answer(callback, "🗑 بسته حذف شد")
    else:
        await safe_answer(callback, "❌ بسته یافت نشد", show_alert=True)
    await admin_plan_view(callback)


# =============== گام ۱: شروع افزودن پلن → پرسیدن نام ===============
@dp.callback_query(F.data == "planadd")
async def admin_plan_add_start(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    user_states[callback.from_user.id] = {"plan_flow": {"step": "name", "plan_id": None}}
    await safe_edit(
        callback,
        "➕ <b>افزودن پلن جدید — مرحله ۱ از ۲</b>\n\n"
        "📝 <b>نام پلن</b> را وارد کنید:\n"
        "مثال: <code>پلن طلایی</code>",
        reply_markup=get_cancel_keyboard("planflow_cancel"),
    )
    await safe_answer(callback)


@dp.callback_query(F.data == "planflow_cancel")
async def admin_plan_flow_cancel(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    flow = user_states.get(callback.from_user.id, {}).get("plan_flow", {})
    # اگر پلنی در میانه راه ساخته شده و هیچ بسته‌ای ندارد، حذفش کن تا پلن خالی نماند
    plan_id = flow.get("plan_id")
    if plan_id is not None and flow.get("created_in_flow"):
        plan = get_plan(plan_id)
        if plan and not plan.get("packages"):
            PLANS["categories"] = [c for c in PLANS.get("categories", []) if c.get("id") != plan_id]
            save_plans()
    user_states.pop(callback.from_user.id, None)
    await safe_answer(callback, "❌ لغو شد")
    await admin_plans(callback)


# =============== گام ۲: انتخاب نوع پلن (دکمه شیشه‌ای) ===============
async def _ask_plan_type(target_message: Message, plan_name: str):
    buttons = []
    row = []
    for label, icon in PLAN_TYPES:
        row.append(InlineKeyboardButton(text=label, callback_data=f"plantype_{label}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="✏️ نوع دلخواه (تایپ کنید)", callback_data="plantype_custom")])
    buttons.append([InlineKeyboardButton(text="❌ انصراف", callback_data="planflow_cancel")])

    await target_message.answer(
        f"➕ <b>افزودن پلن جدید — مرحله ۲ از ۲</b>\n\n"
        f"📝 نام پلن: <b>{esc(plan_name)}</b>\n\n"
        f"🏷 <b>نوع پلن</b> را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode=ParseMode.HTML,
    )


@dp.callback_query(F.data.startswith("plantype_"))
async def admin_plan_type_select(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    admin_id = callback.from_user.id
    flow = user_states.get(admin_id, {}).get("plan_flow")
    if not flow or flow.get("step") != "type":
        await safe_answer(callback, "⚠️ جریان افزودن پلن فعال نیست", show_alert=True)
        return

    choice = callback.data.split("_", 1)[1]
    if choice == "custom":
        flow["step"] = "type_custom"
        user_states[admin_id] = {"plan_flow": flow}
        await safe_edit(
            callback,
            "✏️ <b>نوع دلخواه پلن</b> را تایپ کنید:\nمثال: <code>ویژه گیمرها</code>",
            reply_markup=get_cancel_keyboard("planflow_cancel"),
        )
        await safe_answer(callback)
        return

    icon = next((ic for lbl, ic in PLAN_TYPES if lbl == choice), "📦")
    await _create_plan_and_start_packages(callback.message, admin_id, flow["name"], choice, icon)
    await safe_answer(callback)


async def _create_plan_and_start_packages(message: Message, admin_id: int,
                                          plan_name: str, plan_type: str, icon: str):
    """ساخت پلن در دیتابیس و شروع حلقه افزودن بسته‌ها به صورت متوالی."""
    plan_id = next_numeric_id(PLANS.get("categories", []))
    plan = {
        "id": plan_id,
        "name": plan_name,
        "type": plan_type,
        "icon": icon,
        "is_active": True,
        "packages": [],
        "created_at": now_str(),
    }
    PLANS.setdefault("categories", []).append(plan)
    save_plans()

    user_states[admin_id] = {"plan_flow": {"step": "pkg_volume", "plan_id": plan_id, "draft": {}, "created_in_flow": True}}

    await message.answer(
        f"✅ پلن <b>{esc(plan_name)}</b> ({esc(plan_type)}) ساخته شد!\n\n"
        f"📦 حالا بسته‌ها را <b>یکی‌یکی</b> اضافه کنید.\n"
        f"می‌توانید هر تعداد بسته (مثلاً ۱۰ بسته با حجم و قیمت متفاوت) پشت سر هم بسازید.\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 <b>بسته شماره ۱</b>\n\n"
        f"🔢 <b>حجم بسته</b> را به گیگابایت وارد کنید:\n"
        f"(مثال: <code>10</code> — برای نامحدود: <code>0</code>)",
        reply_markup=get_cancel_keyboard("planflow_cancel"),
        parse_mode=ParseMode.HTML,
    )


# =============== افزودن بسته به پلن موجود ===============
@dp.callback_query(F.data.startswith("pkgadd_"))
async def admin_package_add_start(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    plan_id = parse_int(callback.data.split("_", 1)[1])
    plan = get_plan(plan_id)
    if not plan:
        await safe_answer(callback, "❌ پلن یافت نشد", show_alert=True)
        return

    next_num = len(plan.get("packages", [])) + 1
    user_states[callback.from_user.id] = {
        "plan_flow": {"step": "pkg_volume", "plan_id": plan_id, "draft": {}}
    }
    await safe_edit(
        callback,
        f"➕ <b>افزودن بسته به «{esc(plan.get('name'))}»</b>\n\n"
        f"📦 <b>بسته شماره {next_num}</b>\n\n"
        f"🔢 <b>حجم بسته</b> را به گیگابایت وارد کنید:\n"
        f"(مثال: <code>10</code> — برای نامحدود: <code>0</code>)",
        reply_markup=get_cancel_keyboard("planflow_cancel"),
    )
    await safe_answer(callback)


# =============== پایان افزودن بسته‌ها ===============
@dp.callback_query(F.data == "planflow_done")
async def admin_plan_flow_done(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    admin_id = callback.from_user.id
    flow = user_states.get(admin_id, {}).get("plan_flow", {})
    plan_id = flow.get("plan_id")
    user_states.pop(admin_id, None)

    plan = get_plan(plan_id)
    if plan:
        await safe_answer(callback, 
            f"✅ پلن «{plan.get('name')}» با {len(plan.get('packages', []))} بسته ذخیره شد",
            show_alert=True,
        )
    else:
        await safe_answer(callback, "✅ پایان", show_alert=True)
    await admin_plans(callback)



# =============== هندلر متنی جریان ساخت پلن/بسته (گفت‌وگومحور) ===============
@dp.message(lambda m: user_states.get(m.from_user.id, {}).get("plan_flow") is not None)
async def plan_flow_message_handler(message: Message):
    """پردازش قدم‌به‌قدم ساخت پلن و بسته‌های متوالی."""
    admin_id = message.from_user.id
    if not is_admin(admin_id):
        return

    flow = user_states[admin_id]["plan_flow"]
    step = flow.get("step")
    text = (message.text or "").strip()

    # ---------- مرحله نام پلن ----------
    if step == "name":
        if not text or len(text) < 2:
            await message.reply("❌ نام پلن خیلی کوتاه است. دوباره وارد کنید:",
                                reply_markup=get_cancel_keyboard("planflow_cancel"))
            return
        flow["name"] = text
        flow["step"] = "type"
        user_states[admin_id] = {"plan_flow": flow}
        await _ask_plan_type(message, text)
        return

    # ---------- مرحله نوع دلخواه ----------
    if step == "type_custom":
        if not text:
            await message.reply("❌ لطفاً نوع پلن را تایپ کنید:",
                                reply_markup=get_cancel_keyboard("planflow_cancel"))
            return
        await _create_plan_and_start_packages(message, admin_id, flow.get("name", "پلن"), text, "✏️")
        return

    # ---------- مراحل بسته ----------
    plan = get_plan(flow.get("plan_id"))
    if not plan:
        user_states.pop(admin_id, None)
        await message.reply("❌ پلن یافت نشد. جریان لغو شد.")
        await message.answer("👑 پنل مدیریت", reply_markup=get_admin_keyboard())
        return

    pkg_number = len(plan.get("packages", [])) + 1

    if step == "pkg_volume":
        vol = parse_int(text)
        if vol is None or vol < 0:
            await message.reply(
                "❌ لطفاً یک عدد معتبر وارد کنید (مثال: <code>10</code> — نامحدود: <code>0</code>):",
                reply_markup=get_cancel_keyboard("planflow_cancel"),
                parse_mode=ParseMode.HTML,
            )
            return
        flow["draft"] = {"volume": vol}
        flow["step"] = "pkg_days"
        user_states[admin_id] = {"plan_flow": flow}
        await message.answer(
            f"📦 <b>بسته شماره {pkg_number}</b> — حجم: {format_volume(vol)} ✅\n\n"
            f"⏱ <b>مدت بسته</b> را به روز وارد کنید:\n(مثال: <code>30</code>)",
            reply_markup=get_cancel_keyboard("planflow_cancel"),
            parse_mode=ParseMode.HTML,
        )
        return

    if step == "pkg_days":
        days = parse_int(text)
        if days is None or days <= 0:
            await message.reply(
                "❌ لطفاً یک عدد معتبر بزرگ‌تر از صفر وارد کنید (مثال: <code>30</code>):",
                reply_markup=get_cancel_keyboard("planflow_cancel"),
                parse_mode=ParseMode.HTML,
            )
            return
        flow["draft"]["days"] = days
        flow["step"] = "pkg_price"
        user_states[admin_id] = {"plan_flow": flow}
        await message.answer(
            f"📦 <b>بسته شماره {pkg_number}</b> — مدت: {days} روز ✅\n\n"
            f"💰 <b>قیمت بسته</b> را به تومان وارد کنید:\n(مثال: <code>50000</code>)",
            reply_markup=get_cancel_keyboard("planflow_cancel"),
            parse_mode=ParseMode.HTML,
        )
        return

    if step == "pkg_price":
        price = parse_int(text)
        if price is None or price < 0:
            await message.reply(
                "❌ لطفاً یک عدد معتبر وارد کنید (مثال: <code>50000</code>):",
                reply_markup=get_cancel_keyboard("planflow_cancel"),
                parse_mode=ParseMode.HTML,
            )
            return

        # =============== ثبت بسته ===============
        draft = flow.get("draft", {})
        pkg_id = next_numeric_id(plan.get("packages", []))
        plan.setdefault("packages", []).append({
            "id": pkg_id,
            "volume": draft.get("volume", 0),
            "days": draft.get("days", 30),
            "price": price,
            "is_active": True,
        })
        save_plans()

        done_count = len(plan["packages"])
        next_number = done_count + 1

        # آماده‌سازی برای بسته بعدی (متوالی)
        user_states[admin_id] = {"plan_flow": {
            "step": "pkg_volume", "plan_id": plan["id"], "draft": {},
            "created_in_flow": flow.get("created_in_flow", False),
        }}

        await message.answer(
            f"✅ <b>بسته شماره {done_count} ثبت شد!</b>\n\n"
            f"📦 {format_volume(draft.get('volume', 0))} | ⏱ {draft.get('days', 30)} روز | 💰 {price:,} تومان\n\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📦 <b>بسته شماره {next_number}</b>\n\n"
            f"🔢 حجم بسته بعدی را وارد کنید (گیگابایت):\n"
            f"یا برای پایان، دکمه «✅ پایان و ذخیره» را بزنید.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ پایان و ذخیره", callback_data="planflow_done")],
                [InlineKeyboardButton(text="❌ انصراف", callback_data="planflow_cancel")],
            ]),
            parse_mode=ParseMode.HTML,
        )
        return


# ==================================================================
# 🧪 مخزن تست دستی (قابلیت جدید)
# ==================================================================
@dp.callback_query(F.data == "admin_testpool")
async def admin_testpool(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    user_states.pop(callback.from_user.id, None)

    test_conf = SETTINGS.get("test_service", {})
    enabled = test_conf.get("enabled", True)
    max_per_user = test_conf.get("max_per_user", TEST_MAX_PER_USER)

    text = (
        f"🧪 <b>مخزن تست رایگان</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⚙️ وضعیت سرویس تست: {'🟢 فعال' if enabled else '🔴 غیرفعال'}\n"
        f"📦 کانفیگ‌های موجود در مخزن: <b>{len(TEST_POOL)}</b> عدد\n"
        f"👤 سقف تست برای هر کاربر: {max_per_user} بار\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💡 کاربران با زدن دکمه «🧪 دریافت تست رایگان» یک کانفیگ از مخزن می‌گیرند و آن کانفیگ از مخزن حذف می‌شود تا به کاربر بعدی کانفیگ تکراری داده نشود."
    )

    buttons = [
        [InlineKeyboardButton(text="➕ افزودن کانفیگ تست", callback_data="testpool_add")],
        [InlineKeyboardButton(text="📋 مشاهده مخزن", callback_data="testpool_list")],
        [InlineKeyboardButton(
            text="🔴 غیرفعال کردن تست" if enabled else "🟢 فعال کردن تست",
            callback_data="testpool_toggle",
        )],
        [InlineKeyboardButton(text="🗑 خالی کردن مخزن", callback_data="testpool_clear")],
        [InlineKeyboardButton(text="🔙 برگشت به پنل", callback_data="admin_panel")],
    ]

    await safe_edit(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await safe_answer(callback)


@dp.callback_query(F.data == "testpool_toggle")
async def admin_testpool_toggle(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    SETTINGS.setdefault("test_service", {})["enabled"] = not SETTINGS.get("test_service", {}).get("enabled", True)
    save_settings()
    await safe_answer(callback, "✅ وضعیت تغییر کرد")
    await admin_testpool(callback)


@dp.callback_query(F.data == "testpool_add")
async def admin_testpool_add(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    user_states[callback.from_user.id] = {"testpool_add": True}
    await safe_edit(
        callback,
        "➕ <b>افزودن کانفیگ تست به مخزن</b>\n\n"
        "📝 کانفیگ/لینک‌های تست را بفرستید.\n\n"
        "💡 نکته‌ها:\n"
        "• می‌توانید در هر خط یک کانفیگ بفرستید (چندتایی یکجا)\n"
        "• می‌توانید چند پیام پشت سر هم بفرستید\n"
        "• بعد از اتمام، دکمه «✅ پایان افزودن» را بزنید",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ پایان افزودن", callback_data="testpool_done")],
            [InlineKeyboardButton(text="❌ انصراف", callback_data="testpool_done")],
        ]),
    )
    await safe_answer(callback)


@dp.callback_query(F.data == "testpool_done")
async def admin_testpool_done(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    user_states.pop(callback.from_user.id, None)
    await safe_answer(callback, "✅ پایان افزودن")
    await admin_testpool(callback)


@dp.message(lambda m: user_states.get(m.from_user.id, {}).get("testpool_add") is True)
async def admin_testpool_add_message(message: Message):
    """دریافت کانفیگ‌های تست از ادمین؛ هر خط یک کانفیگ."""
    admin_id = message.from_user.id
    if not is_admin(admin_id):
        return

    text = (message.text or "").strip()
    if not text:
        await message.reply("❌ لطفاً متن کانفیگ/لینک را بفرستید.")
        return

    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    added = 0
    for ln in lines:
        TEST_POOL.append({
            "id": next_numeric_id(TEST_POOL),
            "link": ln,
            "added_at": now_str(),
        })
        added += 1
    save_test_pool()

    await message.answer(
        f"✅ <b>{added} کانفیگ</b> به مخزن اضافه شد.\n"
        f"📦 موجودی فعلی مخزن: <b>{len(TEST_POOL)}</b> عدد\n\n"
        f"می‌توانید باز هم بفرستید یا «✅ پایان افزودن» را بزنید.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ پایان افزودن", callback_data="testpool_done")]
        ]),
        parse_mode=ParseMode.HTML,
    )


@dp.callback_query(F.data == "testpool_list")
async def admin_testpool_list(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return

    if not TEST_POOL:
        await safe_answer(callback, "📦 مخزن خالی است", show_alert=True)
        await admin_testpool(callback)
        return

    text = f"📋 <b>مخزن تست</b> ({len(TEST_POOL)} کانفیگ)\n\n"
    buttons = []
    for idx, item in enumerate(TEST_POOL[:20], start=1):
        link_full = item.get("link", "")
        preview = (link_full[:30] + "…") if len(link_full) > 30 else link_full
        text += f"{idx}. <code>{esc(preview)}</code>\n"
        buttons.append([InlineKeyboardButton(
            text=f"🗑 حذف شماره {idx}",
            callback_data=f"testpooldel_{item.get('id')}",
        )])
    if len(TEST_POOL) > 20:
        text += f"\n… و {len(TEST_POOL) - 20} کانفیگ دیگر"
    buttons.append([InlineKeyboardButton(text="🔙 برگشت", callback_data="admin_testpool")])

    await safe_edit(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await safe_answer(callback)


@dp.callback_query(F.data.startswith("testpooldel_"))
async def admin_testpool_delete(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    item_id = parse_int(callback.data.split("_", 1)[1])
    before = len(TEST_POOL)
    TEST_POOL[:] = [c for c in TEST_POOL if c.get("id") != item_id]
    if len(TEST_POOL) < before:
        save_test_pool()
        await safe_answer(callback, "🗑 کانفیگ حذف شد")
    else:
        await safe_answer(callback, "❌ یافت نشد", show_alert=True)
    await admin_testpool_list(callback)


@dp.callback_query(F.data == "testpool_clear")
async def admin_testpool_clear(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    await safe_edit(
        callback,
        f"⚠️ <b>خالی کردن مخزن تست</b>\n\nهر {len(TEST_POOL)} کانفیگ موجود حذف می‌شود. مطمئنید؟",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ بله، همه را حذف کن", callback_data="testpool_clearyes")],
            [InlineKeyboardButton(text="❌ انصراف", callback_data="admin_testpool")],
        ]),
    )
    await safe_answer(callback)


@dp.callback_query(F.data == "testpool_clearyes")
async def admin_testpool_clear_yes(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    TEST_POOL.clear()
    save_test_pool()
    await safe_answer(callback, "🗑 مخزن خالی شد", show_alert=True)
    await admin_testpool(callback)


# ==================================================================
# 👑 مدیریت ادمین‌ها (قابلیت جدید)
# ==================================================================
@dp.callback_query(F.data == "admin_admins")
async def admin_admins(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    user_states.pop(callback.from_user.id, None)

    admins = SETTINGS.get("admins", [])
    text = (
        f"👑 <b>مدیریت ادمین‌ها</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⭐️ سوپر ادمین: <code>{SUPER_ADMIN_ID}</code>\n"
        f"👥 ادمین‌های اضافه: {len(admins)} نفر\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
    )
    if admins:
        text += "\n<b>لیست ادمین‌ها:</b>\n"
        for idx, aid in enumerate(admins, start=1):
            u = USERS.get(str(aid), {})
            name = u.get("name", "")
            name_part = f" — {esc(name)}" if name else ""
            text += f"{idx}. <code>{aid}</code>{name_part}\n"
    else:
        text += "\n💡 هنوز ادمینی اضافه نشده است."

    text += "\n\n⚙️ ادمین‌ها به پنل مدیریت و اعلان‌های سفارش دسترسی دارند."

    buttons = [[InlineKeyboardButton(text="➕ افزودن ادمین جدید", callback_data="adminadd")]]
    for aid in admins:
        buttons.append([InlineKeyboardButton(
            text=f"🗑 حذف ادمین {aid}",
            callback_data=f"adminremove_{aid}",
        )])
    buttons.append([InlineKeyboardButton(text="🔙 برگشت به پنل", callback_data="admin_panel")])

    await safe_edit(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await safe_answer(callback)


@dp.callback_query(F.data == "adminadd")
async def admin_add_start(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    user_states[callback.from_user.id] = {"admin_add": True}
    await safe_edit(
        callback,
        "➕ <b>افزودن ادمین جدید</b>\n\n"
        "🆔 آیدی عددی کاربر را وارد کنید:\n\n"
        "💡 کاربر می‌تواند با دستور /id آیدی خود را ببیند.",
        reply_markup=get_cancel_keyboard("admin_admins"),
    )
    await safe_answer(callback)


@dp.message(lambda m: user_states.get(m.from_user.id, {}).get("admin_add") is True)
async def admin_add_message(message: Message):
    admin_id = message.from_user.id
    if not is_admin(admin_id):
        return

    new_id = parse_int(message.text)
    if new_id is None or new_id <= 0:
        await message.reply("❌ لطفاً یک آیدی عددی معتبر وارد کنید:",
                            reply_markup=get_cancel_keyboard("admin_admins"))
        return

    user_states.pop(admin_id, None)

    if new_id == SUPER_ADMIN_ID:
        await message.answer("⚠️ این کاربر سوپر ادمین است!", reply_markup=get_admin_keyboard())
        return
    if new_id in SETTINGS.get("admins", []):
        await message.answer("⚠️ این کاربر از قبل ادمین است.", reply_markup=get_admin_keyboard())
        return

    SETTINGS.setdefault("admins", []).append(new_id)
    save_settings()

    # اطلاع به ادمین جدید
    try:
        await bot.send_message(
            new_id,
            "👑 <b>تبریک! شما به عنوان ادمین ربات منصوب شدید.</b>\n\n"
            "از این پس به پنل مدیریت و اعلان‌های سفارش دسترسی دارید.\n"
            "برای ورود به پنل، /admin را بزنید یا از منوی اصلی دکمه «👑 پنل ادمین» را انتخاب کنید.",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        logger.warning(f"خطا در اطلاع به ادمین جدید {new_id}: {e}")

    await message.answer(
        f"✅ <b>ادمین جدید اضافه شد!</b>\n\n🆔 <code>{new_id}</code>",
        reply_markup=get_admin_keyboard(),
        parse_mode=ParseMode.HTML,
    )


@dp.callback_query(F.data.startswith("adminremove_"))
async def admin_remove(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    uid = parse_int(callback.data.split("_", 1)[1])
    if uid is None:
        await safe_answer(callback, "❌ خطا", show_alert=True)
        return
    if uid == SUPER_ADMIN_ID:
        await safe_answer(callback, "⛔ سوپر ادمین قابل حذف نیست", show_alert=True)
        return
    if uid in SETTINGS.get("admins", []):
        SETTINGS["admins"].remove(uid)
        save_settings()
        await safe_answer(callback, f"🗑 ادمین {uid} حذف شد", show_alert=True)
        try:
            await bot.send_message(uid, "ℹ️ دسترسی ادمین شما در ربات پایان یافت.")
        except Exception:
            pass
    else:
        await safe_answer(callback, "❌ ادمین یافت نشد", show_alert=True)
    await admin_admins(callback)
# ==================================================================
# ⌨️ مدیریت دکمه‌های شیشه‌ای (قابلیت جدید)
# ==================================================================
@dp.callback_query(F.data == "admin_keyboard")
async def admin_keyboard_menu(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    user_states.pop(callback.from_user.id, None)

    kb_conf = SETTINGS.get("keyboard", {})
    text = (
        "⌨️ <b>مدیریت دکمه‌های شیشه‌ای منوی اصلی</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "از اینجا می‌توانید:\n"
        "• 👁 دکمه‌ها را <b>نمایش/مخفی</b> کنید\n"
        "• ✏️ <b>متن دکمه‌ها</b> را تغییر دهید\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "وضعیت فعلی دکمه‌ها:\n"
    )

    buttons = []
    for key, conf in kb_conf.items():
        visible = conf.get("visible", True)
        status = "👁 نمایش" if visible else "🚫 مخفی"
        text += f"{'🟢' if visible else '🔴'} {esc(conf.get('text', key))}\n"
        buttons.append([
            InlineKeyboardButton(text=f"{status}: {conf.get('text', key)[:18]}",
                                 callback_data=f"kbtoggle_{key}"),
            InlineKeyboardButton(text="✏️", callback_data=f"kbrename_{key}"),
        ])

    buttons.append([InlineKeyboardButton(text="🔄 بازنشانی به حالت پیش‌فرض", callback_data="kbreset")])
    buttons.append([InlineKeyboardButton(text="🔙 برگشت به پنل", callback_data="admin_panel")])

    await safe_edit(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await safe_answer(callback)


@dp.callback_query(F.data.startswith("kbtoggle_"))
async def admin_keyboard_toggle(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    key = callback.data.split("_", 1)[1]
    conf = SETTINGS.setdefault("keyboard", {}).setdefault(key, {"visible": True, "text": key})
    conf["visible"] = not conf.get("visible", True)
    save_settings()
    await safe_answer(callback, 
        f"✅ دکمه «{conf.get('text', key)}» {'نمایش داده می‌شود' if conf['visible'] else 'مخفی شد'}"
    )
    await admin_keyboard_menu(callback)


@dp.callback_query(F.data.startswith("kbrename_"))
async def admin_keyboard_rename_start(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    key = callback.data.split("_", 1)[1]
    conf = SETTINGS.get("keyboard", {}).get(key, {})
    user_states[callback.from_user.id] = {"kb_rename": key}
    await safe_edit(
        callback,
        f"✏️ <b>تغییر متن دکمه</b>\n\n"
        f"متن فعلی: <code>{esc(conf.get('text', key))}</code>\n\n"
        f"📝 متن جدید دکمه را وارد کنید:",
        reply_markup=get_cancel_keyboard("admin_keyboard"),
    )
    await safe_answer(callback)


@dp.callback_query(F.data == "kbreset")
async def admin_keyboard_reset(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    SETTINGS["keyboard"] = json.loads(json.dumps(DEFAULT_KEYBOARD))
    save_settings()
    await safe_answer(callback, "🔄 دکمه‌ها به حالت پیش‌فرض برگشتند", show_alert=True)
    await admin_keyboard_menu(callback)


# ==================================================================
# 🏷️ مدیریت کوپن‌ها
# ==================================================================
@dp.callback_query(F.data == "admin_coupons")
async def admin_coupons(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    user_states.pop(callback.from_user.id, None)

    text = f"🏷️ <b>مدیریت کوپن‌ها</b>\n\n📊 تعداد کوپن‌ها: {len(COUPONS)}\n"
    if COUPONS:
        text += "\n<b>لیست کوپن‌ها:</b>\n"
        for code, c in COUPONS.items():
            status = "🟢" if c.get("status") == "active" else "🔴"
            max_uses = c.get("max_uses", 0)
            used = len(c.get("used_by", []))
            limit_txt = f"{used}/{max_uses}" if max_uses else f"{used}/∞"
            text += f"{status} <code>{esc(code)}</code> — {c.get('percent', 0)}% — استفاده: {limit_txt}\n"

    buttons = [[InlineKeyboardButton(text="➕ ساخت کوپن جدید", callback_data="couponadd")]]
    for code in list(COUPONS.keys())[:15]:
        buttons.append([InlineKeyboardButton(text=f"🗑 حذف {code}", callback_data=f"coupondel_{code}")])
    buttons.append([InlineKeyboardButton(text="🔙 برگشت به پنل", callback_data="admin_panel")])

    await safe_edit(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await safe_answer(callback)


@dp.callback_query(F.data == "couponadd")
async def admin_coupon_add_start(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    user_states[callback.from_user.id] = {"coupon_flow": {"step": "code"}}
    await safe_edit(
        callback,
        "➕ <b>ساخت کوپن جدید — مرحله ۱ از ۳</b>\n\n"
        "📝 <b>کد کوپن</b> را وارد کنید:\nمثال: <code>OFF20</code>",
        reply_markup=get_cancel_keyboard("admin_coupons"),
    )
    await safe_answer(callback)


@dp.callback_query(F.data.startswith("coupondel_"))
async def admin_coupon_delete(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    code = callback.data.split("_", 1)[1]
    if code in COUPONS:
        del COUPONS[code]
        save_coupons()
        await safe_answer(callback, f"🗑 کوپن {code} حذف شد", show_alert=True)
    else:
        await safe_answer(callback, "❌ کوپن یافت نشد", show_alert=True)
    await admin_coupons(callback)


# ==================================================================
# 📊 آمار
# ==================================================================
@dp.callback_query(F.data == "admin_stats")
async def admin_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return

    total_users = len(USERS)
    total_balance = sum(u.get("balance", 0) for u in USERS.values())
    purchases = [o for o in ORDERS.values() if o.get("type") == "purchase"]
    approved = [o for o in purchases if o.get("status") == "approved"]
    revenue = sum(o.get("price", 0) for o in approved)
    pending_receipts = len([o for o in purchases if o.get("status") == "pending"])
    awaiting_config = len([o for o in purchases if o.get("status") == "awaiting_config"])
    total_orders = len(purchases)
    charges = [o for o in ORDERS.values()
               if o.get("type") == "balance_charge" and o.get("status") == "approved"]
    charge_total = sum(o.get("price", 0) for o in charges)
    tests = len([o for o in ORDERS.values() if o.get("type") == "test"])

    text = (
        f"📊 <b>آمار ربات</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 کل کاربران: {total_users}\n"
        f"🚫 لیست سیاه: {len(BLACKLIST)}\n"
        f"👑 ادمین‌ها: {len(get_admin_ids())}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 کل سفارش‌های خرید: {total_orders}\n"
        f"✅ تحویل شده: {len(approved)}\n"
        f"⏳ فیش در انتظار تایید: {pending_receipts}\n"
        f"📤 در انتظار کانفیگ: {awaiting_config}\n"
        f"🧪 تست‌های دریافتی: {tests}\n"
        f"📦 مخزن تست: {len(TEST_POOL)} عدد\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 درآمد (خریدها): {revenue:,} تومان\n"
        f"💳 مجموع شارژها: {charge_total:,} تومان\n"
        f"💵 مجموع موجودی کاربران: {total_balance:,} تومان\n"
        f"📦 پلن‌ها: {len(PLANS.get('categories', []))} | کوپن‌ها: {len(COUPONS)}"
    )

    await safe_edit(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔙 برگشت به پنل", callback_data="admin_panel")
    ]]))
    await safe_answer(callback)


# ==================================================================
# 📢 پیام همگانی
# ==================================================================
@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    user_states[callback.from_user.id] = {"broadcast": {"step": "message"}}
    await safe_edit(
        callback,
        "📢 <b>پیام همگانی</b>\n\n"
        "📝 پیام خود را بفرستید (متن، عکس، ویدیو و...).\n"
        "پیام دقیقاً به همان شکل برای همه کاربران کپی می‌شود.",
        reply_markup=get_cancel_keyboard("admin_panel"),
    )
    await safe_answer(callback)


@dp.callback_query(F.data == "broadcast_confirm")
async def admin_broadcast_confirm(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    admin_id = callback.from_user.id
    state = user_states.get(admin_id, {}).get("broadcast", {})
    if state.get("step") != "confirm":
        await safe_answer(callback, "⚠️ پیامی برای ارسال وجود ندارد", show_alert=True)
        return

    user_states.pop(admin_id, None)
    await safe_edit(callback, "📢 <b>در حال ارسال پیام همگانی...</b>")
    await safe_answer(callback)

    sent, failed = 0, 0
    for uid_str in list(USERS.keys()):
        try:
            uid = int(uid_str)
        except (ValueError, TypeError):
            continue
        if uid in BLACKLIST:
            continue
        try:
            await bot.copy_message(uid, state["chat_id"], state["message_id"])
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)

    await callback.message.answer(
        f"📢 <b>پیام همگانی تمام شد</b>\n\n✅ ارسال موفق: {sent}\n❌ ناموفق: {failed}",
        reply_markup=get_admin_keyboard(),
        parse_mode=ParseMode.HTML,
    )


@dp.callback_query(F.data == "broadcast_cancel")
async def admin_broadcast_cancel(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    user_states.pop(callback.from_user.id, None)
    await safe_answer(callback, "❌ ارسال لغو شد")
    await admin_panel(callback)


# ==================================================================
# 🚫 لیست سیاه
# ==================================================================
@dp.callback_query(F.data == "admin_blacklist")
async def admin_blacklist_menu(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    user_states.pop(callback.from_user.id, None)

    text = f"🚫 <b>لیست سیاه</b>\n\n📊 تعداد مسدودشده: {len(BLACKLIST)}\n"
    if BLACKLIST:
        text += "\n"
        for uid in sorted(BLACKLIST)[:20]:
            u = USERS.get(str(uid), {})
            name = u.get("name", "")
            text += f"• <code>{uid}</code>{' — ' + esc(name) if name else ''}\n"
        if len(BLACKLIST) > 20:
            text += f"… و {len(BLACKLIST) - 20} مورد دیگر\n"

    buttons = [
        [InlineKeyboardButton(text="➕ افزودن به لیست سیاه", callback_data="blacklist_add")],
    ]
    for uid in sorted(BLACKLIST)[:10]:
        buttons.append([InlineKeyboardButton(text=f"✅ آزادسازی {uid}",
                                             callback_data=f"blacklist_rm_{uid}")])
    buttons.append([InlineKeyboardButton(text="🔙 برگشت به پنل", callback_data="admin_panel")])

    await safe_edit(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await safe_answer(callback)


@dp.callback_query(F.data == "blacklist_add")
async def admin_blacklist_add_start(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    user_states[callback.from_user.id] = {"blacklist_add": True}
    await safe_edit(
        callback,
        "🚫 <b>افزودن به لیست سیاه</b>\n\n🆔 آیدی عددی کاربر را وارد کنید:",
        reply_markup=get_cancel_keyboard("admin_blacklist"),
    )
    await safe_answer(callback)


@dp.callback_query(F.data.startswith("blacklist_rm_"))
async def admin_blacklist_remove(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    uid = parse_int(callback.data.split("_", 2)[2])
    if uid in BLACKLIST:
        BLACKLIST.discard(uid)
        save_blacklist()
        await safe_answer(callback, f"✅ کاربر {uid} آزاد شد", show_alert=True)
    else:
        await safe_answer(callback, "❌ یافت نشد", show_alert=True)
    await admin_blacklist_menu(callback)


# ==================================================================
# ⚙️ تنظیمات
# ==================================================================
@dp.callback_query(F.data == "admin_settings")
async def admin_settings(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    user_states.pop(callback.from_user.id, None)

    price = SETTINGS.get("price", {})
    card = SETTINGS.get("card", {})
    shop_open = SETTINGS.get("shop_open", True)

    text = (
        f"⚙️ <b>تنظیمات</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🛒 فروشگاه: {'🟢 باز' if shop_open else '🔴 بسته'}\n"
        f"🏦 بانک: {esc(card.get('bank', '-'))}\n"
        f"💳 کارت: <code>{esc(card.get('number', '-'))}</code>\n"
        f"👤 صاحب کارت: {esc(card.get('holder', '-'))}\n"
        f"💰 حداقل شارژ: {price.get('min_charge', MIN_CHARGE):,} تومان\n"
        f"💰 حداکثر شارژ: {price.get('max_charge', MAX_CHARGE):,} تومان\n"
        f"🎁 پاداش دعوت: {price.get('referral_percent', REFERRAL_PERCENT)}٪ از مبلغ خرید\n"
        f"🧪 سقف تست هر کاربر: {SETTINGS.get('test_service', {}).get('max_per_user', TEST_MAX_PER_USER)}\n"
        f"💬 آیدی پشتیبانی: {esc(get_support())}"
    )

    buttons = [
        [InlineKeyboardButton(
            text="🔴 بستن فروشگاه" if shop_open else "🟢 باز کردن فروشگاه",
            callback_data="setshoptoggle",
        )],
        [InlineKeyboardButton(text="💳 ویرایش کارت", callback_data="setcard")],
        [InlineKeyboardButton(text="💰 حداقل/حداکثر شارژ", callback_data="setcharge")],
        [InlineKeyboardButton(text="🎁 پاداش دعوت", callback_data="setrefbonus")],
        [InlineKeyboardButton(text="🧪 سقف تست هر کاربر", callback_data="settestmax")],
        [InlineKeyboardButton(text="💬 آیدی پشتیبانی", callback_data="setsupport")],
        [InlineKeyboardButton(text="🔙 برگشت به پنل", callback_data="admin_panel")],
    ]

    await safe_edit(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await safe_answer(callback)


@dp.callback_query(F.data == "setshoptoggle")
async def admin_shop_toggle(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    SETTINGS["shop_open"] = not SETTINGS.get("shop_open", True)
    save_settings()
    state_fa = "باز 🟢" if SETTINGS["shop_open"] else "بسته 🔴"
    await safe_answer(callback, f"🛒 فروشگاه: {state_fa}", show_alert=True)
    await admin_settings(callback)


@dp.callback_query(F.data == "setcard")
async def admin_set_card(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    user_states[callback.from_user.id] = {"settings_edit": "card"}
    await safe_edit(
        callback,
        "💳 <b>ویرایش اطلاعات کارت</b>\n\n"
        "📝 اطلاعات را در یک پیام و در ۳ خط بفرستید:\n"
        "خط ۱: شماره کارت\n"
        "خط ۲: نام صاحب کارت\n"
        "خط ۳: نام بانک",
        reply_markup=get_cancel_keyboard("admin_settings"),
    )
    await safe_answer(callback)


@dp.callback_query(F.data == "setcharge")
async def admin_set_charge(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    user_states[callback.from_user.id] = {"settings_edit": "charge"}
    await safe_edit(
        callback,
        "💰 <b>حداقل و حداکثر شارژ</b>\n\n"
        "📝 دو عدد را با فاصله بفرستید (تومان):\n"
        "مثال: <code>10000 5000000</code>",
        reply_markup=get_cancel_keyboard("admin_settings"),
    )
    await safe_answer(callback)


@dp.callback_query(F.data == "setrefbonus")
async def admin_set_refbonus(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    user_states[callback.from_user.id] = {"settings_edit": "refbonus"}
    await safe_edit(
        callback,
        "🎁 <b>پاداش دعوت از دوستان</b>\n\n"
        "📝 درصد پاداش را وارد کنید (درصدی از مبلغ خرید دوست شما):\n"
        "مثال: <code>10</code> یعنی ۱۰٪ از مبلغ خرید\n\n"
        "💡 اگر عدد <code>0</code> بفرستید، پاداش به حالت مبلغ ثابت برمی‌گردد.",
        reply_markup=get_cancel_keyboard("admin_settings"),
    )
    await safe_answer(callback)


@dp.callback_query(F.data == "settestmax")
async def admin_set_testmax(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    user_states[callback.from_user.id] = {"settings_edit": "testmax"}
    await safe_edit(
        callback,
        "🧪 <b>سقف تست برای هر کاربر</b>\n\n📝 تعداد را وارد کنید:\nمثال: <code>1</code>",
        reply_markup=get_cancel_keyboard("admin_settings"),
    )
    await safe_answer(callback)


# ==================================================================
# 💾 بکاپ
# ==================================================================
@dp.callback_query(F.data == "admin_backup")
async def admin_backup(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return

    await safe_answer(callback, "⏳ در حال ساخت بکاپ...")
    try:
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, path in FILES.items():
                if os.path.exists(path):
                    zf.write(path, arcname=f"{name}.json")
        buf.seek(0)
        filename = f"velorabot_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        await callback.message.answer_document(
            BufferedInputFile(buf.read(), filename=filename),
            caption="💾 <b>بکاپ کامل دیتابیس</b>",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        logger.error(f"خطا در ساخت بکاپ: {e}")
        await callback.message.answer(f"❌ خطا در ساخت بکاپ: {esc(e)}")


# ==================================================================
# 📥 هندلرهای متنی ادمین (ورودی‌های مرحله‌ای)
# ==================================================================
@dp.message(lambda m: user_states.get(m.from_user.id, {}).get("balance_adjust") is not None)
async def admin_balance_adjust_message(message: Message):
    if not is_admin(message.from_user.id):
        return
    state = user_states[message.from_user.id]["balance_adjust"]
    uid = state.get("user_id")
    mode = state.get("mode")

    amount = parse_int(message.text)
    if amount is None or amount <= 0:
        await message.reply("❌ لطفاً یک عدد معتبر وارد کنید:",
                            reply_markup=get_cancel_keyboard(f"userview_{uid}"))
        return

    user_states.pop(message.from_user.id, None)
    if str(uid) not in USERS:
        await message.answer("❌ کاربر یافت نشد.", reply_markup=get_admin_keyboard())
        return

    if mode == "add":
        new_balance = add_balance(uid, amount)
        action_fa = "افزایش"
    else:
        new_balance = reduce_balance(uid, amount)
        action_fa = "کاهش"

    await message.answer(
        f"✅ <b>{action_fa} موجودی انجام شد</b>\n\n"
        f"👤 کاربر: <code>{uid}</code>\n"
        f"💰 مبلغ: {amount:,} تومان\n"
        f"💳 موجودی جدید: {new_balance:,} تومان",
        reply_markup=get_admin_keyboard(),
        parse_mode=ParseMode.HTML,
    )
    try:
        if mode == "add":
            await bot.send_message(uid, f"💰 مبلغ {amount:,} تومان توسط مدیریت به حساب شما اضافه شد.\n💳 موجودی: {new_balance:,} تومان")
        else:
            await bot.send_message(uid, f"💸 مبلغ {amount:,} تومان توسط مدیریت از حساب شما کسر شد.\n💳 موجودی: {new_balance:,} تومان")
    except Exception:
        pass


@dp.message(lambda m: user_states.get(m.from_user.id, {}).get("awaiting_user_search") is True)
async def admin_user_search_message(message: Message):
    if not is_admin(message.from_user.id):
        return
    user_states.pop(message.from_user.id, None)
    uid = parse_int(message.text)
    if uid is None or str(uid) not in USERS:
        await message.answer("❌ کاربری با این آیدی یافت نشد.", reply_markup=get_admin_keyboard())
        return

    u = USERS[str(uid)]
    await message.answer(
        f"👤 <b>کاربر یافت شد</b>\n\n"
        f"🆔 <code>{uid}</code>\n"
        f"👤 {esc(u.get('name', 'کاربر'))}\n"
        f"💰 موجودی: {u.get('balance', 0):,} تومان",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚙️ مدیریت این کاربر", callback_data=f"userview_{uid}")],
            [InlineKeyboardButton(text="🔙 برگشت", callback_data="admin_users")],
        ]),
        parse_mode=ParseMode.HTML,
    )


@dp.message(lambda m: user_states.get(m.from_user.id, {}).get("kb_rename") is not None)
async def admin_kb_rename_message(message: Message):
    if not is_admin(message.from_user.id):
        return
    key = user_states[message.from_user.id]["kb_rename"]
    text = (message.text or "").strip()
    if not text or len(text) > 40:
        await message.reply("❌ متن دکمه باید بین ۱ تا ۴۰ کاراکتر باشد. دوباره وارد کنید:",
                            reply_markup=get_cancel_keyboard("admin_keyboard"))
        return
    user_states.pop(message.from_user.id, None)
    SETTINGS.setdefault("keyboard", {}).setdefault(key, {"visible": True})["text"] = text
    save_settings()
    await message.answer(f"✅ متن دکمه به «{esc(text)}» تغییر کرد.", reply_markup=get_admin_keyboard(),
                         parse_mode=ParseMode.HTML)


@dp.message(lambda m: user_states.get(m.from_user.id, {}).get("coupon_flow") is not None)
async def admin_coupon_flow_message(message: Message):
    if not is_admin(message.from_user.id):
        return
    flow = user_states[message.from_user.id]["coupon_flow"]
    step = flow.get("step")
    text = (message.text or "").strip()

    if step == "code":
        if not text or len(text) < 2 or " " in text:
            await message.reply("❌ کد کوپن نامعتبر است (بدون فاصله، حداقل ۲ حرف). دوباره وارد کنید:",
                                reply_markup=get_cancel_keyboard("admin_coupons"))
            return
        if text in COUPONS:
            await message.reply("⚠️ این کد از قبل وجود دارد. کد دیگری وارد کنید:",
                                reply_markup=get_cancel_keyboard("admin_coupons"))
            return
        flow["code"] = text
        flow["step"] = "percent"
        user_states[message.from_user.id] = {"coupon_flow": flow}
        await message.answer("💥 <b>درصد تخفیف</b> را وارد کنید (۱ تا ۱۰۰):\nمثال: <code>20</code>",
                             reply_markup=get_cancel_keyboard("admin_coupons"),
                             parse_mode=ParseMode.HTML)
        return

    if step == "percent":
        percent = parse_int(text)
        if percent is None or percent < 1 or percent > 100:
            await message.reply("❌ عددی بین ۱ تا ۱۰۰ وارد کنید:",
                                reply_markup=get_cancel_keyboard("admin_coupons"))
            return
        flow["percent"] = percent
        flow["step"] = "max_uses"
        user_states[message.from_user.id] = {"coupon_flow": flow}
        await message.answer("🔢 <b>سقف استفاده</b> را وارد کنید (۰ = نامحدود):\nمثال: <code>50</code>",
                             reply_markup=get_cancel_keyboard("admin_coupons"),
                             parse_mode=ParseMode.HTML)
        return

    if step == "max_uses":
        max_uses = parse_int(text)
        if max_uses is None or max_uses < 0:
            await message.reply("❌ عددی صفر یا بزرگ‌تر وارد کنید:",
                                reply_markup=get_cancel_keyboard("admin_coupons"))
            return
        COUPONS[flow["code"]] = {
            "code": flow["code"],
            "percent": flow["percent"],
            "max_uses": max_uses,
            "used_by": [],
            "status": "active",
            "created_at": now_str(),
        }
        save_coupons()
        user_states.pop(message.from_user.id, None)
        await message.answer(
            f"✅ <b>کوپن ساخته شد!</b>\n\n"
            f"🏷️ کد: <code>{esc(flow['code'])}</code>\n"
            f"💥 تخفیف: {flow['percent']}%\n"
            f"🔢 سقف استفاده: {'نامحدود' if max_uses == 0 else max_uses}",
            reply_markup=get_admin_keyboard(),
            parse_mode=ParseMode.HTML,
        )
        return


@dp.message(lambda m: user_states.get(m.from_user.id, {}).get("broadcast", {}).get("step") == "message")
async def admin_broadcast_message(message: Message):
    if not is_admin(message.from_user.id):
        return
    user_states[message.from_user.id] = {"broadcast": {
        "step": "confirm",
        "chat_id": message.chat.id,
        "message_id": message.message_id,
    }}
    await message.answer(
        f"📢 <b>پیش‌نمایش آماده است</b>\n\nپیام شما برای <b>{len(USERS)}</b> کاربر ارسال می‌شود. مطمئنید؟",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ بله، ارسال کن", callback_data="broadcast_confirm")],
            [InlineKeyboardButton(text="❌ انصراف", callback_data="broadcast_cancel")],
        ]),
        parse_mode=ParseMode.HTML,
    )


@dp.message(lambda m: user_states.get(m.from_user.id, {}).get("blacklist_add") is True)
async def admin_blacklist_add_message(message: Message):
    if not is_admin(message.from_user.id):
        return
    uid = parse_int(message.text)
    if uid is None or uid <= 0:
        await message.reply("❌ لطفاً یک آیدی عددی معتبر وارد کنید:",
                            reply_markup=get_cancel_keyboard("admin_blacklist"))
        return
    user_states.pop(message.from_user.id, None)
    if uid == SUPER_ADMIN_ID or uid in SETTINGS.get("admins", []):
        await message.answer("⛔ نمی‌توانید ادمین را بلاک کنید.", reply_markup=get_admin_keyboard())
        return
    BLACKLIST.add(uid)
    save_blacklist()
    await message.answer(f"🚫 کاربر <code>{uid}</code> به لیست سیاه اضافه شد.",
                         reply_markup=get_admin_keyboard(), parse_mode=ParseMode.HTML)


@dp.message(lambda m: user_states.get(m.from_user.id, {}).get("settings_edit") is not None)
async def admin_settings_edit_message(message: Message):
    if not is_admin(message.from_user.id):
        return
    field = user_states[message.from_user.id]["settings_edit"]
    text = (message.text or "").strip()

    if field == "card":
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        if len(lines) < 3:
            await message.reply("❌ لطفاً هر ۳ خط را کامل بفرستید (شماره کارت / نام / بانک):",
                                reply_markup=get_cancel_keyboard("admin_settings"))
            return
        SETTINGS.setdefault("card", {})["number"] = lines[0]
        SETTINGS["card"]["holder"] = lines[1]
        SETTINGS["card"]["bank"] = lines[2]
        save_settings()
        user_states.pop(message.from_user.id, None)
        await message.answer("✅ اطلاعات کارت به‌روزرسانی شد.", reply_markup=get_admin_keyboard())
        return

    if field == "charge":
        parts = text.split()
        if len(parts) != 2:
            await message.reply("❌ دو عدد با فاصله بفرستید. مثال: <code>10000 5000000</code>",
                                reply_markup=get_cancel_keyboard("admin_settings"),
                                parse_mode=ParseMode.HTML)
            return
        min_c = parse_int(parts[0])
        max_c = parse_int(parts[1])
        if min_c is None or max_c is None or min_c <= 0 or max_c <= min_c:
            await message.reply("❌ اعداد نامعتبر است (حداکثر باید بیشتر از حداقل باشد). دوباره وارد کنید:",
                                reply_markup=get_cancel_keyboard("admin_settings"))
            return
        SETTINGS.setdefault("price", {})["min_charge"] = min_c
        SETTINGS["price"]["max_charge"] = max_c
        save_settings()
        user_states.pop(message.from_user.id, None)
        await message.answer(f"✅ محدوده شارژ: {min_c:,} تا {max_c:,} تومان",
                             reply_markup=get_admin_keyboard())
        return

    if field == "refbonus":
        val = parse_int(text)
        if val is None or val < 0:
            await message.reply("❌ عدد معتبر وارد کنید:",
                                reply_markup=get_cancel_keyboard("admin_settings"))
            return
        SETTINGS.setdefault("price", {})["referral_percent"] = val
        if val == 0:
            SETTINGS["price"]["referral_percent"] = 0
        save_settings()
        user_states.pop(message.from_user.id, None)
        if val > 0:
            msg = f"✅ پاداش دعوت: {val}٪ از مبلغ خرید دوست"
        else:
            msg = "✅ پاداش دعوت: حالت مبلغ ثابت ({:,} تومان)".format(
                SETTINGS.get("price", {}).get("referral_bonus", REFERRAL_BONUS))
        await message.answer(msg, reply_markup=get_admin_keyboard())
        return

    if field == "testmax":
        val = parse_int(text)
        if val is None or val < 1:
            await message.reply("❌ عددی بزرگ‌تر از صفر وارد کنید:",
                                reply_markup=get_cancel_keyboard("admin_settings"))
            return
        SETTINGS.setdefault("test_service", {})["max_per_user"] = val
        save_settings()
        user_states.pop(message.from_user.id, None)
        await message.answer(f"✅ سقف تست هر کاربر: {val} بار", reply_markup=get_admin_keyboard())
        return



# ==================================================================
# 🗃 مخزن کانفیگ + تحویل خودکار + 📢 عضویت اجباری + 💬 پشتیبانی (قابلیت‌های جدید)
# ==================================================================

async def deliver_order_config(order_id: int) -> None:
    """تحویل کانفیگ خرید: اگر «حالت فروش» پلن «از مخزن» باشد و کانفیگ موجود باشد، خودکار از مخزن؛
    در غیر این صورت (دستی، یا مخزن خالی) → جریان دستی (اعلان به ادمین برای ریپلای)."""
    order = get_order(order_id)
    if not order:
        return
    plan = get_plan(order.get("plan_id"))
    if get_sale_mode(plan) == "pool":
        item = pop_pool_config(order.get("plan_id"), order.get("package_id"))
        if item:
            await send_config_to_user(
                order["user_id"],
                item.get("link", ""),
                title=(
                    f"🎉 <b>سفارش شما آماده شد!</b>\n\n"
                    f"🆔 سفارش: #{order_id}\n"
                    f"📦 پلن: {esc(order.get('plan_name') or 'سرویس')}\n"
                    f"📊 بسته: {format_volume(order.get('volume', 0))} / {order.get('days', 0)} روز"
                ),
            )
            update_order(order_id, status="approved", config_link=item.get("link", ""),
                         approved_date=now_str())
            await log_event(
                f"🗃 سفارش #{order_id} به‌صورت خودکار از مخزن تحویل شد (کاربر <code>{order['user_id']}</code>)."
            )
            await notify_admins(
                f"🗃 <b>تحویل خودکار از مخزن</b>\n\n"
                f"🆔 سفارش: #{order_id}\n"
                f"👤 کاربر: <code>{order['user_id']}</code>\n"
                f"📦 پلن: {esc(order.get('plan_name') or '-')}\n"
                f"📊 بسته: {format_volume(order.get('volume', 0))} / {order.get('days', 0)} روز\n"
                f"🗳 باقیمانده مخزن این بسته: {pool_count(order.get('plan_id'), order.get('package_id'))} عدد"
            )
            return
        # مخزن خالی → هشدار به ادمین‌ها و سقوط به حالت دستی
        await notify_admins(
            f"⚠️ <b>مخزن کانفیگ خالی است!</b>\n\n"
            f"سفارش #{order_id} (پلن «{esc(order.get('plan_name') or '-')}»، بسته "
            f"{format_volume(order.get('volume', 0))}) روی حالت «از مخزن» است ولی مخزن این بسته خالی است.\n"
            f"لطفاً از «🗃 مخزن کانفیگ» کانفیگ اضافه کنید؛ این سفارش به حالت دستی رفت."
        )
    # حالت دستی (یا مخزن خالی) → جریان دستی
    await send_order_config_request(order_id)


# =============== 🛒 حالت فروش پلن (از مخزن / دستی) ===============
@dp.callback_query(F.data.startswith("plansale_"))
async def admin_plan_sale_mode(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    plan_id = parse_int(callback.data.split("_", 1)[1])
    plan = get_plan(plan_id)
    if not plan:
        await safe_answer(callback, "❌ پلن یافت نشد", show_alert=True)
        return
    plan["sale_mode"] = "manual" if get_sale_mode(plan) == "pool" else "pool"
    save_plans()
    new_fa = "🗃 از مخزن (خودکار)" if plan["sale_mode"] == "pool" else "✋ دستی (ادمین)"
    await safe_answer(callback, f"🛒 حالت فروش: {new_fa}", show_alert=True)
    await admin_plan_view(callback)


# =============== 💬 تنظیم آیدی پشتیبانی ===============
@dp.callback_query(F.data == "setsupport")
async def admin_set_support(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    user_states[callback.from_user.id] = {"settings_edit": "support"}
    await safe_edit(
        callback,
        "💬 <b>تنظیم آیدی پشتیبانی</b>\n\n"
        "📝 یوزرنیم پشتیبانی را بفرستید:\n"
        "مثال: <code>@your_support</code>",
        reply_markup=get_cancel_keyboard("admin_settings"),
    )
    await safe_answer(callback)


# =============== 🗃 مخزن کانفیگ (مرتب‌شده بر اساس پلن + حجم) ===============
async def _render_cpool_pkg(callback: CallbackQuery, plan_id: int, pkg_id: int) -> None:
    plan = get_plan(plan_id)
    pkg = get_package(plan, pkg_id)
    if not plan or not pkg:
        await safe_answer(callback, "❌ بسته یافت نشد", show_alert=True)
        return
    cnt = pool_count(plan_id, pkg_id)
    mode = get_sale_mode(plan)
    mode_fa = "🗃 از مخزن (خودکار)" if mode == "pool" else "✋ دستی (ادمین)"
    text = (
        f"🗃 <b>مخزن کانفیگ</b>\n\n"
        f"📦 پلن: {esc(plan.get('name'))}\n"
        f"📊 حجم: {format_volume(pkg.get('volume', 0))} / {pkg.get('days', 30)} روز\n"
        f"🛒 حالت فروش: <b>{mode_fa}</b>\n"
        f"🗳 موجودی مخزن: <b>{cnt}</b> کانفیگ\n\n"
        + ("⚡️ این پلن روی حالت خودکار است — خریدار بلافاصله کانفیگ می‌گیرد."
           if mode == "pool" else
           "✋ این پلن دستی است — برای تحویل خودکار، حالت فروش را در «مدیریت پلن‌ها» روی «از مخزن» بگذارید.")
    )
    buttons = [
        [InlineKeyboardButton(text="➕ افزودن کانفیگ", callback_data=f"cpooladd_{plan_id}_{pkg_id}")],
        [InlineKeyboardButton(text="📋 مشاهده/حذف کانفیگ‌ها", callback_data=f"cpoollist_{plan_id}_{pkg_id}")],
        [InlineKeyboardButton(text="🗑 خالی کردن این بسته", callback_data=f"cpoolclear_{plan_id}_{pkg_id}")],
        [InlineKeyboardButton(text="🔙 برگشت", callback_data=f"cpoolplan_{plan_id}")],
    ]
    await safe_edit(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


async def _render_cpool_list(callback: CallbackQuery, plan_id: int, pkg_id: int) -> None:
    plan = get_plan(plan_id)
    pkg = get_package(plan, pkg_id)
    items = pool_configs(plan_id, pkg_id)
    if not items:
        await safe_answer(callback, "📦 مخزن این بسته خالی است", show_alert=True)
        await _render_cpool_pkg(callback, plan_id, pkg_id)
        return
    text = f"📋 <b>مخزن: {esc(plan.get('name'))} — {format_volume(pkg.get('volume', 0))}</b> ({len(items)} کانفیگ)\n\n"
    buttons = []
    for idx, item in enumerate(items[:20], start=1):
        link_full = item.get("link", "")
        preview = (link_full[:25] + "…") if len(link_full) > 25 else link_full
        text += f"{idx}. <code>{esc(preview)}</code>\n"
        buttons.append([InlineKeyboardButton(
            text=f"🗑 حذف شماره {idx}",
            callback_data=f"cpooldel_{plan_id}_{pkg_id}_{item.get('id')}",
        )])
    if len(items) > 20:
        text += f"\n… و {len(items) - 20} کانفیگ دیگر"
    buttons.append([InlineKeyboardButton(text="🔙 برگشت", callback_data=f"cpoolpkg_{plan_id}_{pkg_id}")])
    await safe_edit(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


@dp.callback_query(F.data == "admin_configpool")
async def admin_configpool(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    user_states.pop(callback.from_user.id, None)
    plans = PLANS.get("categories", [])
    if not plans:
        await safe_answer(callback, "❌ هیچ پلنی وجود ندارد. اول از «مدیریت پلن‌ها» پلن بسازید.", show_alert=True)
        return
    text = (
        "🗃 <b>مخزن کانفیگ</b>\n\n"
        "برای کدام پلن می‌خواهید کانفیگ اضافه یا مدیریت کنید؟\n\n"
        "💡 راهنما: پلن‌هایی که کنارشان 🗃 سبز است در «حالت خودکار از مخزن» هستند — "
        "یعنی خریدار به‌محض پرداخت، کانفیگش بلافاصله از همین مخزن تحویل داده می‌شود. "
        "برای تغییر حالت، وارد پلن شوید."
    )
    buttons = []
    for plan in plans:
        total = sum(1 for c in CONFIG_POOL if c.get("plan_id") == plan.get("id"))
        mode_icon = "🗃" if get_sale_mode(plan) == "pool" else "✋"
        buttons.append([InlineKeyboardButton(
            text=f"{mode_icon} {plan.get('icon', '📦')} {plan.get('name')} — {total} عدد",
            callback_data=f"cpoolplan_{plan.get('id')}",
        )])
    buttons.append([InlineKeyboardButton(text="🔙 برگشت به پنل", callback_data="admin_panel")])
    await safe_edit(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await safe_answer(callback)


@dp.callback_query(F.data.startswith("cpoolplan_"))
async def admin_configpool_plan(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    plan_id = parse_int(callback.data.split("_", 1)[1])
    plan = get_plan(plan_id)
    if not plan:
        await safe_answer(callback, "❌ پلن یافت نشد", show_alert=True)
        return
    packages = plan.get("packages", [])
    text = f"🗃 <b>مخزن: {esc(plan.get('name'))}</b>\n\nبرای کدام حجم (بسته) می‌خواهید کانفیگ اضافه/مدیریت کنید؟"
    buttons = []
    if packages:
        for idx, pkg in enumerate(packages, start=1):
            cnt = pool_count(plan_id, pkg.get("id"))
            buttons.append([InlineKeyboardButton(
                text=f"{idx}. {format_volume(pkg.get('volume', 0))} / {pkg.get('days', 30)} روز — {cnt} عدد",
                callback_data=f"cpoolpkg_{plan_id}_{pkg.get('id')}",
            )])
    else:
        text += "\n\n❌ این پلن بسته‌ای ندارد. اول از «مدیریت پلن‌ها» بسته اضافه کنید."
    buttons.append([InlineKeyboardButton(text="🔙 برگشت", callback_data="admin_configpool")])
    await safe_edit(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await safe_answer(callback)


@dp.callback_query(F.data.startswith("cpoolpkg_"))
async def admin_configpool_pkg(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    parts = callback.data.split("_")
    plan_id, pkg_id = parse_int(parts[1]), parse_int(parts[2])
    await _render_cpool_pkg(callback, plan_id, pkg_id)
    await safe_answer(callback)


@dp.callback_query(F.data.startswith("cpooladd_"))
async def admin_configpool_add(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    parts = callback.data.split("_")
    plan_id, pkg_id = parse_int(parts[1]), parse_int(parts[2])
    plan = get_plan(plan_id)
    pkg = get_package(plan, pkg_id)
    if not plan or not pkg:
        await safe_answer(callback, "❌ بسته یافت نشد", show_alert=True)
        return
    user_states[callback.from_user.id] = {"configpool_add": {"plan_id": plan_id, "package_id": pkg_id}}
    await safe_edit(
        callback,
        f"➕ <b>افزودن کانفیگ به مخزن</b>\n\n"
        f"📦 پلن: {esc(plan.get('name'))}\n"
        f"📊 حجم: {format_volume(pkg.get('volume', 0))} / {pkg.get('days', 30)} روز\n\n"
        "📝 کانفیگ/لینک‌ها را بفرستید.\n\n"
        "💡 می‌توانید هر خط یک کانفیگ (چندتایی یکجا) یا چند پیام پشت سر هم بفرستید.\n"
        "بعد از اتمام، دکمه «✅ پایان افزودن» را بزنید.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ پایان افزودن", callback_data="configpool_done")],
            [InlineKeyboardButton(text="❌ انصراف", callback_data="configpool_done")],
        ]),
    )
    await safe_answer(callback)


@dp.message(lambda m: user_states.get(m.from_user.id, {}).get("configpool_add") is not None)
async def admin_configpool_add_message(message: Message):
    """دریافت کانفیگ‌های مخزن از ادمین؛ هر خط یک کانفیگ."""
    admin_id = message.from_user.id
    if not is_admin(admin_id):
        return
    state = user_states[admin_id]["configpool_add"]
    plan_id, pkg_id = state["plan_id"], state["package_id"]
    text = (message.text or "").strip()
    if not text:
        await message.reply("❌ لطفاً متن کانفیگ/لینک را بفرستید.")
        return
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    added = 0
    for ln in lines:
        CONFIG_POOL.append({
            "id": next_numeric_id(CONFIG_POOL),
            "plan_id": plan_id,
            "package_id": pkg_id,
            "link": ln,
            "added_at": now_str(),
        })
        added += 1
    save_config_pool()
    await message.answer(
        f"✅ <b>{added} کانفیگ</b> به مخزن اضافه شد.\n"
        f"📦 موجودی این بسته: <b>{pool_count(plan_id, pkg_id)}</b> عدد\n\n"
        "می‌توانید باز هم بفرستید یا «✅ پایان افزودن» را بزنید.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ پایان افزودن", callback_data="configpool_done")]
        ]),
        parse_mode=ParseMode.HTML,
    )


@dp.callback_query(F.data == "configpool_done")
async def admin_configpool_done(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    user_states.pop(callback.from_user.id, None)
    await safe_answer(callback, "✅ پایان افزودن")
    await admin_configpool(callback)


@dp.callback_query(F.data.startswith("cpoollist_"))
async def admin_configpool_list(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    parts = callback.data.split("_")
    plan_id, pkg_id = parse_int(parts[1]), parse_int(parts[2])
    await _render_cpool_list(callback, plan_id, pkg_id)
    await safe_answer(callback)


@dp.callback_query(F.data.startswith("cpooldel_"))
async def admin_configpool_delete(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    parts = callback.data.split("_")
    plan_id, pkg_id, item_id = parse_int(parts[1]), parse_int(parts[2]), parse_int(parts[3])
    before = len(CONFIG_POOL)
    CONFIG_POOL[:] = [c for c in CONFIG_POOL if c.get("id") != item_id]
    if len(CONFIG_POOL) < before:
        save_config_pool()
        await safe_answer(callback, "🗑 کانفیگ حذف شد")
    else:
        await safe_answer(callback, "❌ یافت نشد", show_alert=True)
    await _render_cpool_list(callback, plan_id, pkg_id)


@dp.callback_query(F.data.startswith("cpoolclear_"))
async def admin_configpool_clear(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    parts = callback.data.split("_")
    plan_id, pkg_id = parse_int(parts[1]), parse_int(parts[2])
    cnt = pool_count(plan_id, pkg_id)
    await safe_edit(
        callback,
        f"⚠️ <b>خالی کردن مخزن این بسته</b>\n\nهر {cnt} کانفیگ موجود حذف می‌شود. مطمئنید؟",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ بله، همه را حذف کن", callback_data=f"cpoolclearyes_{plan_id}_{pkg_id}")],
            [InlineKeyboardButton(text="❌ انصراف", callback_data=f"cpoolpkg_{plan_id}_{pkg_id}")],
        ]),
    )
    await safe_answer(callback)


@dp.callback_query(F.data.startswith("cpoolclearyes_"))
async def admin_configpool_clear_yes(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    parts = callback.data.split("_")
    plan_id, pkg_id = parse_int(parts[1]), parse_int(parts[2])
    CONFIG_POOL[:] = [c for c in CONFIG_POOL if not (c.get("plan_id") == plan_id and c.get("package_id") == pkg_id)]
    save_config_pool()
    await safe_answer(callback, "🗑 مخزن این بسته خالی شد", show_alert=True)
    await _render_cpool_pkg(callback, plan_id, pkg_id)


# =============== 🎁 هدیه موجودی (ادمین به کاربر) ===============
@dp.callback_query(F.data == "admin_gift")
async def admin_gift(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    user_states.pop(callback.from_user.id, None)
    text = (
        "🎁 <b>هدیه دادن موجودی</b>\n\n"
        "📝 <b>آیدی عددی کاربر</b> را بفرستید:\n"
        "💡 آیدی کاربران از بخش «👥 کاربران» قابل مشاهده است.\n\n"
        "مثال: <code>123456789</code>"
    )
    await safe_edit(
        callback, text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="❌ انصراف", callback_data="admin_panel", style="danger"),
        ]]),
    )
    user_states[callback.from_user.id] = {"gift_step": "user_id"}
    await safe_answer(callback)


@dp.callback_query(F.data == "gift_cancel")
async def admin_gift_cancel(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    user_states.pop(callback.from_user.id, None)
    await safe_answer(callback, "انصراف")
    await admin_panel(callback)


@dp.message(lambda m: user_states.get(m.from_user.id, {}).get("gift_step") is not None)
async def admin_gift_message(message: Message):
    """جریان هدیه موجودی: آیدی کاربر → مبلغ → تایید."""
    admin_id = message.from_user.id
    if not is_admin(admin_id):
        return
    state = user_states.get(admin_id, {})
    step = state.get("gift_step")
    text = (message.text or "").strip()

    if step == "user_id":
        target = parse_int(text)
        if target is None or str(target) not in USERS:
            await message.reply(
                "❌ کاربری با این آیدی پیدا نشد.\n"
                "📝 آیدی عددی معتبر بفرستید (یا /cancel):")
            return
        target_user = USERS[str(target)]
        balance = target_user.get("balance", 0)
        name = target_user.get("name") or target_user.get("username") or str(target)
        state["gift_user_id"] = target
        state["gift_step"] = "amount"
        await message.answer(
            f"👤 کاربر: {esc(name)} (<code>{target}</code>)\n"
            f"💳 موجودی فعلی: {balance:,} تومان\n\n"
            f"📝 <b>مبلغ هدیه</b> را به تومان بفرستید:\n"
            f"مثال: <code>50000</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    if step == "amount":
        amount = parse_int(text)
        if amount is None or amount <= 0:
            await message.reply("❌ مبلغ معتبر وارد کنید (عدد بزرگ‌تر از صفر):")
            return
        target = state.get("gift_user_id")
        if not target or str(target) not in USERS:
            state["gift_step"] = "user_id"
            await message.reply("❌ خطا — کاربر پیدا نشد. دوباره آیدی را بفرستید:")
            return
        new_balance = add_balance(int(target), amount)
        target_user = USERS[str(target)]
        name = target_user.get("name") or target_user.get("username") or str(target)
        user_states.pop(admin_id, None)
        await message.answer(
            f"✅ <b>هدیه ثبت شد!</b>\n\n"
            f"👤 کاربر: {esc(name)} (<code>{target}</code>)\n"
            f"🎁 مبلغ هدیه: {amount:,} تومان\n"
            f"💳 موجودی جدید کاربر: {new_balance:,} تومان",
            parse_mode=ParseMode.HTML,
        )
        try:
            await bot.send_message(
                int(target),
                f"🎁 <b>هدیه دریافت کردید!</b>\n\n"
                f"💰 مبلغ {amount:,} تومان به موجودی شما اضافه شد.\n"
                f"💳 موجودی فعلی: {new_balance:,} تومان\n\n"
                f"🙏 از اینکه با ما هستید متشکریم!",
            )
        except Exception as e:
            await message.reply(f"⚠️ به کاربر اطلاع‌رسانی نشد: {esc(str(e)[:80])}")
        await log_event(
            f"🎁 <b>هدیه موجودی</b> — ادمین <code>{admin_id}</code> مبلغ {amount:,} تومان "
            f"به کاربر <code>{target}</code> هدیه داد."
        )
        return


@dp.message(Command("cancel"))
async def cmd_cancel(message: Message):
    """لغو هر حالت در انتظار (مثل جریان هدیه)."""
    user_states.pop(message.from_user.id, None)
    await message.answer("✅ لغو شد.", reply_markup=get_admin_keyboard() if is_admin(message.from_user.id) else get_back_only_keyboard())


# =============== 🏆 پاداش پله‌ای دعوت ===============
@dp.callback_query(F.data == "admin_milestones")
async def admin_milestones(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    user_states.pop(callback.from_user.id, None)
    conf = milestones_conf()
    enabled = conf.get("enabled", True)
    only_paid = conf.get("require_purchase", False)
    tiers = milestone_tiers()

    text = (
        f"🏆 <b>پاداش پله‌ای دعوت از دوستان</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⚙️ وضعیت: {'🟢 فعال' if enabled else '🔴 غیرفعال'}\n"
        f"🧾 شرط شمارش: {'فقط دعوت‌شده‌هایی که خرید کرده‌اند' if only_paid else 'همه‌ی دعوت‌شده‌ها'}\n"
        f"📊 تعداد پله‌ها: {len(tiers)}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    if tiers:
        text += "<b>پله‌های فعلی:</b>\n"
        for t in tiers:
            text += f"👥 {int(t['count'])} دعوت → 💰 {int(t['reward']):,} تومان\n"
    else:
        text += "❕ هیچ پله‌ای تعریف نشده است.\n"
    text += ("\n💡 هر پله فقط یک‌بار برای هر کاربر پرداخت می‌شود و "
             "به‌صورت خودکار به موجودی او اضافه می‌گردد.")

    buttons = [
        [InlineKeyboardButton(
            text="🔴 غیرفعال کردن پاداش پله‌ای" if enabled else "🟢 فعال کردن پاداش پله‌ای",
            callback_data="ms_toggle",
        )],
        [InlineKeyboardButton(text="➕ افزودن یا ویرایش پله", callback_data="ms_add")],
        [InlineKeyboardButton(
            text="🧾 شمارش: فقط خریدکرده‌ها" if not only_paid else "👥 شمارش: همه دعوت‌شده‌ها",
            callback_data="ms_reqpurchase",
        )],
        [InlineKeyboardButton(text="📊 آمار برترین دعوت‌کننده‌ها", callback_data="ms_top")],
    ]
    for t in tiers:
        buttons.append([InlineKeyboardButton(
            text=f"🗑 حذف پله {int(t['count'])} دعوت",
            callback_data=f"ms_del_{int(t['count'])}",
        )])
    buttons.append([InlineKeyboardButton(text="🔙 برگشت به پنل", callback_data="admin_panel")])

    await safe_edit(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await safe_answer(callback)


@dp.callback_query(F.data == "ms_toggle")
async def admin_milestones_toggle(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    conf = milestones_conf()
    conf["enabled"] = not conf.get("enabled", True)
    save_settings()
    await safe_answer(callback, f"🏆 پاداش پله‌ای: {'فعال 🟢' if conf['enabled'] else 'غیرفعال 🔴'}", show_alert=True)
    await admin_milestones(callback)


@dp.callback_query(F.data == "ms_reqpurchase")
async def admin_milestones_reqpurchase(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    conf = milestones_conf()
    conf["require_purchase"] = not conf.get("require_purchase", False)
    save_settings()
    state_fa = "فقط خریدکرده‌ها 🧾" if conf["require_purchase"] else "همه دعوت‌شده‌ها 👥"
    await safe_answer(callback, f"شمارش رفرال: {state_fa}", show_alert=True)
    await admin_milestones(callback)


@dp.callback_query(F.data.startswith("ms_del_"))
async def admin_milestones_delete(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    count = parse_int(callback.data.split("_")[-1])
    conf = milestones_conf()
    before = len(conf.get("tiers", []))
    conf["tiers"] = [t for t in conf.get("tiers", []) if int(t.get("count", 0)) != count]
    save_settings()
    if len(conf["tiers"]) < before:
        await safe_answer(callback, f"🗑 پله {count} دعوت حذف شد")
    else:
        await safe_answer(callback, "❌ یافت نشد", show_alert=True)
    await admin_milestones(callback)


@dp.callback_query(F.data == "ms_add")
async def admin_milestones_add(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    user_states[callback.from_user.id] = {"ms_add": True}
    await safe_edit(
        callback,
        "➕ <b>افزودن یا ویرایش پله</b>\n\n"
        "📝 به این شکل بفرستید: <code>تعداد دعوت - مبلغ پاداش</code>\n\n"
        "<b>مثال‌ها:</b>\n"
        "<code>10 - 100000</code>\n"
        "<code>20 - 200000</code>\n"
        "<code>50 - 500000</code>\n\n"
        "💡 می‌توانید چند پله را در چند خط یکجا بفرستید.\n"
        "💡 اگر پله‌ای با همان تعداد وجود داشته باشد، مبلغش به‌روزرسانی می‌شود.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ پایان", callback_data="ms_done")],
        ]),
    )
    await safe_answer(callback)


@dp.callback_query(F.data == "ms_done")
async def admin_milestones_done(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    user_states.pop(callback.from_user.id, None)
    await safe_answer(callback, "✅ پایان")
    await admin_milestones(callback)


@dp.callback_query(F.data == "ms_top")
async def admin_milestones_top(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    counts = {}
    for u in USERS.values():
        ref = u.get("referred_by")
        if ref:
            counts[int(ref)] = counts.get(int(ref), 0) + 1
    top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:15]

    text = "📊 <b>برترین دعوت‌کننده‌ها</b>\n\n"
    if not top:
        text += "❕ هنوز هیچ دعوتی ثبت نشده است."
    else:
        for i, (uid, cnt) in enumerate(top, 1):
            info = USERS.get(str(uid), {})
            name = info.get("name") or info.get("username") or str(uid)
            claimed = info.get("milestones_claimed", []) or []
            paid = sum(
                int(t["reward"]) for t in milestone_tiers()
                if int(t["count"]) in [int(c) for c in claimed]
            )
            text += (f"{i}. {esc(name)} (<code>{uid}</code>)\n"
                     f"   👥 {cnt} دعوت · 🏆 پاداش گرفته: {paid:,} تومان\n")

    await safe_edit(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 برگشت", callback_data="admin_milestones")],
    ]))
    await safe_answer(callback)


@dp.message(lambda m: user_states.get(m.from_user.id, {}).get("ms_add") is True)
async def admin_milestones_add_message(message: Message):
    """دریافت پله‌ها از ادمین: هر خط «تعداد - مبلغ»."""
    admin_id = message.from_user.id
    if not is_admin(admin_id):
        return
    raw = (message.text or "").strip()
    if not raw:
        await message.reply("❌ لطفاً به شکل <code>10 - 100000</code> بفرستید.", parse_mode=ParseMode.HTML)
        return

    conf = milestones_conf()
    tiers = {int(t["count"]): int(t["reward"]) for t in conf.get("tiers", []) if t.get("count")}
    added, failed = 0, 0

    for line in raw.split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = re.split(r"[-–—:,\s]+", line)
        nums = [parse_int(p) for p in parts if parse_int(p) is not None]
        if len(nums) >= 2 and nums[0] > 0 and nums[1] > 0:
            tiers[int(nums[0])] = int(nums[1])
            added += 1
        else:
            failed += 1

    if not added:
        await message.reply("❌ خطی معتبر پیدا نشد. نمونه: <code>10 - 100000</code>", parse_mode=ParseMode.HTML)
        return

    conf["tiers"] = [{"count": c, "reward": r} for c, r in sorted(tiers.items())]
    save_settings()

    summary = "\n".join(
        f"👥 {t['count']} دعوت → 💰 {t['reward']:,} تومان" for t in conf["tiers"]
    )
    warn = f"\n⚠️ {failed} خط نامعتبر رد شد." if failed else ""
    await message.answer(
        f"✅ <b>{added} پله ثبت شد</b>{warn}\n\n<b>پله‌های فعلی:</b>\n{summary}",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ پایان", callback_data="ms_done")],
        ]),
    )


# =============== 📢 عضویت اجباری ===============
@dp.callback_query(F.data == "admin_forcejoin")
async def admin_forcejoin(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    user_states.pop(callback.from_user.id, None)
    enabled = SETTINGS.get("force_join_enabled", True)
    channels = get_force_channels()
    text = (
        "📢 <b>عضویت اجباری</b>\n\n"
        f"⚙️ وضعیت: {'🟢 فعال' if enabled else '🔴 غیرفعال'}\n"
        f"📋 تعداد کانال‌ها: {len(channels)}\n"
    )
    if channels:
        for i, ch in enumerate(channels, 1):
            text += f"{i}. {esc(ch)}\n"
    else:
        text += "\n(هیچ کانالی اضافه نشده است)\n"
    text += "\n💡 کاربر برای دریافت تست یا خرید کانفیگ باید عضو این کانال(ها) باشد."
    buttons = [
        [InlineKeyboardButton(text="➕ افزودن کانال", callback_data="forcejoin_add")],
        [InlineKeyboardButton(
            text="🔴 غیرفعال کردن عضویت اجباری" if enabled else "🟢 فعال کردن عضویت اجباری",
            callback_data="forcejoin_toggle",
        )],
    ]
    for i, ch in enumerate(channels):
        buttons.append([InlineKeyboardButton(text=f"🗑 حذف {ch}", callback_data=f"forcejoindel_{i}")])
    buttons.append([InlineKeyboardButton(text="🔙 برگشت به پنل", callback_data="admin_panel")])
    await safe_edit(callback, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await safe_answer(callback)


@dp.callback_query(F.data == "forcejoin_toggle")
async def admin_forcejoin_toggle(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    SETTINGS["force_join_enabled"] = not SETTINGS.get("force_join_enabled", True)
    save_settings()
    state_fa = "فعال 🟢" if SETTINGS["force_join_enabled"] else "غیرفعال 🔴"
    await safe_answer(callback, f"📢 عضویت اجباری: {state_fa}", show_alert=True)
    await admin_forcejoin(callback)


@dp.callback_query(F.data == "forcejoin_add")
async def admin_forcejoin_add(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    user_states[callback.from_user.id] = {"forcejoin_add": True}
    await safe_edit(
        callback,
        "➕ <b>افزودن کانال عضویت اجباری</b>\n\n"
        "📝 یوزرنیم یا آیدی کانال را بفرستید.\n"
        "مثال: <code>@mychannel</code> یا <code>-1001234567890</code>\n\n"
        "⚠️ ربات باید در آن کانال عضو (و ترجیحاً ادمین) باشد تا بتواند عضویت کاربر را بررسی کند.",
        reply_markup=get_cancel_keyboard("admin_forcejoin"),
    )
    await safe_answer(callback)


@dp.message(lambda m: user_states.get(m.from_user.id, {}).get("forcejoin_add") is True)
async def admin_forcejoin_add_message(message: Message):
    """افزودن کانال عضویت اجباری از پیام ادمین."""
    admin_id = message.from_user.id
    if not is_admin(admin_id):
        return
    ch = (message.text or "").strip()
    if not ch:
        await message.reply("❌ یوزرنیم/آیدی کانال را بفرستید.")
        return
    if not (ch.startswith("@") or ch.startswith("http") or ch.lstrip("-").isdigit()):
        ch = "@" + ch
    SETTINGS.setdefault("force_join_channels", [])
    if ch in SETTINGS["force_join_channels"]:
        user_states.pop(admin_id, None)
        await message.answer("⚠️ این کانال قبلاً اضافه شده است.", reply_markup=get_admin_keyboard())
        return
    SETTINGS["force_join_channels"].append(ch)
    save_settings()
    user_states.pop(admin_id, None)
    await message.answer(f"✅ کانال {esc(ch)} به عضویت اجباری اضافه شد.",
                         reply_markup=get_admin_keyboard(), parse_mode=ParseMode.HTML)


@dp.callback_query(F.data.startswith("forcejoindel_"))
async def admin_forcejoin_delete(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await safe_answer(callback, "⛔ دسترسی ندارید", show_alert=True)
        return
    idx = parse_int(callback.data.split("_", 1)[1])
    channels = get_force_channels()
    if idx is None or idx < 0 or idx >= len(channels):
        await safe_answer(callback, "❌ یافت نشد", show_alert=True)
        return
    removed = channels.pop(idx)
    SETTINGS["force_join_channels"] = channels
    save_settings()
    await safe_answer(callback, f"🗑 {removed} حذف شد")
    await admin_forcejoin(callback)


# ==================================================================
# هندلر fallback — هر پیام دیگر
# ==================================================================
# =============== فروش خودکار پنل نمایندگی سنایی ===============
sale_quotes = {}
sale_lock = asyncio.Lock()


def sales_wallet():
    return WalletSales(
        USERS, lambda users: save_json(FILES["users"], users),
        os.environ.get("RESELLER_FERNET_KEY", ""),
    )


def reseller_prices():
    return SETTINGS.setdefault("reseller_prices", {})


def sales_markup(rows, back="back_to_main"):
    rows.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data=back)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def panel_details(api, ledger, order):
    return (
        f"✅ <b>پنل نمایندگی آماده است</b>\n"
        f"📊 حجم اولیه: {order['quota']:,} گیگ\n"
        f"👤 نام کاربری: <code>{esc(order['username'])}</code>\n"
        f"🔑 رمز اولیه: <code>{esc(ledger.password(order))}</code>\n"
        f"🔗 <a href=\"{esc(api.login_url(order['username']))}\">ورود به پنل نمایندگی</a>"
    )


async def deliver_panel(api, ledger, uid, ref):
    order = ledger.orders(uid)[ref]
    if order["state"] == "pending":
        try:
            result = await api.provision(ref, order, ledger.password(order))
        except PlanUnavailable:
            ledger.refund(uid, ref)
            try:
                await bot.send_message(uid, "این پلن دیگر فعال نیست. مبلغ به کیف پول برگشت.")
            except Exception:
                logger.warning("Could not notify customer of refund: %s", ref)
            return "مبلغ سفارش به کیف پول برگشت."
        order, _ = ledger.complete(uid, ref, result)

    if order["state"] == "ready":
        text = panel_details(api, ledger, order)
        for field, recipient, message in (
            ("buyer_notified", uid, text),
            ("owner_notified", SUPER_ADMIN_ID, f"🧾 سفارش {ref}\nخریدار: <code>{uid}</code>\n{text}"),
        ):
            if order.get(field):
                continue
            try:
                await bot.send_message(recipient, message, protect_content=True)
            except Exception:
                logger.warning("Could not send delegated order notification: %s", ref)
                continue
            user = copy.deepcopy(USERS[str(uid)])
            user["reseller_orders"][ref][field] = True
            ledger._commit(uid, user)
        return "پنل آماده است. جزئیات در «پنل‌های من» ثبت شد."
    return "مبلغ سفارش به کیف پول برگشته است."


async def recover_panel_orders():
    while True:
        try:
            api, ledger = SalesAPI.from_env(), sales_wallet()
            for uid, user in list(USERS.items()):
                refs = [
                    ref for ref, order in user.get("reseller_orders", {}).items()
                    if order["state"] == "pending"
                    or (order["state"] == "ready"
                        and not (order.get("buyer_notified") and order.get("owner_notified")))
                ]
                for ref in refs:
                    try:
                        async with sale_lock:
                            await deliver_panel(api, ledger, int(uid), ref)
                    except (SalesError, KeyError, TypeError):
                        logger.warning("Delegated order is still pending delivery: %s", ref)
        except SalesError:
            logger.warning("Sanaei sales settings are unavailable.")
        await asyncio.sleep(45)


@dp.callback_query((F.data == "buy_service") | F.data.startswith("rsstore:"))
async def sell_reseller_panel(callback: CallbackQuery):
    uid = callback.from_user.id
    if uid in BLACKLIST or not SETTINGS.get("shop_open", True):
        return await safe_answer(callback, "فروشگاه در دسترس نیست.", show_alert=True)
    if await force_join_gate(callback, callback.data):
        return
    offset = max(0, parse_int(callback.data.split(":", 1)[-1]) or 0)
    try:
        catalog = await SalesAPI.from_env().catalog()
    except SalesError:
        return await safe_answer(callback, "فهرست فروش در دسترس نیست.", show_alert=True)
    rows = []
    quotes = {}
    available = [p for p in catalog["plans"] if reseller_prices().get(str(p["id"]), 0) > 0]
    for plan in available[offset:offset + 15]:
        price = reseller_prices().get(str(plan["id"]), 0)
        if price > 0 and catalog["groupId"] > 0:
            ref = uuid.uuid4().hex
            quotes[ref] = {"plan": plan["id"], "quota": plan["quotaGiB"],
                           "name": plan["name"], "price": price, "group": catalog["groupId"]}
            rows.append([InlineKeyboardButton(
                text=f"📦 {plan['name'][:42]} | {plan['quotaGiB']:,} گیگ | {price:,} تومان",
                callback_data=f"rsquote:{ref}",
            )])
    if offset:
        rows.append([InlineKeyboardButton(text="قبلی", callback_data=f"rsstore:{max(0, offset - 15)}")])
    if offset + 15 < len(available):
        rows.append([InlineKeyboardButton(text="بعدی", callback_data=f"rsstore:{offset + 15}")])
    sale_quotes[uid] = quotes
    await safe_edit(callback, "📦 <b>خرید پنل نمایندگی</b>\n"
                    + ("پلن موردنظر را انتخاب کنید." if rows else "فعلاً پلن فعالی برای فروش وجود ندارد."),
                    reply_markup=sales_markup(rows))
    await safe_answer(callback)


@dp.callback_query(F.data.startswith("rsquote:"))
async def confirm_reseller_quote(callback: CallbackQuery):
    uid = callback.from_user.id
    ref = callback.data.split(":", 1)[1]
    quote = sale_quotes.get(uid, {}).get(ref)
    if quote is None or uid in BLACKLIST or not SETTINGS.get("shop_open", True):
        return await safe_answer(callback, "لطفاً فروشگاه را دوباره باز کنید.", show_alert=True)
    balance = get_user(uid)["balance"]
    rows = [[InlineKeyboardButton(text="✅ پرداخت از کیف پول", callback_data=f"rsbuy:{ref}")]]
    await safe_edit(callback,
                    f"📦 <b>{esc(quote['name'])}</b> | {quote['quota']:,} گیگ\n"
                    f"💰 مبلغ: {quote['price']:,} تومان\n💳 موجودی: {balance:,} تومان",
                    reply_markup=sales_markup(rows, "buy_service"))
    await safe_answer(callback)


@dp.callback_query(F.data.startswith("rsbuy:"))
async def pay_reseller_wallet(callback: CallbackQuery):
    uid = callback.from_user.id
    ref = callback.data.split(":", 1)[1]
    if uid in BLACKLIST or not SETTINGS.get("shop_open", True):
        return await safe_answer(callback, "فروشگاه در دسترس نیست.", show_alert=True)
    if await force_join_gate(callback, callback.data):
        return
    await safe_answer(callback)
    try:
        async with sale_lock:
            api, ledger = SalesAPI.from_env(), sales_wallet()
            get_user(uid)
            if ref not in ledger.orders(uid):
                quote = sale_quotes.get(uid, {}).get(ref)
                if not quote or reseller_prices().get(str(quote["plan"])) != quote["price"]:
                    await callback.message.answer("قیمت یا انتخاب شما تغییر کرده. فروشگاه را دوباره باز کنید.")
                    return
                ledger.reserve(uid, ref, quote)
            status = await deliver_panel(api, ledger, uid, ref)
    except InsufficientFunds:
        status = "موجودی کافی نیست. از «افزایش موجودی» استفاده کنید."
    except (SalesError, KeyError, TypeError):
        pending = USERS.get(str(uid), {}).get("reseller_orders", {}).get(ref)
        status = ("پرداخت ثبت شد و بات وضعیت سفارش را دوباره بررسی می‌کند."
                  if pending else "پرداخت ثبت نشد. بعداً دوباره امتحان کنید.")
    await callback.message.answer(status, reply_markup=get_main_keyboard(is_admin(uid), uid))


@dp.callback_query(F.data.startswith("rspanels:"))
async def reseller_panels(callback: CallbackQuery):
    uid = callback.from_user.id
    if uid in BLACKLIST:
        return await safe_answer(callback, "دسترسی مسدود است.", show_alert=True)
    index = parse_int(callback.data.split(":", 1)[1]) or 0
    get_user(uid)
    orders = list(USERS[str(uid)].get("reseller_orders", {}).items())[::-1]
    index = max(0, min(index, max(len(orders) - 1, 0)))
    labels = {"ready": "آماده", "pending": "در حال بررسی", "refunded": "بازپرداخت"}
    rows = [[InlineKeyboardButton(
        text=f"📦 {order['name'][:35]} | {order['quota']:,} گیگ | {labels[order['state']]}",
        callback_data=f"rsview:{ref}",
    )] for ref, order in orders[index:index + 12]]
    if index:
        rows.append([InlineKeyboardButton(text="قبلی", callback_data=f"rspanels:{max(index-12, 0)}")])
    if index + 12 < len(orders):
        rows.append([InlineKeyboardButton(text="بعدی", callback_data=f"rspanels:{index+12}")])
    await safe_edit(callback, "📁 <b>پنل‌های من</b>" if orders else "هنوز پنلی نخریدید.",
                    reply_markup=sales_markup(rows))
    await safe_answer(callback)


@dp.callback_query(F.data == "my_configs")
async def open_reseller_panels(callback: CallbackQuery):
    await reseller_panels(callback.model_copy(update={"data": "rspanels:0"}))


@dp.callback_query(F.data.startswith("rsview:"))
async def see_reseller_panel(callback: CallbackQuery):
    uid = callback.from_user.id
    ref = callback.data.split(":", 1)[1]
    order = USERS.get(str(uid), {}).get("reseller_orders", {}).get(ref)
    if uid in BLACKLIST or not order:
        return await safe_answer(callback, "سفارش در دسترس نیست.", show_alert=True)
    if order["state"] != "ready":
        return await safe_answer(callback, "سفارش هنوز آماده نیست یا بازپرداخت شده.", show_alert=True)
    try:
        text = panel_details(SalesAPI.from_env(), sales_wallet(), order)
        await callback.message.answer(text, protect_content=True)
        await safe_answer(callback)
    except SalesError:
        await safe_answer(callback, "جزئیات ورود در دسترس نیست.", show_alert=True)


def admin_sales_launch():
    return [
        [InlineKeyboardButton(text="📦 پلن‌های نمایندگی", callback_data="rsadminplans"),
         InlineKeyboardButton(text="📊 گزارش نماینده‌ها", callback_data="rsreport:0")],
    ]


@dp.callback_query(F.data == "rsadminplans")
async def reseller_admin_plans(callback: CallbackQuery):
    uid = callback.from_user.id
    if not is_admin(uid):
        return await safe_answer(callback, "دسترسی ندارید.", show_alert=True)
    try:
        catalog = await SalesAPI.from_env().catalog()
    except SalesError:
        return await safe_answer(callback, "اتصال به سنایی برقرار نشد.", show_alert=True)
    rows = [[InlineKeyboardButton(text="➕ افزودن پلن", callback_data="rssetup:plan"),
             InlineKeyboardButton(text="👥 گروه فروش", callback_data="rssetup:group")]]
    groups = {int(g["ID"]): g["Name"] for g in catalog["groups"]}
    text = f"📦 <b>پلن‌های فروش</b>\nگروه: {esc(groups.get(catalog['groupId'], 'تنظیم نشده'))}"
    for plan in catalog["plans"][:20]:
        price = reseller_prices().get(str(plan["id"]), 0)
        text += f"\n{plan['id']} | {esc(plan['name'])} | {plan['quotaGiB']} گیگ | {price:,} تومان"
    rows.append([InlineKeyboardButton(text="💰 تنظیم قیمت یا توقف فروش", callback_data="rssetup:price")])
    await safe_edit(callback, text, reply_markup=sales_markup(rows, "admin_panel"))
    await safe_answer(callback)


@dp.callback_query(F.data.startswith("rssetup:"))
async def reseller_admin_setup(callback: CallbackQuery):
    uid = callback.from_user.id
    if not is_admin(uid):
        return await safe_answer(callback, "دسترسی ندارید.", show_alert=True)
    mode = callback.data.split(":", 1)[1]
    prompts = {
        "plan": "نام | حجم گیگ (حداقل ۱۰۰) | قیمت تومان\nمثلاً: نمایندگی ۱۵۰ | ۱۵۰ | ۵۰۰۰۰۰",
        "group": "اسم دقیق یا شناسهٔ گروه سنایی را بفرستید. مثال: forosh",
        "price": "شناسهٔ پلن | قیمت تومان\nبرای خارج کردن از فروش قیمت را ۰ بگذارید.",
    }
    if mode not in prompts:
        return await safe_answer(callback)
    user_states[uid] = {"reseller_admin": mode}
    await safe_edit(callback, prompts[mode], reply_markup=sales_markup([], "rsadminplans"))
    await safe_answer(callback)


@dp.callback_query(F.data.startswith("rsreport:"))
async def reseller_admin_reports(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await safe_answer(callback, "دسترسی ندارید.", show_alert=True)
    after = parse_int(callback.data.split(":", 1)[1]) or 0
    try:
        accounts = await SalesAPI.from_env().request("GET", "/accounts", params={"after": after})
    except SalesError:
        return await safe_answer(callback, "گزارش سنایی در دسترس نیست.", show_alert=True)
    page = accounts[:12]
    text = "📊 <b>گزارش نماینده‌ها</b>\nشناسه | نام کاربری | مصرف / سقف (گیگ)"
    for row in page:
        text += (f"\n{row['id']} | {esc(row['username'])} | "
                 f"{row['usedBytes'] / 1024**3:.1f} / {row['quotaBytes'] / 1024**3:.0f}")
    rows = [[InlineKeyboardButton(text="＋ / − تغییر حجم", callback_data="rsquota")]]
    if len(accounts) > len(page):
        rows.append([InlineKeyboardButton(text="بعدی", callback_data=f"rsreport:{page[-1]['id']}")])
    if after:
        rows.append([InlineKeyboardButton(text="صفحهٔ اول", callback_data="rsreport:0")])
    await safe_edit(callback, text, reply_markup=sales_markup(rows, "admin_panel"))
    await safe_answer(callback)


@dp.callback_query(F.data == "rsquota")
async def reseller_quota_prompt(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return await safe_answer(callback, "دسترسی ندارید.", show_alert=True)
    user_states[callback.from_user.id] = {"reseller_admin": "quota"}
    await safe_edit(callback, "شناسهٔ نماینده | سقف فعلی به گیگ | تغییر حجم\n"
                    "مثال: <code>21 | 150 | +50</code> یا <code>21 | 150 | -20</code>",
                    reply_markup=sales_markup([], "rsreport:0"))
    await safe_answer(callback)


@dp.message(lambda m: m.from_user and "reseller_admin" in user_states.get(m.from_user.id, {}))
async def reseller_admin_input(message: Message):
    uid = message.from_user.id
    if not is_admin(uid):
        return
    mode = user_states.pop(uid)["reseller_admin"]
    if not message.text:
        return await message.answer("لطفاً مقدارها را به صورت متن بفرستید.")
    fields = [part.strip() for part in message.text.split("|")]
    try:
        api = SalesAPI.from_env()
        if mode == "plan":
            name, quota, price = fields
            quota, price = int(quota), int(price)
            if not 1 <= len(name) <= 100 or not 100 <= quota <= 1_000_000 or not 0 < price <= 10**12:
                raise ValueError
            plan = await api.create_plan(name, quota)
            set_reseller_price(int(plan["id"]), price)
        elif mode == "group":
            catalog = await api.catalog()
            matches = [int(g["ID"]) for g in catalog["groups"]
                       if fields == [str(g["ID"])] or fields[0].casefold() == g["Name"].casefold()]
            if len(fields) != 1 or len(matches) != 1:
                raise ValueError
            await api.request("PUT", "/settings", json={"groupId": matches[0]})
        elif mode == "price":
            plan, price = map(int, fields)
            if not 0 <= price <= 10**12 or not any(p["id"] == plan for p in (await api.catalog())["plans"]):
                raise ValueError
            set_reseller_price(plan, price)
        else:
            account, current, delta = map(int, fields)
            if account <= 0 or not 1 <= current <= 1_000_000 or not 1 <= current + delta <= 1_000_000 or not delta:
                raise ValueError
            await api.request("PUT", f"/accounts/{account}/quota", json={
                "expectedQuotaGiB": current, "quotaGiB": current + delta,
            })
    except (SalesError, ValueError, KeyError, TypeError):
        await message.answer("تغییر تأیید نشد. داده‌ها و آخرین وضعیت سنایی را بررسی کنید.",
                             reply_markup=sales_markup([], "admin_panel"))
        return
    await message.answer("✅ تغییر ثبت شد.", reply_markup=sales_markup([], "admin_panel"))


def set_reseller_price(plan, price):
    updated = {**reseller_prices(), str(plan): price}
    if not save_json(FILES["settings"], {**SETTINGS, "reseller_prices": updated}):
        raise SalesError("Could not persist the plan price.")
    SETTINGS["reseller_prices"] = updated


async def private_sales_middleware(handler, event, data):
    message = event.message if isinstance(event, CallbackQuery) else event
    if not message or message.chat.type != "private":
        if isinstance(event, CallbackQuery):
            await safe_answer(event, "ربات را در چت خصوصی باز کنید.", show_alert=True)
        return
    if isinstance(event, CallbackQuery):
        callback = event.data or ""
        if callback in {"pay_balance", "pay_card", "get_test_service", "apply_coupon", "admin_plans", "admin_testpool",
                        "admin_configpool"} or callback.startswith(("buyplan_", "buypkg_")):
            return await safe_answer(event, "از منوی فروش پنل نمایندگی استفاده کنید.", show_alert=True)
        if callback in {"admin_panel", "back_to_main", "rsadminplans", "rsquota"} or callback.startswith(("rssetup:", "rsreport:")):
            user_states.pop(event.from_user.id, None)
    return await handler(event, data)


dp.message.outer_middleware(private_sales_middleware)
dp.callback_query.outer_middleware(private_sales_middleware)


@dp.message()
async def fallback_handler(message: Message):
    user_id = message.from_user.id
    if user_id in BLACKLIST:
        return
    # اگر کاربر در حالتی نیست، منوی اصلی را نشان بده
    if user_states.get(user_id):
        return
    await message.answer(
        "🚀 از منوی اصلی استفاده کنید:",
        reply_markup=get_main_keyboard(is_admin(user_id), user_id),
    )


# ==================================================================
# 🚀 اجرای ربات
# ==================================================================
async def on_startup():
    try:
        me = await bot.get_me()
        logger.info(f"🤖 ربات روشن شد: @{me.username}")
        for admin_id in get_admin_ids():
            try:
                await bot.send_message(admin_id, "🚀 <b>ربات روشن شد و آنلاین است.</b>",
                                       parse_mode=ParseMode.HTML)
            except Exception:
                pass
    except Exception as e:
        logger.error(f"خطا در استارتاپ: {e}")


async def main():
    if not BOT_TOKEN or BOT_TOKEN == "PUT_YOUR_BOT_TOKEN_HERE":
        raise SystemExit("❌ لطفاً BOT_TOKEN را در بالای فایل تنظیم کنید!")
    SalesAPI.from_env()
    sales_wallet()
    process_lock = sqlite3.connect(os.path.join(DATA_DIR, "process-lock.sqlite3"), timeout=0)
    try:
        process_lock.execute("BEGIN IMMEDIATE")
        await on_startup()
        recovery = asyncio.create_task(recover_panel_orders())
        try:
            await dp.start_polling(bot)
        finally:
            recovery.cancel()
            await asyncio.gather(recovery, return_exceptions=True)
    finally:
        process_lock.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("⛔ ربات خاموش شد")
