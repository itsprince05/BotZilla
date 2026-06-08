import os
import json

BOT_DIR = os.path.dirname(os.path.abspath(__file__))
SHOWS_FILE = os.path.join(BOT_DIR, "shows.json")
ALLOWED_USERS_FILE = os.path.join(BOT_DIR, "allowed_users.json")
ALL_USERS_FILE = os.path.join(BOT_DIR, "all_users.json")
ADMINS_FILE = os.path.join(BOT_DIR, "admins.json")
POCKETFM_AUTH_FILE = os.path.join(BOT_DIR, "pocketfm_auth.json")

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

def get_pocketfm_auth():
    if not os.path.exists(POCKETFM_AUTH_FILE):
        default_auth = {
            "uid": "a5fe3866d35c4094011d4e2d7020a4a3d0d0eef3",
            "device_id": "SBDIHHLLYX3",
            "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJjYXRlZ29yeSI6ImFjY2VzcyIsImRldmljZV9pZCI6IlNCRElISExMWVgzIiwiZXhwaXJ5IjoxNzgwOTgxNjQ4LCJpYXQiOjE3ODA4MDg4NDgsImxvY2FsZSI6IklOIiwicGxhdGZvcm0iOiJhbmRyb2lkIiwicm9sZSI6Ikxpc3RlbmVyIiwidGVuYW50IjoicG9ja2V0X2ZtIiwidWlkIjoiYTVmZTM4NjZkMzVjNDA5NDAxMWQ0ZTJkNzAyMGE0YTNkMGQwZWVmMyIsInZlcnNpb24iOiJ2MiJ9.bjTZL8S-clyUXNLK7PQyoHQ2NRxgygN_i4wDHwnJ0-s",
            "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJjYXRlZ29yeSI6InJlZnJlc2giLCJkZXZpY2VfaWQiOiJTQkRJSEhMTFlYMyIsImV4cGlyeSI6MTc5NTE1ODkxNiwiaWF0IjoxNzc5NjA2OTE2LCJsb2NhbGUiOiJJTiIsInBsYXRmb3JtIjoiYW5kcm9pZCIsInRlbmFudCI6InBvY2tldF9mbSIsInVpZCI6ImE1ZmUzODY2ZDM1YzQwOTQwMTFkNGUyZDcwMjBhNGEzZDBkMGVlZjMiLCJ2ZXJzaW9uIjoidjIifQ.PmsLPVv4KP2vF11cpyh2NZ1-I91h2HRhENJyn-7rhNg"
        }
        with open(POCKETFM_AUTH_FILE, "w") as f:
            json.dump(default_auth, f, indent=4)
        return default_auth
    with open(POCKETFM_AUTH_FILE, "r") as f:
        return json.load(f)

def save_pocketfm_auth(auth_data):
    with open(POCKETFM_AUTH_FILE, "w") as f:
        json.dump(auth_data, f, indent=4)

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
