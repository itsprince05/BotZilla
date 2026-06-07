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
from pyrogram.enums import ChatType
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

from flask import Flask, request, jsonify, render_template_string, send_file
import threading

flask_app = Flask(__name__)
import logging
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

SHOWS_FILE = os.path.join(BOT_DIR, "shows.json")
ALLOWED_USERS_FILE = os.path.join(BOT_DIR, "allowed_users.json")
ALL_USERS_FILE = os.path.join(BOT_DIR, "all_users.json")
AVATARS_DIR = os.path.join(BOT_DIR, "avatars")
ADMINS_FILE = os.path.join(BOT_DIR, "admins.json")
os.makedirs(AVATARS_DIR, exist_ok=True)

HTML_TEMPLATE = ""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>BotZilla Dashboard</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
        body { font-family: 'Outfit', sans-serif; background-color: #f0f2f5; margin: 0; padding: 0; color: #1c1e21; -webkit-user-select: none; user-select: none; }
        .action-bar { position: sticky; top: 0; z-index: 100; box-sizing: border-box; height: 48px; background: #2481cc; color: white; padding: 0 10px; gap: 10px; display: flex; align-items: center; }
        .navbar-icon { width: 32px; height: 32px; border-radius: 50%; display: flex; align-items: center; justify-content: center; background: white; color: #2481cc; cursor: pointer; flex-shrink: 0; }
        .navbar-title { font-size: 18px; font-weight: 600; letter-spacing: 0.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .tabs-container { display: flex; background: #fff; border-bottom: 1px solid #e0e0e0; }
        .tab { flex: 1; text-align: center; padding: 12px 0; font-weight: 600; color: #666; cursor: pointer; border-bottom: 2px solid transparent; transition: 0.2s; }
        .tab:hover { background: #f8f9fa; }
        .tab.active { color: #2481cc; background: #eef5fb; border-bottom: 2px solid #2481cc; }
        .container { max-width: 800px; margin: 0 auto; padding: 15px; }
        .tab-content { display: none; }
        .tab-content.active { display: block; }
        .card { background: #ffffff; border-radius: 10px; padding: 10px; border: 1px solid #e0e0e0; margin-bottom: 15px; display: flex; flex-direction: column; gap: 10px; }
        .card h3 { margin-top: 0; font-size: 16px; color: #1c1e21; margin-bottom: 5px; }
        input, textarea { width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 10px; box-sizing: border-box; font-family: inherit; font-size: 14px; outline: none; }
        input:focus, textarea:focus { border-color: #2481cc; }
        textarea::-webkit-scrollbar { display: none; }
        textarea { -ms-overflow-style: none; scrollbar-width: none; }
        .primary-btn { width: 100%; padding: 12px; background: #2481cc; color: white; border: none; border-radius: 10px; font-weight: 600; font-size: 15px; cursor: pointer; }
        .primary-btn:hover { background: #1e6eb0; }
        .item-list { display: flex; flex-direction: column; gap: 10px; }
        .list-card { background: #ffffff; border-radius: 10px; padding: 10px; border: 1px solid #e0e0e0; display: flex; justify-content: space-between; align-items: center; cursor: pointer; transition: 0.2s; }
        .list-card:active { background: #f8f9fa; }
        .list-title { font-weight: 600; font-size: 15px; color: #1c1e21; }
        .list-subtitle { font-size: 13px; color: #666; margin-top: 5px; }
        .btn-group { display: flex; gap: 10px; align-items: center; }
        .icon-btn { display: flex; justify-content: center; align-items: center; cursor: pointer; width: 36px; height: 36px; border-radius: 50%; flex-shrink: 0; padding: 0; margin: 0; }
        .icon-btn svg { display: block; margin: auto; }
        .delete-btn { background: #fff5f5; color: #fa5252; }
        .action-btn { background: #fff5f5; color: #fa5252; }
        .action-btn.paused { background: #e6ffe6; color: #2b8a3e; }
        
        .checkbox-wrapper { display: flex; align-items: center; justify-content: center; width: 36px; height: 36px; }
        .checkbox-wrapper input[type="checkbox"] { width: 20px; height: 20px; cursor: pointer; accent-color: #2481cc; }

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

<div id="main-view">
    <div class="action-bar">
        <div class="navbar-icon">
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m12 14 9-5-9-5-9 5 9 5z"/><path d="m12 14-9-5 9-5 9 5-9 5z"/><path d="m12 14 9-5-9-5-9 5 9 5z"/><path d="m12 21 9-5-9-5-9 5 9 5z"/><path d="m12 21-9-5 9-5 9 5-9 5z"/></svg>
        </div>
        <div class="navbar-title">BotZilla Dashboard</div>
    </div>
    
    <div class="tabs-container">
        <div class="tab active" onclick="switchTab('shows', event)">Shows</div>
        <div class="tab" onclick="switchTab('buyers', event)">Buyers</div>
        <div class="tab" onclick="switchTab('users', event)">Users</div>
    </div>
    
    <div class="container">
        <div id="shows" class="tab-content active">
            <div class="card">
                <h3>Add New Show</h3>
                <form id="addShowForm" style="display: flex; flex-direction: column; gap: 10px;">
                    <textarea id="showName" rows="1" required placeholder="Show Name" style="resize: none; overflow-y: auto; max-height: 90px; box-sizing: border-box;" oninput="this.style.height = 'auto'; this.style.height = Math.min(this.scrollHeight, 90) + 'px'"></textarea>
                    <input type="text" id="showId" placeholder="Show ID (e.g. mpd url)">
                    <textarea id="showKeys" rows="3" required placeholder="KID:KEY&#10;KID:KEY" style="resize: none;"></textarea>
                    <button type="submit" class="primary-btn">Save Show</button>
                </form>
            </div>
            <div class="item-list" id="showsTable"></div>
        </div>
        
        <div id="buyers" class="tab-content">
            <div class="item-list" id="buyersTable"></div>
        </div>
        
        <div id="users" class="tab-content">
            <div class="item-list" id="usersTable"></div>
        </div>
    </div>
</div>

<div id="buyer-view" style="display: none;">
    <div class="action-bar">
        <div class="navbar-icon" onclick="closeBuyerPage()">
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 12H5"/><path d="m12 19-7-7 7-7"/></svg>
        </div>
        <div class="navbar-title" id="buyerPageTitle">User Name</div>
    </div>
    
    <div class="tabs-container">
        <div class="tab active" onclick="switchBuyerTab('allowed-shows', event)">Allowed Shows</div>
        <div class="tab" onclick="switchBuyerTab('total-shows', event)">Total Shows</div>
    </div>
    
    <div class="container" style="padding-bottom: 80px;">
        <div id="allowed-shows" class="tab-content active">
            <div class="item-list" id="allowedShowsTable"></div>
        </div>
        <div id="total-shows" class="tab-content">
            <div class="item-list" id="totalShowsTable"></div>
        </div>
    </div>
    
    <div id="buyer-footer" style="position: fixed; bottom: 0; left: 0; width: 100%; background: #fff; padding: 15px; box-sizing: border-box; border-top: 1px solid #ddd; z-index: 100; display: none;">
        <div style="max-width: 800px; margin: 0 auto;">
            <button class="primary-btn" onclick="saveBuyerShows()">Update</button>
        </div>
    </div>
</div>

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
    let globalShows = {};
    let globalBuyers = {};
    let globalUsers = {};
    let currentBuyerId = null;

    function switchTab(tabId, event) {
        document.querySelectorAll('#main-view .tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('#main-view .tab-content').forEach(t => t.classList.remove('active'));
        event.currentTarget.classList.add('active');
        document.getElementById(tabId).classList.add('active');
        if (tabId === 'shows') loadShows();
        else if (tabId === 'buyers') loadBuyers();
        else if (tabId === 'users') loadUsers();
    }

    function loadShows() {
        fetch('/api/shows').then(r => r.json()).then(shows => {
            globalShows = shows;
            const container = document.getElementById('showsTable');
            container.innerHTML = '';
            Object.entries(shows).forEach(([name, data]) => {
                container.innerHTML += \`
                    <div class="list-card">
                        <div style="flex: 1; overflow: hidden;">
                            <div class="list-title">\${name}</div>
                        </div>
                        <div class="btn-group">
                            <div class="icon-btn delete-btn" onclick="showDeletePopup('\${name}'); event.stopPropagation();">
                                <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 11v6"/><path d="M14 11v6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                            </div>
                        </div>
                    </div>
                \`;
            });
        });
    }

    function loadBuyers() {
        Promise.all([fetch('/api/buyers').then(r => r.json()), fetch('/api/users').then(r => r.json()), fetch('/api/shows').then(r => r.json())])
        .then(([buyers, users, shows]) => {
            globalBuyers = buyers;
            globalUsers = users;
            globalShows = shows;
            const container = document.getElementById('buyersTable');
            container.innerHTML = '';
            Object.entries(buyers).forEach(([uid, data]) => {
                const isPaused = data.status === 'paused';
                const icon = isPaused ? 
                    \`<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>\` : 
                    \`<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>\`;
                
                const userData = users[uid] || {};
                const name = data.name || userData.name || 'Unknown';
                const username = userData.username ? \` @\${userData.username}\` : '';
                const initial = name.charAt(0).toUpperCase() || '?';
                const bgStyle = isPaused ? 'background-color: #ffe6e6;' : '';
                
                const allowedList = data.shows || [];
                const allowedCount = allowedList.length;
                
                container.innerHTML += \`
                    <div class="list-card" style="\${bgStyle}" onclick="openBuyerPage('\${uid}')">
                        <div style="display: flex; align-items: center; gap: 15px; flex: 1; overflow: hidden;">
                            <img src="/api/avatars/\${uid}" style="width: 40px; height: 40px; border-radius: 50%; object-fit: cover; flex-shrink: 0;" onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';" />
                            <div style="display: none; width: 40px; height: 40px; border-radius: 50%; background: #2481cc; color: white; align-items: center; justify-content: center; font-weight: bold; font-size: 18px; flex-shrink: 0;">
                                \${initial}
                            </div>
                            <div style="flex: 1; overflow: hidden;">
                                <div class="list-title">\${name}</div>
                                <div class="list-subtitle">\${uid}\${username}<br/>\${allowedCount} allowed show\${allowedCount !== 1 ? 's' : ''}</div>
                            </div>
                        </div>
                        <div class="btn-group">
                            <div class="icon-btn action-btn \${isPaused ? 'paused' : ''}" onclick="event.stopPropagation(); toggleBuyer('\${uid}')" title="Toggle Access">
                                \${icon}
                            </div>
                        </div>
                    </div>
                \`;
            });
        });
    }

    function loadUsers() {
        Promise.all([fetch('/api/buyers').then(r => r.json()), fetch('/api/users').then(r => r.json())])
        .then(([buyers, users]) => {
            const container = document.getElementById('usersTable');
            container.innerHTML = '';
            Object.entries(users).forEach(([uid, userData]) => {
                const name = userData.name || 'Unknown';
                const username = userData.username ? \` @\${userData.username}\` : '';
                const initial = name.charAt(0).toUpperCase() || '?';
                const isBuyer = !!buyers[uid];
                const bgStyle = isBuyer ? 'background-color: #e6ffe6;' : '';
                
                container.innerHTML += \`
                    <div class="list-card" style="\${bgStyle}">
                        <div style="display: flex; align-items: center; gap: 15px; flex: 1; overflow: hidden;">
                            <img src="/api/avatars/\${uid}" style="width: 40px; height: 40px; border-radius: 50%; object-fit: cover; flex-shrink: 0;" onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';" />
                            <div style="display: none; width: 40px; height: 40px; border-radius: 50%; background: #2481cc; color: white; align-items: center; justify-content: center; font-weight: bold; font-size: 18px; flex-shrink: 0;">
                                \${initial}
                            </div>
                            <div style="flex: 1; overflow: hidden;">
                                <div class="list-title">\${name}</div>
                                <div class="list-subtitle">\${uid}\${username}</div>
                            </div>
                        </div>
                    </div>
                \`;
            });
        });
    }

    // BUYER PAGE LOGIC
    function openBuyerPage(uid) {
        currentBuyerId = uid;
        const buyer = globalBuyers[uid];
        const userData = globalUsers[uid] || {};
        document.getElementById('buyerPageTitle').innerText = buyer.name || userData.name || uid;
        document.getElementById('main-view').style.display = 'none';
        document.getElementById('buyer-view').style.display = 'block';
        
        switchBuyerTab('allowed-shows', {currentTarget: document.querySelector('#buyer-view .tab:nth-child(1)')});
    }
    
    function closeBuyerPage() {
        currentBuyerId = null;
        document.getElementById('buyer-view').style.display = 'none';
        document.getElementById('main-view').style.display = 'block';
        loadBuyers();
    }
    
    function switchBuyerTab(tabId, event) {
        document.querySelectorAll('#buyer-view .tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('#buyer-view .tab-content').forEach(t => t.classList.remove('active'));
        if (event && event.currentTarget) event.currentTarget.classList.add('active');
        document.getElementById(tabId).classList.add('active');
        
        const footer = document.getElementById('buyer-footer');
        if (tabId === 'total-shows') {
            footer.style.display = 'block';
            renderTotalShows();
        } else {
            footer.style.display = 'none';
            renderAllowedShows();
        }
    }
    
    function renderAllowedShows() {
        const container = document.getElementById('allowedShowsTable');
        container.innerHTML = '';
        const buyer = globalBuyers[currentBuyerId] || {};
        const allowedList = buyer.shows || [];
        
        if (allowedList.length === 0) {
            container.innerHTML = '<div style="text-align:center; color:#666; padding: 20px;">No allowed shows</div>';
            return;
        }
        
        allowedList.forEach(showName => {
            container.innerHTML += \`
                <div class="list-card" style="cursor: default;">
                    <div style="flex: 1; overflow: hidden;">
                        <div class="list-title">\${showName}</div>
                    </div>
                </div>
            \`;
        });
    }
    
    function renderTotalShows() {
        const container = document.getElementById('totalShowsTable');
        container.innerHTML = '';
        const buyer = globalBuyers[currentBuyerId] || {};
        const allowedSet = new Set(buyer.shows || []);
        
        Object.entries(globalShows).forEach(([name, data]) => {
            const isChecked = allowedSet.has(name) ? 'checked' : '';
            container.innerHTML += \`
                <div class="list-card" onclick="toggleCheckbox(this)">
                    <div style="flex: 1; overflow: hidden;">
                        <div class="list-title">\${name}</div>
                    </div>
                    <div class="checkbox-wrapper" onclick="event.stopPropagation()">
                        <input type="checkbox" class="show-checkbox" value="\${name}" \${isChecked} onchange="event.stopPropagation()">
                    </div>
                </div>
            \`;
        });
    }
    
    function toggleCheckbox(element) {
        const cb = element.querySelector('input[type="checkbox"]');
        cb.checked = !cb.checked;
    }
    
    function saveBuyerShows() {
        if (!currentBuyerId) return;
        const checkboxes = document.querySelectorAll('#totalShowsTable .show-checkbox');
        const selected = Array.from(checkboxes).filter(cb => cb.checked).map(cb => cb.value);
        
        fetch('/api/buyers/' + currentBuyerId + '/shows', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({shows: selected})
        }).then(r => r.json()).then(res => {
            if(res.success) {
                globalBuyers[currentBuyerId].shows = selected;
                alert('Saved successfully!');
            }
        });
    }

    document.getElementById('addShowForm').onsubmit = function(e) {
        e.preventDefault();
        const btn = this.querySelector('button');
        const origText = btn.innerText;
        btn.innerText = 'Saving...';
        
        const name = document.getElementById('showName').value;
        const id = document.getElementById('showId').value;
        const keys = document.getElementById('showKeys').value;
        
        fetch('/api/shows', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({name, id, keys})
        }).then(r => r.json()).then(res => {
            if(res.success) {
                document.getElementById('showName').value = '';
                document.getElementById('showId').value = '';
                document.getElementById('showKeys').value = '';
                loadShows();
            }
            btn.innerText = origText;
        });
    };

    function toggleBuyer(uid) {
        fetch('/api/buyers/' + uid + '/toggle', {method: 'POST'})
        .then(r => r.json())
        .then(() => loadBuyers());
    }

    let itemToDelete = null;
    let deleteTimer = null;
    function showDeletePopup(name) {
        itemToDelete = name;
        document.getElementById('delete-popup').style.display = 'flex';
        const btn = document.getElementById('delete-btn-submit');
        btn.innerText = 'Wait (3)';
        btn.disabled = true;
        btn.style.opacity = '0.5';
        
        let count = 3;
        deleteTimer = setInterval(() => {
            count--;
            if (count > 0) {
                btn.innerText = \`Wait (\${count})\`;
            } else {
                clearInterval(deleteTimer);
                btn.innerText = 'Delete';
                btn.disabled = false;
                btn.style.opacity = '1';
            }
        }, 1000);
    }
    function hideDeletePopup() {
        document.getElementById('delete-popup').style.display = 'none';
        itemToDelete = null;
        if (deleteTimer) clearInterval(deleteTimer);
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
    loadBuyers();
    loadUsers();
</script>
</body>
</html>
""

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

def get_allowed_users():
    if not os.path.exists(ALLOWED_USERS_FILE):
        return {}
    with open(ALLOWED_USERS_FILE, 'r') as f:
        try:
            data = json.load(f)
            if isinstance(data, list):
                return {str(uid): {"name": "Unknown", "status": "active"} for uid in data}
            return data
        except:
            return {}

def save_allowed_users(users):
    with open(ALLOWED_USERS_FILE, 'w') as f:
        json.dump(users, f, indent=4)

def get_admins():
    if not os.path.exists(ADMINS_FILE):
        return []
    with open(ADMINS_FILE, 'r') as f:
        try:
            return json.load(f)
        except:
            return []

def save_admins(admins):
    with open(ADMINS_FILE, 'w') as f:
        json.dump(admins, f, indent=4)

def get_all_users():
    if not os.path.exists(ALL_USERS_FILE):
        return {}
    with open(ALL_USERS_FILE, 'r') as f:
        try:
            data = json.load(f)
            for k, v in data.items():
                if isinstance(v, str):
                    data[k] = {"name": v, "username": None}
            return data
        except:
            return {}

def save_all_users(users):
    with open(ALL_USERS_FILE, 'w') as f:
        json.dump(users, f, indent=4)

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
    shows = get_shows()
    sanitized = {name: {} for name in shows.keys()}
    return jsonify(sanitized)

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

@flask_app.route('/api/buyers', methods=['GET'])
def api_get_buyers():
    buyers = get_allowed_users()
    owner_str_ids = [str(x) for x in OWNER_IDS]
    filtered_buyers = {k: v for k, v in buyers.items() if k not in owner_str_ids}
    return jsonify(filtered_buyers)

@flask_app.route('/api/buyers/<userid>/toggle', methods=['POST'])
def api_toggle_buyer(userid):
    allowed = get_allowed_users()
    if userid in allowed:
        curr = allowed[userid].get("status", "active")
        allowed[userid]["status"] = "paused" if curr == "active" else "active"
        save_allowed_users(allowed)
        return jsonify({"success": True})
    return jsonify({"success": False})

@flask_app.route('/api/buyers/<userid>/shows', methods=['POST'])
def api_update_buyer_shows(userid):
    data = request.json
    shows_list = data.get('shows', [])
    allowed = get_allowed_users()
    if userid in allowed:
        allowed[userid]["shows"] = shows_list
        save_allowed_users(allowed)
        return jsonify({"success": True})
    return jsonify({"success": False})

@flask_app.route('/api/users', methods=['GET'])
def api_get_users():
    users = get_all_users()
    owner_str_ids = [str(x) for x in OWNER_IDS]
    filtered_users = {k: v for k, v in users.items() if k not in owner_str_ids}
    return jsonify(filtered_users)

@flask_app.route('/api/avatars/<uid>')
def api_get_avatar(uid):
    avatar_path = os.path.join(AVATARS_DIR, f"{uid}.jpg")
    if os.path.exists(avatar_path):
        return send_file(avatar_path, mimetype='image/jpeg')
    return "", 404

def start_flask(port):
    flask_app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)



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
                notify_text = (
                    "Someone just started the bot...\n\n"
                    "Name...\n"
                    f"{name}\n\n"
                    "User ID...\n"
                    f"`{user.id}`"
                )
                if username:
                    notify_text += f"\n\nUsername...\n@{username}"
                    
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
            "<b>Widevine DRM Downloader (Pyrogram)</b>\n\n"
            f"mp4decrypt: {'Ready' if has_mp4decrypt else 'Not Found'}\n"
            f"Dashboard: {tunnel_url if tunnel_url else 'Starting...'}\n\n"
            "<b>Commands</b>\n"
            "/drm — Start download\n"
            "/dash — Show Dashboard URL\n"
            "/allow — Allow user\n"
            "/remove — Remove user\n"
            "/cancel — Cancel operation\n\n"
            "<b>Owner Only</b>\n"
            "/admin — Add admin\n"
            "/radmin — Remove admin\n"
            "/status — Check tools\n"
            "/update — Pull and restart",
            quote=False,
        )
    else:
        await message.reply_text(
            "<b>Widevine DRM Downloader</b>\n\n"
            "<b>Commands</b>\n"
            "/drm — Start download\n"
            "/cancel — Cancel operation",
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
        await message.reply_text(f"User {user_id} is now an Admin.", quote=False)
    else:
        await message.reply_text(f"User {user_id} is already an Admin.", quote=False)

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
        await message.reply_text(f"User {user_id} is removed from Admins.", quote=False)
    else:
        await message.reply_text(f"User {user_id} was not an Admin.", quote=False)

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
        await message.reply_text("Usage: /allow userid name", quote=False)
        return
    try:
        user_id = int(args[1])
    except ValueError:
        await message.reply_text("Invalid userid.", quote=False)
        return
        
    name = args[2].strip()
    uid_str = str(user_id)
    allowed = get_allowed_users()
    if uid_str not in allowed:
        allowed[uid_str] = {"name": name, "status": "active"}
        save_allowed_users(allowed)
        await message.reply_text(f"User {name} ({user_id}) is now allowed.", quote=False)
    else:
        allowed[uid_str]["name"] = name
        save_allowed_users(allowed)
        await message.reply_text(f"User {user_id} is already allowed, name updated.", quote=False)

@app.on_message(filters.command("remove"))
@admin_or_owner
async def cmd_remove(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply_text("Usage: /remove userid", quote=False)
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
        await message.reply_text(f"User {user_id} access removed.", quote=False)
    else:
        await message.reply_text(f"User {user_id} was not in the allowed list.", quote=False)

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

        await status_msg.edit_text("Update Complete...")
        
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


@app.on_message(filters.command(["drm", "shows"]))
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


@app.on_message(filters.text & ~filters.command(["start", "status", "cancel", "update", "drm", "shows", "allow", "remove", "dash", "dashboard"]))
@authorized_only
async def handle_text(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in user_states:
        return

    state = user_states[user_id]
    step = state.get("step")

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
        uid_str = str(message.from_user.id)
        is_owner = OWNER_IDS and message.from_user.id in OWNER_IDS
        is_admin = message.from_user.id in get_admins()
        
        if not (is_owner or is_admin):
            allowed = get_allowed_users()
            user_shows = allowed.get(uid_str, {}).get("shows", [])
            shows = {k: v for k, v in shows.items() if k in user_shows}
            
        if not shows and not (is_owner or is_admin):
            await status_msg.edit_text("You don't have access to any shows.")
            del user_states[message.from_user.id]
            return
        
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
            if is_owner or is_admin:
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
