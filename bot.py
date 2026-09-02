import os
import sqlite3
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# ---------- CONFIG ----------
BOT_TOKEN = "8626184976:AAE-0P4GMhObXUfMWcpAff36CdwsDDBCayI"
ADMIN_ID = 8745088070
REFERRAL_REWARD = 2
DB_PATH = "xyvenstars.db"

# ---------- DATABASE ----------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                joined_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                balance INTEGER DEFAULT 0,
                total_earned INTEGER DEFAULT 0,
                invited_count INTEGER DEFAULT 0,
                active_count INTEGER DEFAULT 0,
                stars_from_referrals INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER,
                referred_id INTEGER UNIQUE,
                join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                type TEXT,
                amount INTEGER,
                description TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS rewards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE,
                cost INTEGER,
                description TEXT,
                is_active INTEGER DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                reward_id INTEGER,
                status TEXT DEFAULT 'pending',
                request_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS withdrawals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount INTEGER,
                reward_name TEXT,
                status TEXT DEFAULT 'pending',
                request_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                admin_note TEXT,
                approved_date TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS giveaways (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                prize TEXT,
                condition TEXT,
                winners_count INTEGER DEFAULT 1,
                end_date TIMESTAMP,
                status TEXT DEFAULT 'active'
            );
            CREATE TABLE IF NOT EXISTS giveaway_participants (
                giveaway_id INTEGER,
                user_id INTEGER,
                PRIMARY KEY (giveaway_id, user_id)
            );
        """)
        # Insert default rewards
        default_rewards = [
            ("Teddy", 15, "🧸 Cute Teddy Gift"),
            ("Special Gift", 20, "🎁 Surprise Gift"),
            ("Diamond", 150, "💎 Shiny Diamond"),
            ("Ring", 150, "💍 Elegant Ring"),
        ]
        for name, cost, desc in default_rewards:
            conn.execute("INSERT OR IGNORE INTO rewards (name, cost, description) VALUES (?, ?, ?)", (name, cost, desc))
        conn.commit()

init_db()

# ---------- HELPERS ----------
def get_user(user_id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if not row:
        return None
    user = dict(row)
    # Admin gets unlimited Stars
    if user_id == ADMIN_ID:
        user['balance'] = 999999999  # effectively unlimited
    return user

def create_user(user_id, username="", first_name=""):
    with get_db() as conn:
        conn.execute("INSERT OR IGNORE INTO users (user_id, username, first_name) VALUES (?, ?, ?)", (user_id, username, first_name))

def add_transaction(user_id, ttype, amount, desc):
    with get_db() as conn:
        conn.execute("INSERT INTO transactions (user_id, type, amount, description) VALUES (?, ?, ?, ?)", (user_id, ttype, amount, desc))

def update_balance(user_id, delta):
    # For admin, we ignore balance updates (keep unlimited)
    if user_id == ADMIN_ID:
        return
    with get_db() as conn:
        conn.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (delta, user_id))
        if delta > 0:
            conn.execute("UPDATE users SET total_earned = total_earned + ? WHERE user_id = ?", (delta, user_id))

def is_admin(user_id):
    return user_id == ADMIN_ID

# ---------- CONVERSATION STATES ----------
RECIPIENT, AMOUNT = range(2)

# ---------- MAIN MENU ----------
async def main_menu(update, context):
    query = update.callback_query
    if query:
        await query.answer()
        user_id = query.from_user.id
        msg = query.message
    else:
        user_id = update.effective_user.id
        msg = update.message

    create_user(user_id, update.effective_user.username or "", update.effective_user.first_name or "")

    keyboard = [
        [InlineKeyboardButton("💼 My Balance", callback_data="balance"),
         InlineKeyboardButton("👥 Invite Friends", callback_data="invite")],
        [InlineKeyboardButton("💰 Earn Stars", callback_data="earn"),
         InlineKeyboardButton("🎁 Gift Store", callback_data="gifts")],
        [InlineKeyboardButton("🎉 Giveaways", callback_data="giveaways"),
         InlineKeyboardButton("ℹ️ How It Works", callback_data="howto")],
        [InlineKeyboardButton("⭐ Gift Stars", callback_data="gift_start"),
         InlineKeyboardButton("👤 Profile", callback_data="profile")]
    ]
    text = "🌟 *XyvenStars*\n\nWelcome to XyvenStars ⭐\n\nEarn Stars by inviting friends, completing available tasks and participating in giveaways.\n\nCollect Stars and exchange them for Telegram gifts."
    if query:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ---------- PROFILE ----------
async def profile(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = get_user(user_id)
    if not user:
        await query.edit_message_text("User not found.")
        return
    text = f"👤 *Profile*\n\n🆔 ID: `{user['user_id']}`\n👤 Name: {user['first_name'] or 'N/A'}\n📅 Joined: {user['joined_date'][:10]}\n\n⭐ Balance: {user['balance']}\n⭐ Total Earned: {user['total_earned']}\n\n👥 Invited: {user['invited_count']}\n✅ Active: {user['active_count']}\n⭐ From Referrals: {user['stars_from_referrals']}"
    keyboard = [
        [InlineKeyboardButton("📜 Transaction History", callback_data="history")],
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ---------- BALANCE ----------
async def balance(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = get_user(user_id)
    if not user:
        await query.edit_message_text("User not found.")
        return
    text = f"⭐ *Your Balance*\n\nCurrent Balance: {user['balance']} ⭐\nTotal Earned: {user['total_earned']} ⭐"
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ---------- INVITE ----------
async def invite(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = get_user(user_id)
    bot_username = context.bot.username
    link = f"https://t.me/{bot_username}?start={user_id}"
    text = f"👥 *Referral Program*\n\nYour referral link:\n`{link}`\n\n⭐ Earn {REFERRAL_REWARD} Stars for every successful referral.\n\n📊 Your Statistics:\n👥 Invited: {user['invited_count']}\n⭐ Earned from referrals: {user['stars_from_referrals']} ⭐"
    keyboard = [
        [InlineKeyboardButton("🔗 Share With Friends", switch_inline_query=link)],
        [InlineKeyboardButton("🏆 Leaderboard", callback_data="leaderboard")],
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ---------- EARN ----------
async def earn(update, context):
    query = update.callback_query
    await query.answer()
    text = "💰 *Earn Stars*\n\n✅ Invite friends (+2 ⭐ per active referral)\n✅ Participate in giveaways\n✅ Daily bonuses (coming soon)"
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ---------- GIFT STORE ----------
async def gifts(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = get_user(user_id)
    with get_db() as conn:
        rewards = conn.execute("SELECT * FROM rewards WHERE is_active = 1 ORDER BY cost").fetchall()
    if not rewards:
        await query.edit_message_text("No gifts available.")
        return
    text = "🎁 *Gift Store*\n\nExchange your ⭐ Stars for Telegram gifts:\n\n"
    keyboard = []
    for r in rewards:
        text += f"{r['description']} — {r['cost']} ⭐\n"
        keyboard.append([InlineKeyboardButton(f"Claim {r['name']}", callback_data=f"claim_{r['id']}")])
    text += f"\nYour balance: {user['balance']} ⭐"
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="main_menu")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ---------- CLAIM GIFT ----------
async def claim_gift(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    reward_id = int(query.data.split('_')[1])
    with get_db() as conn:
        reward = conn.execute("SELECT * FROM rewards WHERE id = ? AND is_active = 1", (reward_id,)).fetchone()
        user = conn.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if not reward:
        await query.edit_message_text("Gift not available.")
        return
    # Check balance (admin has unlimited, but we check anyway)
    if user['balance'] < reward['cost'] and user_id != ADMIN_ID:
        await query.edit_message_text("❌ Insufficient balance.")
        return
    # Deduct (for admin we don't deduct)
    if user_id != ADMIN_ID:
        with get_db() as conn:
            conn.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (reward['cost'], user_id))
    # Still record transaction
    with get_db() as conn:
        conn.execute("INSERT INTO orders (user_id, reward_id, status) VALUES (?, ?, 'approved')", (user_id, reward_id))
        conn.execute("INSERT INTO transactions (user_id, type, amount, description) VALUES (?, ?, ?, ?)", (user_id, 'gift_purchase', -reward['cost'] if user_id != ADMIN_ID else 0, f"Purchased {reward['name']}"))
    await query.edit_message_text(f"✅ You have successfully claimed **{reward['name']}**!", parse_mode="Markdown")

# ---------- GIVEAWAYS ----------
async def giveaways(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    with get_db() as conn:
        active = conn.execute("SELECT * FROM giveaways WHERE status = 'active' AND end_date > datetime('now')").fetchall()
    if not active:
        text = "🎉 No active giveaways at the moment."
    else:
        text = "🎉 *Active Giveaways*\n\n"
        for g in active:
            part = conn.execute("SELECT 1 FROM giveaway_participants WHERE giveaway_id = ? AND user_id = ?", (g['id'], user_id)).fetchone()
            status = "✅ Entered" if part else "➡️ /enter_" + str(g['id'])
            text += f"**{g['title']}**\nPrize: {g['prize']}\nCondition: {g['condition']}\nWinners: {g['winners_count']}\nEnds: {g['end_date'][:16]}\n{status}\n\n"
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ---------- LEADERBOARD ----------
async def leaderboard(update, context):
    query = update.callback_query
    await query.answer()
    with get_db() as conn:
        top = conn.execute("SELECT user_id, username, first_name, invited_count FROM users ORDER BY invited_count DESC LIMIT 10").fetchall()
    if not top:
        await query.edit_message_text("No referrals yet. Be the first!")
        return
    text = "🏆 *TOP REFERRERS*\n\n"
    medals = ["🥇", "🥈", "🥉"]
    for i, u in enumerate(top):
        medal = medals[i] if i < 3 else f"{i+1}."
        name = u['first_name'] or u['username'] or str(u['user_id'])
        text += f"{medal} {name} — {u['invited_count']} referrals\n"
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="invite")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ---------- TRANSACTION HISTORY ----------
async def history(update, context):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    with get_db() as conn:
        txns = conn.execute("SELECT type, amount, description, timestamp FROM transactions WHERE user_id = ? ORDER BY timestamp DESC LIMIT 20", (user_id,)).fetchall()
    if not txns:
        text = "📜 No transactions yet."
    else:
        text = "📜 *Recent Transactions*\n\n"
        for t in txns:
            sign = "+" if t['amount'] > 0 else ""
            text += f"{t['timestamp'][:16]} — {sign}{t['amount']} ⭐ ({t['description']})\n"
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="profile")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ---------- HOW IT WORKS ----------
async def howto(update, context):
    query = update.callback_query
    await query.answer()
    text = "ℹ️ *How It Works*\n\n1️⃣ Share your referral link with friends.\n2️⃣ They start the bot via your link.\n3️⃣ You automatically earn +2 ⭐ per new user.\n4️⃣ Use ⭐ to claim gifts from the Gift Store.\n5️⃣ Participate in giveaways for extra rewards!\n\nNo channel joining required – just share and earn!"
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ---------- GIFT STARS (Send Stars to Another User) ----------
async def gift_start(update, context):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "⭐ *Gift Stars*\n\n"
        "Enter the recipient's Telegram ID or @username.\n\n"
        "Example: `123456789` or `@username`\n"
        "Send /cancel to abort.",
        parse_mode="Markdown"
    )
    return RECIPIENT

async def gift_recipient(update, context):
    text = update.message.text.strip()
    if text.startswith('/cancel'):
        await update.message.reply_text("❌ Cancelled.")
        return ConversationHandler.END
    # Try to parse as user ID or username
    recipient = text
    # If it's a username, strip @
    if recipient.startswith('@'):
        recipient = recipient[1:]
    context.user_data['gift_recipient'] = recipient
    await update.message.reply_text("Now enter the amount of Stars you want to send:")
    return AMOUNT

async def gift_amount(update, context):
    text = update.message.text.strip()
    if text.startswith('/cancel'):
        await update.message.reply_text("❌ Cancelled.")
        return ConversationHandler.END
    try:
        amount = int(text)
        if amount <= 0:
            await update.message.reply_text("Amount must be positive.")
            return AMOUNT
    except ValueError:
        await update.message.reply_text("Please enter a valid number.")
        return AMOUNT

    sender_id = update.effective_user.id
    sender = get_user(sender_id)
    if not sender:
        await update.message.reply_text("You are not registered. Use /start first.")
        return ConversationHandler.END

    # Find recipient
    recipient_identifier = context.user_data['gift_recipient']
    with get_db() as conn:
        if recipient_identifier.isdigit():
            recipient_row = conn.execute("SELECT user_id FROM users WHERE user_id = ?", (int(recipient_identifier),)).fetchone()
        else:
            recipient_row = conn.execute("SELECT user_id FROM users WHERE LOWER(username) = LOWER(?)", (recipient_identifier,)).fetchone()
    if not recipient_row:
        await update.message.reply_text("❌ Recipient not found in database. They must have used the bot at least once.")
        return ConversationHandler.END
    recipient_id = recipient_row['user_id']

    if recipient_id == sender_id:
        await update.message.reply_text("❌ You cannot gift Stars to yourself.")
        return ConversationHandler.END

    # Check sender balance (admin has unlimited)
    if sender_id != ADMIN_ID and sender['balance'] < amount:
        await update.message.reply_text(f"❌ Insufficient balance. You have {sender['balance']} ⭐.")
        return ConversationHandler.END

    # Process transfer
    if sender_id != ADMIN_ID:
        update_balance(sender_id, -amount)
    else:
        # For admin, we don't deduct; but we record transaction with amount 0 for admin? We'll record a transaction with amount 0 but description.
        pass
    update_balance(recipient_id, amount)
    # Record transactions
    add_transaction(sender_id, 'gift_sent', -amount if sender_id != ADMIN_ID else 0, f"Gifted {amount} ⭐ to {recipient_id}")
    add_transaction(recipient_id, 'gift_received', amount, f"Received {amount} ⭐ from {sender_id}")

    await update.message.reply_text(
        f"✅ Successfully gifted {amount} ⭐ to user {recipient_id}!\n"
        f"Your new balance: {sender['balance'] if sender_id != ADMIN_ID else '∞'} ⭐"
    )
    # Notify recipient
    try:
        await context.bot.send_message(recipient_id, f"🎁 You received a gift of {amount} ⭐ from user {sender_id}!")
    except:
        pass

    return ConversationHandler.END

async def gift_cancel(update, context):
    await update.message.reply_text("❌ Gift cancelled.")
    return ConversationHandler.END

# ---------- ADMIN PANEL ----------
async def admin_panel(update, context):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Unauthorized.")
        return
    keyboard = [
        [InlineKeyboardButton("📊 Statistics", callback_data="admin_stats")],
        [InlineKeyboardButton("👥 Users", callback_data="admin_users")],
        [InlineKeyboardButton("🎁 Manage Gifts", callback_data="admin_gifts")],
        [InlineKeyboardButton("💸 Pending Withdrawals", callback_data="admin_withdrawals")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🎉 Giveaways", callback_data="admin_giveaways")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="admin_settings")],
    ]
    await update.message.reply_text("⚙️ *Admin Panel*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def admin_stats(update, context):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.edit_message_text("Unauthorized.")
        return
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total_refs = conn.execute("SELECT COUNT(*) FROM referrals").fetchone()[0]
        balance = conn.execute("SELECT SUM(balance) FROM users").fetchone()[0] or 0
        pending = conn.execute("SELECT COUNT(*) FROM withdrawals WHERE status='pending'").fetchone()[0]
    text = f"📊 *Statistics*\n\n👥 Total Users: {total}\n📨 Total Referrals: {total_refs}\n⭐ Total Stars: {balance}\n⏳ Pending Withdrawals: {pending}"
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="admin_back")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def admin_users(update, context):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.edit_message_text("Unauthorized.")
        return
    with get_db() as conn:
        users = conn.execute("SELECT user_id, username, first_name, balance, joined_date FROM users ORDER BY joined_date DESC LIMIT 20").fetchall()
    if not users:
        await query.edit_message_text("No users.")
        return
    text = "👥 *Recent Users*\n\n"
    for u in users:
        text += f"ID: {u['user_id']} | {u['first_name'] or 'N/A'} | ⭐{u['balance']}\n"
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="admin_back")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def admin_gifts(update, context):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.edit_message_text("Unauthorized.")
        return
    with get_db() as conn:
        rewards = conn.execute("SELECT * FROM rewards").fetchall()
    text = "🎁 *Manage Gifts*\n\n"
    for r in rewards:
        text += f"{r['name']} — {r['cost']} ⭐ ({'Active' if r['is_active'] else 'Inactive'})\n"
    text += "\nTo add: /addgift <name> <cost> <description>\nTo toggle: /togglegift <gift_id>"
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="admin_back")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def admin_withdrawals(update, context):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.edit_message_text("Unauthorized.")
        return
    with get_db() as conn:
        pending = conn.execute("SELECT * FROM withdrawals WHERE status='pending'").fetchall()
    if not pending:
        await query.edit_message_text("No pending withdrawals.")
        return
    text = "💸 *Pending Withdrawals*\n\n"
    for w in pending:
        text += f"User: {w['user_id']} | {w['amount']} ⭐ | {w['reward_name']} | {w['request_date'][:16]}\n"
        text += f"/approve_{w['user_id']}_{w['amount']} | /reject_{w['user_id']}_{w['amount']}\n\n"
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="admin_back")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def admin_broadcast(update, context):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.edit_message_text("Unauthorized.")
        return
    await query.edit_message_text("Send broadcast: /broadcast <message>")

async def admin_giveaways(update, context):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.edit_message_text("Unauthorized.")
        return
    await query.edit_message_text("🎉 *Giveaways*\n\n/create_giveaway <title> <prize> <condition> <winners> <end_date>")

async def admin_settings(update, context):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.edit_message_text("Unauthorized.")
        return
    await query.edit_message_text("⚙️ *Settings*\n\nReferral reward: 2 ⭐\nAdmin: 8745088070")

async def admin_back(update, context):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.edit_message_text("Unauthorized.")
        return
    await admin_panel(update, context)

# ---------- START WITH REFERRAL ----------
async def start(update, context):
    user_id = update.effective_user.id
    username = update.effective_user.username or ""
    first_name = update.effective_user.first_name or ""

    # Check if user already exists
    with get_db() as conn:
        existing = conn.execute("SELECT 1 FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if not existing:
        create_user(user_id, username, first_name)
        # Process referral if any
        if context.args and context.args[0].isdigit():
            referrer_id = int(context.args[0])
            if referrer_id != user_id:
                # Check if this user is already referred
                with get_db() as conn:
                    ref = conn.execute("SELECT 1 FROM referrals WHERE referred_id = ?", (user_id,)).fetchone()
                if not ref:
                    with get_db() as conn:
                        conn.execute("INSERT INTO referrals (referrer_id, referred_id) VALUES (?, ?)", (referrer_id, user_id))
                        # Credit referrer (except if referrer is admin? admin doesn't need stars but still count)
                        conn.execute("UPDATE users SET invited_count = invited_count + 1, stars_from_referrals = stars_from_referrals + ? WHERE user_id = ?", (REFERRAL_REWARD, referrer_id))
                        conn.execute("UPDATE users SET balance = balance + ?, total_earned = total_earned + ? WHERE user_id = ?", (REFERRAL_REWARD, REFERRAL_REWARD, referrer_id))
                    add_transaction(referrer_id, 'referral', REFERRAL_REWARD, f"Active referral from {user_id}")
                    await context.bot.send_message(referrer_id, f"✅ You earned {REFERRAL_REWARD} ⭐ for a new referral!")
    await main_menu(update, context)

# ---------- WITHDRAWAL COMMAND ----------
async def withdraw(update, context):
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text("Usage: /withdraw <amount> <reward_name>\nExample: /withdraw 50 GiftCard")
        return
    try:
        amount = int(context.args[0])
        reward_name = " ".join(context.args[1:]) if len(context.args) > 1 else "Withdrawal"
    except:
        await update.message.reply_text("Invalid format.")
        return
    user = get_user(user_id)
    if not user or user['balance'] < amount and user_id != ADMIN_ID:
        await update.message.reply_text("Insufficient balance.")
        return
    # Deduct (for admin we don't deduct, but still record)
    if user_id != ADMIN_ID:
        with get_db() as conn:
            conn.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, user_id))
    with get_db() as conn:
        conn.execute("INSERT INTO withdrawals (user_id, amount, reward_name, status) VALUES (?, ?, ?, 'pending')", (user_id, amount, reward_name))
        add_transaction(user_id, 'withdrawal', -amount if user_id != ADMIN_ID else 0, f"Withdrawal: {reward_name}")
    # Notify admin
    await context.bot.send_message(
        ADMIN_ID,
        f"🔔 *NEW WITHDRAWAL*\n\nUser: {user_id}\nAmount: {amount} ⭐\nReward: {reward_name}",
        parse_mode="Markdown"
    )
    await update.message.reply_text("✅ Withdrawal request submitted for admin approval.")

# ---------- ADMIN APPROVE / REJECT ----------
async def approve(update, context):
    if not is_admin(update.effective_user.id):
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /approve <user_id> <amount>")
        return
    try:
        user_id = int(context.args[0])
        amount = int(context.args[1])
    except:
        await update.message.reply_text("Invalid arguments.")
        return
    with get_db() as conn:
        conn.execute("UPDATE withdrawals SET status='approved', approved_date=datetime('now') WHERE user_id=? AND amount=? AND status='pending'", (user_id, amount))
    await update.message.reply_text(f"✅ Withdrawal for user {user_id} approved.")
    try:
        await context.bot.send_message(user_id, "✅ Your withdrawal has been approved.")
    except:
        pass

async def reject(update, context):
    if not is_admin(update.effective_user.id):
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /reject <user_id> <amount>")
        return
    try:
        user_id = int(context.args[0])
        amount = int(context.args[1])
    except:
        await update.message.reply_text("Invalid arguments.")
        return
    with get_db() as conn:
        # Refund balance (only if not admin)
        if user_id != ADMIN_ID:
            conn.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        conn.execute("UPDATE withdrawals SET status='rejected' WHERE user_id=? AND amount=? AND status='pending'", (user_id, amount))
        add_transaction(user_id, 'refund', amount if user_id != ADMIN_ID else 0, "Withdrawal rejected – stars refunded")
    await update.message.reply_text(f"❌ Withdrawal for user {user_id} rejected (refunded).")
    try:
        await context.bot.send_message(user_id, "❌ Your withdrawal was rejected. Stars have been refunded.")
    except:
        pass

# ---------- BROADCAST ----------
async def broadcast(update, context):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Usage: /broadcast <message>")
        return
    msg = " ".join(context.args)
    with get_db() as conn:
        users = conn.execute("SELECT user_id FROM users").fetchall()
    sent = 0
    for u in users:
        try:
            await context.bot.send_message(u['user_id'], f"📢 *Announcement*\n\n{msg}", parse_mode="Markdown")
            sent += 1
        except:
            pass
    await update.message.reply_text(f"✅ Broadcast sent to {sent} users.")

# ---------- ADD GIFT ----------
async def add_gift(update, context):
    if not is_admin(update.effective_user.id):
        return
    if len(context.args) < 3:
        await update.message.reply_text("Usage: /addgift <name> <cost> <description>")
        return
    name = context.args[0]
    try:
        cost = int(context.args[1])
    except:
        await update.message.reply_text("Cost must be a number.")
        return
    desc = " ".join(context.args[2:])
    with get_db() as conn:
        conn.execute("INSERT OR REPLACE INTO rewards (name, cost, description, is_active) VALUES (?, ?, ?, 1)", (name, cost, desc))
    await update.message.reply_text(f"✅ Gift added: {name} ({cost} ⭐)")

# ---------- TOGGLE GIFT ----------
async def toggle_gift(update, context):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Usage: /togglegift <gift_id>")
        return
    try:
        gid = int(context.args[0])
    except:
        await update.message.reply_text("Invalid ID.")
        return
    with get_db() as conn:
        curr = conn.execute("SELECT is_active FROM rewards WHERE id = ?", (gid,)).fetchone()
        if not curr:
            await update.message.reply_text("Gift not found.")
            return
        new_status = 0 if curr['is_active'] else 1
        conn.execute("UPDATE rewards SET is_active = ? WHERE id = ?", (new_status, gid))
    await update.message.reply_text(f"✅ Gift {gid} {'activated' if new_status else 'deactivated'}.")

# ---------- ENTER GIVEAWAY ----------
async def enter_giveaway(update, context):
    if not context.args:
        await update.message.reply_text("Usage: /enter_<giveaway_id>")
        return
    try:
        gid = int(context.args[0])
    except:
        await update.message.reply_text("Invalid ID.")
        return
    user_id = update.effective_user.id
    with get_db() as conn:
        giveaway = conn.execute("SELECT * FROM giveaways WHERE id = ? AND status='active' AND end_date > datetime('now')", (gid,)).fetchone()
        if not giveaway:
            await update.message.reply_text("This giveaway is not active.")
            return
        # Check if already entered
        part = conn.execute("SELECT 1 FROM giveaway_participants WHERE giveaway_id = ? AND user_id = ?", (gid, user_id)).fetchone()
        if part:
            await update.message.reply_text("You already entered this giveaway.")
            return
        conn.execute("INSERT INTO giveaway_participants (giveaway_id, user_id) VALUES (?, ?)", (gid, user_id))
    await update.message.reply_text("✅ You have entered the giveaway! Good luck!")

# ---------- CREATE GIVEAWAY ----------
async def create_giveaway(update, context):
    if not is_admin(update.effective_user.id):
        return
    if len(context.args) < 5:
        await update.message.reply_text("Usage: /create_giveaway <title> <prize> <condition> <winners_count> <end_date>")
        return
    title = context.args[0]
    prize = context.args[1]
    condition = context.args[2]
    try:
        winners = int(context.args[3])
        end_date = context.args[4]  # expects YYYY-MM-DD HH:MM
    except:
        await update.message.reply_text("Invalid winners or date format.")
        return
    with get_db() as conn:
        conn.execute("INSERT INTO giveaways (title, prize, condition, winners_count, end_date) VALUES (?, ?, ?, ?, ?)",
                     (title, prize, condition, winners, end_date))
    await update.message.reply_text("✅ Giveaway created successfully!")

# ---------- MAIN ----------
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", main_menu))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("withdraw", withdraw))
    app.add_handler(CommandHandler("approve", approve))
    app.add_handler(CommandHandler("reject", reject))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("addgift", add_gift))
    app.add_handler(CommandHandler("togglegift", toggle_gift))
    app.add_handler(CommandHandler("enter_giveaway", enter_giveaway))
    app.add_handler(CommandHandler("create_giveaway", create_giveaway))

    # Gift Conversation
    gift_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(gift_start, pattern="^gift_start$")],
        states={
            RECIPIENT: [MessageHandler(filters.TEXT & ~filters.COMMAND, gift_recipient)],
            AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, gift_amount)],
        },
        fallbacks=[CommandHandler("cancel", gift_cancel)],
    )
    app.add_handler(gift_conv)

    # Callbacks
    app.add_handler(CallbackQueryHandler(main_menu, pattern="^main_menu$"))
    app.add_handler(CallbackQueryHandler(profile, pattern="^profile$"))
    app.add_handler(CallbackQueryHandler(balance, pattern="^balance$"))
    app.add_handler(CallbackQueryHandler(invite, pattern="^invite$"))
    app.add_handler(CallbackQueryHandler(earn, pattern="^earn$"))
    app.add_handler(CallbackQueryHandler(gifts, pattern="^gifts$"))
    app.add_handler(CallbackQueryHandler(giveaways, pattern="^giveaways$"))
    app.add_handler(CallbackQueryHandler(leaderboard, pattern="^leaderboard$"))
    app.add_handler(CallbackQueryHandler(history, pattern="^history$"))
    app.add_handler(CallbackQueryHandler(howto, pattern="^howto$"))
    app.add_handler(CallbackQueryHandler(claim_gift, pattern="^claim_"))
    app.add_handler(CallbackQueryHandler(admin_stats, pattern="^admin_stats$"))
    app.add_handler(CallbackQueryHandler(admin_users, pattern="^admin_users$"))
    app.add_handler(CallbackQueryHandler(admin_gifts, pattern="^admin_gifts$"))
    app.add_handler(CallbackQueryHandler(admin_withdrawals, pattern="^admin_withdrawals$"))
    app.add_handler(CallbackQueryHandler(admin_broadcast, pattern="^admin_broadcast$"))
    app.add_handler(CallbackQueryHandler(admin_giveaways, pattern="^admin_giveaways$"))
    app.add_handler(CallbackQueryHandler(admin_settings, pattern="^admin_settings$"))
    app.add_handler(CallbackQueryHandler(admin_back, pattern="^admin_back$"))

    print("🤖 XyvenStars is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
