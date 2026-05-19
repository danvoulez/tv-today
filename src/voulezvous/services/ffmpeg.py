import asyncio
import shutil
from pathlib import Path

import structlog

from voulezvous.config import settings

logger = structlog.get_logger()


async def run_ffmpeg(args: list[str]) -> tuple[int, str, str]:
    cmd = [settings.ffmpeg_path] + args
    logger.info("ffmpeg_run", cmd=" ".join(cmd))
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode or 0, stdout.decode(), stderr.decode()


async def normalize_video(input_path: Path, output_path: Path) -> Path:
    w, h = settings.house_resolution.split("x")
    args = [
        "-y",
        "-i", str(input_path),
        "-c:v", settings.house_video_codec,
        "-c:a", settings.house_audio_codec,
        "-r", str(settings.house_frame_rate),
        "-ar", str(settings.house_audio_sample_rate),
        "-vf",
        f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2",
        "-movflags", "+faststart",
        str(output_path),
    ]
    rc, _, stderr = await run_ffmpeg(args)
    if rc != 0:
        raise RuntimeError(f"FFmpeg normalize failed (rc={rc}): {stderr[-500:]}")
    return output_path


async def mix_audio(
    video_path: Path,
    music_path: Path,
    output_path: Path,
    video_gain: float = 0.5,
    music_gain: float = 0.5,
) -> Path:
    args = [
        "-y",
        "-i", str(video_path),
        "-i", str(music_path),
        "-filter_complex",
        f"[0:a]volume={video_gain}[va];[1:a]volume={music_gain}[ma];"
        f"[va][ma]amix=inputs=2:duration=first:dropout_transition=2[aout]",
        "-map", "0:v",
        "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", settings.house_audio_codec,
        "-ar", str(settings.house_audio_sample_rate),
        "-shortest",
        str(output_path),
    ]
    rc, _, stderr = await run_ffmpeg(args)
    if rc != 0:
        raise RuntimeError(f"FFmpeg mix failed (rc={rc}): {stderr[-500:]}")
    return output_path


async def stream_to_target(input_path: Path, target: str) -> tuple[int, str]:
    if target == "null":
        args = ["-y", "-re", "-i", str(input_path), "-f", "null", "-"]
    elif target == "hls":
        return await stream_to_hls(input_path)
    else:
        args = [
            "-re",
            "-i", str(input_path),
            "-c", "copy",
            "-f", "flv",
            target,
        ]
    rc, _, stderr = await run_ffmpeg(args)
    return rc, stderr


async def stream_to_hls(input_path: Path) -> tuple[int, str]:
    hls_dir = settings.spool_hls
    hls_dir.mkdir(parents=True, exist_ok=True)
    playlist = hls_dir / "stream.m3u8"

    args = [
        "-re",
        "-i", str(input_path),
        "-c:v", "copy",
        "-c:a", "copy",
        "-f", "hls",
        "-hls_time", str(settings.hls_segment_duration),
        "-hls_list_size", str(settings.hls_playlist_size),
        "-hls_flags", "delete_segments+append_list+omit_endlist+program_date_time",
        "-hls_segment_filename", str(hls_dir / "seg_%05d.ts"),
        str(playlist),
    ]
    rc, _, stderr = await run_ffmpeg(args)
    return rc, stderr


def copy_file(src: Path, dst: Path) -> Path:
    shutil.copy2(src, dst)
    return dst
