import re

with open('bot.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace('<body>\n    <div class="action-bar">', '<body>\n    <div id="main-page">\n        <div class="action-bar">')

content = content.replace('    <!-- DELETE POPUP -->', '''    </div>

    <!-- USER SHOWS PAGE -->
    <div id="user-shows-page" style="display: none; height: 100vh; flex-direction: column;">
        <div class="action-bar" style="justify-content: flex-start; gap: 15px;">
            <div class="navbar-icon" onclick="closeUserShows()" style="cursor: pointer;">
                <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m15 18-6-6 6-6"/></svg>
            </div>
            <div class="navbar-title" id="userShowsTitle">User Name</div>
        </div>
        <div class="tabs-container">
            <div class="tab user-shows-tab active" onclick="switchUserShowsTab('allowed-shows-tab', event)">Allowed Shows</div>
            <div class="tab user-shows-tab" onclick="switchUserShowsTab('total-shows-tab', event)">Total Shows</div>
        </div>
        <div class="container" style="flex: 1; overflow-y: auto; padding-bottom: 80px;">
            <div id="allowed-shows-tab" class="user-shows-tab-content tab-content active">
                <div class="item-list" id="allowedShowsList"></div>
            </div>
            <div id="total-shows-tab" class="user-shows-tab-content tab-content">
                <div class="item-list" id="totalShowsList"></div>
            </div>
        </div>
        <div style="position: fixed; bottom: 0; left: 0; width: 100%; padding: 15px; background: #f0f2f5; box-sizing: border-box;">
            <button onclick="updateUserShows()" class="primary-btn">Update</button>
        </div>
    </div>

    <!-- DELETE POPUP -->''')

content = content.replace('</style>', '''        .checkbox { width: 20px; height: 20px; }
        .user-shows-tab-content { display: none; }
        .user-shows-tab-content.active { display: block; }
    </style>''')

old_buyers_js = '''                    const userData = users[uid] || {};
                    const name = data.name || userData.name || 'Unknown';
                    const username = userData.username ? ` @${userData.username}` : '';
                    const initial = name.charAt(0).toUpperCase() || '?';
                    const bgStyle = isPaused ? 'background-color: #ffe6e6;' : '';
                    
                    container.innerHTML += `
                        <div class="list-card" style="${bgStyle}">
                            <div style="display: flex; align-items: center; gap: 15px; flex: 1; overflow: hidden;">'''

new_buyers_js = '''                    const userData = users[uid] || {};
                    const name = data.name || userData.name || 'Unknown';
                    const username = userData.username ? ` @${userData.username}` : '';
                    const initial = name.charAt(0).toUpperCase() || '?';
                    const bgStyle = isPaused ? 'background-color: #ffe6e6;' : '';
                    const allowedCount = (data.allowed_shows || []).length;
                    
                    container.innerHTML += `
                        <div class="list-card" style="${bgStyle}; cursor: pointer;" onclick="openUserShows('${uid}', '${name}')">
                            <div style="display: flex; align-items: center; gap: 15px; flex: 1; overflow: hidden;">'''

content = content.replace(old_buyers_js, new_buyers_js)

old_card_end = '''                                    <div class="list-subtitle">${uid}${username}</div>
                                </div>
                            </div>
                            <div class="btn-group">
                                <div class="icon-btn action-btn ${isPaused ? 'paused' : ''}" onclick="toggleBuyer('${uid}')" title="Toggle Access">'''

new_card_end = '''                                    <div class="list-subtitle">${uid}${username}</div>
                                    <div class="list-subtitle" style="margin-top:2px;">${allowedCount} allowed show(s)</div>
                                </div>
                            </div>
                            <div class="btn-group" onclick="event.stopPropagation()">
                                <div class="icon-btn action-btn ${isPaused ? 'paused' : ''}" onclick="toggleBuyer('${uid}')" title="Toggle Access">'''

content = content.replace(old_card_end, new_card_end)

js_funcs = '''
        let currentUserShowsUid = null;
        
        function openUserShows(uid, name) {
            currentUserShowsUid = uid;
            document.getElementById('main-page').style.display = 'none';
            document.getElementById('user-shows-page').style.display = 'flex';
            document.getElementById('userShowsTitle').innerText = name;
            
            Promise.all([fetch('/api/shows').then(r => r.json()), fetch('/api/buyers').then(r => r.json())])
            .then(([shows, buyers]) => {
                const buyer = buyers[uid] || {};
                const allowed = buyer.allowed_shows || [];
                
                const allowedList = document.getElementById('allowedShowsList');
                allowedList.innerHTML = '';
                if (allowed.length === 0) {
                    allowedList.innerHTML = '<div style="padding:10px;text-align:center;color:#666;">0 allowed shows</div>';
                } else {
                    allowed.forEach(showName => {
                        allowedList.innerHTML += `
                            <div class="list-card">
                                <div class="list-title">${showName}</div>
                            </div>`;
                    });
                }
                
                const totalList = document.getElementById('totalShowsList');
                totalList.innerHTML = '';
                Object.keys(shows).forEach(showName => {
                    const isChecked = allowed.includes(showName) ? 'checked' : '';
                    totalList.innerHTML += `
                        <div class="list-card" style="cursor: pointer;" onclick="const cb = document.getElementById('cb_${showName}'); cb.checked = !cb.checked;">
                            <div class="list-title">${showName}</div>
                            <input type="checkbox" id="cb_${showName}" class="checkbox" value="${showName}" ${isChecked} onclick="event.stopPropagation()">
                        </div>`;
                });
            });
        }
        
        function closeUserShows() {
            document.getElementById('user-shows-page').style.display = 'none';
            document.getElementById('main-page').style.display = 'block';
            currentUserShowsUid = null;
            loadBuyers();
        }
        
        function switchUserShowsTab(tabId, event) {
            document.querySelectorAll('#user-shows-page .user-shows-tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('#user-shows-page .user-shows-tab-content').forEach(t => t.classList.remove('active'));
            event.currentTarget.classList.add('active');
            document.getElementById(tabId).classList.add('active');
        }
        
        function updateUserShows() {
            if (!currentUserShowsUid) return;
            const checkboxes = document.querySelectorAll('#totalShowsList .checkbox');
            const newAllowed = [];
            checkboxes.forEach(cb => {
                if (cb.checked) newAllowed.push(cb.value);
            });
            
            fetch(`/api/buyers/${currentUserShowsUid}/shows`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(newAllowed)
            }).then(r => r.json()).then(res => {
                if(res.success) {
                    closeUserShows();
                } else {
                    alert('Failed to update allowed shows');
                }
            });
        }
'''

content = content.replace('function loadShows() {', js_funcs + '\n        function loadShows() {')

with open('bot.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("UI Updated successfully!")
