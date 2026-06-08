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
import socket
import threading
import platform

import aiohttp
from mutagen.mp4 import MP4, MP4Cover
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.enums import ChatType, ChatAction
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

# Cloudflare Tunnel variables
tunnel_url = None
tunnel_process = None
dashboard_port = 5000

# Conversation state
# {user_id: {"mpd_url": str, "mpd_content": str}}
user_states = {}
download_flags = {}
stopped_flags = {}
user_queues = {}
active_downloads = {}
global_download_semaphore = None

async def process_user_queue(user_id):
    processed_count = 0
    while True:
        task = await user_queues[user_id].get()
        if task is None:
            break
            
        try:
            processed_count += 1
            client = task['client']
            chat_id = task['chat_id']
            show_id = task['show_id']
            mode = task['mode']
            episodes = task['episodes']
            
            await run_batch_download(client, chat_id, user_id, show_id, mode, episodes)
        except Exception as e:
            logger.error(f"Queue error for {user_id}: {e}")
        finally:
            user_queues[user_id].task_done()
            if user_queues[user_id].empty():
                if not stopped_flags.get(user_id, False):
                    if processed_count > 1:
                        await client.send_message(chat_id, "All Completed...")
                    else:
                        await client.send_message(chat_id, "Completed...")
                processed_count = 0
                stopped_flags[user_id] = False

from db import get_shows, save_shows, get_allowed_users, save_allowed_users, get_admins, save_admins, get_all_users, save_all_users, get_pocketfm_auth, save_pocketfm_auth
from dashboard import start_flask




def owner_only(func):
    async def wrapper(client: Client, update):
        user = getattr(update, "from_user", None)
        if not user: return
        user_id = user.id
        if OWNER_IDS and user_id not in OWNER_IDS: return
        
        chat = getattr(update, "chat", None)
        if not chat and hasattr(update, "message") and update.message:
            chat = update.message.chat
        if chat:
            if chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP]: return
            if ALLOWED_CHATS and chat.id not in ALLOWED_CHATS: return
            
        return await func(client, update)
    return wrapper

def admin_or_owner(func):
    async def wrapper(client: Client, update):
        user = getattr(update, "from_user", None)
        if not user: return
        user_id = user.id
        
        is_owner = OWNER_IDS and user_id in OWNER_IDS
        is_admin = user_id in get_admins()
        
        if not (is_owner or is_admin): return
        
        chat = getattr(update, "chat", None)
        if not chat and hasattr(update, "message") and update.message:
            chat = update.message.chat
        if chat:
            if chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP]: return
            if ALLOWED_CHATS and chat.id not in ALLOWED_CHATS: return
                
        return await func(client, update)
    return wrapper

def authorized_only(func):
    async def wrapper(client: Client, update):
        user = getattr(update, "from_user", None)
        if not user: return
        user_id = user.id
        
        chat = getattr(update, "chat", None)
        if not chat and hasattr(update, "message") and update.message:
            chat = update.message.chat
        if not chat: return
        chat_id = chat.id
        
        is_owner = OWNER_IDS and user_id in OWNER_IDS
        allowed = get_allowed_users()
        is_allowed = str(user_id) in allowed and allowed[str(user_id)].get("status") == "active"
        if not (is_owner or is_allowed): return
        
        if chat_id != user_id:
            if ALLOWED_CHATS and chat_id not in ALLOWED_CHATS: return
            
        return await func(client, update)
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


async def download_file(url: str, output_path: str, status_msg: Message = None) -> bool:
    connector = aiohttp.TCPConnector(limit=0, force_close=False, enable_cleanup_closed=True)
    timeout = aiohttp.ClientTimeout(total=600)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    try:
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            async with session.get(url, headers=headers, ssl=SSL_CTX) as response:
                if response.status != 200:
                    if status_msg: await status_msg.edit_text(f"Download failed — HTTP {response.status}")
                    return False

                with open(output_path, "wb") as f:
                    async for chunk in response.content.iter_chunked(262144):
                        f.write(chunk)

        size_mb = round(os.path.getsize(output_path) / 1048576, 2)
        if status_msg: await status_msg.edit_text(f"Downloaded — {size_mb} MB")
        return True

    except Exception as e:
        if status_msg: await status_msg.edit_text(f"Download error: {str(e)[:200]}")
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


async def fix_m4a_duration(input_file: str, output_file: str) -> bool:
    cmd = ["ffmpeg", "-y", "-i", input_file, "-c", "copy", output_file]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        return proc.returncode == 0
    except Exception:
        return False


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

    # Ensure cloudflared
    cf_path = os.path.join(BOT_DIR, "cloudflared.exe" if os.name == "nt" else "cloudflared")
    if not os.path.exists(cf_path):
        logger.info("cloudflared not found.\nDownloading...")
        is_windows = os.name == "nt"
        if is_windows:
            url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
        else:
            url = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64"
        try:
            async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        with open(cf_path, "wb") as f:
                            f.write(await resp.read())
                        if not is_windows:
                            os.chmod(cf_path, 0o755)
        except Exception as e:
            logger.error(f"Error downloading cloudflared: {e}")

def get_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]

def stop_tunnel():
    """Kill existing tunnel process without starting a new one"""
    global tunnel_process, tunnel_url
    if tunnel_process:
        try:
            tunnel_process.terminate()
            tunnel_process.kill()
        except Exception:
            pass
        tunnel_process = None
    tunnel_url = None

