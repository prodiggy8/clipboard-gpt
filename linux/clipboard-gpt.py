#!/usr/bin/env python3
"""
Requirements: Wayland clipboard manager & Gemini API key
"""
from __future__ import annotations
from google import genai
from google.genai import types
import hashlib
import os
import shutil
import subprocess
import sys
import time
from dotenv import load_dotenv

load_dotenv()

CLIPBOARD_PROMPT = "Please solve the following problem. Return the instructions to solve (no math, just text) and the final answer (latex)."
GEMINI_MODEL = "gemini-2.5-flash"
POLL_INTERVAL = 0.5
MIME_TO_EXT = {
    "image/png": ".png",
    "image/x-png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/pjpeg": ".jpg",
}
_FALLBACK_MIMES = ("image/png", "image/jpeg")


def _mime_for_ext(ext: str) -> str:
    ext = ext.lower()

    if ext == ".png":
        return "image/png"
    
    if ext in (".jpg", ".jpeg"):
        return "image/jpeg"
    
    return "image/png"


def _client() -> genai.Client:
    key = os.environ.get("API_KEY")

    if not key:
        print("API_KEY missing.", file=sys.stderr)
        sys.exit(1)
    
    return genai.Client(api_key=key)


def _wl_paste_types(primary: bool) -> list[str]:
    if not shutil.which("wl-paste"):
        return []
    cmd = ["wl-paste", "--list-types"]
    if primary:
        cmd.insert(1, "-p")
    r = subprocess.run(
        cmd,
        capture_output=True,
        timeout=5,
    )
    if r.returncode != 0:
        return []
    text = r.stdout.decode("utf-8", errors="replace")
    return [line.strip() for line in text.splitlines() if line.strip()]


def _first_png_or_jpeg_mime(types: list[str]) -> str | None:
    for t in types:
        base = t.split(";", 1)[0].strip().lower()
        if base in MIME_TO_EXT:
            return base
    return None


def _ext_for_mime(mime: str) -> str:
    base = mime.split(";", 1)[0].strip().lower()
    return MIME_TO_EXT[base]


def _try_wl_paste_once(primary: bool) -> tuple[bytes, str] | None:
    types = _wl_paste_types(primary)
    mimes_to_try = []
    seen = set()

    first = _first_png_or_jpeg_mime(types)

    if first:
        mimes_to_try.append(first)
        seen.add(first)

    for m in _FALLBACK_MIMES:
        if m not in seen:
            mimes_to_try.append(m)
            seen.add(m)

    base = ["wl-paste"]

    if primary:
        base.append("-p")

    for mime in mimes_to_try:
        r = subprocess.run(
            [*base, "-t", mime],
            capture_output=True,
            timeout=15,
        )
        if r.returncode == 0 and r.stdout:
            return r.stdout, _ext_for_mime(mime)

    return None


def _digest(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def read_clipboard_image() -> tuple[bytes, str] | None:
    for primary in (False, True):
        got = _try_wl_paste_once(primary)
        if got is not None:
            return got

    return None


def describe_clipboard_image(client: genai.Client, data: bytes, ext: str) -> str:
    img = types.Part.from_bytes(data=data, mime_type=_mime_for_ext(ext))

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[
            CLIPBOARD_PROMPT,
            img,
        ],
    )
    
    if response.text is None:
        return ""

    return response.text


def write_clipboard_text(text: str) -> None:
    subprocess.run(
        ["wl-copy"],
        input=text.encode("utf-8"),
        check=True,
        timeout=60,
    )

def run_forever() -> int:
    if not shutil.which("wl-paste"):
        print("wl-paste not found.", file=sys.stderr)
        return 1

    if not shutil.which("wl-copy"):
        print("wl-copy not found.", file=sys.stderr)
        return 1

    client = _client()
    last_digest = None

    try:
        while True:
            result = read_clipboard_image()
            
            if result is None:
                time.sleep(POLL_INTERVAL)
                continue

            data, ext = result
            d = _digest(data)
            
            if d == last_digest:
                time.sleep(POLL_INTERVAL)
                continue

            last_digest = d
            
            try:
                out = describe_clipboard_image(client, data, ext)
                print(out, flush=True)
                write_clipboard_text(out)
            except Exception as e:
                print(f"Gemini or clipboard failed: {e}", file=sys.stderr)
            
            time.sleep(POLL_INTERVAL)
    
    except KeyboardInterrupt:
        if sys.stderr.isatty():
            print("Stopped.", file=sys.stderr)
        return 0


def main() -> int:
    return run_forever()

if __name__ == "__main__":
    sys.exit(main())
