import os
import sqlite3
import json
import logging
import random
import string
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMember
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
CHANNEL_USERNAME = "xyvenstar"  # without '@'
CHANNEL_LINK = "https://t.me/xyvenstar"
REFERRAL_REWARD = 2  # stars per active referral
DEFAULT_REWARDS = [
    {"name": "Teddy", "cost": 15, "description": "🧸 Cute Teddy Gift"},
    {"name": "Special Gift", "cost": 20, "description": "🎁 Surprise Gift"},
    {"name": "Diamond", "cost": 150, "description": "💎 Shiny Diamond"},
    {"name": "Ring", "cost": 150, "description": "💍 Elegant Ring"},
]

# ---------- DATABASE ----------
DB_PATH = "xyvenstars.db"

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
                stars_from_referrals INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER,
                referred_id INTEGER UNIQUE,
                is_active BOOLEAN DEFAULT 0,
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
                is_active BOOLEAN DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                reward_id INTEGER,
                status TEXT DEFAULT 'pending',
                request_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completion_date TIMESTAMP,
                admin_note TEXT
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
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
        """)
        # Insert default rewards if not present
        for reward in DEFAULT_REWARDS:
            conn.execute(
                "INSERT OR IGNORE INTO rewards (name, cost, description) VALUES (?, ?, ?)",
                (reward['name'], reward['cost'], reward['description'])
            )
        conn.commit()

init_db()

# ---------- HELPERS ----------
def get_user(user_id: int) -> Optional[Dict]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    return dict(row) if row else None

def create_user(user_id: int, username: str = "", first_name: str = ""):
    with get_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (user_id, username, first_name) VALUES (?, ?, ?)",
            (user_id, username, first_name)
        )

def add_transaction(user_id: int, ttype: str, amount: int, desc: str):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO transactions (user_id, type, amount, description) VALUES (?, ?, ?, ?)",
            (user_id, ttype, amount, desc)
        )

def update_balance(user_id: int, delta: int):
    with get_db() as conn:
        conn.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (delta, user_id))
        if delta > 0:
            conn.execute("UPDATE users SET total_earned = total_earned + ? WHERE user_id = ?", (delta, user_id))

def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

def get_referral_link(user_id: int) -> str:
    return f"https://t.me/{BOT_USERNAME}?start={user_id}"

# We need bot username for link; we'll set it later in start.

# ---------- CHANNEL VERIFICATION ----------
async def is_subscribed(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await context.bot.get_chat_member(f"@{CHANNEL_USERNAME}", user_id)
        return member.status in (ChatMember.MEMBER, ChatMember.ADMINISTRATOR, ChatMember.CREATOR)
    except:
        return False

async def ensure_subscribed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    if await is_subscribed(user_id, context):
        return True
    keyboard = [
        [InlineKeyboardButton("📢 Join Channel", url=CHANNEL_LINK)],
        [InlineKeyboardButton("✅ Check Subscription", callback_data="check_sub")],
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
    ]
    await update.message.reply_text(
        "🌟 Please join our channel first to use all features!\n\n"
        "👉 @xyvenstar",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return False

# ---------- MAIN MENU ----------
async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
        user_id = query.from_user.id
        msg = query.message
    else:
        user_id = update.effective_user.id
        msg = update.message
    create_user(user_id, update.effective_user.username, update.effective_user.first_name)
    # Check channel subscription
    if not await is_subscribed(user_id, context):
        keyboard = [
            [InlineKeyboardButton("📢 Join Channel", url=CHANNEL_LINK)],
            [InlineKeyboardButton("✅ Check Subscription", callback_data="check_sub")]
        ]
        text = "🌟 *Welcome to XyvenStars!*\n\n"
        text += "Please join our channel to unlock all features:\n👉 @xyvenstar"
        if query:
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        else:
            await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
        return

    keyboard = [
        [InlineKeyboardButton("⭐ My Balance", callback_data="balance"),
         InlineKeyboardButton("👥 Invite Friends", callback_data="invite")],
        [InlineKeyboardButton("🎁 Earn Stars", callback_data="earn"),
         InlineKeyboardButton("🎁 Claim Gift", callback_data="gifts")],
        [InlineKeyboardButton("🎉 Giveaways", callback_data="giveaways"),
         InlineKeyboardButton("ℹ️ How It Works", callback_data="howto")],
        [InlineKeyboardButton("👤 Profile", callback_data="profile")]
    ]
    text = "🌟 *XyvenStars*\n\n"
    text += "Welcome to the ultimate referral and rewards bot!\n"
    text += "Earn ⭐ Stars by inviting friends and redeem amazing gifts."
    if query:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ---------- PROFILE ----------
async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = get_user(user_id)
    if not user:
        await query.edit_message_text("User not found.")
        return
    text = f"👤 *Profile*\n\n"
    text += f"🆔 ID: `{user['user_id']}`\n"
    text += f"👤 Name: {user['first_name'] or 'N/A'}\n"
    text += f"📅 Joined: {user['joined_date'][:10]}\n\n"
    text += f"⭐ Balance: {user['balance']}\n"
    text += f"⭐ Total Earned: {user['total_earned']}\n\n"
    text += f"👥 Invited: {user['invited_count']}\n"
    text += f"✅ Active: {user['active_count']}\n"
    text += f"⭐ From Referrals: {user['stars_from_referrals']}\n"
    keyboard = [
        [InlineKeyboardButton("⭐ Transfer Stars", callback_data="transfer")],
        [InlineKeyboardButton("🎁 My Orders", callback_data="my_orders")],
        [InlineKeyboardButton("📜 Transaction History", callback_data="history")],
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ---------- BALANCE ----------
async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = get_user(user_id)
    if not user:
        await query.edit_message_text("User not found.")
        return
    text = f"⭐ *Your Balance*\n\n"
    text += f"Current Balance: {user['balance']} ⭐\n"
    text += f"Total Earned: {user['total_earned']} ⭐"
    keyboard = [
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ---------- INVITE ----------
async def invite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = get_user(user_id)
    # Get bot username
    bot_username = context.bot.username
    link = f"https://t.me/{bot_username}?start={user_id}"
    text = f"👥 *Referral Program*\n\n"
    text += f"Your referral link:\n`{link}`\n\n"
    text += f"⭐ +{REFERRAL_REWARD} Stars for every active referral!\n\n"
    text += f"📊 Your Stats:\n"
    text += f"Invited: {user['invited_count']}\n"
    text += f"Active: {user['active_count']}\n"
    text += f"Earned from referrals: {user['stars_from_referrals']} ⭐"
    keyboard = [
        [InlineKeyboardButton("📤 Share With Friends", switch_inline_query=link)],
        [InlineKeyboardButton("🏆 Leaderboard", callback_data="leaderboard")],
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ---------- EARN ----------
async def earn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    text = "🎁 *Earn Stars*\n\n"
    text += "You can earn ⭐ Stars by:\n"
    text += "✅ Inviting friends ( +2 ⭐ per active referral )\n"
    text += "✅ Participating in giveaways\n"
    text += "✅ Daily bonuses (coming soon)\n"
    text += "✅ Completing tasks (coming soon)"
    keyboard = [
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ---------- GIFT STORE ----------
async def gifts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = get_user(user_id)
    with get_db() as conn:
        rewards = conn.execute("SELECT * FROM rewards WHERE is_active = 1 ORDER BY cost").fetchall()
    if not rewards:
        await query.edit_message_text("No gifts available at the moment.")
        return
    text = "🎁 *Gift Store*\n\n"
    text += "Exchange your ⭐ Stars for amazing gifts:\n\n"
    keyboard = []
    for r in rewards:
        # Button text: "🧸 Teddy — 15 ⭐"
        name = r['name']
        cost = r['cost']
        desc = r['description']
        text += f"{desc} — {cost} ⭐\n"
        keyboard.append([InlineKeyboardButton(f"👉 Claim {name}", callback_data=f"claim_{r['id']}")])
    text += "\nYour balance: " + str(user['balance']) + " ⭐"
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="main_menu")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ---------- CLAIM GIFT ----------
async def claim_gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    reward_id = int(query.data.split('_')[1])
    with get_db() as conn:
        reward = conn.execute("SELECT * FROM rewards WHERE id = ? AND is_active = 1", (reward_id,)).fetchone()
        user = conn.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if not reward:
        await query.edit_message_text("This gift is no longer available.")
        return
    if user['balance'] < reward['cost']:
        await query.edit_message_text("❌ Insufficient balance. You need more ⭐ Stars.")
        return
    # Deduct balance, create order
    with get_db() as conn:
        conn.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (reward['cost'], user_id))
        conn.execute(
            "INSERT INTO orders (user_id, reward_id, status) VALUES (?, ?, ?)",
            (user_id, reward_id, 'approved')  # immediate approval
        )
        conn.execute(
            "INSERT INTO transactions (user_id, type, amount, description) VALUES (?, ?, ?, ?)",
            (user_id, 'gift_purchase', -reward['cost'], f"Purchased {reward['name']}")
        )
    await query.edit_message_text(
        f"✅ You have successfully claimed **{reward['name']}**!\n"
        f"Your new balance: {user['balance'] - reward['cost']} ⭐",
        parse_mode="Markdown"
    )

# ---------- GIVEAWAYS ----------
async def giveaways(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    with get_db() as conn:
        active = conn.execute("SELECT * FROM giveaways WHERE status = 'active' AND end_date > datetime('now')").fetchall()
        expired = conn.execute("SELECT * FROM giveaways WHERE status = 'active' AND end_date <= datetime('now')").fetchall()
        # update expired
        for g in expired:
            conn.execute("UPDATE giveaways SET status = 'ended' WHERE id = ?", (g['id'],))
        giveaways = conn.execute("SELECT * FROM giveaways WHERE status = 'active' ORDER BY end_date ASC").fetchall()
    if not giveaways:
        text = "🎉 No active giveaways at the moment."
    else:
        text = "🎉 *Active Giveaways*\n\n"
        for g in giveaways:
            text += f"**{g['title']}**\n"
            text += f"Prize: {g['prize']}\n"
            text += f"Condition: {g['condition']}\n"
            text += f"Winners: {g['winners_count']}\n"
            text += f"Ends: {g['end_date'][:16]}\n"
            # Check if user already participated
            part = conn.execute("SELECT 1 FROM giveaway_participants WHERE giveaway_id = ? AND user_id = ?", (g['id'], user_id)).fetchone()
            if part:
                text += "✅ You have entered this giveaway.\n\n"
            else:
                text += f"➡️ /enter_{g['id']} to participate.\n\n"
    keyboard = [
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ---------- LEADERBOARD ----------
async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    with get_db() as conn:
        top = conn.execute(
            "SELECT user_id, username, first_name, active_count FROM users ORDER BY active_count DESC LIMIT 10"
        ).fetchall()
    if not top:
        await query.edit_message_text("No referrals yet. Be the first!")
        return
    text = "🏆 *TOP REFERRERS*\n\n"
    medals = ["🥇", "🥈", "🥉"]
    for i, user in enumerate(top):
        medal = medals[i] if i < 3 else f"{i+1}."
        name = user['first_name'] or user['username'] or str(user['user_id'])
        text += f"{medal} {name} — {user['active_count']} referrals\n"
    keyboard = [
        [InlineKeyboardButton("🔙 Back", callback_data="invite")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ---------- TRANSACTION HISTORY ----------
async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    with get_db() as conn:
        txns = conn.execute(
            "SELECT type, amount, description, timestamp FROM transactions WHERE user_id = ? ORDER BY timestamp DESC LIMIT 20",
            (user_id,)
        ).fetchall()
    if not txns:
        text = "📜 No transactions yet."
    else:
        text = "📜 *Recent Transactions*\n\n"
        for t in txns:
            sign = "+" if t['amount'] > 0 else ""
            text += f"{t['timestamp'][:16]} — {sign}{t['amount']} ⭐ ({t['description']})\n"
    keyboard = [
        [InlineKeyboardButton("🔙 Back", callback_data="profile")]
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ---------- ADMIN PANEL ----------
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Unauthorized.")
        return
    keyboard = [
        [InlineKeyboardButton("📊 Statistics", callback_data="admin_stats")],
        [InlineKeyboardButton("👥 Users", callback_data="admin_users")],
        [InlineKeyboardButton("🎁 Manage Gifts", callback_data="admin_gifts")],
        [InlineKeyboardButton("⭐ Manage Rewards", callback_data="admin_rewards")],
        [InlineKeyboardButton("💸 Pending Withdrawals", callback_data="admin_withdrawals")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🏆 Leaderboard", callback_data="admin_leaderboard")],
        [InlineKeyboardButton("🎉 Giveaways", callback_data="admin_giveaways")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="admin_settings")],
    ]
    await update.message.reply_text(
        "⚙️ *Admin Panel*\n\nChoose an action:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

# ---------- ADMIN STATISTICS ----------
async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.edit_message_text("Unauthorized.")
        return
    with get_db() as conn:
        total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        active_users = conn.execute("SELECT COUNT(*) FROM users WHERE is_active = 1").fetchone()[0]
        total_refs = conn.execute("SELECT COUNT(*) FROM referrals").fetchone()[0]
        active_refs = conn.execute("SELECT COUNT(*) FROM referrals WHERE is_active = 1").fetchone()[0]
        total_stars = conn.execute("SELECT SUM(balance) FROM users").fetchone()[0] or 0
        spent = conn.execute("SELECT SUM(amount) FROM transactions WHERE type = 'gift_purchase'").fetchone()[0] or 0
        pending_withdrawals = conn.execute("SELECT COUNT(*) FROM withdrawals WHERE status = 'pending'").fetchone()[0]
        approved_withdrawals = conn.execute("SELECT COUNT(*) FROM withdrawals WHERE status = 'approved'").fetchone()[0]
        rejected_withdrawals = conn.execute("SELECT COUNT(*) FROM withdrawals WHERE status = 'rejected'").fetchone()[0]
    text = "📊 *Statistics*\n\n"
    text += f"👥 Total Users: {total_users}\n"
    text += f"✅ Active Users: {active_users}\n"
    text += f"📨 Total Referrals: {total_refs}\n"
    text += f"✅ Active Referrals: {active_refs}\n"
    text += f"⭐ Total Stars Distributed: {total_stars}\n"
    text += f"💸 Stars Spent: {spent}\n"
    text += f"⏳ Pending Withdrawals: {pending_withdrawals}\n"
    text += f"✅ Approved Withdrawals: {approved_withdrawals}\n"
    text += f"❌ Rejected Withdrawals: {rejected_withdrawals}"
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="admin_back")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

# ---------- ADMIN BACK ----------
async def admin_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.edit_message_text("Unauthorized.")
        return
    await admin_panel(update, context)

# ---------- MAIN ----------
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    # Store bot username for link generation
    app.bot_data['bot_username'] = None  # will be set in /start

    # Command handlers
    app.add_handler(CommandHandler("start", main_menu))
    app.add_handler(CommandHandler("menu", main_menu))
    app.add_handler(CommandHandler("profile", profile))
    app.add_handler(CommandHandler("ref", invite))
    app.add_handler(CommandHandler("earn", earn))
    app.add_handler(CommandHandler("gifts", gifts))
    app.add_handler(CommandHandler("history", history))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("help", main_menu))

    # Callback query handlers
    app.add_handler(CallbackQueryHandler(main_menu, pattern="^main_menu$"))
    app.add_handler(CallbackQueryHandler(profile, pattern="^profile$"))
    app.add_handler(CallbackQueryHandler(balance, pattern="^balance$"))
    app.add_handler(CallbackQueryHandler(invite, pattern="^invite$"))
    app.add_handler(CallbackQueryHandler(earn, pattern="^earn$"))
    app.add_handler(CallbackQueryHandler(gifts, pattern="^gifts$"))
    app.add_handler(CallbackQueryHandler(giveaways, pattern="^giveaways$"))
    app.add_handler(CallbackQueryHandler(leaderboard, pattern="^leaderboard$"))
    app.add_handler(CallbackQueryHandler(history, pattern="^history$"))
    app.add_handler(CallbackQueryHandler(claim_gift, pattern="^claim_"))
    app.add_handler(CallbackQueryHandler(admin_panel, pattern="^admin_panel$"))
    app.add_handler(CallbackQueryHandler(admin_stats, pattern="^admin_stats$"))
    app.add_handler(CallbackQueryHandler(admin_back, pattern="^admin_back$"))

    # Channel subscription check callback
    async def check_sub(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        if await is_subscribed(user_id, context):
            await query.edit_message_text("✅ You are subscribed! Enjoy all features.")
            await main_menu(update, context)
        else:
            await query.edit_message_text(
                "❌ You are not subscribed yet.\n"
                "Please join our channel first:\n" + CHANNEL_LINK,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📢 Join Channel", url=CHANNEL_LINK)],
                    [InlineKeyboardButton("✅ Check Again", callback_data="check_sub")]
                ])
            )
    app.add_handler(CallbackQueryHandler(check_sub, pattern="^check_sub$"))

    # Withdrawal request (simple command)
    async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        args = context.args
        if not args:
            await update.message.reply_text("Usage: /withdraw <amount> <reward_name>")
            return
        # For simplicity, user types: /withdraw 50 GiftCard
        # We'll parse amount (first arg) and rest as reward name
        try:
            amount = int(args[0])
            reward_name = " ".join(args[1:]) if len(args) > 1 else "Withdrawal"
        except:
            await update.message.reply_text("Invalid format. Use: /withdraw <amount> <reward_name>")
            return
        user = get_user(user_id)
        if not user:
            await update.message.reply_text("User not found.")
            return
        if user['balance'] < amount:
            await update.message.reply_text("Insufficient balance.")
            return
        # Deduct balance and create withdrawal request
        with get_db() as conn:
            conn.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (amount, user_id))
            conn.execute(
                "INSERT INTO withdrawals (user_id, amount, reward_name, status) VALUES (?, ?, ?, ?)",
                (user_id, amount, reward_name, 'pending')
            )
            conn.execute(
                "INSERT INTO transactions (user_id, type, amount, description) VALUES (?, ?, ?, ?)",
                (user_id, 'withdrawal', -amount, f"Withdrawal request: {reward_name}")
            )
        # Notify admin
        await context.bot.send_message(
            ADMIN_ID,
            f"🔔 *NEW WITHDRAWAL*\n\n"
            f"User: @{update.effective_user.username or 'N/A'}\n"
            f"Telegram ID: {user_id}\n"
            f"Amount: {amount} ⭐\n"
            f"Reward: {reward_name}\n"
            f"Request ID: (auto)\n\n"
            f"Use /approve {user_id} {amount} or /reject {user_id} {amount} to handle.",
            parse_mode="Markdown"
        )
        await update.message.reply_text("✅ Withdrawal request submitted for admin approval.")

    # Approve/Reject commands (admin only)
    async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_admin(update.effective_user.id):
            await update.message.reply_text("Unauthorized.")
            return
        args = context.args
        if len(args) < 2:
            await update.message.reply_text("Usage: /approve <user_id> <amount>")
            return
        try:
            user_id = int(args[0])
            amount = int(args[1])
        except:
            await update.message.reply_text("Invalid arguments.")
            return
        # Update withdrawal status to approved
        with get_db() as conn:
            conn.execute(
                "UPDATE withdrawals SET status = 'approved', approved_date = datetime('now') WHERE user_id = ? AND amount = ? AND status = 'pending'",
                (user_id, amount)
            )
        await update.message.reply_text(f"✅ Withdrawal for user {user_id} approved.")
        # Notify user
        try:
            await context.bot.send_message(user_id, "✅ Your withdrawal has been approved.")
        except:
            pass

    async def reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not is_admin(update.effective_user.id):
            await update.message.reply_text("Unauthorized.")
            return
        args = context.args
        if len(args) < 2:
            await update.message.reply_text("Usage: /reject <user_id> <amount>")
            return
        try:
            user_id = int(args[0])
            amount = int(args[1])
        except:
            await update.message.reply_text("Invalid arguments.")
            return
        # Refund balance and mark rejected
        with get_db() as conn:
            conn.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
            conn.execute(
                "UPDATE withdrawals SET status = 'rejected' WHERE user_id = ? AND amount = ? AND status = 'pending'",
                (user_id, amount)
            )
            conn.execute(
                "INSERT INTO transactions (user_id, type, amount, description) VALUES (?, ?, ?, ?)",
                (user_id, 'refund', amount, f"Withdrawal rejected - refund")
            )
        await update.message.reply_text(f"❌ Withdrawal for user {user_id} rejected (refunded).")
        try:
            await context.bot.send_message(user_id, "❌ Your withdrawal has been rejected. Stars refunded.")
        except:
            pass

    app.add_handler(CommandHandler("withdraw", withdraw))
    app.add_handler(CommandHandler("approve", approve))
    app.add_handler(CommandHandler("reject", reject))
    # Handle /start with referral
    async def start_with_ref(update: Update, context: ContextTypes.DEFAULT_TYPE):
        # Check if start parameter exists
        if context.args and context.args[0].isdigit():
            referrer_id = int(context.args[0])
            user_id = update.effective_user.id
            if user_id == referrer_id:
                await update.message.reply_text("You cannot refer yourself.")
                await main_menu(update, context)
                return
            # Check if already referred
            with get_db() as conn:
                existing = conn.execute("SELECT 1 FROM referrals WHERE referred_id = ?", (user_id,)).fetchone()
            if existing:
                await update.message.reply_text("You have already been referred.")
                await main_menu(update, context)
                return
            # Create referral record (inactive until user joins channel)
            with get_db() as conn:
                conn.execute(
                    "INSERT INTO referrals (referrer_id, referred_id, is_active) VALUES (?, ?, ?)",
                    (referrer_id, user_id, 0)
                )
                # Update referrer's invited count
                conn.execute("UPDATE users SET invited_count = invited_count + 1 WHERE user_id = ?", (referrer_id,))
            await update.message.reply_text("✅ You were referred by someone! Please join our channel to activate your referral.")
        await main_menu(update, context)

    app.add_handler(CommandHandler("start", start_with_ref))

    # Check subscription for new users periodically? We'll check on each main menu.

    # Start polling
    print("Bot started. Press Ctrl+C to stop.")
    app.run_polling()

if __name__ == "__main__":
    main()
