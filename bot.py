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
from mutagen.mp4 import MP4
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

# Cloudflare Tunnel variables
tunnel_url = None
tunnel_process = None
dashboard_port = 5000

# Conversation state
# {user_id: {"mpd_url": str, "mpd_content": str}}
user_states = {}

from flask import Flask, request, jsonify, render_template_string
import threading

flask_app = Flask(__name__)
import logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

SHOWS_FILE = os.path.join(BOT_DIR, "shows.json")

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>BotZilla Dashboard</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        body { 
            font-family: 'Outfit', sans-serif; 
            background-color: #f0f2f5; 
            margin: 0; padding: 0; 
            color: #1c1e21; 
            -webkit-user-select: none; user-select: none;
        }
        .action-bar { 
            position: sticky; top: 0; z-index: 100; box-sizing: border-box; height: 48px;
            background: #2481cc; color: white; padding: 0 10px; gap: 10px;
            display: flex; align-items: center;
        }
        .navbar-icon { width: 32px; height: 32px; border-radius: 50%; margin-right: 0; display: flex; align-items: center; justify-content: center; background: white; color: #2481cc; }
        .navbar-title { font-size: 18px; font-weight: 600; letter-spacing: 0.5px; }
        
        .container { max-width: 800px; margin: 0 auto; padding: 15px; }
        
        .card { 
            background: #ffffff; border-radius: 10px; padding: 15px; border: 1px solid #e0e0e0; 
            margin-bottom: 15px; display: flex; flex-direction: column; gap: 10px;
        }
        .card h3 { margin-top: 0; font-size: 16px; color: #1c1e21; margin-bottom: 5px; }
        
        input, textarea { width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 10px; box-sizing: border-box; font-family: inherit; font-size: 14px; outline: none; }
        input:focus, textarea:focus { border-color: #2481cc; }
        
        textarea::-webkit-scrollbar { display: none; }
        textarea { -ms-overflow-style: none; scrollbar-width: none; }
        
        .primary-btn { width: 100%; padding: 12px; background: #2481cc; color: white; border: none; border-radius: 10px; font-weight: 600; font-size: 15px; cursor: pointer; }
        .primary-btn:hover { background: #1e6eb0; }
        
        .item-list { display: flex; flex-direction: column; gap: 10px; }
        .show-card { background: #ffffff; border-radius: 10px; padding: 15px; border: 1px solid #e0e0e0; display: flex; justify-content: space-between; align-items: center; }
        .show-title { font-weight: 600; font-size: 15px; color: #1c1e21; }
        .show-id { font-size: 13px; color: #666; margin-top: 5px; }
        .show-keys { font-size: 12px; color: #2481cc; font-family: monospace; background: #eef5fb; padding: 8px; border-radius: 6px; margin-top: 8px; word-break: break-all; }
        
        .delete-btn { display: flex; justify-content: center; align-items: center; cursor: pointer; width: 36px; height: 36px; border-radius: 50%; background: #fff5f5; color: #fa5252; flex-shrink: 0; margin-left: 10px; }
        
        /* DELETE POPUP */
        #delete-popup { display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.5); z-index:9999; align-items:center; justify-content:center; }
        .popup-box { background:#fff; padding:20px; border-radius:12px; width:calc(100% - 40px); max-width:320px; box-sizing:border-box; }
        .popup-box h3 { margin-top:0; color:#1c1e21; }
        .popup-box p { font-size:14px; color:#666; margin-bottom:15px; }
        .popup-btns { display:flex; gap:10px; }
        .popup-btns button { flex:1; padding:12px 15px; border:none; border-radius:10px; cursor:pointer; font-family:inherit; font-weight:600; font-size:15px; }
        .cancel-btn { background:#f0f2f5; color:#333; }
        .confirm-btn { background:#fa5252; color:#fff; }
    </style>
</head>
<body>
    <div class="action-bar">
        <div class="navbar-icon">
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m12 14 9-5-9-5-9 5 9 5z"/><path d="m12 14-9-5 9-5 9 5-9 5z"/><path d="m12 14 9-5-9-5-9 5 9 5z"/><path d="m12 21 9-5-9-5-9 5 9 5z"/><path d="m12 21-9-5 9-5 9 5-9 5z"/></svg>
        </div>
        <div class="navbar-title">BotZilla DRM Dashboard</div>
    </div>
    
    <div class="container">
        <!-- ADD SHOW FORM -->
        <div class="card">
            <h3>Add New Show</h3>
            <form id="addShowForm" style="display: flex; flex-direction: column; gap: 15px;">
                <textarea id="showName" rows="1" required placeholder="Show Name" style="resize: none; overflow-y: auto; max-height: 90px; box-sizing: border-box;" oninput="this.style.height = 'auto'; this.style.height = Math.min(this.scrollHeight, 90) + 'px'"></textarea>
                <input type="text" id="showId" placeholder="Show ID">
                <textarea id="decryptionKey" rows="4" required placeholder="Decryption Keys" style="resize: none;"></textarea>
                <button type="submit" class="primary-btn">Save Show</button>
            </form>
        </div>

        <!-- SAVED SHOWS -->
        <div class="item-list" id="showsTable">
            <!-- Shows will be populated here -->
        </div>
    </div>

    <!-- DELETE POPUP -->
    <div id="delete-popup">
        <div class="popup-box">
            <h3>Confirm Delete</h3>
            <p>Are you sure you want to delete this show?</p>
            <div class="popup-btns">
                <button class="cancel-btn" onclick="hideDeletePopup()">Cancel</button>
                <button id="delete-btn-submit" class="confirm-btn" onclick="confirmDelete()">Delete</button>
            </div>
        </div>
    </div>

    <script>
        function loadShows() {
            fetch('/api/shows')
                .then(r => r.json())
                .then(shows => {
                    const container = document.getElementById('showsTable');
                    container.innerHTML = '';
                    Object.entries(shows).forEach(([name, data]) => {
                        let keysHtml = '';
                        if (typeof data.keys === 'object') {
                            keysHtml = Object.entries(data.keys).map(([kid, key]) => `${kid}:${key}`).join('<br>');
                        } else {
                            keysHtml = String(data.keys);
                        }
                        
                        container.innerHTML += `
                            <div class="show-card">
                                <div style="flex: 1; overflow: hidden;">
                                    <div class="show-title">${name}</div>
                                    <div class="show-id">ID: ${data.id || 'N/A'}</div>
                                    <div class="show-keys">${keysHtml}</div>
                                </div>
                                <div class="delete-btn" onclick="showDeletePopup('${name}')">
                                    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 11v6"/><path d="M14 11v6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                                </div>
                            </div>
                        `;
                    });
                });
        }

        document.getElementById('addShowForm').addEventListener('submit', (e) => {
            e.preventDefault();
            const btn = e.target.querySelector('button');
            const name = document.getElementById('showName').value;
            const id = document.getElementById('showId').value;
            const keysText = document.getElementById('decryptionKey').value;
            
            btn.disabled = true;
            btn.textContent = "Saving...";
            
            fetch('/api/shows', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ name, id, keys_text: keysText })
            }).then(r => r.json()).then(res => {
                btn.disabled = false;
                btn.textContent = "Save Show";
                if(res.success) {
                    document.getElementById('addShowForm').reset();
                    loadShows();
                } else {
                    alert('Error adding show');
                }
            });
        });

        let itemToDelete = null;
        function showDeletePopup(name) {
            itemToDelete = name;
            document.getElementById('delete-popup').style.display = 'flex';
        }

        function hideDeletePopup() {
            document.getElementById('delete-popup').style.display = 'none';
            itemToDelete = null;
        }

        function confirmDelete() {
            if(!itemToDelete) return;
            fetch('/api/shows/' + encodeURIComponent(itemToDelete), { method: 'DELETE' })
                .then(() => {
                    hideDeletePopup();
                    loadShows();
                });
        }

        loadShows();
    </script>
</body>
</html>
"""

def get_shows():
    if not os.path.exists(SHOWS_FILE):
        return {}
    with open(SHOWS_FILE, 'r') as f:
        try:
            return json.load(f)
        except:
            return {}

def save_shows(shows):
    with open(SHOWS_FILE, 'w') as f:
        json.dump(shows, f, indent=4)

def parse_keys_input(text: str) -> dict:
    import re
    keys = {}
    for line in re.split(r'[,\n]+', text):
        line = line.strip()
        if ':' in line:
            parts = line.split(':', 1)
            kid = parts[0].strip().lower()
            key = parts[1].strip().lower()
            keys[kid] = key
    return keys

@flask_app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@flask_app.route('/api/shows', methods=['GET'])
def api_get_shows():
    return jsonify(get_shows())

@flask_app.route('/api/shows', methods=['POST'])
def api_add_show():
    data = request.json
    name = data.get('name')
    if not name:
        return jsonify({"success": False, "error": "Name required"})
    
    shows = get_shows()
    keys_dict = parse_keys_input(data.get('keys_text', ''))
    
    shows[name] = {
        "id": data.get('id', ''),
        "keys": keys_dict
    }
    save_shows(shows)
    return jsonify({"success": True})

@flask_app.route('/api/shows/<name>', methods=['DELETE'])
def api_delete_show(name):
    shows = get_shows()
    if name in shows:
        del shows[name]
        save_shows(shows)
    return jsonify({"success": True})

def start_flask(port):
    flask_app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)



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

                with open(output_path, "wb") as f:
                    async for chunk in response.content.iter_chunked(262144):
                        f.write(chunk)

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
        logger.info("cloudflared not found. Downloading...")
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

def restart_tunnel():
    global tunnel_process, tunnel_url
    if tunnel_process:
        try:
            tunnel_process.terminate()
            tunnel_process.kill()
        except Exception:
            pass
    tunnel_url = None
    
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


@app.on_message(filters.command("start"))
@owner_only
async def cmd_start(client: Client, message: Message):
    has_mp4decrypt = check_tool(MP4DECRYPT_PATH)

    await message.reply_text(
        "<b>Widevine DRM Downloader (Pyrogram)</b>\n\n"
        f"mp4decrypt: {'Ready' if has_mp4decrypt else 'Not Found'}\n"
        f"Dashboard: {tunnel_url if tunnel_url else 'Starting...'}\n\n"
        "<b>Commands</b>\n"
        "/drm — Start download\n"
        "/dash — Show Dashboard URL\n"
        "/status — Check tools\n"
        "/update — Pull and restart\n"
        "/cancel — Cancel operation",
    )

@app.on_message(filters.command(["dash", "dashboard"]))
@owner_only
async def cmd_dash(client: Client, message: Message):
    status_msg = await message.reply_text("Dashboard url...")
    restart_tunnel()
    
    for _ in range(30):
        if tunnel_url:
            break
        await asyncio.sleep(1)
        
    if tunnel_url:
        await status_msg.edit_text(f"Dashboard url...\n\n{tunnel_url}", disable_web_page_preview=True)
    else:
        await status_msg.edit_text("Dashboard url...\n\nFailed to generate Dashboard URL.")


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

        await status_msg.edit_text(f"Pulled.\n<code>{output[:200]}</code>\n\nInstalling requirements...")

        pip_proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "pip", "install", "-r", "requirements.txt",
            cwd=BOT_DIR,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        pip_stdout, pip_stderr = await pip_proc.communicate()
        
        if pip_proc.returncode != 0:
            pip_err = (pip_stderr or pip_stdout).decode(errors="replace").strip()
            await status_msg.edit_text(f"Pip install failed, but restarting anyway...\n<code>{pip_err[:200]}</code>")
            await asyncio.sleep(2)
        else:
            await status_msg.edit_text("Requirements installed.\n\nRestarting...")

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
        
        shows = get_shows()
        
        if not shows:
            state["step"] = "ASK_KEYS"
            await status_msg.edit_text(
                "<b>Step 2/2 — Decryption Keys</b>\n\n"
                "Send KID:KEY pairs, one per line.\n\n"
                "Format:\n"
                "<code>kid1:key1\n"
                "kid2:key2</code>",
            )
        else:
            state["step"] = "SELECT_SHOW"
            keyboard = []
            for show_name in shows.keys():
                keyboard.append([InlineKeyboardButton(show_name, callback_data=f"show_{show_name}")])
            keyboard.append([InlineKeyboardButton("✍️ Enter Manual Key", callback_data="manual_key")])
            
            await status_msg.edit_text(
                "<b>Step 2/2 — Select Show Key</b>\n\n"
                "Select a saved show from the dashboard or enter keys manually.",
                reply_markup=InlineKeyboardMarkup(keyboard)
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
@owner_only
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
            
            mpd_url = state["mpd_url"]
            mpd_content = state["mpd_content"]
            del user_states[user_id]
            
            await process_drm(client, query.message, mpd_url, mpd_content, keys)
        else:
            await query.answer("Show not found in dashboard!", show_alert=True)

async def main():
    if not BOT_TOKEN or not API_ID or not API_HASH:
        logger.error("BOT_TOKEN, API_ID, or API_HASH not found in .env file!")
        return

    await ensure_tools()

    # Start Dashboard tunnel
    start_cloudflare_tunnel()
    
    await app.start()
    logger.info("Bot started via Pyrogram MTProto...")
    await asyncio.sleep(2)

    if os.path.exists(RESTART_FLAG):
        try:
            with open(RESTART_FLAG, "r") as f:
                data = json.load(f)
            
            chat_id = data.get("chat_id")
            if chat_id:
                try:
                    status_msg = await app.send_message(chat_id=int(chat_id), text="Bot is running...")
                    os.remove(RESTART_FLAG)
                except Exception as e:
                    logger.error(f"Failed to send initial restart message: {e}")
                    # Try fallback to first owner
                    if OWNER_IDS:
                        status_msg = await app.send_message(chat_id=OWNER_IDS[0], text="Bot is running...")
                    os.remove(RESTART_FLAG)
                
                for _ in range(30):
                    if tunnel_url:
                        break
                    await asyncio.sleep(1)
                
                if tunnel_url:
                    msg_text = f"Bot is running...\n\n{tunnel_url}"
                else:
                    msg_text = "Bot is running...\n\nURL not ready yet. Use /dashboard later.."
                    
                await status_msg.edit_text(text=msg_text, disable_web_page_preview=True)
            else:
                os.remove(RESTART_FLAG)
        except Exception as e:
            logger.error(f"Post-restart notification failed: {e}")
            try:
                os.remove(RESTART_FLAG)
            except:
                pass

    # Keep running
    import pyrogram
    await pyrogram.idle()
    await app.stop()

if __name__ == "__main__":
    app.run(main())
