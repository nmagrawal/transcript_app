import streamlit as st
import asyncio
import re
import io
import zipfile
from pathlib import Path
from playwright.async_api import async_playwright

# nest_asyncio is a critical helper to allow Playwright's async functions
# to run inside Streamlit's existing async environment.
import nest_asyncio
nest_asyncio.apply()

# --- App Configuration ---
st.set_page_config(
    page_title="Universal Transcript Scraper",
    page_icon="📜",
    layout="centered"
)

# Initialize session state to store results across reruns
if 'transcript_files' not in st.session_state:
    st.session_state.transcript_files = []

# --- Core Scraping Logic (adapted from previous scripts) ---

def parse_vtt(vtt_content: str) -> str:
    lines = vtt_content.strip().split('\n')
    transcript_lines = [re.sub(r'>>\s*', '', line).strip() for line in lines if line.strip() and "-->" not in line and "WEBVTT" not in line and not line.strip().isdigit()]
    return "\n".join(dict.fromkeys(transcript_lines).keys())

def sanitize_filename(name: str) -> str:
    sanitized = re.sub(r'[\\/*?:"<>|]', "", name).strip()
    return (sanitized[:150] + '...') if len(sanitized) > 150 else sanitized

async def handle_granicus_url(page):
    player_locator = page.locator(".flowplayer")
    cc_button_locator = page.locator(".fp-cc").first
    await player_locator.click(timeout=10000)
    await page.wait_for_timeout(500)
    await player_locator.click(timeout=10000)
    await page.wait_for_timeout(500)
    await player_locator.hover(timeout=5000)
    await cc_button_locator.click(timeout=10000)
    await page.wait_for_timeout(500)
    await page.locator(".fp-menu").get_by_text("On", exact=True).click(timeout=10000)

async def handle_viebit_url(page):
    await page.locator(".vjs-big-play-button").click(timeout=20000)
    await page.locator(".vjs-play-control").click(timeout=10000)
    await page.wait_for_timeout(500)
    await page.locator("button.vjs-subs-caps-button").click(timeout=10000)
    await page.locator('.vjs-menu-item:has-text("English")').click(timeout=10000)

async def process_single_url(url: str, log_container):
    """ The core scraping logic, adapted to update the Streamlit UI. """
    log_container.info(f"▶️ Processing: {url}")
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, channel="chrome")
            page = await browser.new_page()

            vtt_future = asyncio.Future()
            async def handle_response(response):
                if ".vtt" in response.url and not vtt_future.done():
                    log_container.info(f"  - ✅ Intercepted VTT file!")
                    vtt_future.set_result(await response.text())

            page.on("response", handle_response)
            await page.goto(url, wait_until="load", timeout=45000)

            if "granicus.com" in url:
                log_container.info("  - Detected Granicus. Executing trigger sequence...")
                await handle_granicus_url(page)
            elif "viebit.com" in url:
                log_container.info("  - Detected Viebit. Executing trigger sequence...")
                await handle_viebit_url(page)
            else:
                log_container.error(f"  - ❌ FAILED: Unknown platform for this URL.")
                await browser.close()
                return None

            log_container.info("  - Waiting for VTT capture...")
            vtt_content = await asyncio.wait_for(vtt_future, timeout=20)
            log_container.info("  - VTT content captured successfully!")

            video_title = await page.title()
            sanitized_title = sanitize_filename(video_title)
            transcript = parse_vtt(vtt_content)
            
            await browser.close()
            return (f"{sanitized_title}.txt", transcript)

    except Exception as e:
        log_container.error(f"  - ❌ An error occurred: {e}")
        return None

# --- Streamlit UI ---

st.title("📜 Universal Transcript Scraper")
st.markdown("Paste video URLs below (one per line) from supported platforms like **Dublin/Granicus** or **Fremont/Viebit**.")

urls_text = st.text_area("Video URLs", height=150, placeholder="https://dublin.granicus.com/player/clip/...\nhttps://fremontca.viebit.com/watch?hash=...")

col1, col2 = st.columns([1, 1])

with col1:
    process_button = st.button("🚀 Process URLs", type="primary")

with col2:
    if st.button("🧹 Clear Results"):
        st.session_state.transcript_files = []
        st.success("Results cleared!")
        # A small trick to force a UI update
        st.experimental_rerun()

if process_button:
    urls = [url.strip() for url in urls_text.splitlines() if url.strip()]
    if not urls:
        st.warning("Please paste at least one URL.")
    else:
        st.session_state.transcript_files = [] # Clear previous results on new run
        log_expander = st.expander("Processing Log", expanded=True)
        
        with st.spinner("Processing... This may take a moment."):
            for url in urls:
                with log_expander:
                    result = asyncio.run(process_single_url(url, st.container()))
                    if result:
                        st.session_state.transcript_files.append(result)
        
        st.success("All URLs have been processed!")

if st.session_state.transcript_files:
    st.markdown("---")
    st.header("Downloads")
    st.info(f"Successfully generated {len(st.session_state.transcript_files)} transcript(s).")

    # Create a zip file in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
        for filename, content in st.session_state.transcript_files:
            zip_file.writestr(filename, content)

    st.download_button(
        label="📥 Download All Transcripts (.zip)",
        data=zip_buffer.getvalue(),
        file_name="transcripts.zip",
        mime="application/zip",
    )