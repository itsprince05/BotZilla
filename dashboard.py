from flask import Flask, render_template_string, request, jsonify
import json
import os

app = Flask(__name__)
SHOWS_FILE = os.path.join(os.path.dirname(__file__), "shows.json")

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
        .navbar-icon { width: 32px; height: 32px; border-radius: 50%; margin-right: 12px; display: flex; align-items: center; justify-content: center; background: white; color: #2481cc; }
        .navbar-title { font-size: 18px; font-weight: 600; letter-spacing: 0.5px; }
        
        .container { max-width: 800px; margin: 0 auto; padding: 15px; }
        
        .card { 
            background: #ffffff; border-radius: 10px; padding: 15px; border: 1px solid #e0e0e0; 
            margin-bottom: 15px; display: flex; flex-direction: column; gap: 10px;
        }
        .card h3 { margin-top: 0; font-size: 16px; color: #1c1e21; margin-bottom: 5px; }
        
        input, textarea { width: 100%; padding: 12px; border: 1px solid #ddd; border-radius: 10px; box-sizing: border-box; font-family: inherit; font-size: 14px; outline: none; }
        input:focus, textarea:focus { border-color: #2481cc; }
        
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
            <form id="addShowForm" style="display: flex; flex-direction: column; gap: 10px;">
                <input type="text" id="showName" required placeholder="Show Name (e.g. Super Yoddha S1)">
                <input type="text" id="showId" placeholder="Show ID (Optional)">
                <textarea id="decryptionKey" rows="3" required placeholder="kid:key (one per line)"></textarea>
                <button type="submit" class="primary-btn">Save Show Keys</button>
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
                btn.textContent = "Save Show Keys";
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

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/shows', methods=['GET'])
def api_get_shows():
    return jsonify(get_shows())

@app.route('/api/shows', methods=['POST'])
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

@app.route('/api/shows/<name>', methods=['DELETE'])
def api_delete_show(name):
    shows = get_shows()
    if name in shows:
        del shows[name]
        save_shows(shows)
    return jsonify({"success": True})

def start_flask(port):
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
