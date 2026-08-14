#!/usr/bin/env python3
from __future__ import annotations

import base64
import gzip
import hashlib
import importlib
import json
import os
import secrets
import sys
import tempfile
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PAYLOADS = ROOT / "payloads"
EXPECTED = {
    "app.py": "7a439e7752b69d822252bddf60c561af729f2fe53167b76bb269d94723fd3bcd",
    "instagram_reel_poster.py": "a39139d23929e7e3cdab73743c55ab56a1b966596fb0fe4f09f2b08771ba4da7",
}


def rebuild(name: str, target: Path) -> None:
    chunks = sorted(PAYLOADS.glob(f"{name}.gz.b64.part*"))
    if not chunks:
        raise SystemExit(f"Missing payload chunks for {name}")
    encoded = b"".join(p.read_bytes().strip() for p in chunks)
    try:
        data = gzip.decompress(base64.b64decode(encoded, validate=True))
    except Exception as exc:
        raise SystemExit(f"Unable to decode payload for {name}: {exc}") from exc
    digest = hashlib.sha256(data).hexdigest()
    if digest != EXPECTED[name]:
        raise SystemExit(f"Checksum mismatch for {name}: {digest}")
    target.write_bytes(data)


def install_instagram_video_url_patch(poster, app) -> None:
    """
    Meta's current Instagram API requires Reel containers to include a public
    video_url. The original payload attempted a local resumable binary upload.
    This patch stages the already-downloaded Reel behind this Railway service,
    gives Meta that HTTPS URL, and leaves the rest of the proven queue/state
    logic unchanged.
    """

    def public_base_url() -> str:
        explicit = os.getenv("PUBLIC_MEDIA_BASE_URL", "").strip().rstrip("/")
        if explicit:
            return explicit
        domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip()
        return f"https://{domain}" if domain else ""

    original_download_video = poster.download_video

    def download_video_and_stage(video):
        base = public_base_url()
        if not base:
            raise poster.ReelPosterError(
                "Public media URL is missing. In Railway open Settings > Networking > "
                "Public Networking, click Generate Domain, then redeploy before posting."
            )

        path = original_download_video(video)
        suffix = path.suffix.lower() or ".mp4"
        token = secrets.token_urlsafe(32).replace("-", "_")
        staged = path.with_name(f"serve_{token}{suffix}")
        path.replace(staged)

        poster._PUBLIC_VIDEO_URL = (
            f"{base}/media/{urllib.parse.quote(staged.name, safe='')}"
        )
        return staged

    def create_reel_container(caption: str):
        video_url = getattr(poster, "_PUBLIC_VIDEO_URL", "")
        if not video_url:
            raise poster.ReelPosterError("Temporary public Reel URL was not staged")

        payload = poster.graph_request(
            "POST",
            f"{poster.INSTAGRAM_USER_ID}/media",
            {
                "media_type": "REELS",
                "video_url": video_url,
                "caption": caption,
                "share_to_feed": "true" if poster.SHARE_TO_FEED else "false",
            },
        )
        container_id = str(payload.get("id") or "").strip()
        if not container_id:
            raise poster.ReelPosterError(
                "Instagram container response did not include an id"
            )

        # Preserve the original function's tuple return contract. upload_binary()
        # is patched to a no-op because Instagram now fetches video_url itself.
        return container_id, "railway-video-url"

    def upload_binary_noop(upload_uri, video_path):
        return None

    def poll_container_current(container_id: str):
        # Meta's current Reel container status endpoint exposes status_code + status.
        # Do not request the obsolete/nonexistent video_status field.
        deadline = poster.time.monotonic() + poster.POLL_TIMEOUT
        last = {}
        while poster.time.monotonic() < deadline:
            last = poster.graph_request(
                "GET",
                container_id,
                {"fields": "id,status_code,status"},
            )
            status_code = str(last.get("status_code") or "").upper()
            if status_code == "FINISHED":
                return last
            if status_code in {"ERROR", "EXPIRED"}:
                raise poster.ReelPosterError(
                    f"Instagram container {container_id} ended with {status_code}: "
                    f"{poster.sanitize(last.get('status') or last)}"
                )
            poster.time.sleep(poster.POLL_INTERVAL)
        raise poster.ReelPosterError(
            f"Instagram container {container_id} did not reach FINISHED within "
            f"{poster.POLL_TIMEOUT}s; last status={poster.sanitize(last)}"
        )

    poster.download_video = download_video_and_stage
    poster.create_reel_container = create_reel_container
    poster.upload_binary = upload_binary_noop
    poster.poll_container = poll_container_current
    poster.PUBLIC_MEDIA_BASE_URL = public_base_url()

    def serve_media(handler, head_only: bool = False) -> bool:
        parsed = urllib.parse.urlsplit(handler.path)
        if not parsed.path.startswith("/media/"):
            return False

        name = urllib.parse.unquote(parsed.path[len("/media/"):])
        if (
            not name
            or "/" in name
            or "\\" in name
            or not name.startswith("serve_")
        ):
            handler.send_response(404)
            handler.end_headers()
            return True

        root = poster.TEMP_DIR.resolve()
        target = (poster.TEMP_DIR / name).resolve()
        if target.parent != root or not target.is_file():
            handler.send_response(404)
            handler.end_headers()
            return True

        size = target.stat().st_size
        start = 0
        end = max(0, size - 1)
        status = 200

        range_header = handler.headers.get("Range", "").strip()
        if range_header.startswith("bytes="):
            try:
                spec = range_header[6:].split(",", 1)[0].strip()
                left, right = spec.split("-", 1)
                if left:
                    start = int(left)
                if right:
                    end = int(right)
                if not left and right:
                    length = int(right)
                    start = max(0, size - length)
                    end = size - 1
                if start < 0 or end < start or start >= size:
                    raise ValueError
                end = min(end, size - 1)
                status = 206
            except Exception:
                handler.send_response(416)
                handler.send_header("Content-Range", f"bytes */{size}")
                handler.end_headers()
                return True

        length = end - start + 1 if size else 0
        content_type = (
            "video/quicktime" if target.suffix.lower() == ".mov" else "video/mp4"
        )

        handler.send_response(status)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Accept-Ranges", "bytes")
        handler.send_header("Cache-Control", "private, no-store")
        handler.send_header("Content-Length", str(length))
        if status == 206:
            handler.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        handler.end_headers()

        if not head_only and length:
            with target.open("rb") as fh:
                fh.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = fh.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    handler.wfile.write(chunk)
                    remaining -= len(chunk)
        return True

    old_get = app.HealthHandler.do_GET

    def patched_get(handler):
        if serve_media(handler, head_only=False):
            return
        return old_get(handler)

    def patched_head(handler):
        if serve_media(handler, head_only=True):
            return
        if handler.path in {"/", "/health"}:
            handler.send_response(200)
            handler.send_header("Content-Type", "application/json")
            handler.end_headers()
            return
        handler.send_response(404)
        handler.end_headers()

    app.HealthHandler.do_GET = patched_get
    app.HealthHandler.do_HEAD = patched_head


def main() -> None:
    runtime = Path(tempfile.mkdtemp(prefix="ig-reels-runtime-"))
    rebuild("instagram_reel_poster.py", runtime / "instagram_reel_poster.py")
    rebuild("app.py", runtime / "app.py")

    sys.path.insert(0, str(runtime))
    os.chdir(runtime)

    poster = importlib.import_module("instagram_reel_poster")
    app = importlib.import_module("app")

    install_instagram_video_url_patch(poster, app)
    raise SystemExit(app.main())


if __name__ == "__main__":
    main()
