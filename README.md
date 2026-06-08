# Nigel Vlast - Working Edition

Nigel is a high-performance, standalone Telegram MTProto relay that bridges Telegram, the web, and your cloud storage. It uses the MTProto engine to natively handle large files (up to 2GB) without Docker or local API servers.

## Key Features

- **Native 2GB support:** Bypasses Bot API file-size limitations.
- **Sequential pipeline:** Pipes `yt-dlp` → `7zip` to save disk space during transfers.
- **Military-grade encryption:** AES-256 password-protected `.7z` archives.
- **Azure optimized:** Tuned for small instances (B1s/B2s) with low RAM usage.
- **Smart throttling:** Intelligent progress updates to avoid Telegram Flood Waits.

## Prerequisites

### 1) System dependencies (Linux)

Install required binaries:

```bash
sudo apt update && sudo apt install p7zip-full -y
sudo wget https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -O /usr/local/bin/yt-dlp
sudo chmod a+rx /usr/local/bin/yt-dlp
curl https://rclone.org/install.sh | sudo bash
```

### 2) Telegram credentials

You need the following values for your `.env` file:

- `API_ID` and `API_HASH` — obtain from https://my.telegram.org
- `BOT_TOKEN` — create a bot via @BotFather
- `ALLOWED_USER_ID` — get your numerical ID via @userinfobot

Example `.env` (replace with your values):

```env
API_ID=123456
API_HASH=your_api_hash
BOT_TOKEN=123:ABC
ALLOWED_USER_ID=123456789
```

### 3) Rclone headless setup (Google Drive / OneDrive)

On a remote VPS without a browser, use Rclone's headless flow:

1. On the VPS: run `rclone config` and create a new remote (e.g., named `drive`).
2. When prompted for "Use auto config?", choose `n` (No).
3. On your local machine: run the `rclone authorize "<remote>" "..."` command shown on the VPS. A browser will open locally — authenticate and copy the resulting JSON token.
4. Paste the JSON token back into the VPS prompt.
5. Verify with:

```bash
rclone lsd drive:
```

## Installation

```bash
git clone https://github.com/yourusername/nigel.git
cd nigel
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .example.env .env
nano .env   # edit with your credentials
python bot.py
```

## Resource management (Azure B-Series)

- **CPU:** Sequential processing reduces CPU credit exhaustion.
- **RAM:** Standalone Python runtime uses less memory than Docker.
- **Disk safety:** The bot checks a `MIN_FREE_DISK_GB` buffer before starting jobs to avoid OS crashes.

## Disclaimer

This project is for personal data management. Ensure you comply with Telegram's Terms of Service and your storage provider's policies. Never commit your `.env` or `.session` files to public repositories.