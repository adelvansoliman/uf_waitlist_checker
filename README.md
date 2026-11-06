# UF Waitlist Monitor

A **read-only Python monitor** for University of Florida course **waitlist capacity**. It checks the public ONE.UF course-search API periodically and sends a **Discord webhook notification** when it detects a possible opening on a previously full waitlist. It **never enrolls in a class or joins a waitlist**, and it does **not** need your GatorLink password, Windows Hello, or Duo session.

Default configuration: **Spring 2027 (`TERM=2271`)**, **EEL4712C**, **every 30 minutes**. Works on **Windows, macOS, and Linux** (including the AMD Kria KR260 running Ubuntu).

> **Important distinction:** This detects **waitlist capacity** (`waitList.total < waitList.cap`), **not actual open seats in the course**. The public API can return `openSeats: null`. Its `waitList.isEligible` field is **not proof of your personal prerequisite eligibility**. The bot deliberately flags possible openings even if `isEligible` stays `N`; always verify the **Add to Waitlist** option in ONE.UF. Counts may lag or change before you act.

## Features

- Monitors one or multiple exact course codes, with optional class-number filters.
- Sends Discord alerts only when a waitlist is observed with room; avoids repeated alerts while it stays open.
- Remembers notified sections across restarts in `.state/notified.json` (excluded from Git).
- `--test` sends a Discord test without contacting UF; `--once` checks UF once and exits.
- Uses no ONE.UF credentials and makes no enrollment-related requests.
- Includes an optional `systemd` service for an always-on Linux/Kria device.

## 1. Create a Discord webhook

1. Create a private text channel in a Discord server (for example, `#uf-waitlist`).
2. Open **Edit Channel → Integrations → Webhooks**.
3. Select **Create Webhook**, give it a name, and **Copy Webhook URL**.
4. Keep the URL private: anyone holding it can post into that channel. Do not commit it to GitHub.

