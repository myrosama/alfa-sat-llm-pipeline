#!/usr/bin/env python3
"""
ALFA SAT — Remote Pipeline Runner with Telegram Bot Control
Runs the full batch (Option 5 style) and reports to Telegram.
Accepts commands: /status, /stop, /start, /progress
"""
import os
import sys
import json
import time
import random
import signal
import subprocess
import threading
import datetime
import requests
from pathlib import Path

# ─── Telegram Bot Config ───
BOT_TOKEN = "8526659713:AAEjjZC-5WKwzUVPk5iNqO-wy_uK-Uo8yzg"
ADMIN_CHAT_ID = "6412992293"
TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# ─── Pipeline Config ───
PIPELINE_SCRIPT = "pipeline.py"
FIX_RUNNER = "fix_runner.py"
PROGRESS_FILE = "progress.json"
USAGE_FILE = "key_usage.json"
OUTPUT_DIR = "output"
PDF_FOLDER = "pdfs"
PYTHON_EXEC = [sys.executable, "-X", "utf8"]

# ─── State ───
is_running = False
should_stop = False
current_pdf = ""
pdfs_done_session = 0
pdfs_total_session = 0
session_start_time = None
last_update_id = 0


def tg_send(text, parse_mode="HTML"):
    """Send a message to the admin via Telegram."""
    try:
        requests.post(f"{TG_API}/sendMessage", json={
            "chat_id": ADMIN_CHAT_ID,
            "text": text,
            "parse_mode": parse_mode
        }, timeout=10)
    except Exception as e:
        print(f"⚠️ TG Send Error: {e}")


def tg_get_updates():
    """Poll for new Telegram commands."""
    global last_update_id
    try:
        resp = requests.get(f"{TG_API}/getUpdates", params={
            "offset": last_update_id + 1,
            "timeout": 1
        }, timeout=5)
        data = resp.json()
        if data.get("ok"):
            return data.get("result", [])
    except:
        pass
    return []


def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except:
            return default
    return default


def get_progress_stats():
    progress = load_json(PROGRESS_FILE, {"completed": [], "failed": []})
    usage = load_json(USAGE_FILE, {})
    total_completed = len(progress.get("completed", []))
    total_failed = len(progress.get("failed", []))

    now_day = datetime.datetime.now().strftime("%Y-%m-%d")
    total_calls_today = 0
    key_stats = []
    for key, data in usage.items():
        if data.get("day") == now_day:
            count = data.get("daily_count", 0)
            total_calls_today += count
            emoji = "🟢" if count < 400 else "🟡" if count < 500 else "🔴"
            key_stats.append(f"  {emoji} ..{key[-6:]}: {count}/500")

    return {
        "completed": total_completed,
        "failed": total_failed,
        "calls_today": total_calls_today,
        "active_keys": len(usage),
        "key_stats": "\n".join(key_stats) if key_stats else "  No usage data yet"
    }


def build_status_message():
    stats = get_progress_stats()
    elapsed = ""
    if session_start_time:
        delta = datetime.datetime.now() - session_start_time
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        elapsed = f"\n⏱ Session uptime: {hours}h {minutes}m {seconds}s"

    eta = ""
    if pdfs_done_session > 0 and session_start_time:
        delta = datetime.datetime.now() - session_start_time
        avg_per_pdf = delta.total_seconds() / pdfs_done_session
        remaining = pdfs_total_session - pdfs_done_session
        eta_secs = avg_per_pdf * remaining
        eta_hours, eta_rem = divmod(int(eta_secs), 3600)
        eta_mins, _ = divmod(eta_rem, 60)
        eta = f"\n📊 ETA: ~{eta_hours}h {eta_mins}m remaining"

    status = "🟢 RUNNING" if is_running else "🔴 STOPPED"
    current = f"\n📄 Current: <b>{current_pdf}</b>" if current_pdf else ""

    return (
        f"<b>🚀 ALFA SAT Pipeline — Remote Status</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Status: {status}{current}\n"
        f"✅ Session: {pdfs_done_session}/{pdfs_total_session} PDFs\n"
        f"🏁 Total completed: {stats['completed']}\n"
        f"❌ Failed: {stats['failed']}\n"
        f"🔑 API calls today: {stats['calls_today']}{elapsed}{eta}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Key Usage:</b>\n{stats['key_stats']}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Commands:</b>\n"
        f"/status — Current status\n"
        f"/stop — Stop after current PDF\n"
        f"/start — Resume processing\n"
        f"/progress — Show detailed progress"
    )


def handle_commands():
    """Background thread to listen for Telegram commands."""
    global should_stop, last_update_id
    while True:
        try:
            updates = tg_get_updates()
            for update in updates:
                last_update_id = update["update_id"]
                msg = update.get("message", {})
                text = msg.get("text", "").strip().lower()
                chat_id = str(msg.get("chat", {}).get("id", ""))

                if chat_id != ADMIN_CHAT_ID:
                    continue

                if text == "/status":
                    tg_send(build_status_message())
                elif text == "/stop":
                    should_stop = True
                    tg_send("⏸ <b>Stopping after current PDF finishes...</b>")
                elif text == "/start":
                    should_stop = False
                    tg_send("▶️ <b>Resuming processing...</b>\n(Will continue with next PDF)")
                elif text == "/progress":
                    progress = load_json(PROGRESS_FILE, {"completed": []})
                    completed = progress.get("completed", [])
                    last_5 = completed[-5:] if len(completed) > 5 else completed
                    msg_text = "<b>📋 Last completed PDFs:</b>\n"
                    for p in last_5:
                        msg_text += f"  ✅ {p}\n"
                    msg_text += f"\n<b>Total: {len(completed)} completed</b>"
                    tg_send(msg_text)
                elif text == "/help":
                    tg_send(build_status_message())
        except Exception as e:
            print(f"Command handler error: {e}")
        time.sleep(2)


