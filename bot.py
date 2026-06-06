import os
import re
import sys
import io
import json
import zipfile
import asyncio
import logging
import subprocess
import tempfile
import ssl
import time
import xml.etree.ElementTree as ET

import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_IDS = [int(x.strip()) for x in os.getenv("OWNER_IDS", "").split(",") if x.strip()]
_MP4DECRYPT_BIN = "mp4decrypt.exe" if os.name == "nt" else "mp4decrypt"
MP4DECRYPT_PATH = os.getenv("MP4DECRYPT_PATH", os.path.join(os.path.dirname(__file__), _MP4DECRYPT_BIN))
DEFAULT_QUALITY = os.getenv("DEFAULT_QUALITY", "64k")
ALLOWED_CHATS = [int(x.strip()) for x in os.getenv("ALLOWED_CHATS", "").split(",") if x.strip()]

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

ASK_MPD, ASK_KEYS = range(2)
RESTART_FLAG = os.path.join(os.path.dirname(__file__), "restart.flag")
BOT_DIR = os.path.dirname(os.path.abspath(__file__))

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE


def owner_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        if ALLOWED_CHATS and chat_id not in ALLOWED_CHATS:
            return
        user_id = update.effective_user.id
        if OWNER_IDS and user_id not in OWNER_IDS:
            return
        return await func(update, context)
    return wrapper