def restart_tunnel():
    """Kill existing tunnel and start a new one"""
    stop_tunnel()
    
    cf_path = os.path.join(BOT_DIR, "cloudflared.exe" if os.name == "nt" else "cloudflared")
    if not os.path.exists(cf_path):
        return

    def read_stream(stream):
        global tunnel_url
        for line in iter(stream.readline, b''):
            decoded = line.decode('utf-8', errors='ignore').strip()
            if ".trycloudflare.com" in decoded and not tunnel_url:
                match = re.search(r"https://[a-zA-Z0-9\-]+\.trycloudflare\.com", decoded)
                if match:
                    tunnel_url = match.group(0)
                    logger.info(f"Dashboard available at: {tunnel_url}")

    try:
        global tunnel_process
        tunnel_process = subprocess.Popen(
            [cf_path, "tunnel", "--url", f"http://127.0.0.1:{dashboard_port}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        threading.Thread(target=read_stream, args=(tunnel_process.stdout,), daemon=True).start()
        threading.Thread(target=read_stream, args=(tunnel_process.stderr,), daemon=True).start()
    except Exception as e:
        logger.error(f"Failed to start tunnel: {e}")

def start_cloudflare_tunnel():
    global dashboard_port
    dashboard_port = get_free_port()
    # Start flask in thread
    threading.Thread(target=start_flask, args=(dashboard_port,), daemon=True).start()
    restart_tunnel()


app = Client("drm_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

@app.on_message(group=-1)
async def log_user(client: Client, message: Message):
    chat = message.chat
    if chat and chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        if ALLOWED_CHATS and chat.id not in ALLOWED_CHATS:
            return
            
    user = getattr(message, "from_user", None)
    if user and user.id:
        all_users = get_all_users()
        uid_str = str(user.id)
        
        is_new_user = uid_str not in all_users
        
        current = all_users.get(uid_str, {})
        if not isinstance(current, dict):
            current = {}
            
        today = time.strftime('%Y-%m-%d')
        last_updated = current.get("last_updated")
        
        avatar_path = os.path.join(AVATARS_DIR, f"{uid_str}.jpg")
        needs_avatar_download = not os.path.exists(avatar_path)
        
        if last_updated == today and not needs_avatar_download:
            return
            
        name = user.first_name or ""
        if getattr(user, "last_name", None):
            name += f" {user.last_name}"
        name = name.strip() or "Unknown"
        username = getattr(user, "username", None)
        
        all_users[uid_str] = {"name": name, "username": username, "last_updated": today}
        save_all_users(all_users)

        if is_new_user and ALLOWED_CHATS:
            async def notify_new_user():
                if username:
                    notify_text = (
                        "Someone just started the bot...\n\n"
                        "Name...\n"
                        f"{name}\n\n"
                        "User ID...\n"
                        f"`{user.id}`\n\n"
                        "Username...\n"
                        f"@{username}"
                    )
                else:
                    notify_text = (
                        "Someone just started the bot...\n\n"
                        "Name...\n"
                        f"{name}\n\n"
                        "User ID...\n"
                        f"`{user.id}`"
                    )
                for group_id in ALLOWED_CHATS:
                    try:
                        await client.send_message(group_id, notify_text, disable_web_page_preview=True)
                        break
                    except Exception:
                        pass
            asyncio.create_task(notify_new_user())
            
        if last_updated != today or needs_avatar_download:
            async def download_avatar():
                try:
                    photos = []
                    async for photo in client.get_chat_photos(user.id, limit=1):
                        photos.append(photo)
                    if photos:
                        await client.download_media(photos[0].file_id, file_name=avatar_path)
                except Exception:
                    pass
            asyncio.create_task(download_avatar())



@app.on_message(filters.command("start"))
@authorized_only
async def cmd_start(client: Client, message: Message):
    is_owner = OWNER_IDS and message.from_user.id in OWNER_IDS
    is_admin = message.from_user.id in get_admins()
    
    if message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP] and (is_owner or is_admin):
        has_mp4decrypt = check_tool(MP4DECRYPT_PATH)
        await message.reply_text(
            "BotZilla Downloader\n\n"
            "Commands\n"
            "/dashboard Show Dashboard URL\n"
            "/allow Allow user\n"
            "/remove Remove user\n\n"
            "Owner Only\n"
            "/admin Add admin\n"
            "/radmin Remove admin\n"
            "/update Pull and restart",
            quote=False,
        )
    else:
        name = message.from_user.first_name or "User"
        buyers = get_allowed_users()
        uid_str = str(message.from_user.id)
        buyer_data = buyers.get(uid_str, {})
        
        reply_msg = (
            f"Hey {name}\n\n"
            "Use below command to access bot\n\n"
            "/show_list Get show list\n"
            "/running Check task list"
        )
        
        if buyer_data.get("set_cover"):
            reply_msg += "\n/set_cover Set cover in episode"
        if buyer_data.get("set_artist"):
            reply_msg += "\n/set_artist Set artist in episode"
            
        await message.reply_text(
            reply_msg,
            quote=False,
        )

@app.on_message(filters.command("admin"))
@owner_only
async def cmd_admin(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply_text("Usage: /admin userid", quote=False)
        return
    try:
        user_id = int(message.command[1])
    except ValueError:
        await message.reply_text("Invalid userid.", quote=False)
        return
        
    admins = get_admins()
    if user_id not in admins:
        admins.append(user_id)
        save_admins(admins)
        await message.reply_text(f"User {user_id} is now an Admin...", quote=False)
    else:
        await message.reply_text(f"User {user_id} is already an Admin...", quote=False)

@app.on_message(filters.command("radmin"))
@owner_only
async def cmd_radmin(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply_text("Usage: /radmin userid", quote=False)
        return
    try:
        user_id = int(message.command[1])
    except ValueError:
        await message.reply_text("Invalid userid.", quote=False)
        return
        
    admins = get_admins()
    if user_id in admins:
        admins.remove(user_id)
        save_admins(admins)
        await message.reply_text(f"User {user_id} is removed from Admins...", quote=False)
    else:
        await message.reply_text(f"User {user_id} was not an Admin...", quote=False)

@app.on_message(filters.command(["dash", "dashboard"]))
@admin_or_owner
async def cmd_dash(client: Client, message: Message):
    status_msg = await message.reply_text("Generating new dashboard access...", quote=False)
    restart_tunnel()
    
    for _ in range(30):
        if tunnel_url:
            break
        await asyncio.sleep(1)
        
    if tunnel_url:
        await status_msg.edit_text(f"Dashboard URL...\n\n{tunnel_url}", disable_web_page_preview=True)
    else:
        await status_msg.edit_text("Dashboard URL...\n\nFailed to generate Dashboard URL...")


@app.on_message(filters.command("status"))
@owner_only
async def cmd_status(client: Client, message: Message):
    has_mp4decrypt = check_tool(MP4DECRYPT_PATH)

    await message.reply_text(
        "<b>Status</b>\n\n"
        f"mp4decrypt: {'Ready' if has_mp4decrypt else 'Missing'}\n"
        f"Path: <code>{MP4DECRYPT_PATH}</code>\n\n",
        quote=False,
    )


@app.on_message(filters.command("cancel"))
@authorized_only
async def cmd_cancel(client: Client, message: Message):
    if message.from_user.id in user_states:
        del user_states[message.from_user.id]
    await message.reply_text("Cancelled.", quote=False)


@app.on_message(filters.command("allow"))
@admin_or_owner
async def cmd_allow(client: Client, message: Message):
    args = message.text.split(" ", 2)
    if len(args) < 3:
        await message.reply_text("Try /allow userid name", quote=False)
        return
    try:
        user_id = int(args[1])
    except ValueError:
        await message.reply_text("Invalid userid.", quote=False)
        return
        
    name = args[2].strip().title()
    uid_str = str(user_id)
    allowed = get_allowed_users()
    if uid_str not in allowed:
        allowed[uid_str] = {"name": name, "status": "active"}
        save_allowed_users(allowed)
        await message.reply_text(f"{name}\n<code>{user_id}</code> is now allowed...", quote=False)
    else:
        allowed[uid_str]["name"] = name
        save_allowed_users(allowed)
        await message.reply_text(f"User {user_id} is already allowed, name updated...", quote=False)

@app.on_message(filters.command("remove"))
@admin_or_owner
async def cmd_remove(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply_text("Try /remove userid", quote=False)
        return
    try:
        user_id = int(message.command[1])
    except ValueError:
        await message.reply_text("Invalid userid.", quote=False)
        return
        
    uid_str = str(user_id)
    allowed = get_allowed_users()
    if uid_str in allowed:
        del allowed[uid_str]
        save_allowed_users(allowed)
        await message.reply_text(f"User {user_id} access removed...", quote=False)
    else:
        await message.reply_text(f"User {user_id} was not in the allowed list...", quote=False)

@app.on_message(filters.command("update"))
@owner_only
async def cmd_update(client: Client, message: Message):
    chat_id = message.chat.id
    status_msg = await message.reply_text("Updating Bot...", quote=False)

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
            await status_msg.edit_text("Already up to date...")
            return

        await status_msg.edit_text("Update complete...")
        
        # Install requirements
        pip_proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "pip", "install", "-r", "requirements.txt",
            cwd=BOT_DIR,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await pip_proc.communicate()
        
        with open(RESTART_FLAG, "w") as f:
            json.dump({"chat_id": chat_id}, f)
        
        await asyncio.sleep(1)
        stop_tunnel()
        os.execv(sys.executable, [sys.executable] + sys.argv)

    except Exception as e:
        await status_msg.edit_text(f"Update failed...")


# ── RAW TELEGRAM API (no Pyrogram needed) ──────────────────────
import urllib.request
import urllib.parse

def _tg_raw_send(chat_id, text):
    """Send message via raw Bot API. Returns message_id or None."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    try:
        req = urllib.request.Request(url, data=data)
        resp = urllib.request.urlopen(req, timeout=15)
        result = json.loads(resp.read())
        return result.get("result", {}).get("message_id")
    except Exception as e:
        logger.error(f"_tg_raw_send failed: {e}")
        return None

def _tg_raw_edit(chat_id, message_id, text):
    """Edit message via raw Bot API."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "disable_web_page_preview": "true",
    }).encode()
    try:
        req = urllib.request.Request(url, data=data)
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:
        logger.error(f"_tg_raw_edit failed: {e}")


async def main():
    if not BOT_TOKEN or not API_ID or not API_HASH:
        logger.error("BOT_TOKEN, API_ID, or API_HASH not found in .env file!")
        return

    # ── STEP 0: Instant startup message via raw API ──
    restart_chat_id = None
    restart_msg_id = None
    if os.path.exists(RESTART_FLAG):
        try:
            with open(RESTART_FLAG, "r") as f:
                data = json.load(f)
            restart_chat_id = data.get("chat_id")
            os.remove(RESTART_FLAG)
        except Exception:
            pass

    if restart_chat_id:
        logger.info(f"Sending startup message to {restart_chat_id}...")
        restart_msg_id = _tg_raw_send(restart_chat_id, "Bot is running...")
    elif OWNER_IDS:
        restart_chat_id = OWNER_IDS[0]
        restart_msg_id = _tg_raw_send(restart_chat_id, "Bot is running...")

    # ── STEP 1: Download tools ──
    try:
        await ensure_tools()
    except Exception as e:
        logger.error(f"ensure_tools failed: {e}")

    # ── STEP 2: Start Dashboard tunnel ──
    try:
        start_cloudflare_tunnel()
    except Exception as e:
        logger.error(f"start_cloudflare_tunnel failed: {e}")

    # ── STEP 3: Start Pyrogram ──
    await app.start()
    logger.info("Bot started via Pyrogram MTProto...")

    # ── STEP 4: Edit startup message with dashboard URL ──
    if restart_chat_id and restart_msg_id:
        for _ in range(30):
            if tunnel_url:
                break
            await asyncio.sleep(1)

        if tunnel_url:
            _tg_raw_edit(restart_chat_id, restart_msg_id, f"Bot is running...\n\n{tunnel_url}")
        else:
            _tg_raw_edit(restart_chat_id, restart_msg_id, "Bot is running...\n\nURL not ready yet.\nUse /dashboard later...")

    # Keep running
    import pyrogram
    await pyrogram.idle()
    await app.stop()


import math

def get_show_list_keyboard(shows_list, shows, page=1):
    items_per_page = 10
    total_shows = len(shows_list)
    total_pages = math.ceil(total_shows / items_per_page)
    if total_pages == 0:
        total_pages = 1
    
    start_idx = (page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    
    current_shows = shows_list[start_idx:end_idx]
    
    keyboard = []
    for show in current_shows:
        show_id = shows.get(show, {}).get("id", "0")
        keyboard.append([InlineKeyboardButton(show, callback_data=f"showdt_{show_id}")])
        
    if total_pages > 1:
        nav_row = []
        if page > 1:
            nav_row.append(InlineKeyboardButton("Prev", callback_data=f"showlist_page_{page-1}"))
        
        nav_row.append(InlineKeyboardButton(f"Total {total_shows}", callback_data="ignore"))
        
        if page < total_pages:
            nav_row.append(InlineKeyboardButton("Next", callback_data=f"showlist_page_{page+1}"))
            
        keyboard.append(nav_row)
        
    return InlineKeyboardMarkup(keyboard)

@app.on_message(filters.command("show_list"))
@authorized_only
async def cmd_shows_list(client: Client, message: Message):
    user_id = message.from_user.id
    is_owner = OWNER_IDS and user_id in OWNER_IDS
    shows = get_shows()
    
    if not is_owner:
        allowed_users = get_allowed_users()
        user_allowed = allowed_users.get(str(user_id), {}).get("allowed_shows", [])
        shows = {k: v for k, v in shows.items() if k in user_allowed}
        
    if not shows:
        await message.reply_text("You have no allowed shows...", quote=False)
        return
        
    shows_list = sorted(list(shows.keys()), key=lambda x: x.lower())
    keyboard = get_show_list_keyboard(shows_list, shows, page=1)
    
    await message.reply_text(
        "You can download the episodes of below shows...\n",
        reply_markup=keyboard,
        quote=False
    )

@app.on_callback_query(filters.regex(r"^showlist_page_(\d+)$"))
@authorized_only
async def showlist_pagination(client: Client, query):
    page = int(query.matches[0].group(1))
    user_id = query.from_user.id
    is_owner = OWNER_IDS and user_id in OWNER_IDS
    shows = get_shows()
    
    if not is_owner:
        allowed_users = get_allowed_users()
        user_allowed = allowed_users.get(str(user_id), {}).get("allowed_shows", [])
        shows = {k: v for k, v in shows.items() if k in user_allowed}
        
    shows_list = sorted(list(shows.keys()), key=lambda x: x.lower())
    keyboard = get_show_list_keyboard(shows_list, shows, page=page)
    
    await query.message.edit_text(
        "You can download the episodes of below shows...\n",
        reply_markup=keyboard
    )
    await query.answer()

@app.on_callback_query(filters.regex(r"^ignore$"))
async def ignore_callback(client: Client, query):
    await query.answer()

async def fetch_pocketfm_show_details(show_id: str, curr_ptr: int = 0):
    auth = get_pocketfm_auth()
    
    headers = {
        "Host": "api.pocketfm.com",
        "uid": auth["uid"],
        "version-name": "9.1.3",
        "platform-version": "29",
        "app-version": "2013",
        "authorization": f"Bearer {auth['access_token']}"
    }
    
    url = f"https://api.pocketfm.com/v2/content_api/show.get_details?show_id={show_id}&curr_ptr={curr_ptr}&info_level=full"
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            data = await resp.json()
            
            if data.get("code") == "TOKEN_EXPIRED":
                refresh_url = "https://iam.pocketfm.com/v1/auth/refresh"
                refresh_headers = {
                    "Host": "iam.pocketfm.com",
                    "uid": auth["uid"],
                    "platform": "android",
                    "device-id": auth["device_id"],
                    "app-name": "pocket_fm",
                    "version-name": "9.1.3",
                    "platform-version": "29",
                    "app-version": "2013"
                }
                refresh_payload = {
                    "refresh_token": auth["refresh_token"]
                }
                
                async with session.post(refresh_url, headers=refresh_headers, json=refresh_payload) as r_resp:
                    r_data = await r_resp.json()
                    
                    if "access_token" in r_data and "refresh_token" in r_data:
                        auth["access_token"] = r_data["access_token"]
                        auth["refresh_token"] = r_data["refresh_token"]
                        save_pocketfm_auth(auth)
                        
                        headers["authorization"] = f"Bearer {auth['access_token']}"
                        async with session.get(url, headers=headers) as new_resp:
                            data = await new_resp.json()
                    else:
                        return None
                        
            return data

@app.on_callback_query(filters.regex(r"^showdt_(.+)$"))
@authorized_only
async def show_details_callback(client: Client, query):
    show_id = query.matches[0].group(1)
    await query.message.edit_text("Getting details of selected show...")
    
    data = await fetch_pocketfm_show_details(show_id)
    if not data or data.get("status") != 1:
        await query.message.edit_text("Failed to fetch show details. Please try again.")
        return
        
    result = data.get("result", [{}])[0]
    title = result.get("show_title", "Unknown")
    lang = result.get("language", "Unknown")
    episodes = result.get("episodes_count", 0)
    image_url = result.get("image_url", "")
    
    caption = (
        f"{title}\n\n"
        f"Language - {lang.capitalize()}\n\n"
        f"{episodes} Episodes"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("All Episode", callback_data=f"dlall_{show_id}")],
        [InlineKeyboardButton("Select Episode", callback_data=f"dlsel_{show_id}")]
    ])
    
    try:
        await client.send_photo(
            chat_id=query.message.chat.id,
            photo=image_url,
            caption=caption,
            reply_markup=keyboard
        )
        await query.message.edit_text("Details of selected show...")
    except Exception as e:
        logger.error(f"Failed to send show photo: {e}")
        await query.message.edit_text("Failed to send show details.")

@app.on_callback_query(filters.regex(r"^dlall_(.+)$"))
@authorized_only
async def dlall_callback(client: Client, query):
    show_id = query.matches[0].group(1)
    user_id = query.from_user.id
    
    if user_id not in user_queues:
        user_queues[user_id] = asyncio.Queue(maxsize=3)
        asyncio.create_task(process_user_queue(user_id))
        
    if user_queues[user_id].full():
        await query.answer("Waiting list is full (Max 3)\nPlease wait for current tasks to finish...", show_alert=True)
        return
        
    try:
        await query.message.edit_reply_markup(reply_markup=None)
    except:
        pass
        
    show_name = next((n for n, d in get_shows().items() if d.get("id") == show_id), "Unknown Show")
    await user_queues[user_id].put({"client": client, "chat_id": query.message.chat.id, "show_id": show_id, "show_name": show_name, "mode": "all", "episodes": []})
    
    if download_flags.get(user_id):
        await query.answer(f"Added to waiting list...\nPosition {user_queues[user_id].qsize()}", show_alert=True)
    else:
        await query.answer("Download started...", show_alert=False)

@app.on_callback_query(filters.regex(r"^dlsel_(.+)$"))
@authorized_only
async def dlsel_callback(client: Client, query):
    show_id = query.matches[0].group(1)
    user_id = query.from_user.id
    if user_id not in user_queues:
        user_queues[user_id] = asyncio.Queue(maxsize=3)
        asyncio.create_task(process_user_queue(user_id))
        
    if user_queues[user_id].full():
        await query.answer("Waiting list is full (Max 3)\nPlease wait for current tasks to finish...", show_alert=True)
        return
        
    try:
        await query.message.edit_reply_markup(reply_markup=None)
    except:
        pass
    
    user_states[user_id] = {"step": "ASK_EPISODES", "show_id": show_id}
    await client.send_message(
        query.message.chat.id,
        "Send episode number which you want to download...\n\n"
        "Single 1\n"
        "Multiple 1 10"
    )

@app.on_message(filters.command("running"))
@authorized_only
async def cmd_running(client: Client, message: Message):
    user_id = message.from_user.id
    running_info = active_downloads.get(user_id)
    queue = user_queues.get(user_id)
    
    if not running_info and (not queue or queue.empty()):
        await message.reply_text("No active process to stop...", quote=False)
        return
        
    reply_lines = ["Running and waiting list...\n"]
    
    if running_info:
        reply_lines.append(f"{running_info['show_name']}\n{running_info['remaining']} episode\n")
        
    if queue and not queue.empty():
        for task in list(queue._queue):
            show_name = task.get("show_name", "Unknown Show")
            mode = task.get("mode", "all")
            if mode == "all":
                reply_lines.append(f"{show_name}\nAll episode\n")
            else:
                eps = task.get("episodes", [1, 1])
                reply_lines.append(f"{show_name}\n{eps[1] - eps[0] + 1} episode\n")
                
    await message.reply_text("\n".join(reply_lines).strip(), quote=False)

@app.on_message(filters.command("stop"))
@authorized_only
async def cmd_stop(client: Client, message: Message):
    user_id = message.from_user.id
    if download_flags.get(user_id):
        download_flags[user_id] = False
        stopped_flags[user_id] = True
    
    if user_id in user_queues:
        while not user_queues[user_id].empty():
            try:
                user_queues[user_id].get_nowait()
                user_queues[user_id].task_done()
            except:
                pass
        await message.reply_text("Process stopped and waiting list is cleared...", quote=False)
    else:
        await message.reply_text("No active process to stop...", quote=False)

@app.on_message(filters.command("set_cover"))
@authorized_only
async def cmd_set_cover(client: Client, message: Message):
    uid_str = str(message.from_user.id)
    allowed = get_allowed_users()
    if not allowed.get(uid_str, {}).get("set_cover"):
        return
    user_states[message.from_user.id] = {"step": "ASK_COVER"}
    await message.reply_text("Send the cover photo you want to set for episodes...", quote=False)

@app.on_message(filters.command("set_artist"))
@authorized_only
async def cmd_set_artist(client: Client, message: Message):
    uid_str = str(message.from_user.id)
    allowed = get_allowed_users()
    if not allowed.get(uid_str, {}).get("set_artist"):
        return
    user_states[message.from_user.id] = {"step": "ASK_ARTIST"}
    await message.reply_text("Send the artist name you want to set for episodes...", quote=False)

async def run_batch_download(client, chat_id, user_id, show_id, mode, episodes):
    download_flags[user_id] = True
    try:
        shows = get_shows()
        keys = {}
        for name, data in shows.items():
            if data.get("id") == show_id:
                keys = data.get("keys", {})
                break
                
        if not keys:
            await client.send_message(chat_id, "Keys not found for this show!")
            download_flags[user_id] = False
            return

        data = await fetch_pocketfm_show_details(show_id)
        if not data or data.get("status") != 1:
            await client.send_message(chat_id, "Failed to fetch show details.")
            download_flags[user_id] = False
            return
            
        total_ep = data.get("result", [{}])[0].get("episodes_count", 0)
        
        if mode == "all":
            start_ep = 1
            end_ep = total_ep
            await client.send_message(chat_id, "Downloading all episodes...\n\nIf you want to cancel or stop the process just send /stop")
        else:
            start_ep = episodes[0]
            end_ep = min(episodes[1], total_ep)
            if start_ep == end_ep:
                await client.send_message(chat_id, f"Downloading Ep - {start_ep}\n\nIf you want to cancel or stop the process just send /stop")
            else:
                await client.send_message(chat_id, f"Downloading Ep from {start_ep} - {end_ep}\n\nIf you want to cancel or stop the process just send /stop")
            
        show_name = next((n for n, d in shows.items() if d.get("id") == show_id), "Unknown Show")
        for ep_num in range(start_ep, end_ep + 1):
            active_downloads[user_id] = {"show_name": show_name, "remaining": (end_ep - ep_num + 1)}
            if not download_flags.get(user_id):
                await client.send_message(chat_id, "Stopped")
                download_flags[user_id] = False
                return
                
            data = await fetch_pocketfm_show_details(show_id, ep_num - 1)
            if not data or data.get("status") != 1:
                continue
                
            result = data.get("result", [{}])[0]
            stories = result.get("stories", [])
            if not stories:
                continue
                
            story = stories[0]
            mpd_url = story.get("media_url_enc")
            story_title = story.get("story_title", f"Ep - {ep_num}")
            seq_num = story.get("natural_sequence_number", ep_num)
            
            if not mpd_url:
                await client.send_message(
                    chat_id,
                    f"Ep - {seq_num} was not found\n\n{story_title}\n\nContact Admin"
                )
                continue
                
            status_msg = await client.send_message(chat_id, f"Downloading...\n\n{story_title}")
            
            mpd_content = await fetch_mpd(mpd_url)
            if not mpd_content:
                await status_msg.delete()
                continue
                
            qualities = get_mpd_qualities(mpd_content)
            # Always choose the lowest quality representation
            quality = qualities[0] if qualities else "128k"
            audio_info = parse_mpd(mpd_content, quality)
            if not audio_info:
                await status_msg.delete()
                continue
                
            mpd_base_url = mpd_url.rsplit("/", 1)[0]
            audio_url = f"{mpd_base_url}/{audio_info['file']}"
            
            global global_download_semaphore
            if global_download_semaphore is None:
                global_download_semaphore = asyncio.Semaphore(5)
                
            async with global_download_semaphore:
                work_dir = tempfile.mkdtemp(prefix="drm_")
                try:
                    encrypted_file = os.path.join(work_dir, "encrypted_audio.mp4")
                    
                    if not await download_file(audio_url, encrypted_file, None):
                        await status_msg.delete()
                        continue
                        
                    safe_title = re.sub(r'[\\/*?:"<>|]', "", story_title).strip()
                    if not safe_title:
                        safe_title = f"Ep - {seq_num}"
                    output_name = safe_title
                    decrypted_file = os.path.join(work_dir, f"{output_name}.m4a")
                    
                    success, error_msg = await run_decrypt(MP4DECRYPT_PATH, keys, encrypted_file, decrypted_file)
                    if not success:
                        await status_msg.delete()
                        continue
                        
                    os.remove(encrypted_file)
                    
                    fixed_file = os.path.join(work_dir, f"{output_name}_fixed.m4a")
                    await fix_m4a_duration(decrypted_file, fixed_file)
                    
                    if not os.path.exists(fixed_file):
                        fixed_file = decrypted_file
                    
                    # Add metadata and cover if permitted
                    allowed = get_allowed_users()
                    user_data = allowed.get(str(user_id), {})
                    
                    artist_name = user_data.get("artist_name") if user_data.get("set_artist") else None
                    cover_path = os.path.join(BOT_DIR, "covers", f"{user_id}.jpg")
                    has_cover = os.path.exists(cover_path) and user_data.get("set_cover")

                    audio_duration = 0
                    def inject_metadata():
                        nonlocal audio_duration
                        audio_info_mp4 = MP4(fixed_file)
                        audio_duration = int(audio_info_mp4.info.length)
                        audio_info_mp4["\xa9nam"] = story_title
                        if artist_name:
                            audio_info_mp4["\xa9ART"] = artist_name
                        if has_cover:
                            with open(cover_path, "rb") as f:
                                audio_info_mp4["covr"] = [MP4Cover(f.read(), imageformat=MP4Cover.FORMAT_JPEG)]
                        audio_info_mp4.save()
                        
                    try:
                        await asyncio.to_thread(inject_metadata)
                    except Exception:
                        pass

                    await status_msg.edit_text(f"Uploading...\n\n{story_title}")
                    await client.send_chat_action(chat_id, ChatAction.UPLOAD_AUDIO)
                        
                    await client.send_audio(
                        chat_id=chat_id,
                        audio=fixed_file,
                        duration=audio_duration,
                        caption=story_title,
                        performer=artist_name,
                        title=story_title,
                        thumb=cover_path if has_cover else None,
                        file_name=f"{output_name}.m4a"
                    )
                    await status_msg.delete()
                finally:
                    import shutil
                    shutil.rmtree(work_dir, ignore_errors=True)
        
    except Exception as e:
        logger.error(f"Batch download error: {e}")
    finally:
        download_flags[user_id] = False
        active_downloads.pop(user_id, None)

@app.on_message(filters.command("drm"))
@authorized_only
async def drm_start(client: Client, message: Message):
    if not check_tool(MP4DECRYPT_PATH):
        await message.reply_text(
            "<b>mp4decrypt not found</b>\n"
            f"Expected: <code>{MP4DECRYPT_PATH}</code>\n\n"
            "Download from: https://www.bento4.com/downloads/",
            quote=False,
        )
        return

    user_states[message.from_user.id] = {"step": "ASK_MPD", "user_id": message.from_user.id}
    await message.reply_text(
        "<b>Step 1/2 — MPD URL</b>\n\n"
        "Send the MPD manifest URL.",
        quote=False,
    )


@app.on_message((filters.text | filters.photo) & ~filters.command(["start", "status", "cancel", "stop", "update", "drm", "show_list", "allow", "remove", "dash", "dashboard", "set_cover", "set_artist"]))
@authorized_only
async def handle_text(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in user_states:
        return

    state = user_states[user_id]
    step = state.get("step")
    
    if step == "ASK_COVER":
        if not message.photo:
            await message.reply_text("Please send a valid photo for the cover.")
            return
            
        covers_dir = os.path.join(BOT_DIR, "covers")
        os.makedirs(covers_dir, exist_ok=True)
        cover_path = os.path.join(covers_dir, f"{user_id}.jpg")
        
        await message.download(file_name=cover_path)
        await message.reply_text("Cover photo saved successfully...")
        del user_states[user_id]
        return
        
    if step == "ASK_ARTIST":
        if not message.text:
            await message.reply_text("Please send a valid text for the artist name.")
            return
            
        artist_name = message.text.strip()
        allowed = get_allowed_users()
        uid_str = str(user_id)
        if uid_str in allowed:
            allowed[uid_str]["artist_name"] = artist_name
            save_allowed_users(allowed)
            
        await message.reply_text("Artist name saved successfully...")
        del user_states[user_id]
        return

    if getattr(message, "text", None) is None:
        return
        
    if step == "ASK_EPISODES":
        text = message.text.strip().lower()
        parts = text.replace("single", "").replace("multiple", "").strip().split()
        if not parts:
            await message.reply_text("Invalid episode number...\n\nSend episode number which you want to download...\n\nSingle 1\nMultiple 1 10")
            return
            
        try:
            start_ep = int(parts[0])
            end_ep = int(parts[1]) if len(parts) > 1 else start_ep
            
            show_id = state["show_id"]
            data = await fetch_pocketfm_show_details(show_id)
            if not data or data.get("status") != 1:
                await message.reply_text("Failed to fetch show details. Cannot validate.")
                del user_states[user_id]
                return
                
            total_ep = data.get("result", [{}])[0].get("episodes_count", 0)
            if end_ep > total_ep or start_ep < 1:
                await message.reply_text("Invalid episode number...\n\nSend episode number which you want to download...\n\nSingle 1\nMultiple 1 10")
                return
                
            if user_id not in user_queues:
                user_queues[user_id] = asyncio.Queue(maxsize=3)
                asyncio.create_task(process_user_queue(user_id))
                
            if user_queues[user_id].full():
                await message.reply_text("Waiting list is full (Max 3)\nPlease wait for current tasks to finish...")
                del user_states[user_id]
                return
                
            show_name = next((n for n, d in get_shows().items() if d.get("id") == show_id), "Unknown Show")
            await user_queues[user_id].put({"client": client, "chat_id": message.chat.id, "show_id": show_id, "show_name": show_name, "mode": "select", "episodes": [start_ep, end_ep]})
            
            if download_flags.get(user_id):
                await message.reply_text(f"Added to waiting list...\nPosition {user_queues[user_id].qsize()}")
                
            del user_states[user_id]
        except:
            await message.reply_text("Invalid episode number...\n\nSend episode number which you want to download...\n\nSingle 1\nMultiple 1 10")
            return

    if step == "ASK_MPD":
        mpd_url = message.text.strip()
        if not mpd_url.startswith("http"):
            await message.reply_text("Invalid URL. Send a valid MPD URL starting with http/https.", quote=False)
            return

        status_msg = await message.reply_text("Fetching MPD manifest...", quote=False)
        mpd_content = await fetch_mpd(mpd_url)
        
        if not mpd_content:
            await status_msg.edit_text("Failed to fetch MPD. Check the URL and try again.")
            return

        state["mpd_url"] = mpd_url
        state["mpd_content"] = mpd_content
        
        shows = get_shows()
        is_owner = OWNER_IDS and user_id in OWNER_IDS
        
        if not is_owner:
            allowed_users = get_allowed_users()
            user_allowed = allowed_users.get(str(user_id), {}).get("allowed_shows", [])
            shows = {k: v for k, v in shows.items() if k in user_allowed}
        
        if not shows:
            if is_owner:
                state["step"] = "ASK_KEYS"
                await status_msg.edit_text(
                    "<b>Step 2/2 — Decryption Keys</b>\n\n"
                    "Send KID:KEY pairs, one per line.\n\n"
                    "Format:\n"
                    "<code>kid1:key1\n"
                    "kid2:key2</code>",
                )
            else:
                await status_msg.edit_text("You have no allowed shows for decryption. Access denied.")
                del user_states[user_id]
        else:
            state["step"] = "SELECT_SHOW"
            keyboard = []
            for show_name in shows.keys():
                keyboard.append([InlineKeyboardButton(show_name, callback_data=f"show_{show_name}")])
            if is_owner:
                keyboard.append([InlineKeyboardButton("✍️ Enter Manual Key", callback_data="manual_key")])
            
            await status_msg.edit_text(
                "<b>Step 2/2 — Select Show Key</b>\n\n"
                "Select a saved show to use its keys.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        
    elif step == "ASK_KEYS":
        keys_text = message.text.strip()
        keys = parse_keys_input(keys_text)

        if not keys:
            await message.reply_text("No valid keys found.\nSend in format: <code>kid:key</code>", quote=False)
            return

        state["keys"] = keys
        await process_drm(client, message, state)
        del user_states[user_id]


async def process_drm(client: Client, message: Message, state: dict):
    keys = state["keys"]
    mpd_url = state["mpd_url"]
    mpd_content = state["mpd_content"]
    user_id = state.get("user_id")

    qualities = get_mpd_qualities(mpd_content)
    quality = "128k" if "128k" in qualities else (qualities[0] if qualities else "128k")
    output_name = str(int(time.time()))

    is_owner = OWNER_IDS and user_id in OWNER_IDS
    if is_owner:
        keys_preview = "\n".join([f"  <code>{kid}:{key}</code>" for kid, key in keys.items()])
    else:
        keys_preview = "  <i>[Hidden for security]</i>"
    
    status_msg = await message.reply_text(
        "<b>Starting</b>\n\n"
        f"MPD: <code>{mpd_url[:80]}...</code>\n"
        f"Keys:\n{keys_preview}\n"
        f"Quality: <code>{quality}</code>\n"
        f"Output: <code>{output_name}</code>\n\n"
        "Processing...",
        quote=False,
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
        
        fixed_file = os.path.join(work_dir, f"{output_name}_fixed.m4a")
        await status_msg.edit_text("[4/5] Fixing stream headers...")
        
        # Extremely fast 0.5s remux to fix DASH fmp4 structure (adds moov atom with duration)
        await fix_m4a_duration(decrypted_file, fixed_file)
        
        if not os.path.exists(fixed_file):
            fixed_file = decrypted_file

        await status_msg.edit_text("[5/5] Uploading as Audio...")

        audio_duration = 0
        try:
            audio_info = MP4(fixed_file)
            audio_duration = int(audio_info.info.length)
        except Exception as ex:
            logger.warning(f"Could not extract duration: {ex}")

        # Upload using extracted duration
        await message.reply_audio(
            audio=fixed_file,
            duration=audio_duration,
            caption=f"<b>{output_name}.m4a</b> ({decrypted_size} MB) | {quality}",
        )

        result_text = (
            f"<b>Done</b>\n\n"
            f"{output_name}.m4a — {decrypted_size} MB\n"
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


@app.on_callback_query()
@authorized_only
async def handle_callback(client: Client, query):
    user_id = query.from_user.id
    if user_id not in user_states:
        await query.answer("Session expired.", show_alert=True)
        return
        
    state = user_states[user_id]
    if state.get("step") != "SELECT_SHOW":
        await query.answer("Invalid step.", show_alert=True)
        return
        
    data = query.data
    if data == "manual_key":
        state["step"] = "ASK_KEYS"
        await query.edit_message_text(
            "<b>Step 2/2 — Decryption Keys</b>\n\n"
            "Send KID:KEY pairs, one per line.\n\n"
            "Format:\n"
            "<code>kid1:key1\n"
            "kid2:key2</code>",
        )
    elif data.startswith("show_"):
        show_name = data.split("show_", 1)[1]
        shows = get_shows()
        if show_name in shows:
            keys = shows[show_name]["keys"]
            if not keys:
                await query.answer("Selected show has no keys saved!", show_alert=True)
                return
            
            await query.edit_message_text(f"Selected: <b>{show_name}</b>\nStarting decryption...")
            
            state["keys"] = keys
            del user_states[user_id]
            
            await process_drm(client, query.message, state)
        else:
            await query.answer("Show not found in dashboard!", show_alert=True)

if __name__ == "__main__":
    try:
        app.run(main())
    except Exception as e:
        logger.error(f"FATAL CRASH: {e}")
        import traceback
        crash_info = traceback.format_exc()
        logger.error(crash_info)
        try:
            with open(os.path.join(BOT_DIR, "crash.log"), "w") as f:
                f.write(crash_info)
        except:
            pass
        # Notify owner about crash via raw API
        if OWNER_IDS:
            _tg_raw_send(OWNER_IDS[0], f"Bot CRASHED!\n\n{str(e)[:500]}")
