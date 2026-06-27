import os

import requests
from dotenv import load_dotenv


def main():
    load_dotenv()

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("Missing TELEGRAM_BOT_TOKEN. Add it to your .env file first.")

    configured_chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if configured_chat_id:
        print(f"TELEGRAM_CHAT_ID in .env: {configured_chat_id}")
        print("If your bot is sending alerts, this chat ID is already working.")
        print()

    url = f"https://api.telegram.org/bot{token}/getUpdates"
    response = requests.get(url, timeout=20)
    response.raise_for_status()

    data = response.json()
    updates = data.get("result", [])

    if not updates:
        print("No Telegram updates found.")
        print("This is normal if Telegram has no inbound messages waiting for the bot.")
        print("Bot alerts sent to you do not appear here.")
        print("To create a new update, send a fresh message to your bot, then run this script again.")
        return

    chats = {}
    for update in updates:
        message = (
            update.get("message")
            or update.get("edited_message")
            or update.get("channel_post")
            or update.get("edited_channel_post")
        )
        if not message:
            continue

        chat = message.get("chat", {})
        chat_id = chat.get("id")
        if chat_id is None:
            continue

        name_parts = [
            chat.get("title"),
            chat.get("first_name"),
            chat.get("last_name"),
            chat.get("username"),
        ]
        chat_name = " ".join(str(part) for part in name_parts if part)
        chats[chat_id] = chat_name or "(no name)"

    if not chats:
        print("Updates were found, but no chat IDs were available.")
        return

    print("Telegram chat IDs:")
    for chat_id, chat_name in chats.items():
        print(f"{chat_id} - {chat_name}")


if __name__ == "__main__":
    main()
