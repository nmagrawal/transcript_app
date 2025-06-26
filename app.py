import asyncio
import re
from pathlib import Path
import streamlit as st
from playwright.async_api import async_playwright, TimeoutError

import os
if not os.path.exists("/home/appuser/.playwright"):
    os.system("playwright install chromium")


# --- Utility Functions ---

def parse_vtt(vtt_content: str) -> str:
    lines = vtt_content.strip().split('\n')
    transcript_lines = []
    seen_lines = set()

    for line in lines:
        if not line.strip() or "WEBVTT" in line or "-->" in line or line.strip().isdigit():
            continue
        cleaned_line = re.sub(r'>>\s*', '', line).strip()
        if cleaned_line and cleaned_line not in seen_lines:
            transcript_lines.append(cleaned_line)
            seen_lines.add(cleaned_line)
    return "\n".join(transcript_lines)

def sanitize_filename(name: str) -> str:
    sanitized = re.sub(r'[\\/*?:"<>|]', "", name).strip()
    return (sanitized[:150] + '...') if len(sanitized) > 150 else sanitized

async def handle_granicus_url(page):
    await page.locator(".flowplayer").click(timeout=10000)
    await page.wait_for_timeout(500)
    await page.locator(".flowplayer").click(timeout=10000)
    await page.wait_for_timeout(500)
    await page.locator(".flowplayer").hover(timeout=5000)
    await page.locator(".fp-cc").first.click(timeout=10000)
    await page.wait_for_timeout(500)
    await page.locator(".fp-menu").get_by_text("On", exact=True).click(timeout=10000)

async def handle_viebit_url(page):
    await page.locator(".vjs-big-play-button").click(timeout=20000)
    await page.locator(".vjs-play-control").click(timeout=10000)
    await page.wait_for_timeout(500)
    await page.locator("button.vjs-subs-caps-button").click(timeout=10000)
    await page.locator('.vjs-menu-item:has-text("English")').click(timeout=10000)

async def process_url(url: str, browser_channel="chrome"):
    transcript = None
    filename = None
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, channel=browser_channel)
        page = await browser.new_page()
        vtt_future = asyncio.Future()

        async def handle_response(response):
            if ".vtt" in response.url and not vtt_future.done():
                try:
                    vtt_future.set_result(await response.text())
                except Exception as e:
                    vtt_future.set_exception(e)

        page.on("response", handle_response)

        try:
            await page.goto(url, wait_until="load", timeout=45000)
            if "granicus.com" in url:
                await handle_granicus_url(page)
            elif "viebit.com" in url:
                await handle_viebit_url(page)
            else:
                return "Unsupported platform", None

            vtt_content = await asyncio.wait_for(vtt_future, timeout=20)
            video_title = await page.title()
            sanitized_title = sanitize_filename(video_title)
            transcript = parse_vtt(vtt_content)
            filename = f"{sanitized_title}.txt"

        except asyncio.TimeoutError:
            return "Timeout error", None
        except Exception as e:
            return f"Error: {str(e)}", None
        finally:
            await browser.close()

    return transcript, filename


st.set_page_config(page_title="City Video Transcript Tool", layout="wide")
st.title("📼 City Video Transcript Extractor")

st.markdown("Enter video URLs from Granicus or Viebit-supported platforms (one per line):")

url_input = st.text_area("Paste URLs here:", height=200, placeholder="https://...")

if st.button("Generate Transcripts"):
    urls = [line.strip() for line in url_input.split("\n") if line.strip()]
    if not urls:
        st.warning("Please enter at least one valid URL.")
    else:
        results = []

        async def run_all():
            tasks = [process_url(url) for url in urls]
            return await asyncio.gather(*tasks)

        transcripts = asyncio.run(run_all())

        for (transcript, filename), original_url in zip(transcripts, urls):
            st.markdown(f"### Transcript from: {original_url}")
            if isinstance(transcript, str) and filename:
                st.text_area("Transcript Preview", transcript[:2000], height=300)
                st.download_button(
                    label="Download Full Transcript",
                    data=transcript,
                    file_name=filename,
                    mime="text/plain"
                )
            else:
                st.error(f"❌ Could not process URL: {original_url}. Reason: {transcript}")
