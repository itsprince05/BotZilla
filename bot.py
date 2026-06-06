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
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
OWNER_IDS = [int(x.strip()) for x in os.getenv("OWNER_IDS", "").split(",") if x.strip()]
_MP4DECRYPT_BIN = "mp4decrypt.exe" if os.name == "nt" else "mp4decrypt"
MP4DECRYPT_PATH = os.getenv("MP4DECRYPT_PATH", os.path.join(os.path.dirname(__file__), _MP4DECRYPT_BIN))
ALLOWED_CHATS = [int(x.strip()) for x in os.getenv("ALLOWED_CHATS", "").split(",") if x.strip()]

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

RESTART_FLAG = os.path.join(os.path.dirname(__file__), "restart.flag")
BOT_DIR = os.path.dirname(os.path.abspath(__file__))

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

# Conversation state
# {user_id: {"mpd_url": str, "mpd_content": str}}
user_states = {}


def owner_only(func):
    async def wrapper(client: Client, message: Message):
        chat_id = message.chat.id
        if ALLOWED_CHATS and chat_id not in ALLOWED_CHATS:
            return
        user_id = message.from_user.id
        if OWNER_IDS and user_id not in OWNER_IDS:
            return
        return await func(client, message)
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


async def download_file(url: str, output_path: str, status_msg: Message) -> bool:
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
                    async for chunk in response.content.iter_chunked(1048576):
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


