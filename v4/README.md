# YouTube Bot v4

Automated YouTube video watch bot using CloakBrowser + Playwright.

## Setup

```bash
pip install -r requirements.txt
playwright install chromium
```

## Usage

```bash
# Edit config.json with your video URL and proxy list
python bot.py

# Or use a custom config
python bot.py my_config.json
```

## Configuration

See `config.json` for all options. Key settings:

- `video_url` - YouTube video to watch
- `proxy_file` - File with proxy list (format: `protocol://user:pass@host:port`)
- `headless` - Run browser in headless mode
- `max_parallel_workers` - Number of concurrent browser instances
- `min/max_watch_percentage` - Random watch percentage range
- `like_probability` / `comment_probability` - Engagement rates
