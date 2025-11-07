import logging
import sqlite3
import re
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatMemberAdministrator, ChatMemberOwner
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from deep_translator import GoogleTranslator

# --- KONFIGURATSIYA ---
TOKEN = "8544997548:AAE_tKvdXTBWzl6P_KZqtYkTTeljIwXuBwI"
OWNER_ID = 7882410957
BOT_USERNAME = "aurafarmrobot"

# --- LOGGING ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- MA'LUMOTLAR BAZASI ---
def init_db():
    conn = sqlite3.connect('aura_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            aura_balance INTEGER DEFAULT 0,
            daily_sent INTEGER DEFAULT 0,
            last_sent_date TEXT
        )
    ''')
    conn.commit()
    conn.close()

def get_or_create_user(user_id, username):
    conn = sqlite3.connect('aura_bot.db')
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    if not user:
        cursor.execute("INSERT INTO users (user_id, username, aura_balance) VALUES (?, ?, ?)", (user_id, username, 0))
        conn.commit()
        user = (user_id, username, 0, 0, None)
    conn.close()
    return user

def update_user(user_id, aura_change=None, daily_sent_change=None):
    conn = sqlite3.connect('aura_bot.db')
    cursor = conn.cursor()
    
    if aura_change is not None:
        cursor.execute("UPDATE users SET aura_balance = aura_balance + ? WHERE user_id = ?", (aura_change, user_id))
    
    if daily_sent_change is not None:
        today_str = datetime.now().strftime('%Y-%m-%d')
        cursor.execute("SELECT last_sent_date FROM users WHERE user_id = ?", (user_id,))
        last_date = cursor.fetchone()[0]
        
        if last_date != today_str:
            cursor.execute("UPDATE users SET daily_sent = ?, last_sent_date = ? WHERE user_id = ?", (daily_sent_change, today_str, user_id))
        else:
            cursor.execute("UPDATE users SET daily_sent = daily_sent + ? WHERE user_id = ?", (daily_sent_change, user_id))
            
    conn.commit()
    conn.close()

# --- TARJIMA ---
def get_user_language(update: Update):
    if update.message.chat.type != 'private':
        return 'uz'
    lang_code = update.message.from_user.language_code
    if lang_code:
        if 'ru' in lang_code: return 'ru'
        if 'en' in lang_code: return 'en'
    return 'uz'

def translate(text, target_lang):
    if target_lang == 'uz': return text
    try:
        translator = GoogleTranslator(source='uz', target=target_lang)
        return translator.translate(text)
    except Exception as e:
        logger.error(f"Tarjima xatosi: {e}")
        return text

# --- KOMANDALAR ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type == 'private':
        lang = get_user_language(update)
        user = update.effective_user
        get_or_create_user(user.id, user.username)
        
        keyboard = [[InlineKeyboardButton(
            text=translate("Meni guruhga qo'sh", lang),
            url=f"https://t.me/{BOT_USERNAME}?startgroup=true"
        )]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # < va > belgilarini HTML xavfsiz shaklga o‘tkazamiz
        text = translate(
            f"Assalomu alaykum, {user.mention_html()}! 👋\n\n"
            f"Men Aura Fermer Botman.\n\n"
            f"Guruhlarda ishlayman:\n"
            f"• `+&lt;son&gt; AURA` - Reply qilib aurani qo'shish.\n"
            f"• `-&lt;son&gt; AURA` - Reply qilib aurani ayirish.\n\n"
            f"Oddiy a'zolar uchun kunlik 100 ta limit bor. Adminlar uchun limit yo'q!",
            lang
        )
        
        await update.message.reply_html(text, reply_markup=reply_markup)

async def start_in_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type in ['group', 'supergroup']:
        lang = get_user_language(update)
        text = translate(
            "👋 Salom, men Aura Fermer Botman!\n\n"
            "Guruhda quyidagi buyruqlardan foydalanishingiz mumkin:\n"
            "• `+<son> AURA` - Kimdidir reply qilib, unga aura qo'shing.\n"
            "• `-<son> AURA` - Kimdidir reply qilib, undan aura ayiring.\n\n"
            "⚠️ Botni ishlatishni boshlash uchun guruhda adminlik ruxsatini bering! \n\n"
            "Oddiy a'zolar uchun kunlik 100 ta limit bor. Adminlar uchun limit yo'q!",
            lang
        )
        await update.message.reply_text(text)

# --- AURA TIZIMI ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    message = update.message
    chat = message.chat

    if chat.type not in ['group', 'supergroup']:
        return

    if not message.text:
        return

    text = message.text.strip().upper()
    
    # faqat reply qilingan xabarlar
    if message.reply_to_message and message.reply_to_message.from_user:
        sender = message.from_user
        receiver = message.reply_to_message.from_user
        
        if sender.id == receiver.id:
            await message.reply_text("O'zingizga o'zingiz aura yubora olmaysiz!")
            return

        match = re.fullmatch(r'([+-]\d+)\s*AURA', text)
        if not match:
            return

        amount = int(match.group(1))
        
        await process_aura_transfer(update, sender, receiver, amount)

async def process_aura_transfer(update: Update, sender, receiver, amount):
    is_admin = False
    is_owner = False
    
    if sender.id == OWNER_ID:
        is_owner = True
    else:
        try:
            chat_member = await update.effective_chat.get_member(sender.id)
            if isinstance(chat_member, (ChatMemberAdministrator, ChatMemberOwner)):
                is_admin = True
        except Exception as e:
            logger.error(f"Admin huquqini tekshirishda xatolik: {e}")

    if not is_owner and not is_admin:
        sender_data = get_or_create_user(sender.id, sender.username)
        today_str = datetime.now().strftime('%Y-%m-%d')
        daily_sent = sender_data[3]
        last_sent_date = sender_data[4]
        
        if last_sent_date != today_str:
            daily_sent = 0
        
        if daily_sent + abs(amount) > 100:
            await update.message.reply_text(f"Kunlik aura yuborish limitingiz 100 ta. Siz {daily_sent} ta yubordingiz.")
            return

    if not is_owner and not is_admin:
        update_user(sender.id, daily_sent_change=abs(amount))
    
    update_user(receiver.id, aura_change=amount)
    
    receiver_data = get_or_create_user(receiver.id, receiver.username)
    new_balance = receiver_data[2]
    
    action = "qo'shdi" if amount > 0 else "ayirdi"
    await update.message.reply_text(
        f"{sender.mention_html()} {receiver.mention_html()} ga {abs(amount)} AURA {action}.\n"
        f"{receiver.first_name} ning yangi balansi: {new_balance} AURA 💎",
        parse_mode='HTML'
    )

# --- ASOSIY FUNKSIYA ---
async def main():
    init_db()
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start, filters.ChatType.PRIVATE))
    application.add_handler(CommandHandler("start", start_in_group, filters.ChatType.GROUPS))
    application.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.TEXT, handle_message))

    logger.info("Aura Fermer Bot ishga tushdi...")
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot to'xtatilmoqda...")
        await application.updater.stop()
        await application.stop()
        await application.shutdown()
        logger.info("Bot to'xtatildi.")

if __name__ == '__main__':
    asyncio.run(main())
