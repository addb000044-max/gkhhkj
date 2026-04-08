#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import time
import subprocess
import sys
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

SERVER_NAME = os.environ.get("SERVER_NAME", "server1")
URL = "https://raw.githubusercontent.com/ASKMEB0T-lang/active.txt/main/active.txt"
BOT_SCRIPT = "min.py"
CHECK_INTERVAL = 30
HTTP_PORT = int(os.environ.get("PORT", 8080))

bot_process = None
last_active_servers = None

def log(msg):
    print(f"[{SERVER_NAME}] {time.strftime('%Y-%m-%d %H:%M:%S')} - {msg}", flush=True)

def start_bot():
    global bot_process
    if bot_process is None or bot_process.poll() is not None:
        log("🚀 Starting bot...")
        with open("bot_out.log", "a") as out, open("bot_err.log", "a") as err:
            bot_process = subprocess.Popen(
                [sys.executable, BOT_SCRIPT],
                stdout=out,
                stderr=err,
                start_new_session=True
            )
        log(f"✅ Bot started (PID: {bot_process.pid})")
        time.sleep(2)
        if bot_process.poll() is None:
            log("✅ Bot is running")
        else:
            log("❌ Bot failed to start")
    else:
        log("⚠️ Bot already running")

def stop_bot():
    global bot_process
    if bot_process is not None:
        log("🛑 Stopping bot...")
        bot_process.terminate()
        try:
            bot_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            log("⚠️ Bot not responding, killing...")
            bot_process.kill()
            bot_process.wait()
        bot_process = None
        log("✅ Bot stopped")
    else:
        log("ℹ️ No bot running")

def is_bot_alive():
    return bot_process is not None and bot_process.poll() is None

def get_active_servers():
    """ترجع قائمة بأسماء السيرفرات النشطة من active.txt"""
    for attempt in range(3):
        try:
            timestamp = int(time.time())
            url = f"{URL}?t={timestamp}"
            response = requests.get(url, timeout=10, headers={
                'Cache-Control': 'no-cache',
                'Pragma': 'no-cache'
            })
            response.raise_for_status()
            content = response.text.strip()
            # تقسيم المحتوى إلى أسطر وإزالة الأسطر الفارغة
            servers = [line.strip() for line in content.split('\n') if line.strip()]
            if servers:
                log(f"📥 Active servers: {servers}")
            else:
                log("⚠️ No servers found in active.txt")
            return servers
        except Exception as e:
            log(f"⚠️ Fetch attempt {attempt+1}/3 failed: {e}")
            time.sleep(2)
    log("❌ Could not fetch active.txt. Keeping current state.")
    return None

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b'OK')
    def log_message(self, format, *args):
        pass

def start_health_server():
    try:
        server = HTTPServer(('0.0.0.0', HTTP_PORT), HealthHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        log(f"🌐 Health check server running on port {HTTP_PORT}")
    except Exception as e:
        log(f"⚠️ Failed to start health server: {e}")

log("🚀 Supervisor starting...")
start_health_server()

# جلب القائمة لأول مرة ومقارنة
active_servers = get_active_servers()
if active_servers is not None:
    if SERVER_NAME in active_servers:
        log(f"✅ This server ({SERVER_NAME}) is in active list. Starting bot.")
        start_bot()
    else:
        log(f"⏸️ This server ({SERVER_NAME}) is NOT in active list. Bot will stay stopped.")
        stop_bot()
else:
    log("⚠️ Could not fetch active list. Will retry later. Bot not started.")
    stop_bot()

while True:
    try:
        time.sleep(CHECK_INTERVAL)
        active_servers = get_active_servers()
        if active_servers is not None:
            if SERVER_NAME in active_servers:
                if not is_bot_alive():
                    log("⚠️ Bot not running – starting")
                    start_bot()
                else:
                    # البوت يعمل كما يجب
                    pass
            else:
                if is_bot_alive():
                    log("⏸️ This server is not active, stopping bot...")
                    stop_bot()
                else:
                    # البوت متوقف كما هو مطلوب
                    pass
        else:
            log("⚠️ Failed to fetch active.txt, no changes applied.")
        # مراقبة إضافية: إذا كان البوت يجب أن يعمل لكنه مات فجأة
        if SERVER_NAME in (active_servers if active_servers else []):
            if not is_bot_alive():
                log("🔄 Bot died unexpectedly – restarting...")
                start_bot()
    except KeyboardInterrupt:
        log("👋 Stopping supervisor")
        stop_bot()
        sys.exit(0)
    except Exception as e:
        log(f"💥 Unexpected error: {e}")