#!/bin/bash
# start.sh - PocketFM Bot with Auto Restart Every 5 Hours

# ============================================
# CONFIGURATION
# ============================================
RESTART_INTERVAL_HOURS=5
RESTART_INTERVAL_SECONDS=$((RESTART_INTERVAL_HOURS * 3600))
LOG_FILE="bot.log"

# ============================================
# FUNCTIONS
# ============================================
log_message() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# ============================================
# MAIN LOOP
# ============================================
log_message "=========================================="
log_message "🚀 POCKETFM BOT STARTED"
log_message "⏰ Auto restart every: ${RESTART_INTERVAL_HOURS} hours"
log_message "=========================================="

while true; do
    log_message ""
    log_message "📊 Starting bot session at $(date)"
    log_message "💤 Bot will run for ${RESTART_INTERVAL_HOURS} hours"
    
    # Run bot with timeout (auto restart after interval)
    timeout --preserve-status --signal=SIGINT --kill-after=30s ${RESTART_INTERVAL_SECONDS}s venv/bin/python3 bot.py >> "$LOG_FILE" 2>&1
    
    EXIT_CODE=$?
    
    if [ $EXIT_CODE -eq 0 ]; then
        log_message "✅ Bot completed normally"
    elif [ $EXIT_CODE -eq 124 ] || [ $EXIT_CODE -eq 137 ]; then
        log_message "⏰ Scheduled restart triggered after ${RESTART_INTERVAL_HOURS} hours"
    else
        log_message "⚠️ Bot stopped with exit code: $EXIT_CODE"
    fi
    
    log_message "🔄 Restarting bot in 5 seconds..."
    sleep 5
done