The official [Discord webhook documentation](https://discord.com/developers/docs/resources/webhook#execute-webhook) describes webhook message posting.

## 2. Set up on Windows (PowerShell)

Install **Python 3.10+** (make sure the `py` command works) and **Git** if you will clone a repository. In a PowerShell window:

```powershell
# If cloning from GitHub (replace URL with your repository URL):
git clone https://github.com/YOUR_USERNAME/uf-waitlist-monitor.git
cd uf-waitlist-monitor

# If you downloaded the ZIP instead: extract it, then cd into that folder.
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
```

Edit `.env`: replace `DISCORD_WEBHOOK_URL` with your real webhook URL and adjust `COURSE_CODES` if desired. Save and close Notepad. Then:

```powershell
.\.venv\Scripts\python.exe check_waitlist.py --test
.\.venv\Scripts\python.exe check_waitlist.py --once
.\.venv\Scripts\python.exe check_waitlist.py
```

The last command checks immediately and then every 30 minutes. Press **Ctrl+C** to stop it.

**Keeping it running on Windows:** The PC must remain on, awake, and connected to the internet. For automatic startup, use **Task Scheduler** → **Create Task** → Trigger **At log on** → Action **Start a program**. Set the program to the absolute path of `.venv\Scripts\python.exe`, arguments to `check_waitlist.py`, and **Start in** to the absolute project folder. Enable its normal restart settings if you want recovery after errors. Running manually in a PowerShell window stops when that session ends.

## 3. Set up on macOS (Terminal)

Install **Python 3.10+** and Git if needed. Open Terminal:

```bash
# If cloning from GitHub (replace URL with your repository URL):
git clone https://github.com/YOUR_USERNAME/uf-waitlist-monitor.git
cd uf-waitlist-monitor

# If using the ZIP: unzip it and cd into the extracted folder instead.
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
nano .env
```

Paste your private Discord URL into the `DISCORD_WEBHOOK_URL` line. In `nano`, press **Control+O**, **Return**, then **Control+X** to save and exit. Test and run:

```bash
.venv/bin/python check_waitlist.py --test
.venv/bin/python check_waitlist.py --once
.venv/bin/python check_waitlist.py
```

Press **Control+C** to stop. The Mac must stay awake and online for the monitor to keep working. To inhibit sleep while you run the process in Terminal, you can instead use:

```bash
caffeinate -i .venv/bin/python check_waitlist.py
```

Closing that Terminal session stops the monitor. For unattended macOS operation you can configure a `launchd` LaunchAgent; this repository provides a ready-to-edit `systemd` service for Linux/Kria instead.

## 4. Configure courses and check frequency

The `.env` file controls the bot:

```dotenv
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR_ID/YOUR_TOKEN
TERM=2271
CATEGORY=CWSP
COURSE_CODES=EEL4712C
CLASS_NUMBERS=
CHECK_INTERVAL_SECONDS=1800
```

Examples:

- Monitor **two courses**: `COURSE_CODES=EEL4712C,EEL3135`
- Only particular class numbers: `CLASS_NUMBERS=13271,13272`
- Check every **15 minutes**: `CHECK_INTERVAL_SECONDS=900`
- Monitor **all sections** in chosen courses: leave `CLASS_NUMBERS=` empty.

The course code is exact: **`EEL4712C`**, not `EEL4712`. If the API returns a partial match, the script intentionally ignores it. Keep polling moderate; the default is 30 minutes.

### Commands

| Command (Windows uses `.\.venv\Scripts\python.exe` instead of `.venv/bin/python`) | Result |
| --- | --- |
| `.venv/bin/python check_waitlist.py --test` | Test Discord only; no UF request |
| `.venv/bin/python check_waitlist.py --once` | Check current UF waitlist status once |
| `.venv/bin/python check_waitlist.py` | Run continuously |
| `.venv/bin/python check_waitlist.py --interval 900` | Temporarily use a 15-minute check interval |
| `.venv/bin/python -m unittest discover -s tests -v` | Run offline unit tests |

## 5. Optional: run 24/7 on the AMD Kria KR260 / Ubuntu

This is useful if you want to **shut down your Windows or Mac computer** while the board keeps checking. The Kria must remain powered on and connected to the internet.

If you've already set up an older `uf-waitlist.service`, stop it first to avoid two monitors running:

```bash
sudo systemctl stop uf-waitlist
sudo systemctl disable uf-waitlist
```

On Ubuntu, put the repository at **`/home/ubuntu/uf-waitlist-monitor`**, then:

```bash
cd /home/ubuntu/uf-waitlist-monitor
sudo apt update
sudo apt install -y python3-venv
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
nano .env
chmod 600 .env
.venv/bin/python check_waitlist.py --test
.venv/bin/python check_waitlist.py --once
```

You can copy the repository from Windows using PowerShell (replace `KRIA_IP` with the board's current IP address). Make sure you transfer the **whole source folder**, not only the Python file. Do **not** copy an existing Windows/macOS `.venv` to Ubuntu; create a fresh `.venv` on the Kria:

```powershell
scp -r C:\path\to\uf-waitlist-monitor ubuntu@KRIA_IP:~/
```

**Important:** Run `scp` in **Windows PowerShell**, not inside the Kria's SSH shell. A Windows `C:\...` path does not work inside Ubuntu.

Once the test succeeds, enable automatic background startup using the included service file:

```bash
cd /home/ubuntu/uf-waitlist-monitor
sudo cp deploy/uf-waitlist.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now uf-waitlist
sudo systemctl status uf-waitlist
```

Look for **`active (running)`**. See the logs:

```bash
sudo journalctl -u uf-waitlist -f
```

Use **Ctrl+C** to exit the log viewer; this **does not** stop the service. You may now disconnect SSH and shut down your Windows/Mac computer. Stop the monitor later with `sudo systemctl stop uf-waitlist`.

If you store the repository under a different path or Linux username, edit `deploy/uf-waitlist.service` before installing it to match the actual paths.

### Kria clock troubleshooting

If the board reports a date such as **2038**, HTTPS requests may fail due to an incorrect system clock. Check and enable network time sync:

```bash
timedatectl
sudo timedatectl set-ntp true
timedatectl
```

If the time remains wrong, check the network connection and Ubuntu's time-sync service before relying on monitoring.

## How the alerting logic works

For each monitored class:

1. Request the public course data from `https://one.uf.edu/apix/soc/schedule/`.
2. Read the waitlist's `cap` and `total`; if both are valid and `total < cap`, flag a **possible** waitlist opening **even if `isEligible` says `N`**.
3. Post to the Discord webhook once, until the waitlist returns to full and later opens again.

For example, a change from `5/5` to `4/5` can produce an alert. This **does not mean the class has an enrollment seat**, and it **does not guarantee you can join the waitlist**. If the API gives missing or inconsistent numbers, the script does not alert.

If Discord is temporarily unavailable, it will try again at the next scheduled check. State is stored locally so a restart normally won't repeat an already-sent alert.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `Set a valid DISCORD_WEBHOOK_URL` | Ensure `.env` exists beside `check_waitlist.py` and contains the real webhook URL. |
| `No matching sections found` | Use the full course code, e.g., `EEL4712C` (including `C`), and check class-number filters. |
| `ModuleNotFoundError` | Install `requirements.txt` with the same virtual environment Python you use to launch the script. |
| Discord message doesn't arrive | Try `--test`, check webhook/channel permissions and any Discord response error. |
| Network / SSL certificate errors | Confirm internet access and correct device date/time. |
| Mac/Windows stops checking | The terminal closed or the computer slept; keep it awake or run on an always-on Kria. |

## Security, limits, and responsible usage

- **No passwords or login tokens** are stored or requested; this uses only the public course-search endpoint.
- `.env` and `.state/` are Git-ignored; **never publish your Discord webhook URL**. Rotate it in Discord if accidentally exposed.
- Respect UF's acceptable-use requirements and avoid excessive polling. This project is **not affiliated with UF**. Public endpoints and API data can change without notice.
- Follow [UF's official waitlist instructions](https://registrar.ufl.edu/registration/waitlist) for the actual registration process.
- The monitor only **notifies**; it **never clicks Add to Waitlist, registers, or modifies your student account**.

## Publish to GitHub

After extracting or cloning the project and creating your private `.env` (which is excluded from commits):

```bash
git init
git add .
git commit -m "Initial UF waitlist monitor"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/uf-waitlist-monitor.git
git push -u origin main
```

Create an **empty** GitHub repository named `uf-waitlist-monitor` first and replace `YOUR_USERNAME` in the command. If you cloned an existing repository instead of extracting the ZIP, skip `git init` and `git remote add origin` because those are already configured.

The included GitHub Actions workflow runs offline unit tests on push and pull request. The workflow does **not** check the UF API or need your webhook secret.
