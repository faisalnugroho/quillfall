#!/usr/bin/env python3
"""Record the Quillfall tutorial video (<=30s) via Playwright.

Flow (timed for 30s at 8fps -> ~240 frames):
  0.0-2.5s   hero: falling leaves + title
  2.5-4.5s   scroll to stats
  4.5-7.5s   load limerick preset into the desk
  7.5-10s    click new wallet (burner created)
  10-13s     click Seal & submit (tx sent)
  13-16s     hold on the busy state (judges reading)
  16-24s     poll until verdict renders (real consensus!)
  24-30s     scroll through the verdict + anthology
"""
import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

URL = "https://faisalnugroho.github.io/quillfall/"
OUT_DIR = Path("/home/ubuntu/quillfall-artifacts")
FRAMES = OUT_DIR / "frames"
VIDEO = OUT_DIR / "quillfall-tutorial.mp4"
FPS = 8
DURATION = 30

sys.path.insert(0, "/home/ubuntu/venv-312-gendid-audit/lib/python3.12/site-packages")


async def main():
    from playwright.async_api import async_playwright

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if FRAMES.exists():
        shutil.rmtree(FRAMES)
    FRAMES.mkdir()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            device_scale_factor=1,
            reduced_motion="no-preference",
        )
        page = await ctx.new_page()
        await page.goto(URL, wait_until="networkidle", timeout=60000)

        # Give the page time to boot (contract.json fetch + stats read)
        for _ in range(30):
            conn = await page.evaluate(
                "document.getElementById('connstatus').textContent")
            if conn == "connected":
                break
            await page.wait_for_timeout(1000)

        async def snap(label):
            ts = time.time()
            n = len(list(FRAMES.glob("f_*.png")))
            await page.screenshot(path=str(FRAMES / f"f_{n:04d}.png"))
            if n % FPS == 0:
                print(f"[{n/FPS:5.1f}s] {label}", flush=True)

        async def hold(seconds, label):
            end = time.time() + seconds
            while time.time() < end:
                await snap(label)
                await page.wait_for_timeout(int(1000 / FPS))

        t_start = time.time()

        # PASS 1 (0-13s): hero -> desk -> preset -> wallet -> submit ->
        # adjudicate click. Ends on "the judges are reading…".
        await page.evaluate("window.scrollTo(0, 0)")
        await hold(2.5, "hero")

        await page.evaluate(
            "document.getElementById('f-title').scrollIntoView({block:'center'})")
        await hold(2.0, "desk+stats")

        await page.get_by_text("load limerick").click()
        await hold(2.0, "preset-loaded")

        await page.get_by_text("+ new").click()
        await page.wait_for_timeout(1500)   # faucet round-trip
        await hold(2.0, "wallet")

        await page.click("#btn-submit")
        # hold until the submission id is visible (real tx, ~10-20s).
        # NO screenshots during the real-time wait — the video is a cut.
        deadline = time.time() + 90
        while time.time() < deadline:
            status = await page.evaluate(
                "document.getElementById('status-submit').textContent")
            if "Submitted" in status:
                break
            await page.wait_for_timeout(2000)
        await page.click("#btn-adjudicate")
        await hold(4.0, "judges-reading")   # ends pass 1 (~13s of frames)

        # — time skip: real consensus runs (45-90s), same page, same session.
        # No screenshots are taken during the wait; the video cuts from the
        # "judges reading" state to the SEALED verdict of THIS submission.
        deadline = time.time() + 420
        verdict_seen = False
        re_cranks = 0
        while time.time() < deadline:
            v = await page.evaluate(
                "(() => { const el = document.getElementById('verdict');"
                " return el && el.style.display !== 'none' ?"
                " el.innerText.slice(0, 60) : ''; })()")
            if v:
                verdict_seen = True
                break
            st = await page.evaluate(
                "document.getElementById('status-adjud').textContent")
            # a discarded consensus round surfaces as Failed/still-pending;
            # re-crank adjudicate (allowed by the contract, max 2 retries)
            if ("Failed" in st or "still pending" in st) and re_cranks < 2:
                re_cranks += 1
                print(f"re-cranking adjudicate #{re_cranks}", flush=True)
                try:
                    await page.click("#btn-adjudicate")
                except Exception:
                    pass
            await page.wait_for_timeout(3000)
        print("verdict seen:", verdict_seen, "re_cranks:", re_cranks,
              flush=True)

        # PASS 2 (13-30s): verdict card + anthology + stats
        await page.evaluate(
            "document.getElementById('verdict').scrollIntoView({block:'center'})")
        await hold(6.0, "verdict")
        await page.evaluate(
            "document.querySelector('section:last-of-type').scrollIntoView({block:'start'})")
        await hold(3.0, "anthology")
        await page.evaluate("window.scrollTo(0, 0)")
        await hold(4.0, "stats-final")

        await browser.close()

    n = len(list(FRAMES.glob("f_*.png")))
    print(f"frames: {n} -> {n/FPS:.1f}s at {FPS}fps", flush=True)

    # trim/pad to exactly <=30s and encode
    if VIDEO.exists():
        VIDEO.unlink()
    subprocess.run([
        "ffmpeg", "-y", "-framerate", str(FPS),
        "-i", str(FRAMES / "f_%04d.png"),
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "24",
        "-t", str(DURATION),
        "-vf", "scale=1280:720",
        str(VIDEO),
    ], check=True, capture_output=True)
    dur = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(VIDEO)], capture_output=True, text=True)
    print("video:", VIDEO)
    print("duration:", json.loads(dur.stdout)["format"]["duration"], "s")
    print("size:", VIDEO.stat().st_size, "bytes")


if __name__ == "__main__":
    asyncio.run(main())
