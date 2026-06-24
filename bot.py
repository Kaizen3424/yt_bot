import asyncio
import json
import os
import random
import sys
from cloakbrowser import launch_async
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

# Load configuration from config.json or fall back to defaults
def load_config():
    config_path = "config.json"
    if len(sys.argv) > 1 and sys.argv[1].endswith(".json"):
        config_path = sys.argv[1]
        print(f"[*] Command-line config specified. Loading: {config_path}")
        
    default_config = {
        "video_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "proxy_file": "proxy.txt",
        "cookies_file": "cookies.json",
        "headless": False,
        "max_parallel_workers": 3,
        "min_watch_percentage": 40,
        "max_watch_percentage": 90,
        "like_probability": 0.6,
        "comment_probability": 0.4,
        "comments": [
            "Amazing video! Thanks for sharing.",
            "Really helpful content, keep it up!",
            "Great work on this, subbed!",
            "Loved the explanation here.",
            "This deserves way more views!"
        ],
        "fallback_watch_time_seconds": 60
    }
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r') as f:
                return {**default_config, **json.load(f)}
        except Exception as e:
            print(f"[ERROR] Loading config.json failed, using defaults. Error: {e}")
    return default_config

def load_proxies(file_path):
    if os.path.exists(file_path):
        with open(file_path, 'r') as f:
            return [line.strip() for line in f if line.strip()]
    return []

async def handle_cookie_consent(page, prefix):
    try:
        consent_selectors = [
            'button:has-text("Accept all")',
            'button:has-text("I agree")',
            'button:has-text("Accept")',
            'button:has-text("Consent")',
            'ytd-button-renderer:has-text("Accept all") button'
        ]
        
        for _ in range(3):
            for selector in consent_selectors:
                btn = page.locator(selector)
                if await btn.count() > 0:
                    print(f"{prefix} Cookie consent banner detected. Clicking 'Accept'...")
                    await btn.first.click(force=True)
                    await page.wait_for_timeout(1500)
                    return
            await page.wait_for_timeout(1000)
    except Exception as e:
        print(f"{prefix} [WARNING] Error while handling cookie banner: {e}")

async def is_logged_in(page):
    try:
        if await page.locator('#avatar-btn').count() > 0:
            return True
        if await page.locator('ytd-avatar-button').count() > 0:
            return True
        sign_in_visible = await page.locator('a[aria-label="Sign in"], ytd-masthead ytd-button-renderer a:has-text("Sign in")').count() > 0
        return not sign_in_visible
    except Exception:
        return False

async def ensure_video_playing(page, prefix):
    try:
        is_paused = await page.evaluate("() => { const v = document.querySelector('video'); return v ? v.paused : false; }")
        if not is_paused:
            return
        
        print(f"{prefix} Video is paused. Attempting to start playback...")
        
        # Try JavaScript play() first (most reliable, bypasses UI overlays)
        await page.wait_for_timeout(500)
        played = await page.evaluate("""() => {
            const v = document.querySelector('video');
            if (!v) return false;
            try {
                const p = v.play();
                if (p) p.catch(() => {});
                return true;
            } catch(e) {
                return false;
            }
        }""")
        
        await page.wait_for_timeout(1000)
        
        # Verify if it worked
        still_paused = await page.evaluate("() => { const v = document.querySelector('video'); return v ? v.paused : false; }")
        if not still_paused:
            return
        
        # JS didn't work (autoplay blocked). Try clicking UI buttons.
        print(f"{prefix} JS play blocked. Trying click on player buttons...")
        large_play_btn = page.locator('.ytp-large-play-button')
        if await large_play_btn.count() > 0 and await large_play_btn.first.is_visible():
            await large_play_btn.first.click(timeout=3000, force=True)
        else:
            play_btn = page.locator('.ytp-play-button')
            if await play_btn.count() > 0:
                await play_btn.first.click(timeout=3000, force=True)
            else:
                await page.evaluate("() => document.querySelector('video')?.click()")
        
        await page.wait_for_timeout(1500)
    except Exception as e:
        print(f"{prefix} [WARNING] Could not ensure video is playing: {e}")


