# Twitter Style Automator

A Python project that automates a Twitter (X) account by **analyzing your existing tweets** and **generating and posting new ones** in a similar style. Target handle: **@mcisaul_** (configurable).

## Features

- **Tweet fetching**: X API v2 (Tweepy) to fetch up to ~3200 timeline tweets with pagination and rate-limit handling
- **Storage**: SQLite database (or path of your choice) for fetched tweets
- **Style analysis**: OpenAI GPT analyzes tweets and produces a reusable "style profile" (topics, tone, length, emojis, hashtags, language)
- **Tweet generation**: New tweets from the style profile on a given topic or auto-suggested
- **Posting**: Post generated tweets; optional scheduling with APScheduler
- **Engagement**: Reply to mentions (placeholder), like/retweet by keywords
- **Safety**: Random delays, rate-limit handling, dry-run mode; API keys via `.env`

## Project structure

```
twitter_style_automator/
├── twitter_style_automator.py   # Main CLI entry point
├── tweet_fetcher.py             # X API v2 fetch + SQLite
├── style_analyzer.py            # OpenAI style analysis → profile
├── tweet_generator.py           # OpenAI tweet generation from profile
├── poster.py                    # Posting, scheduling, like/retweet
├── config.py                    # Loads .env and paths
├── requirements.txt
├── .env.example
├── README.md
├── tweets.db                    # Created after fetch (SQLite)
└── style_profile.json           # Created after analyze-style
```

## Setup

### 1. Python environment

