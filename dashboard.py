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
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background: #0f172a; color: #f8fafc; padding: 2rem; margin: 0; }
        .container { max-width: 800px; margin: 0 auto; }
        .card { background: #1e293b; border-radius: 12px; padding: 2rem; margin-bottom: 2rem; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1); border: 1px solid #334155; }
        h1, h2 { color: #38bdf8; margin-top: 0; }
        .form-group { margin-bottom: 1rem; }
        label { display: block; margin-bottom: 0.5rem; font-weight: 500; color: #cbd5e1; }
        input, textarea { width: 100%; padding: 0.75rem; background: #0f172a; border: 1px solid #334155; border-radius: 6px; color: #f8fafc; font-family: monospace; box-sizing: border-box; }
        input:focus, textarea:focus { outline: none; border-color: #38bdf8; }
        button { background: #0ea5e9; color: white; border: none; padding: 0.75rem 1.5rem; border-radius: 6px; font-weight: 600; cursor: pointer; transition: background 0.2s; }
        button:hover { background: #0284c7; }
        table { width: 100%; border-collapse: collapse; margin-top: 1rem; }
        th, td { padding: 1rem; text-align: left; border-bottom: 1px solid #334155; }
        th { color: #94a3b8; font-weight: 500; }
        .key-text { font-family: monospace; color: #10b981; word-break: break-all; }
        .delete-btn { background: #ef4444; padding: 0.5rem 1rem; }
        .delete-btn:hover { background: #dc2626; }
    </style>
</head>
<body>
    <div class="container">
        <div class="card">
            <h1>BotZilla DRM Dashboard</h1>
            <p style="color: #94a3b8; margin-bottom: 2rem;">Save decryption keys for shows here. The bot will automatically use them when downloading.</p>
            
            <form id="addShowForm">
                <div class="form-group">
                    <label>Show Name</label>
                    <input type="text" id="showName" required placeholder="e.g. Super Yoddha Season 1">
                </div>
                <div class="form-group">
                    <label>Show ID (Optional, for reference)</label>
                    <input type="text" id="showId" placeholder="e.g. 12345">
                </div>
                <div class="form-group">
                    <label>Decryption Keys (kid:key format)</label>
                    <textarea id="decryptionKey" rows="4" required placeholder="kid1:key1&#10;kid2:key2"></textarea>
                </div>
                <button type="submit">Add / Update Show</button>
            </form>
        </div>

        <div class="card">
            <h2>Saved Shows</h2>
            <table>
                <thead>
                    <tr>
                        <th>Show Name</th>
                        <th>Keys</th>
                        <th>Action</th>
                    </tr>
                </thead>
                <tbody id="showsTable">
                    <!-- Shows will be populated here -->
                </tbody>
            </table>
        </div>
    </div>

    <script>
        function loadShows() {
            fetch('/api/shows')
                .then(r => r.json())
                .then(shows => {
                    const tbody = document.getElementById('showsTable');
                    tbody.innerHTML = '';
                    Object.entries(shows).forEach(([name, data]) => {
                        const tr = document.createElement('tr');
                        
                        let keysHtml = '';
                        if (typeof data.keys === 'object') {
                            keysHtml = Object.entries(data.keys).map(([kid, key]) => `<div>${kid}:${key}</div>`).join('');
                        } else {
                            keysHtml = String(data.keys);
                        }
                        
                        tr.innerHTML = `
                            <td>
                                <strong>${name}</strong>
                                <div style="color: #64748b; font-size: 0.875rem; margin-top: 0.25rem;">ID: ${data.id || 'N/A'}</div>
                            </td>
                            <td class="key-text">${keysHtml}</td>
                            <td><button class="delete-btn" onclick="deleteShow('${name}')">Delete</button></td>
                        `;
                        tbody.appendChild(tr);
                    });
                });
        }

        document.getElementById('addShowForm').addEventListener('submit', (e) => {
            e.preventDefault();
            const name = document.getElementById('showName').value;
            const id = document.getElementById('showId').value;
            const keysText = document.getElementById('decryptionKey').value;
            
            fetch('/api/shows', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ name, id, keys_text: keysText })
            }).then(r => r.json()).then(res => {
                if(res.success) {
                    document.getElementById('addShowForm').reset();
                    loadShows();
                } else {
                    alert('Error adding show');
                }
            });
        });

        function deleteShow(name) {
            if(confirm('Delete ' + name + '?')) {
                fetch('/api/shows/' + encodeURIComponent(name), { method: 'DELETE' })
                    .then(() => loadShows());
            }
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