async def like_video(page, prefix):
    try:
        print(f"{prefix} Attempting to Like the video...")
        like_selectors = [
            '#segmented-like-button button',
            'ytd-menu-renderer ytd-segmented-like-dislike-button-renderer button',
            'button[aria-label*="like this video" i]',
            'button[aria-label*="Like this video" i]'
        ]
        
        button = None
        for selector in like_selectors:
            loc = page.locator(selector)
            if await loc.count() > 0:
                button = loc.first
                break
                
        if button:
            aria_pressed = await button.get_attribute("aria-pressed")
            if aria_pressed == "true":
                print(f"{prefix} Video is already liked.")
                return True
                
            await button.scroll_into_view_if_needed()
            await button.click(force=True)
            print(f"{prefix} [SUCCESS] Clicked Like button.")
            return True
        else:
            print(f"{prefix} [WARNING] Could not locate Like button.")
            return False
    except Exception as e:
        print(f"{prefix} [ERROR] Failed to like video: {e}")
        return False

async def post_comment(page, comment_text, prefix):
    try:
        print(f"{prefix} Scrolling to comment section...")
        await page.evaluate("window.scrollTo(0, 750)")
        
        comments_selector = '#comments'
        try:
            await page.wait_for_selector(comments_selector, timeout=8000)
        except PlaywrightTimeoutError:
            print(f"{prefix} [WARNING] Comment section container did not load.")
            return False
            
        await page.locator(comments_selector).scroll_into_view_if_needed()
        
        placeholder_selectors = [
            '#simplebox-placeholder',
            '#placeholder-area',
            'yt-formatted-string:has-text("Add a comment...")',
            '#comment-dialog #placeholder-area'
        ]
        
        placeholder = None
        for sel in placeholder_selectors:
            loc = page.locator(sel)
            if await loc.count() > 0 and await loc.first.is_visible():
                placeholder = loc.first
                break
                
        if not placeholder:
            print(f"{prefix} [WARNING] Comment box placeholder not found or visible.")
            return False
            
        print(f"{prefix} Clicking comment input placeholder...")
        await placeholder.click()
        
        input_selectors = [
            '#contenteditable-root',
            'div[contenteditable="true"]',
            'textarea#comment-textarea'
        ]
        
        input_field = None
        for sel in input_selectors:
            loc = page.locator(sel)
            if await loc.count() > 0 and await loc.first.is_visible():
                input_field = loc.first
                break
                
        if not input_field:
            print(f"{prefix} [WARNING] Editable comment text field not found.")
            return False
            
        print(f"{prefix} Typing comment: \"{comment_text}\"")
        await input_field.fill(comment_text)
        
        submit_selectors = [
            'ytd-button-renderer#submit-button button',
            '#submit-button button',
            'button[aria-label="Comment"]'
        ]
        
        submit_btn = None
        for sel in submit_selectors:
            loc = page.locator(sel)
            if await loc.count() > 0 and await loc.first.is_visible():
                submit_btn = loc.first
                break
                
        if submit_btn:
            print(f"{prefix} Clicking Submit Comment button...")
            await submit_btn.click()
            print(f"{prefix} [SUCCESS] Comment posted.")
            await page.evaluate("window.scrollTo(0, 0)")
            return True
        else:
            print(f"{prefix} [WARNING] Submit button not found.")
            return False
    except Exception as e:
        print(f"{prefix} [ERROR] Failed to post comment: {e}")
        return False

async def run_engagement_actions(page, config, prefix):
    logged_in = await is_logged_in(page)
    if not logged_in:
        print(f"{prefix} User is running in Guest mode (not logged in). Skipping engagement actions (Like/Comment).")
        return
        
    print(f"{prefix} Verified Logged-in state. Performing engagement checks...")
    
    like_prob = config.get("like_probability", 0.6)
    if random.random() < like_prob:
        await like_video(page, prefix)
    else:
        print(f"{prefix} Skipped Like action due to probability roll.")
        
    comment_prob = config.get("comment_probability", 0.4)
    comments_list = config.get("comments", ["Great video!"])
    if comments_list and random.random() < comment_prob:
        comment_text = random.choice(comments_list)
        await post_comment(page, comment_text, prefix)
    else:
        print(f"{prefix} Skipped Comment action due to probability roll.")

