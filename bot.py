import os
import asyncio
import logging
import subprocess
import shutil
import uuid
import json
import re
import time
from pathlib import Path
from dotenv import load_dotenv
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message

# --- CONFIGURATION ---
load_dotenv()
API_ID = int(os.getenv("TELEGRAM_API_ID", "2040"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "b18441a1ff607e10a989891a5462e627")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USER_ID = int(os.getenv("TELEGRAM_ALLOWED_USER_ID", 0))
RCLONE_REMOTE = os.getenv("RCLONE_REMOTE_NAME", "drive:")
ZIP_PASSWORD = os.getenv("ZIP_ENCRYPTION_PASSWORD", "DefaultPass123!")

STAGING_DIR = Path.home() / "nigel" / "downloads"
COOKIES_PATH = Path.home() / "nigel" / "cookies.txt"
MIN_FREE_DISK_GB = 2 

url_cache = {}
job_queue = asyncio.Queue()

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

app = Client(
    "nigel_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=4
)

def get_free_space_gb(directory: str) -> float:
    total, used, free = shutil.disk_usage(directory)
    return free / (2**30)

def startup_sweep():
    if STAGING_DIR.exists():
        shutil.rmtree(STAGING_DIR, ignore_errors=True)
    STAGING_DIR.mkdir(parents=True, exist_ok=True)

async def fetch_available_resolutions(url):
    cmd = ["yt-dlp", "--dump-json", "--no-warnings", url]
    if COOKIES_PATH.exists(): cmd.extend(["--cookies", str(COOKIES_PATH)])
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, _ = await proc.communicate()
    if proc.returncode != 0: return None
    try:
        data = json.loads(stdout)
        resolutions = set()
        for f in data.get('formats', []):
            h, v = f.get('height'), f.get('vcodec')
            if h and isinstance(h, int) and v != 'none': resolutions.add(h)
        return sorted(list(resolutions), reverse=True)
    except Exception: return None

async def log_stream_and_update(stream, prefix, status_msg: Message, last_val_ref):
    last_update_time = [0]
    try:
        while True:
            line = await stream.readline()
            if not line: break
            line_str = line.decode().strip()
            
            pct_match = re.search(r"(\d+(\.\d+)?)%", line_str)
            if pct_match:
                current_pct = float(pct_match.group(1))
                now = time.time()
                if int(current_pct // 10) > last_val_ref[0] or (now - last_update_time[0] > 5):
                    last_val_ref[0] = int(current_pct // 10)
                    last_update_time[0] = now
                    try: await status_msg.edit_text(f"📡 {prefix}: {int(current_pct)}%...")
                    except: pass
                continue 

            size_match = re.search(r"(\d+(\.\d+)?)(MiB|GiB|MB|GB)", line_str)
            if size_match:
                val = float(size_match.group(1))
                unit = size_match.group(3)
                now = time.time()
                if (now - last_update_time[0] > 8):
                    last_update_time[0] = now
                    try: await status_msg.edit_text(f"📡 {prefix}: {val:.1f} {unit} processed...")
                    except: pass
            
            logger.info(f"[{prefix}] {line_str}")
    except Exception as e:
        logger.error(f"Stream Error ({prefix}): {e}")

async def process_queue():
    while True:
        job = await job_queue.get()
        status_msg, source_type = job['status_msg'], job['type']
        work_dir = STAGING_DIR / f"job_{status_msg.id}"
        base_name = "file" 
        
        try:
            if get_free_space_gb(str(STAGING_DIR.parent)) < MIN_FREE_DISK_GB: raise Exception("Disk Space Critically Low")
            work_dir.mkdir(parents=True, exist_ok=True)

            if source_type == "Link":
                url, format_flag = job['url'], job['format']
                t_proc = await asyncio.create_subprocess_exec("yt-dlp", "--get-filename", "-o", "%(title)s.%(ext)s", url, stdout=subprocess.PIPE)
                t_out, _ = await t_proc.communicate()
                base_name = t_out.decode().strip() or "video.mp4"
                zip_file = work_dir / f"{base_name}.7z"
                
                dl_cmd = ["yt-dlp", "-f", format_flag, "-i", "--no-warnings", "--progress", "--newline", "-o", "-", url]
                if COOKIES_PATH.exists(): dl_cmd.extend(["--cookies", str(COOKIES_PATH)])
                zip_cmd = ["7z", "a", f"-p{ZIP_PASSWORD}", "-sivideo.mp4", "-t7z", str(zip_file)]
                
                r_fd, w_fd = os.pipe()
                p1 = await asyncio.create_subprocess_exec(*dl_cmd, stdout=w_fd, stderr=subprocess.PIPE)
                os.close(w_fd)
                p2 = await asyncio.create_subprocess_exec(*zip_cmd, stdin=r_fd, stderr=subprocess.PIPE)
                os.close(r_fd)
                
                await asyncio.gather(log_stream_and_update(p1.stderr, "Downloading", status_msg, [0]), p1.wait(), p2.wait())
                await status_msg.edit_text("📤 Uploading to Cloud...")
                await (await asyncio.create_subprocess_exec("rclone", "move", str(zip_file), f"{RCLONE_REMOTE}/Nigel/Links/")).wait()

            else:
                base_name = job['filename']
                raw_file = work_dir / base_name
                zip_file = work_dir / f"{base_name}.7z"
                
                await status_msg.edit_text("📥 Streaming via MTProto...")
                last_pct = [-1]
                async def progress(current, total):
                    pct = int(current * 100 / total)
                    if pct // 20 > last_pct[0]:
                        last_pct[0] = pct // 20
                        try: await status_msg.edit_text(f"📥 Fetching: {pct}%")
                        except: pass

                await app.download_media(job['message'], file_name=str(raw_file), progress=progress)
                await status_msg.edit_text("🔒 Encrypting Archive...")
                await (await asyncio.create_subprocess_exec("7z", "a", f"-p{ZIP_PASSWORD}", str(zip_file), str(raw_file))).wait()
                await status_msg.edit_text("📤 Uploading to Cloud...")
                await (await asyncio.create_subprocess_exec("rclone", "move", str(zip_file), f"{RCLONE_REMOTE}/Nigel/Telegram/")).wait()

            await status_msg.edit_text(f"✅ **Success**\n`{base_name}.7z`", parse_mode=enums.ParseMode.MARKDOWN)
            
        except Exception as e:
            await status_msg.edit_text(f"❌ **Failed**\n`{str(e)}`")
        finally:
            if work_dir.exists(): shutil.rmtree(work_dir, ignore_errors=True)
            job_queue.task_done()

@app.on_message(filters.private & filters.user(ALLOWED_USER_ID))
async def handle_input(client: Client, message: Message):
    if message.media:
        media = getattr(message, message.media.value)
        name = getattr(media, "file_name", f"file_{message.id}")
        msg = await message.reply("📥 Queued Telegram File...")
        await job_queue.put({'type': 'Telegram', 'message': message, 'filename': name, 'status_msg': msg})
        
    elif message.text and message.text.startswith("http"):
        url = message.text.strip()
        status_msg = await message.reply("🔍 Analyzing URL...")
        resolutions = await fetch_available_resolutions(url)
        url_id = str(uuid.uuid4())[:8]
        url_cache[url_id] = url
        
        buttons = []
        if resolutions:
            std = [r for r in resolutions if r in [1080, 720, 480, 360]] or resolutions[:3]
            row = [InlineKeyboardButton(f"{r}p", callback_data=f"dl|{r}|{url_id}") for r in std]
            buttons.append(row)
        buttons.append([InlineKeyboardButton("🎧 Audio", callback_data=f"dl|audio|{url_id}"), InlineKeyboardButton("🔥 Max", callback_data=f"dl|best|{url_id}")])
        await status_msg.edit_text("Select Quality:", reply_markup=InlineKeyboardMarkup(buttons))

@app.on_callback_query()
async def button_callback(client: Client, query: CallbackQuery):
    await query.answer()
    parts = query.data.split("|")
    quality, url_id = parts[1], parts[2]
    url = url_cache.get(url_id)
    if not url: return
    f_str = "bestaudio/best" if quality == "audio" else ("bestvideo+bestaudio/best" if quality == "best" else f"bestvideo[height<={quality}]+bestaudio/best[height<={quality}]/best")
    await query.edit_message_text(f"📥 Queued Link ({quality})...")
    await job_queue.put({'type': 'Link', 'url': url, 'format': f_str, 'status_msg': query.message})

async def main():
    startup_sweep()
    asyncio.create_task(process_queue())
    await app.start()
    logger.info("Nigel MTProto Relay Online.")
    await asyncio.Event().wait()

if __name__ == "__main__":
    app.run(main())