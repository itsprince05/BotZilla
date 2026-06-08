import sys

def main():
    with open('bot.py', 'r', encoding='utf-8') as f:
        lines = f.readlines()

    # Find where flask app stuff starts and ends
    start_idx = -1
    end_idx = -1
    
    for i, line in enumerate(lines):
        if line.startswith('from flask import Flask'):
            start_idx = i
        if line.startswith('def start_flask(port):'):
            end_idx = i + 2 # include the next line and empty line
            break

    if start_idx != -1 and end_idx != -1:
        new_lines = lines[:start_idx] + [
            "from db import (\n",
            "    get_shows, save_shows,\n",
            "    get_allowed_users, save_allowed_users,\n",
            "    get_admins, save_admins,\n",
            "    get_all_users, save_all_users,\n",
            "    get_pocketfm_auth, save_pocketfm_auth\n",
            ")\n",
            "from dashboard import start_flask\n\n"
        ] + lines[end_idx:]
        
        with open('bot.py', 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
            
        print("Successfully refactored bot.py")

if __name__ == '__main__':
    main()