async def get_video_duration(page):
    try:
        duration = await page.evaluate("""() => {
            const v = document.querySelector('video');
            if (v && !isNaN(v.duration) && isFinite(v.duration)) {
                return v.duration;
            }
            return null;
        }""")
        return duration
    except Exception:
        return None

async def robust_watch_and_handle_ads(page, target_watch_time, config, prefix):
    print(f"{prefix} Starting watch loop for {target_watch_time} seconds...")
    elapsed = 0
    engagement_triggered = False
    consecutive_ad_time = 0
    max_ad_wait = 30
    
    engagement_milestone = target_watch_time // 2
    
    while elapsed < target_watch_time:
        try:
            is_ad_showing = await page.evaluate("() => document.querySelector('#movie_player.ad-showing') !== null")
            
            if is_ad_showing:
                consecutive_ad_time += 2
                print(f"{prefix} [AD DETECTED] YouTube ad is running...")
                
                if consecutive_ad_time >= max_ad_wait:
                    print(f"{prefix} [AD DETECTED] Ad exceeded {max_ad_wait}s limit. Reloading page...")
                    await page.goto(page.url, wait_until="domcontentloaded")
                    await page.wait_for_timeout(3000)
                    consecutive_ad_time = 0
                    continue
                
                skip_selectors = '.ytp-ad-skip-button, .ytp-ad-skip-button-modern, .ytp-skip-ad-button'
                skip_btn = page.locator(skip_selectors)
                
                if await skip_btn.count() > 0 and await skip_btn.first.is_visible():
                    print(f"{prefix} [AD DETECTED] Skip button is visible! Skipping ad...")
                    await skip_btn.first.click(force=True)
                    await page.wait_for_timeout(1000)
                else:
                    print(f"{prefix} [AD DETECTED] Waiting for ad/timer to complete...")
                    await page.wait_for_timeout(2000)
                continue
            else:
                consecutive_ad_time = 0
                
            await ensure_video_playing(page, prefix)
            
            if not engagement_triggered and elapsed >= engagement_milestone:
                print(f"{prefix} Reached watch milestone ({elapsed}/{target_watch_time}s). Initiating engagement...")
                await run_engagement_actions(page, config, prefix)
                engagement_triggered = True
            
            await page.wait_for_timeout(1000)
            elapsed += 1
            
            if elapsed % 10 == 0:
                print(f"{prefix} Progress: {elapsed}/{target_watch_time} seconds watched.")
                
        except Exception as e:
            print(f"{prefix} [ERROR] Exception during watch loop: {e}")
            await page.wait_for_timeout(2000)
            
    print(f"{prefix} [SUCCESS] Reached target watch time of {target_watch_time} seconds!")

