import time
import os
import threading
import telebot
import logging
import commands.jrrp
import commands.handle
import commands.bsky

BOT_TOKEN = os.getenv("BOT_TOKEN")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
ALLOWED_GROUPS = set(os.getenv("ALLOWED_GROUPS", "-1145141919810").split(","))
BSKY_HANDLE = os.getenv("BSKY_HANDLE", "").strip()


def parse_poll_interval() -> int:
    try:
        return max(10, int(os.getenv("BSKY_POLL_INTERVAL", "60")))
    except ValueError:
        logging.getLogger().warning(
            "Invalid BSKY_POLL_INTERVAL, fallback to 60 seconds"
        )
        return 60


BSKY_POLL_INTERVAL = parse_poll_interval()

MAX_AI_CHAT_MESSAGE_LENGTH = 100

log_levels = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}
level = log_levels.get(LOG_LEVEL, logging.INFO)

logging.basicConfig(
    format="%(asctime)s - %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=level,
)
logger = logging.getLogger()

if not BOT_TOKEN:
    logger.error("No BOT_TOKEN")
    exit(1)

bot = telebot.TeleBot(token=BOT_TOKEN, parse_mode="HTML")


def is_allowed_group(chat_id: int) -> bool:
    return str(chat_id) in ALLOWED_GROUPS or "-1145141919810" in ALLOWED_GROUPS


def get_bsky_target_chats() -> list[str]:
    return sorted(
        [
            chat_id.strip()
            for chat_id in ALLOWED_GROUPS
            if chat_id.strip() and chat_id.strip() != "-1145141919810"
        ]
    )


@bot.message_handler(commands=["jrrp"])
def command_jrrp(message) -> None:
    if is_allowed_group(message.chat.id):
        bot.reply_to(message, commands.jrrp.main(message.from_user.id))


@bot.message_handler(func=lambda message: True)
def handle_text_message(message) -> None:
    if is_allowed_group(message.chat.id):
        logger.debug(f"JUST TEXT HANDLE - {message}")
        if response := commands.handle.main(message):
            bot.reply_to(message, response)


def start_bot():
    bsky_target_chats = get_bsky_target_chats()

    if BSKY_HANDLE and bsky_target_chats:
        logger.info(
            "Starting bsky poller for %s -> %s",
            BSKY_HANDLE,
            bsky_target_chats,
        )
        threading.Thread(
            target=commands.bsky.poll_latest_posts,
            args=(bot, BSKY_HANDLE, bsky_target_chats, BSKY_POLL_INTERVAL),
            daemon=True,
        ).start()
    elif BSKY_HANDLE:
        logger.warning(
            "BSKY poller is disabled because no valid ALLOWED_GROUPS target is configured"
        )

    while True:
        try:
            logger.info("I'm Running!")
            bot.polling(non_stop=True)
        except Exception as e:
            logger.error(f"Connection error: {e}")
            time.sleep(10)


if __name__ == "__main__":
    start_bot()