```bash
cd twitter_style_automator
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. X (Twitter) API keys

You need **Elevated** access to read user timelines (including your own).

1. Go to [Twitter Developer Portal](https://developer.twitter.com/en/portal/dashboard).
2. Create a Project and App, then enable **OAuth 2.0** and **OAuth 1.0a**.
3. Under "Keys and tokens":
   - **API Key** and **API Secret** (Consumer)
   - **Access Token** and **Access Token Secret** (for the account you’ll post as)
   - **Bearer Token** (for timeline reads with v2)
4. Ensure your app has **Read and Write** permissions.

### 3. AI API key (OpenAI or Claude)

You can use **Claude** (Anthropic) or **OpenAI** for style analysis, tweet generation, and safety checks.

**Option A – Claude (no OpenAI key needed)**  
1. Go to [Anthropic Console](https://console.anthropic.com/) and create an API key.  
2. In `.env` set: `AI_PROVIDER=anthropic` and `ANTHROPIC_API_KEY=your_key`.  
3. Leave `OPENAI_API_KEY` empty if you’re not using OpenAI.

**Option B – OpenAI**  
1. Go to [OpenAI API Keys](https://platform.openai.com/api-keys) and create a key.  
2. In `.env` set: `AI_PROVIDER=openai` and `OPENAI_API_KEY=your_key`.

Default is `AI_PROVIDER=anthropic` if you don’t set it.

### 4. Environment variables

Copy the example env file and fill in your keys:

```bash
cp .env.example .env
```

Edit `.env`:

- `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_TOKEN_SECRET`, `X_BEARER_TOKEN`
- `AI_PROVIDER=anthropic` or `openai`; then the matching key: `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`
- `X_HANDLE=mcisaul_` (no `@`)
- Optional: `MIN_DELAY_SEC`, `MAX_DELAY_SEC` for random delays (defaults 30–120 s)

Never commit `.env` or share these keys.

## Testing (dry-run, no real posts)

Test the full flow **without posting** anything to X. Use `--dry-run` wherever posting is involved.

**1. Activate venv and go to project folder**
```bash
cd twitter_style_automator
source venv/bin/activate   # Windows: venv\Scripts\activate
```

**2. Fetch your tweets** (needs `X_BEARER_TOKEN` in `.env`). This only reads from X; it doesn’t post.
```bash
python twitter_style_automator.py fetch-tweets --max-tweets 100
```
If you hit rate limits, wait and retry or use a smaller `--max-tweets`.

**3. Build the style profile** (needs `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` in `.env`, and `AI_PROVIDER=anthropic` or `openai`).
```bash
python twitter_style_automator.py analyze-style --max-tweets 100
```
You should see `style_profile.json` created.

**4. Generate a tweet (no post)**  
This only prints a tweet; nothing is sent.
```bash
python twitter_style_automator.py generate-tweet
python twitter_style_automator.py generate-tweet --topic "space"
```

**5. Test the post pipeline in dry-run**  
Generates a tweet, runs safety checks, and **logs** what would be posted; does **not** post.
```bash
python twitter_style_automator.py post-tweet --dry-run
python twitter_style_automator.py post-tweet --dry-run --topic "tech"
```
Check the log output and `posted_tweets.log` (entries will be marked `[DRY RUN]`).

**6. (Optional) Test the full “run” flow in dry-run**  
Runs fetch/analyze if needed, then the scheduler in dry-run. Stop after a minute with **Ctrl+C**.
```bash
python twitter_style_automator.py run --dry-run --no-fetch --no-analyze
```
Use `--no-fetch` and `--no-analyze` if you already have tweets and a profile so it only starts the scheduler.

**When you’re ready to post for real**, run without `--dry-run`:
```bash
python twitter_style_automator.py post-tweet
```

## Usage

All commands are run from the project directory (with `venv` activated).

### Full automation (one command)

Run the **entire** flow in one go: fetch tweets (if needed), build/update style profile (if needed), then start the posting scheduler. Stays running until you press Ctrl+C.

```bash
python twitter_style_automator.py run
python twitter_style_automator.py run --interval-hours 12 --topic "tech"
```

Options: `--no-fetch` / `--no-analyze` to skip those steps; `--refresh-days 7` to re-fetch tweets only if the DB is older than 7 days (default).

### Fetch tweets

Stores your timeline in SQLite (up to ~3200 tweets; API limit without archive):

```bash
python twitter_style_automator.py fetch-tweets
python twitter_style_automator.py fetch-tweets --handle mcisaul_ --max-tweets 500
```

### Analyze style

Builds a style profile from stored tweets (saved to `style_profile.json`):

```bash
python twitter_style_automator.py analyze-style
python twitter_style_automator.py analyze-style --max-tweets 200
```

### Generate a tweet (no post)

Print a single generated tweet:

```bash
python twitter_style_automator.py generate-tweet
python twitter_style_automator.py generate-tweet --topic "space exploration"
python twitter_style_automator.py generate-tweet --suggest
```

### Post one tweet (fully automatic, with safeguards)

Generates a tweet, runs **safety checks**, then posts—**no input from you**:

```bash
python twitter_style_automator.py post-tweet
python twitter_style_automator.py post-tweet --topic "tech"
```

Safeguards: daily post limit, AI content check (on-brand, no hate/misinformation), blocklist, and similarity check so it doesn’t repeat recent tweets. All posts are logged to `posted_tweets.log` for review.

Use `--dry-run` to generate and log only, no real post:

```bash
python twitter_style_automator.py post-tweet --topic "tech" --dry-run
```

### Schedule posts (fully automatic)

Runs a scheduler that posts on an interval with the same safeguards. No prompts:

```bash
python twitter_style_automator.py schedule-posts --interval-hours 24
python twitter_style_automator.py schedule-posts --topic "motivation"
```

Stop with `Ctrl+C`. Use `--dry-run` to avoid real posts while testing.

### Reply to mentions (placeholder)

Fetches and logs mentions; reply logic can be wired later:

```bash
python twitter_style_automator.py reply-mentions
python twitter_style_automator.py reply-mentions --dry-run
```

### Like / retweet by keywords

Like and retweet recent tweets matching keywords:

```bash
python twitter_style_automator.py like-retweet --keywords tech space --count 5
python twitter_style_automator.py like-retweet -k python AI --dry-run
```

## Running without your laptop (no need to keep it on 24/7)

You have two main options so the bot keeps posting without your machine running.

### Option A: Cron (simplest – no long-running process)

Your machine (or any server) runs `post-tweet` on a schedule. Each run generates one tweet, runs safety checks, and posts (or skips if over daily limit). Nothing needs to stay running.

1. **One-time setup** on the machine that will run cron (your laptop when it’s on, or a server):
   ```bash
   cd /path/to/twitter_style_automator
   python twitter_style_automator.py fetch-tweets
   python twitter_style_automator.py analyze-style
   ```
2. **Add a cron job** (run every 6 hours, for example):
   ```bash
   crontab -e
   ```
   Add a line (adjust path and venv):
   ```cron
   0 */6 * * * /path/to/twitter_style_automator/venv/bin/python /path/to/twitter_style_automator/twitter_style_automator.py post-tweet >> /path/to/twitter_style_automator/cron.log 2>&1
   ```
   With a topic:
   ```cron
   0 9,15,21 * * * /path/to/venv/bin/python /path/to/twitter_style_automator.py post-tweet --topic "motivation" >> /path/to/cron.log 2>&1
   ```

- **Pros**: No long-running process; works on any machine that’s on at those times (or on a server).  
- **Cons**: Only runs when cron runs (e.g. if the machine is off at 3am, that run is skipped).

### Option B: Run the scheduler 24/7 on a cloud server

To have the **scheduler** run continuously (posting every N hours without relying on cron), run the project on a server that’s always on.

1. **VPS or cloud VM** (e.g. DigitalOcean, Linode, Oracle Cloud free tier, AWS EC2):
   - Create a small Linux VM, clone/copy your project and `.env`.
   - Install Python 3, venv, install deps.
   - Run in the background:
     ```bash
     nohup python twitter_style_automator.py run --interval-hours 24 > automator.log 2>&1 &
     ```
   - Or use **tmux** / **screen** so it survives disconnects:
     ```bash
     tmux new -s automator
     cd /path/to/twitter_style_automator && source venv/bin/activate
     python twitter_style_automator.py run --interval-hours 24
     # Detach: Ctrl+B then D
     ```

2. **As a systemd service** (Linux server): create e.g. `/etc/systemd/system/twitter-automator.service`:
   ```ini
   [Unit]
   Description=Twitter Style Automator
   After=network.target

   [Service]
   Type=simple
   User=YOUR_USER
   WorkingDirectory=/path/to/twitter_style_automator
   ExecStart=/path/to/twitter_style_automator/venv/bin/python twitter_style_automator.py run --interval-hours 24
   Restart=always
   RestartSec=60

   [Install]
   WantedBy=multi-user.target
   ```
   Then: `sudo systemctl daemon-reload`, `sudo systemctl enable twitter-automator`, `sudo systemctl start twitter-automator`.

- **Pros**: True 24/7 scheduling; one `run` command does fetch + analyze + scheduler.  
- **Cons**: You need a server (free tiers are often enough).

**Summary**: Use **cron + `post-tweet`** if you don’t want a long-running process (or only have your laptop). Use **`run` on a VPS/systemd** if you want the scheduler running 24/7 without your laptop.

## Options (global)

- `--db PATH` – SQLite DB path (default: `tweets.db` in project dir)
- `--profile PATH` – Style profile JSON path (default: `style_profile.json`)
- `--handle HANDLE` – X handle without `@` (default: from `X_HANDLE`)
- `--dry-run` – Do not post, like, or retweet; only log

## Autonomous mode and safeguards

The automator is designed to run **without any input from you**. To keep posting careful and on-brand, it uses:

1. **Daily cap** – `MAX_POSTS_PER_DAY` (default 5). No more than that many posts per calendar day.
2. **AI safety check** – Before each post, an OpenAI call scores the tweet (1–5) for: on-brand, appropriate, no hate/misinformation. Only tweets that pass (score ≥ 4) are posted. Set `ENABLE_SAFETY_CHECK=false` in `.env` to disable.
3. **Blocklist** – In `.env`, set `BLOCKLIST=word1,word2,phrase` (comma-separated). Any tweet containing one of these (case-insensitive) is rejected.
4. **Similarity check** – If a generated tweet is too similar to one of your recent timeline tweets (from the DB), it is skipped to avoid repetition.
5. **Post log** – Every post (and dry-run) is appended to `posted_tweets.log` (timestamp, tweet id, text) so you can review what was posted.

You can run `post-tweet` or `schedule-posts` and walk away; the bot will only post when these checks pass.

## Ethical use and compliance

- **Use responsibly** to avoid account suspension. Prefer value-adding, on-brand content.
- **X automation rules**: Avoid spam, duplicate content, and aggressive automation. Disclose automation where required by X’s rules.
- **Rate limits**: The app uses delays and respects X rate limits; scheduling is conservative (e.g. one post every several hours).
- **Content**: You are responsible for what is posted. Review style profile and sample outputs; use `--dry-run` before going live.

## Dependencies

- **tweepy** – X API v2 (and v1.1 where used)
- **openai** – Style analysis and tweet generation
- **apscheduler** – Scheduled posting
- **python-dotenv** – Load `.env`

SQLite is in the standard library.

## License

Use and modify as you like; ensure compliance with X’s and OpenAI’s terms of use.
