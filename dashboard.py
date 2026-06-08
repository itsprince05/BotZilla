import os
from flask import Flask, request, jsonify, render_template, send_file
import logging
from db import (
    get_shows, save_shows, get_allowed_users, save_allowed_users,
    get_all_users, save_all_users, parse_keys_input, get_pocketfm_auth
)
import urllib.request
import json
from dotenv import load_dotenv

load_dotenv()
OWNER_IDS = [int(x.strip()) for x in os.getenv("OWNER_IDS", "").split(",") if x.strip()]
BOT_DIR = os.path.dirname(os.path.abspath(__file__))
AVATARS_DIR = os.path.join(BOT_DIR, "avatars")
os.makedirs(AVATARS_DIR, exist_ok=True)

flask_app = Flask(__name__, template_folder=BOT_DIR)
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

@flask_app.route('/')
def index():
    return render_template('dashboard.html')

@flask_app.route('/user/<userid>')
def user_page(userid):
    users = get_all_users()
    buyers = get_allowed_users()
    shows = get_shows()
    
    buyer = buyers.get(userid, {})
    user = users.get(userid, {})
    name = buyer.get("name") or user.get("name") or "Unknown"
    allowed_shows = buyer.get("allowed_shows", [])
    set_cover = buyer.get("set_cover", False)
    set_artist = buyer.get("set_artist", False)
    
    return render_template('user_shows.html', userid=userid, name=name, allowed_shows=sorted(allowed_shows, key=lambda x: x.lower()), all_shows=sorted(list(shows.keys()), key=lambda x: x.lower()), set_cover=set_cover, set_artist=set_artist)

@flask_app.route('/show/<path:name>')
def show_page(name):
    buyers = get_allowed_users()
    users = get_all_users()
    owner_str_ids = [str(x) for x in OWNER_IDS]
    filtered_buyers = {}
    
    for k, v in buyers.items():
        if k not in owner_str_ids:
            user_data = users.get(k, {})
            merged = v.copy()
            merged["name"] = v.get("name") or user_data.get("name") or "Unknown"
            merged["username"] = user_data.get("username") or ""
            filtered_buyers[k] = merged
            
    filtered_buyers = dict(sorted(filtered_buyers.items(), key=lambda item: item[1].get("name", "").lower()))
    return render_template('show_users.html', show_name=name, buyers=filtered_buyers)

@flask_app.route('/api/fetch_show_name', methods=['GET'])
def api_fetch_show_name():
    show_id = request.args.get('show_id')
    if not show_id:
        return jsonify({"success": False})
        
    auth = get_pocketfm_auth()
    url = f"https://api.pocketfm.com/v2/content_api/show.get_details?show_id={show_id}&curr_ptr=0&info_level=full"
    
    def get_req(access_token):
        return urllib.request.Request(url, headers={
            "Host": "api.pocketfm.com",
            "uid": auth.get("uid", ""),
            "version-name": "9.1.3",
            "platform-version": "29",
            "app-version": "2013",
            "authorization": f"Bearer {access_token}"
        })
    
    try:
        try:
            resp = urllib.request.urlopen(get_req(auth.get('access_token', '')), timeout=10)
            data = json.loads(resp.read())
        except Exception as e:
            if hasattr(e, 'read'):
                try:
                    data = json.loads(e.read())
                except:
                    data = {}
            else:
                raise e
                
        if data.get("code") == "TOKEN_EXPIRED":
            refresh_url = "https://iam.pocketfm.com/v1/auth/refresh"
            refresh_payload = json.dumps({"refresh_token": auth.get("refresh_token", "")}).encode('utf-8')
            refresh_req = urllib.request.Request(refresh_url, data=refresh_payload, headers={
                "Host": "iam.pocketfm.com",
                "uid": auth.get("uid", ""),
                "platform": "android",
                "device-id": auth.get("device_id", ""),
                "app-name": "pocket_fm",
                "version-name": "9.1.3",
                "platform-version": "29",
                "app-version": "2013",
                "Content-Type": "application/json"
            }, method='POST')
            
            try:
                r_resp = urllib.request.urlopen(refresh_req, timeout=10)
                r_data = json.loads(r_resp.read())
            except Exception as e:
                if hasattr(e, 'read'):
                    r_data = json.loads(e.read())
                else:
                    raise e
                    
            if "access_token" in r_data and "refresh_token" in r_data:
                auth["access_token"] = r_data["access_token"]
                auth["refresh_token"] = r_data["refresh_token"]
                from db import save_pocketfm_auth
                save_pocketfm_auth(auth)
                
                resp = urllib.request.urlopen(get_req(auth['access_token']), timeout=10)
                data = json.loads(resp.read())
            else:
                return jsonify({"success": False, "error": "Failed to refresh token"})
                
        title = ""
        result = data.get("result", [])
        if result and isinstance(result, list):
            title = result[0].get("show_title", "")
        if title:
            return jsonify({"success": True, "title": title})
        return jsonify({"success": False})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@flask_app.route('/api/shows', methods=['GET'])