async def watch_with_proxy(proxy_str, worker_id, config):
    proxy_display = proxy_str.split('@')[-1] if '@' in proxy_str else proxy_str
    prefix = f"[Worker-{worker_id} | {proxy_display}]"
    
    print(f"\n{prefix} Launching CloakBrowser...")
    launch_kwargs = {
        "headless": config["headless"],
        "humanize": True,
        "proxy": proxy_str,
        "geoip": True
    }
    
    browser = None
    context = None
    try:
        browser = await launch_async(**launch_kwargs)
        context = await browser.new_context(viewport={"width": 1280, "height": 720})
        
        cookies_file = config.get("cookies_file", "cookies.json")
        if cookies_file and os.path.exists(cookies_file):
            try:
                with open(cookies_file, 'r') as f:
                    cookies = json.load(f)
                    await context.add_cookies(cookies)
                    print(f"{prefix} Successfully loaded session cookies.")
            except Exception as e:
                print(f"{prefix} [ERROR] Failed to load cookies: {e}")
                
        page = await context.new_page()
        page.set_default_timeout(20000)
        
        print(f"{prefix} Navigating to {config['video_url']}...")
        await page.goto(config["video_url"], wait_until="domcontentloaded")
        
        await handle_cookie_consent(page, prefix)
        
        try:
            print(f"{prefix} Waiting for video player to initialize...")
            await page.wait_for_selector('#movie_player', timeout=20000)
            print(f"{prefix} [SUCCESS] Video player initialized.")
        except PlaywrightTimeoutError:
            print(f"{prefix} [ERROR] Video player did not load. Proxy might be down or page blocked.")
            return False
            
        print(f"{prefix} Querying video duration...")
        video_duration = None
        for _ in range(10):
            video_duration = await get_video_duration(page)
            if video_duration and video_duration > 0:
                break
            await page.wait_for_timeout(1000)
            
        if video_duration:
            print(f"{prefix} Detected video duration: {video_duration:.1f} seconds.")
            min_pct = config.get("min_watch_percentage", 40) / 100.0
            max_pct = config.get("max_watch_percentage", 90) / 100.0
            watch_pct = random.uniform(min_pct, max_pct)
            target_watch_time = int(video_duration * watch_pct)
            print(f"{prefix} Target watch percentage: {watch_pct*100:.1f}%. Target watch time: {target_watch_time} seconds.")
        else:
            target_watch_time = config.get("fallback_watch_time_seconds", 60)
            print(f"{prefix} [WARNING] Could not detect video duration. Falling back to default: {target_watch_time} seconds.")
            
        await robust_watch_and_handle_ads(page, target_watch_time, config, prefix)
        return True
        
    except Exception as e:
        print(f"{prefix} [ERROR] Session failed: {e}")
        return False
    finally:
        print(f"{prefix} Cleaning up and closing browser...")
        try:
            if context: await context.close()
            if browser: await browser.close()
        except Exception:
            pass

async def worker_loop(queue, worker_id, config, results):
    while True:
        try:
            proxy_str = queue.get_nowait()
        except asyncio.QueueEmpty:
            break
            
        success = await watch_with_proxy(proxy_str, worker_id, config)
        results.append((proxy_str, success))
        queue.task_done()

async def main():
    config = load_config()
    proxies = load_proxies(config.get("proxy_file", "proxy.txt"))
    
    if not proxies:
        print("[CRITICAL] No proxies found in proxy.txt. Exiting.")
        return
        
    num_workers = config.get("max_parallel_workers", 3)
    print(f"[*] Starting Concurrency Engine...")
    print(f"[*] Loaded {len(proxies)} proxies from {config.get('proxy_file')}")
    print(f"[*] Running {num_workers} parallel workers...")
    
    # Populate the task queue
    queue = asyncio.Queue()
    for proxy in proxies:
        await queue.put(proxy)
        
    results = []
    
    # Spawn worker loops
    workers = []
    for i in range(1, num_workers + 1):
        worker_task = asyncio.create_task(worker_loop(queue, i, config, results))
        workers.append(worker_task)
        
    # Wait for all workers to finish processing the queue
    await asyncio.gather(*workers)
    
    # Report summary
    total_processed = len(results)
    successful_views = sum(1 for _, success in results if success)
    failed_views = total_processed - successful_views
    
    print("\n" + "="*50)
    print("CONCURRENCY BATCH RUN SUMMARY")
    print("="*50)
    print(f"Total Proxies Processed: {total_processed}")
    print(f"Successful Views:        {successful_views}")
    print(f"Failed Connections/Views: {failed_views}")
    print(f"Success Rate:            {(successful_views/total_processed)*100:.1f}%" if total_processed > 0 else "N/A")
    print("="*50)

if __name__ == "__main__":
    # Force stdout to be line-buffered so logs are shown live in redirected files without the -u flag
    sys.stdout.reconfigure(line_buffering=True)
    asyncio.run(main())