def check_tool(path: str) -> bool:
    if os.path.isfile(path):
        if os.name != "nt" and not os.access(path, os.X_OK):
            os.chmod(path, 0o755)
        return True
    try:
        subprocess.run(
            ["where" if os.name == "nt" else "which", path],
            capture_output=True, check=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


async def download_file(url: str, output_path: str, status_msg) -> bool:
    connector = aiohttp.TCPConnector(limit=0, force_close=False, enable_cleanup_closed=True)
    timeout = aiohttp.ClientTimeout(total=600)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    try:
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            async with session.get(url, headers=headers, ssl=SSL_CTX) as response:
                if response.status != 200:
                    await status_msg.edit_text(f"Download failed — HTTP {response.status}")
                    return False

                total = int(response.headers.get("content-length", 0))
                downloaded = 0
                last_percent = -1

                with open(output_path, "wb") as f:
                    async for chunk in response.content.iter_chunked(524288):
                        f.write(chunk)
                        downloaded += len(chunk)

                        if total > 0:
                            percent = int((downloaded / total) * 100)
                            if percent != last_percent and percent % 25 == 0:
                                last_percent = percent
                                size_mb = round(downloaded / 1048576, 2)
                                total_mb = round(total / 1048576, 2)
                                try:
                                    await status_msg.edit_text(
                                        f"Downloading — {percent}% ({size_mb}/{total_mb} MB)"
                                    )
                                except Exception:
                                    pass

        size_mb = round(os.path.getsize(output_path) / 1048576, 2)
        await status_msg.edit_text(f"Downloaded — {size_mb} MB")
        return True

    except Exception as e:
        await status_msg.edit_text(f"Download error: {str(e)[:200]}")
        if os.path.exists(output_path):
            os.remove(output_path)
        return False


async def fetch_mpd(url: str) -> str | None:
    connector = aiohttp.TCPConnector(limit=0)
    timeout = aiohttp.ClientTimeout(total=30)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    try:
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            async with session.get(url, headers=headers, ssl=SSL_CTX) as response:
                if response.status != 200:
                    return None
                return await response.text()
    except Exception:
        return None


def parse_mpd(mpd_content: str, quality: str) -> dict | None:
    try:
        root = ET.fromstring(mpd_content)
        target_file = f"protected_audio_mpd_{quality}.mp4"

        for rep in root.iter("{urn:mpeg:dash:schema:mpd:2011}Representation"):
            base_url_elem = rep.find("{urn:mpeg:dash:schema:mpd:2011}BaseURL")
            if base_url_elem is not None and base_url_elem.text == target_file:
                return {
                    "file": base_url_elem.text,
                    "bandwidth": rep.get("bandwidth", "N/A"),
                    "codec": rep.get("codecs", "N/A"),
                }

        for rep in root.iter("Representation"):
            base_url_elem = rep.find("BaseURL")
            if base_url_elem is not None and base_url_elem.text == target_file:
                return {
                    "file": base_url_elem.text,
                    "bandwidth": rep.get("bandwidth", "N/A"),
                    "codec": rep.get("codecs", "N/A"),
                }

        return None
    except ET.ParseError:
        return None

def get_mpd_qualities(mpd_content: str) -> list[str]:
    qualities = []
    try:
        root = ET.fromstring(mpd_content)
        
        for rep in root.iter("{urn:mpeg:dash:schema:mpd:2011}Representation"):
            base_url_elem = rep.find("{urn:mpeg:dash:schema:mpd:2011}BaseURL")
            if base_url_elem is not None and base_url_elem.text:
                m = re.search(r'protected_audio_mpd_(.*?)\.mp4', base_url_elem.text)
                if m and m.group(1) not in qualities:
                    qualities.append(m.group(1))

        for rep in root.iter("Representation"):
            base_url_elem = rep.find("BaseURL")
            if base_url_elem is not None and base_url_elem.text:
                m = re.search(r'protected_audio_mpd_(.*?)\.mp4', base_url_elem.text)
                if m and m.group(1) not in qualities:
                    qualities.append(m.group(1))

        qualities.sort(key=lambda x: int(re.sub(r'\D', '', x)) if re.sub(r'\D', '', x) else 0)
    except ET.ParseError:
        pass
    return qualities


def parse_keys_input(text: str) -> dict:
    keys = {}

    key_matches = re.findall(r'--key\s+([a-fA-F0-9]+):([a-fA-F0-9]+)', text)
    if key_matches:
        for kid, key in key_matches:
            keys[kid.lower()] = key.lower()
        return keys

    for line in re.split(r'[,\n]+', text):
        line = line.strip()
        if ':' in line:
            parts = line.split(':', 1)
            kid = parts[0].strip().lower()
            key = parts[1].strip().lower()
            if re.match(r'^[a-fA-F0-9]+$', kid) and re.match(r'^[a-fA-F0-9]+$', key):
                keys[kid] = key

    return keys


async def run_decrypt(mp4decrypt_path: str, keys: dict, input_file: str, output_file: str) -> tuple[bool, str]:
    cmd = [mp4decrypt_path]
    for kid, key in keys.items():
        cmd.extend(["--key", f"{kid}:{key}"])
    cmd.extend([input_file, output_file])

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            error = (stderr or stdout).decode(errors="replace")
            return False, error
        return True, "OK"
    except Exception as e:
        return False, str(e)





@owner_only
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    has_mp4decrypt = check_tool(MP4DECRYPT_PATH)

    await update.message.reply_text(
        "<b>Widevine DRM Downloader</b>\n\n"
        f"mp4decrypt: {'Ready' if has_mp4decrypt else 'Not Found'}\n\n"
        "<b>Commands</b>\n"
        "/drm — Start download\n"
        "/status — Check tools\n"
        "/update — Pull and restart\n"
        "/cancel — Cancel operation",
        parse_mode="HTML",
    )


@owner_only
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    has_mp4decrypt = check_tool(MP4DECRYPT_PATH)

    await update.message.reply_text(
        "<b>Status</b>\n\n"
        f"mp4decrypt: {'Ready' if has_mp4decrypt else 'Missing'}\n"
        f"Path: <code>{MP4DECRYPT_PATH}</code>\n\n"
        f"Default Quality: <code>{DEFAULT_QUALITY}</code>",
        parse_mode="HTML",
    )


@owner_only
async def drm_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_tool(MP4DECRYPT_PATH):
        await update.message.reply_text(
            "<b>mp4decrypt not found</b>\n"
            f"Expected: <code>{MP4DECRYPT_PATH}</code>\n\n"
            "Download from: https://www.bento4.com/downloads/",
            parse_mode="HTML",
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "<b>Step 1/4 — MPD URL</b>\n\n"
        "Send the MPD manifest URL.",
        parse_mode="HTML",
    )
    return ASK_MPD


async def receive_mpd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mpd_url = update.message.text.strip()

    if not mpd_url.startswith("http"):
        await update.message.reply_text("Invalid URL. Send a valid MPD URL starting with http/https.")
        return ASK_MPD

    status_msg = await update.message.reply_text("Fetching MPD manifest...")
    mpd_content = await fetch_mpd(mpd_url)
    
    if not mpd_content:
        await status_msg.edit_text("Failed to fetch MPD. Check the URL and try again.")
        return ASK_MPD

    context.user_data["mpd_url"] = mpd_url
    context.user_data["mpd_content"] = mpd_content
    
    await status_msg.edit_text(
        "<b>Step 2/4 — Decryption Keys</b>\n\n"
        "Send KID:KEY pairs, one per line.\n\n"
        "Format:\n"
        "<code>kid1:key1\n"
        "kid2:key2</code>",
        parse_mode="HTML",
    )
    return ASK_KEYS


async def receive_keys(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keys_text = update.message.text.strip()
    keys = parse_keys_input(keys_text)

    if not keys:
        await update.message.reply_text(
            "No valid keys found.\n\n"
            "Send in format: <code>kid:key</code> (one per line)",
            parse_mode="HTML",
        )
        return ASK_KEYS

    context.user_data["keys"] = keys

    qualities = get_mpd_qualities(context.user_data.get("mpd_content", ""))
    quality = "128k" if "128k" in qualities else (qualities[0] if qualities else "128k")
    output_name = str(int(time.time()))

    mpd_url = context.user_data["mpd_url"]
    keys_preview = "\n".join([f"  <code>{kid}:{key}</code>" for kid, key in keys.items()])
    
    status_msg = await update.message.reply_text(
        "<b>Starting</b>\n\n"
        f"MPD: <code>{mpd_url[:80]}...</code>\n"
        f"Keys:\n{keys_preview}\n"
        f"Quality: <code>{quality}</code>\n"
        f"Output: <code>{output_name}</code>\n\n"
        "Processing...",
        parse_mode="HTML",
    )

    work_dir = tempfile.mkdtemp(prefix="drm_")

    try:
        mpd_content = context.user_data.get("mpd_content")
        if not mpd_content:
            await status_msg.edit_text("[1/5] Fetching MPD...")
            mpd_content = await fetch_mpd(mpd_url)
            if not mpd_content:
                await status_msg.edit_text("Failed to fetch MPD.")
                return ConversationHandler.END

        await status_msg.edit_text("[2/5] Parsing MPD...")

        audio_info = parse_mpd(mpd_content, quality)
        if not audio_info:
            await status_msg.edit_text(
                f"Quality <code>{quality}</code> not found in MPD.\n",
                parse_mode="HTML",
            )
            return ConversationHandler.END

        mpd_base_url = mpd_url.rsplit("/", 1)[0]
        audio_url = f"{mpd_base_url}/{audio_info['file']}"

        await status_msg.edit_text(
            f"MPD parsed.\n"
            f"Quality: {quality} | Bandwidth: {audio_info['bandwidth']} bps | Codec: {audio_info['codec']}"
        )
        await asyncio.sleep(0.5)

        encrypted_file = os.path.join(work_dir, "encrypted_audio.mp4")

        await status_msg.edit_text("[3/5] Downloading encrypted audio...")

        if not await download_file(audio_url, encrypted_file, status_msg):
            return ConversationHandler.END

        await asyncio.sleep(0.3)

        decrypted_file = os.path.join(work_dir, f"{output_name}.m4a")

        await status_msg.edit_text(f"[4/5] Decrypting with {len(keys)} key(s)...")

        success, error_msg = await run_decrypt(MP4DECRYPT_PATH, keys, encrypted_file, decrypted_file)

        if not success:
            await status_msg.edit_text(
                f"Decryption failed.\n\n<code>{error_msg[:500]}</code>",
                parse_mode="HTML",
            )
            return ConversationHandler.END

        os.remove(encrypted_file)

        decrypted_size = round(os.path.getsize(decrypted_file) / 1048576, 2)
        await status_msg.edit_text(f"Decrypted — {decrypted_size} MB")
        await asyncio.sleep(0.3)
        
        pseudo_mp3_file = os.path.join(work_dir, f"{output_name}.mp3")
        os.rename(decrypted_file, pseudo_mp3_file)

        await status_msg.edit_text("Uploading as Audio (.mp3 extension)...")

        file_size = round(os.path.getsize(pseudo_mp3_file) / 1048576, 2)
        
        with open(pseudo_mp3_file, "rb") as f:
            await update.message.reply_audio(
                audio=f,
                filename=f"{output_name}.mp3",
                caption=f"<b>{output_name}.mp3</b> ({file_size} MB) | {quality}",
                parse_mode="HTML",
                read_timeout=120,
                write_timeout=120,
                connect_timeout=120,
            )

        result_text = (
            f"<b>Done</b>\n\n"
            f"{output_name}.mp3 — {file_size} MB\n"
            f"\nQuality: {quality} | Keys: {len(keys)}"
        )

        await status_msg.edit_text(result_text, parse_mode="HTML")

    except Exception as e:
        logger.exception("DRM download pipeline error")
        await status_msg.edit_text(
            f"Error:\n<code>{str(e)[:500]}</code>",
            parse_mode="HTML",
        )

    finally:
        for f in os.listdir(work_dir):
            try:
                os.remove(os.path.join(work_dir, f))
            except Exception:
                pass
        try:
            os.rmdir(work_dir)
        except Exception:
            pass

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END


@owner_only
async def cmd_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    status_msg = await update.message.reply_text("Pulling from GitHub...")

    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "pull",
            cwd=BOT_DIR,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        output = (stdout or stderr).decode(errors="replace").strip()

        if proc.returncode != 0:
            await status_msg.edit_text(f"Git pull failed.\n\n<code>{output[:500]}</code>", parse_mode="HTML")
            return

        if "Already up to date" in output:
            await status_msg.edit_text("Already up to date. No restart needed.")
            return

        await status_msg.edit_text(f"Pulled.\n<code>{output[:300]}</code>\n\nRestarting...", parse_mode="HTML")

        with open(RESTART_FLAG, "w") as f:
            json.dump({"chat_id": chat_id}, f)

        await asyncio.sleep(0.5)
        os.execv(sys.executable, [sys.executable] + sys.argv)

    except Exception as e:
        await status_msg.edit_text(f"Update failed: {str(e)[:300]}")


async def ensure_tools():
    if not os.path.exists(MP4DECRYPT_PATH):
        logger.info("mp4decrypt not found. Downloading...")
        is_windows = os.name == "nt"
        if is_windows:
            url = "https://www.bok.net/Bento4/binaries/Bento4-SDK-1-6-0-641.x86_64-microsoft-win32.zip"
            zip_bin_path = "Bento4-SDK-1-6-0-641.x86_64-microsoft-win32/bin/mp4decrypt.exe"
        else:
            url = "https://www.bok.net/Bento4/binaries/Bento4-SDK-1-6-0-641.x86_64-unknown-linux.zip"
            zip_bin_path = "Bento4-SDK-1-6-0-641.x86_64-unknown-linux/bin/mp4decrypt"
        
        try:
            async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        content = await resp.read()
                        with zipfile.ZipFile(io.BytesIO(content)) as z:
                            with z.open(zip_bin_path) as src, open(MP4DECRYPT_PATH, "wb") as dst:
                                dst.write(src.read())
                        if not is_windows:
                            os.chmod(MP4DECRYPT_PATH, 0o755)
                        logger.info("Successfully downloaded and extracted mp4decrypt.")
                    else:
                        logger.error(f"Failed to download mp4decrypt. HTTP {resp.status}")
        except Exception as e:
            logger.error(f"Error downloading mp4decrypt: {e}")

async def post_init(app: Application):
    await ensure_tools()
    
    if not os.path.exists(RESTART_FLAG):
        return
    try:
        with open(RESTART_FLAG, "r") as f:
            data = json.load(f)
        os.remove(RESTART_FLAG)
        chat_id = data.get("chat_id")
        if chat_id:
            await app.bot.send_message(chat_id=chat_id, text="Restarted.")
    except Exception as e:
        logger.error(f"Post-restart notification failed: {e}")


def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not found in .env file!")
        return

    app = Application.builder().token(BOT_TOKEN).build()

    drm_handler = ConversationHandler(
        entry_points=[CommandHandler("drm", drm_start)],
        states={
            ASK_MPD: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_mpd)],
            ASK_KEYS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_keys)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_user=True,
        per_chat=True,
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("update", cmd_update))
    app.add_handler(drm_handler)

    app.post_init = post_init

    logger.info("Bot started — polling...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