def api_get_shows():
    shows = get_shows()
    buyers = get_allowed_users()
    sanitized = {name: {"allowed_count": sum(1 for b in buyers.values() if name in b.get("allowed_shows", []))} for name in shows.keys()}
    return jsonify(sanitized)

@flask_app.route('/api/shows', methods=['POST'])
def api_add_show():
    data = request.json
    name = data.get('name')
    show_id = data.get('id')
    keys_text = data.get('keys_text')
    
    if not name or not show_id or not keys_text:
        return jsonify({"success": False, "error": "All fields are required"})
    
    shows = get_shows()
    keys_dict = parse_keys_input(keys_text)
    
    shows[name] = {
        "id": show_id,
        "keys": keys_dict
    }
    save_shows(shows)
    return jsonify({"success": True})

@flask_app.route('/api/shows/<path:name>', methods=['DELETE'])
def api_delete_show(name):
    shows = get_shows()
    if name in shows:
        del shows[name]
        save_shows(shows)
        
        buyers = get_allowed_users()
        changed = False
        for buyer_id, buyer_data in buyers.items():
            if "allowed_shows" in buyer_data and name in buyer_data["allowed_shows"]:
                buyer_data["allowed_shows"].remove(name)
                changed = True
        
        if changed:
            save_allowed_users(buyers)
            
    return jsonify({"success": True})

@flask_app.route('/api/shows/<path:name>/users', methods=['POST'])
def api_update_show_users(name):
    allowed_users = request.json
    if allowed_users is None:
        allowed_users = []
    
    buyers = get_allowed_users()
    
    for buyer_id, buyer_data in buyers.items():
        if "allowed_shows" not in buyer_data:
            buyer_data["allowed_shows"] = []
            
        if str(buyer_id) in allowed_users:
            if name not in buyer_data["allowed_shows"]:
                buyer_data["allowed_shows"].append(name)
        else:
            if name in buyer_data["allowed_shows"]:
                buyer_data["allowed_shows"].remove(name)
                
    save_allowed_users(buyers)
    return jsonify({"success": True})

@flask_app.route('/api/buyers', methods=['GET'])
def api_get_buyers():
    buyers = get_allowed_users()
    owner_str_ids = [str(x) for x in OWNER_IDS]
    filtered_buyers = {k: v for k, v in buyers.items() if k not in owner_str_ids}
    return jsonify(filtered_buyers)

@flask_app.route('/api/buyers/<userid>/shows', methods=['POST'])
def api_update_buyer_shows(userid):
    allowed_shows = request.json
    if not isinstance(allowed_shows, list):
        return jsonify({"success": False})
        
    allowed = get_allowed_users()
    if userid in allowed:
        allowed[userid]["allowed_shows"] = allowed_shows
        save_allowed_users(allowed)
        return jsonify({"success": True, "shows": allowed_shows})
    return jsonify({"success": False})

@flask_app.route('/api/buyers/<userid>/update_all', methods=['POST'])
def api_update_buyer_all(userid):
    data = request.json
    if not isinstance(data, dict):
        return jsonify({"success": False})
        
    allowed = get_allowed_users()
    if userid in allowed:
        allowed[userid]["allowed_shows"] = data.get("shows", [])
        
        name = data.get("name", "")
        allowed[userid]["name"] = name.title() if name else ""
        
        set_cover = data.get("set_cover", False)
        set_artist = data.get("set_artist", False)
        
        allowed[userid]["set_cover"] = set_cover
        allowed[userid]["set_artist"] = set_artist
        
        if not set_artist and "artist_name" in allowed[userid]:
            del allowed[userid]["artist_name"]
            
        if not set_cover:
            if "has_cover" in allowed[userid]:
                del allowed[userid]["has_cover"]
            cover_path = os.path.join(BOT_DIR, "covers", f"{userid}.jpg")
            if os.path.exists(cover_path):
                try:
                    os.remove(cover_path)
                except:
                    pass
        
        save_allowed_users(allowed)
        return jsonify({"success": True, "shows": data.get("shows", [])})
    return jsonify({"success": False})

@flask_app.route('/api/buyers/<userid>/toggle', methods=['POST'])
def api_toggle_buyer(userid):
    allowed = get_allowed_users()
    if userid in allowed:
        curr = allowed[userid].get("status", "active")
        allowed[userid]["status"] = "paused" if curr == "active" else "active"
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