def clean_id(pdf_id):
    name = pdf_id.split("@")[0].strip()
    cid = name.lower()
    for char in ["(", ")", "[", "]", ",", ".", "-", "+", "=", "#"]:
        cid = cid.replace(char, "")
    cid = cid.replace(" ", "_")
    while "__" in cid:
        cid = cid.replace("__", "_")
    return cid.strip("_")


def run_pipeline():
    """Main pipeline loop — processes all PDFs with full agent pipeline."""
    global is_running, should_stop, current_pdf, pdfs_done_session, pdfs_total_session, session_start_time

    is_running = True
    session_start_time = datetime.datetime.now()

    progress = load_json(PROGRESS_FILE, {"completed": []})
    completed = set(progress.get("completed", []))

    all_pdfs = [f.stem for f in Path(PDF_FOLDER).glob("*.pdf")]
    available = [p for p in all_pdfs if f"{p}.pdf" not in completed]

    if not available:
        tg_send("🎉 <b>All PDFs are already completed!</b> Nothing to process.")
        is_running = False
        return

    random.shuffle(available)
    pdfs_total_session = len(available)
    pdfs_done_session = 0

    tg_send(
        f"🚀 <b>Pipeline Started!</b>\n"
        f"📄 {pdfs_total_session} PDFs to process\n"
        f"🎲 Random order enabled\n"
        f"⏱ Started at: {session_start_time.strftime('%H:%M:%S')}\n\n"
        f"Send /status anytime to check progress."
    )

    for index, pdf_id in enumerate(available, start=1):
        if should_stop:
            tg_send(f"⏸ <b>Pipeline paused by user.</b>\nCompleted {pdfs_done_session}/{pdfs_total_session} this session.\nSend /start then restart the script to resume.")
            break

        pdf_file = os.path.join(PDF_FOLDER, f"{pdf_id}.pdf")
        cid = clean_id(pdf_id)
        name = pdf_id.split("@")[0].strip()
        current_pdf = f"[{index}/{pdfs_total_session}] {name}"

        # Re-check completion
        current_progress = load_json(PROGRESS_FILE, {"completed": []})
        if f"{pdf_id}.pdf" in current_progress.get("completed", []):
            continue

        print(f"\n{'='*60}")
        print(f"🎲 [{index}/{pdfs_total_session}] Processing: {pdf_id}")
        print(f"{'='*60}")

        tg_send(f"📄 <b>[{index}/{pdfs_total_session}]</b> Processing: <b>{name}</b>")

        # Pass 1: Extraction
        try:
            cmd1 = PYTHON_EXEC + [PIPELINE_SCRIPT, pdf_file, name, cid]
            subprocess.run(cmd1, check=False)
        except Exception as e:
            tg_send(f"❌ Pass 1 failed for {name}: {e}")
            continue

        # Pass 2: Fixes + Images + Validation
        try:
            cmd2 = PYTHON_EXEC + [FIX_RUNNER, "--single", cid]
            subprocess.run(cmd2, check=False)
        except Exception as e:
            tg_send(f"❌ Pass 2 failed for {name}: {e}")

        # Save progress
        current_progress = load_json(PROGRESS_FILE, {"completed": []})
        if f"{pdf_id}.pdf" not in current_progress.get("completed", []):
            current_progress["completed"].append(f"{pdf_id}.pdf")
            with open(PROGRESS_FILE, "w") as f:
                json.dump(current_progress, f, indent=2)

        pdfs_done_session += 1

        # Send progress update every 1 PDF
        stats = get_progress_stats()
        elapsed = datetime.datetime.now() - session_start_time
        avg_per_pdf = elapsed.total_seconds() / pdfs_done_session if pdfs_done_session > 0 else 0
        remaining = pdfs_total_session - pdfs_done_session
        eta_secs = avg_per_pdf * remaining
        eta_hours, eta_rem = divmod(int(eta_secs), 3600)
        eta_mins, _ = divmod(eta_rem, 60)

        tg_send(
            f"✅ <b>Done: {name}</b>\n"
            f"📊 Progress: {pdfs_done_session}/{pdfs_total_session}\n"
            f"🔑 API calls today: {stats['calls_today']}\n"
            f"⏱ ETA: ~{eta_hours}h {eta_mins}m"
        )

    current_pdf = ""
    is_running = False

    final_stats = get_progress_stats()
    elapsed = datetime.datetime.now() - session_start_time
    hours, remainder = divmod(int(elapsed.total_seconds()), 3600)
    minutes, _ = divmod(remainder, 60)

    tg_send(
        f"🎉 <b>Pipeline Complete!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ Processed: {pdfs_done_session} PDFs\n"
        f"🏁 Total completed: {final_stats['completed']}\n"
        f"⏱ Total time: {hours}h {minutes}m\n"
        f"🔑 API calls today: {final_stats['calls_today']}"
    )


if __name__ == "__main__":
    print("🚀 ALFA SAT Remote Pipeline Runner")
    print(f"   Bot: @{BOT_TOKEN.split(':')[0]}")
    print(f"   Admin: {ADMIN_CHAT_ID}")
    print(f"   PDFs folder: {PDF_FOLDER}")

    # Start command listener in background
    cmd_thread = threading.Thread(target=handle_commands, daemon=True)
    cmd_thread.start()
    print("📡 Telegram command listener started.")

    # Run the pipeline
    run_pipeline()