app = Client("drm_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)


@app.on_message(filters.command("start"))
@owner_only
async def cmd_start(client: Client, message: Message):
    has_mp4decrypt = check_tool(MP4DECRYPT_PATH)

    await message.reply_text(
        "<b>Widevine DRM Downloader (Pyrogram)</b>\n\n"
        f"mp4decrypt: {'Ready' if has_mp4decrypt else 'Not Found'}\n\n"
        "<b>Commands</b>\n"
        "/drm — Start download\n"
        "/status — Check tools\n"
        "/update — Pull and restart\n"
        "/cancel — Cancel operation",
    )


@app.on_message(filters.command("status"))
@owner_only
async def cmd_status(client: Client, message: Message):
    has_mp4decrypt = check_tool(MP4DECRYPT_PATH)

    await message.reply_text(
        "<b>Status</b>\n\n"
        f"mp4decrypt: {'Ready' if has_mp4decrypt else 'Missing'}\n"
        f"Path: <code>{MP4DECRYPT_PATH}</code>\n\n",
    )


@app.on_message(filters.command("cancel"))
@owner_only
async def cmd_cancel(client: Client, message: Message):
    if message.from_user.id in user_states:
        del user_states[message.from_user.id]
    await message.reply_text("Cancelled.")


@app.on_message(filters.command("update"))
@owner_only
async def cmd_update(client: Client, message: Message):
    chat_id = message.chat.id
    status_msg = await message.reply_text("Pulling from GitHub...")

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
            await status_msg.edit_text(f"Git pull failed.\n\n<code>{output[:500]}</code>")
            return

        if "Already up to date" in output:
            await status_msg.edit_text("Already up to date. No restart needed.")
            return

        await status_msg.edit_text(f"Pulled.\n<code>{output[:300]}</code>\n\nRestarting...")

        with open(RESTART_FLAG, "w") as f:
            json.dump({"chat_id": chat_id}, f)

        await asyncio.sleep(0.5)
        os.execv(sys.executable, [sys.executable] + sys.argv)

    except Exception as e:
        await status_msg.edit_text(f"Update failed: {str(e)[:300]}")


@app.on_message(filters.command("drm"))
@owner_only
async def drm_start(client: Client, message: Message):
    if not check_tool(MP4DECRYPT_PATH):
        await message.reply_text(
            "<b>mp4decrypt not found</b>\n"
            f"Expected: <code>{MP4DECRYPT_PATH}</code>\n\n"
            "Download from: https://www.bento4.com/downloads/",
        )
        return

    user_states[message.from_user.id] = {"step": "ASK_MPD"}
    await message.reply_text(
        "<b>Step 1/2 — MPD URL</b>\n\n"
        "Send the MPD manifest URL.",
    )


@app.on_message(filters.text & ~filters.command(["start", "status", "cancel", "update", "drm"]))
@owner_only
async def handle_text(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in user_states:
        return

    state = user_states[user_id]
    step = state.get("step")

    if step == "ASK_MPD":
        mpd_url = message.text.strip()
        if not mpd_url.startswith("http"):
            await message.reply_text("Invalid URL. Send a valid MPD URL starting with http/https.")
            return

        status_msg = await message.reply_text("Fetching MPD manifest...")
        mpd_content = await fetch_mpd(mpd_url)
        
        if not mpd_content:
            await status_msg.edit_text("Failed to fetch MPD. Check the URL and try again.")
            return

        state["mpd_url"] = mpd_url
        state["mpd_content"] = mpd_content
        state["step"] = "ASK_KEYS"
        
        await status_msg.edit_text(
            "<b>Step 2/2 — Decryption Keys</b>\n\n"
            "Send KID:KEY pairs, one per line.\n\n"
            "Format:\n"
            "<code>kid1:key1\n"
            "kid2:key2</code>",
        )
        
    elif step == "ASK_KEYS":
        keys_text = message.text.strip()
        keys = parse_keys_input(keys_text)

        if not keys:
            await message.reply_text("No valid keys found.\nSend in format: <code>kid:key</code>")
            return

        state["keys"] = keys
        await process_drm(client, message, state)
        del user_states[user_id]


async def process_drm(client: Client, message: Message, state: dict):
    keys = state["keys"]
    mpd_url = state["mpd_url"]
    mpd_content = state["mpd_content"]

    qualities = get_mpd_qualities(mpd_content)
    quality = "128k" if "128k" in qualities else (qualities[0] if qualities else "128k")
    output_name = str(int(time.time()))

    keys_preview = "\n".join([f"  <code>{kid}:{key}</code>" for kid, key in keys.items()])
    
    status_msg = await message.reply_text(
        "<b>Starting</b>\n\n"
        f"MPD: <code>{mpd_url[:80]}...</code>\n"
        f"Keys:\n{keys_preview}\n"
        f"Quality: <code>{quality}</code>\n"
        f"Output: <code>{output_name}</code>\n\n"
        "Processing...",
    )

    work_dir = tempfile.mkdtemp(prefix="drm_")

    try:
        await status_msg.edit_text("[1/5] Parsing MPD...")

        audio_info = parse_mpd(mpd_content, quality)
        if not audio_info:
            await status_msg.edit_text(f"Quality <code>{quality}</code> not found in MPD.\n")
            return

        mpd_base_url = mpd_url.rsplit("/", 1)[0]
        audio_url = f"{mpd_base_url}/{audio_info['file']}"

        await status_msg.edit_text(
            f"MPD parsed.\n"
            f"Quality: {quality} | Bandwidth: {audio_info['bandwidth']} bps | Codec: {audio_info['codec']}"
        )

        encrypted_file = os.path.join(work_dir, "encrypted_audio.mp4")

        await status_msg.edit_text("[2/5] Downloading encrypted audio...")

        if not await download_file(audio_url, encrypted_file, status_msg):
            return

        decrypted_file = os.path.join(work_dir, f"{output_name}.m4a")

        await status_msg.edit_text(f"[3/5] Decrypting with {len(keys)} key(s)...")

        success, error_msg = await run_decrypt(MP4DECRYPT_PATH, keys, encrypted_file, decrypted_file)

        if not success:
            await status_msg.edit_text(f"Decryption failed.\n\n<code>{error_msg[:500]}</code>")
            return

        os.remove(encrypted_file)

        decrypted_size = round(os.path.getsize(decrypted_file) / 1048576, 2)
        await status_msg.edit_text(f"Decrypted — {decrypted_size} MB")
        
        pseudo_mp3_file = os.path.join(work_dir, f"{output_name}.mp3")
        os.rename(decrypted_file, pseudo_mp3_file)

        await status_msg.edit_text("[4/5] Uploading as Audio (.mp3 extension)...")

        file_size = round(os.path.getsize(pseudo_mp3_file) / 1048576, 2)
        
        # Pyrogram natively extracts audio metadata including duration perfectly.
        await message.reply_audio(
            audio=pseudo_mp3_file,
            caption=f"<b>{output_name}.mp3</b> ({file_size} MB) | {quality}",
        )

        result_text = (
            f"<b>Done</b>\n\n"
            f"{output_name}.mp3 — {file_size} MB\n"
            f"\nQuality: {quality} | Keys: {len(keys)}"
        )

        await status_msg.edit_text(result_text)

    except Exception as e:
        logger.exception("DRM download pipeline error")
        await status_msg.edit_text(f"Error:\n<code>{str(e)[:500]}</code>")

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


async def main():
    if not BOT_TOKEN or not API_ID or not API_HASH:
        logger.error("BOT_TOKEN, API_ID, or API_HASH not found in .env file!")
        return

    await ensure_tools()
    
    await app.start()
    logger.info("Bot started via Pyrogram MTProto...")

    if os.path.exists(RESTART_FLAG):
        try:
            with open(RESTART_FLAG, "r") as f:
                data = json.load(f)
            os.remove(RESTART_FLAG)
            chat_id = data.get("chat_id")
            if chat_id:
                await app.send_message(chat_id=chat_id, text="Restarted.")
        except Exception as e:
            logger.error(f"Post-restart notification failed: {e}")

    # Keep running
    import pyrogram
    await pyrogram.idle()
    await app.stop()

if __name__ == "__main__":
    app.run(main())
