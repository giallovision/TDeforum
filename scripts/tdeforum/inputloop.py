"""COMP output 3: the init video conformed to the render, frame for frame.

TouchDesigner's Movie File In cannot open every file Deforum can (AV1 / VP9 / HEVC / 10-bit
mp4s fail with "Failed to open file"), and Deforum does not use the video as-is anyway: it
takes frames ``start, start + stride, ...`` and stretches them to W x H. So at Queue a
background thread (OpenCV, which reads what Deforum reads) writes exactly those frames, one
per render frame, at render size, to ``td_masks/feeds/input_loop_<key>.mp4`` with the codec
the sweep videos use (TD opens those). The loop player then plays that file with the same
playhead maths as the render. Same video + size + frames = cache hit.

When TouchDesigner cannot read the init video at all (e.g. the share's td_inputs is a symlink
Samba does not follow): first it is downloaded from ComfyUI's /view (td_inputs/comfy_videos is
ComfyUI's input folder) into td_masks/comfy_fetch; failing that, the frames Deforum itself
extracted are used after the render: ``<render folder>/inputframes/*.jpg``.
"""

import hashlib
import json
import os
import time

from . import sweep

PREFIX = "input_loop_"


def job_key(share_path, size, start, stride, frames):
    try:
        st = os.stat(share_path)
        stamp = [st.st_size, int(st.st_mtime)]
    except OSError:
        stamp = None
    blob = json.dumps({"v": 1, "src": share_path, "stamp": stamp, "size": list(size), "start": int(start),
                       "stride": int(stride), "frames": int(frames)}, sort_keys=True)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:10]


def make_job(share_path, feed_folder_share, feed_folder_container, size, start, stride, frames, fps):
    key = job_key(share_path, size, start, stride, frames)
    name = "%s%s.mp4" % (PREFIX, key)
    folder = feed_folder_share.rstrip("/") + "/"
    return {"key": key, "src": share_path, "size": [int(size[0]), int(size[1])], "start": int(start),
            "stride": max(1, int(stride)), "frames": int(frames), "fps": float(fps or 30.0),
            "out_share": folder + name, "out_container": feed_folder_container.rstrip("/") + "/" + name,
            "sidecar": folder + name + ".json"}


FRAME_DIRS = ("inputframes", "hybridframes")
FRAME_EXTS = (".jpg", ".jpeg", ".png")


def frames_dir(render_folder):
    """Deforum's extracted init frames in a render folder, or None."""
    for name in FRAME_DIRS:
        folder = os.path.join(render_folder, name)
        if os.path.isdir(folder) and any(f.lower().endswith(FRAME_EXTS) for f in os.listdir(folder)):
            return folder.replace("\\", "/")
    return None


def make_frames_job(folder, feed_folder_share, feed_folder_container, size, frames, fps):
    """A job that conforms Deforum's own extracted frames (``folder``) instead of the video."""
    blob = json.dumps({"v": 1, "dir": folder, "size": list(size), "frames": int(frames)}, sort_keys=True)
    key = "f" + hashlib.sha1(blob.encode("utf-8")).hexdigest()[:9]
    job = make_job(folder, feed_folder_share, feed_folder_container, size, 0, 1, frames, fps)
    name = "%s%s.mp4" % (PREFIX, key)
    base = feed_folder_share.rstrip("/") + "/"
    job.update(key=key, src_dir=folder, out_share=base + name,
               out_container=feed_folder_container.rstrip("/") + "/" + name, sidecar=base + name + ".json")
    return job


def source_readable(job):
    if job.get("src_dir"):
        return os.path.isdir(job["src_dir"])
    return os.path.isfile(job["src"]) or bool(job.get("fetch_url") and job.get("fetch_local")
                                              and not os.environ.get("TDEFORUM_OFFLINE"))


def download(url, path):
    """ComfyUI /view -> path. TDEFORUM_OFFLINE (set by the tests) keeps it off the network."""
    if os.environ.get("TDEFORUM_OFFLINE"):
        raise OSError("offline (TDEFORUM_OFFLINE): not fetching %s" % url)
    return sweep.download(url, path, timeout=30.0)


def _source(job, result=None):
    """The local video to read: the share file, else a copy downloaded from ComfyUI's /view."""
    if os.path.isfile(job["src"]):
        return job["src"]
    local = job.get("fetch_local")
    if job.get("fetch_url") and local:
        if not os.path.isfile(local):
            size = download(job["fetch_url"], local)
            if result is not None:
                result["fetched"] = size
        return local
    return job["src"]


def read_result(sidecar):
    return sweep.read_result(sidecar)


def ready(job):
    done = read_result(job["sidecar"])
    return bool(done and done.get("ok") and os.path.isfile(job["out_share"]))


def conform(job, result=None):
    """Write the conformed video. Returns {"frames", "codec", "source_frames"}."""
    import cv2
    width, height = job["size"]
    if job.get("src_dir"):
        return _conform_frames(cv2, job)
    src = _source(job, result)
    capture = cv2.VideoCapture(src)
    if not capture.isOpened():
        raise RuntimeError("OpenCV cannot open %s" % src)
    tmp = job["out_share"][:-4] + ".tmp" + job["out_share"][-4:]
    os.makedirs(os.path.dirname(tmp) or ".", exist_ok=True)
    writer, codec = sweep._open_writer(cv2, tmp, job["fps"], (width, height))
    written, index, wanted = 0, -1, job["start"]
    try:
        while written < job["frames"]:
            ok, frame = capture.read()
            if not ok:
                break
            index += 1
            if index < wanted:
                continue
            if frame.shape[1] != width or frame.shape[0] != height:
                frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
            writer.write(frame)
            written += 1
            wanted += job["stride"]
    finally:
        writer.release()
        capture.release()
    if not written:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise RuntimeError("no frames read from %s (from frame %d)" % (job["src"], job["start"]))
    os.replace(tmp, job["out_share"])
    return {"frames": written, "codec": codec}


def _conform_frames(cv2, job):
    width, height = job["size"]
    names = sorted(f for f in os.listdir(job["src_dir"]) if f.lower().endswith(FRAME_EXTS))[:job["frames"]]
    if not names:
        raise RuntimeError("no frames in %s" % job["src_dir"])
    tmp = job["out_share"][:-4] + ".tmp" + job["out_share"][-4:]
    os.makedirs(os.path.dirname(tmp) or ".", exist_ok=True)
    writer, codec = sweep._open_writer(cv2, tmp, job["fps"], (width, height))
    written = 0
    try:
        for name in names:
            frame = cv2.imread(os.path.join(job["src_dir"], name))
            if frame is None:
                continue
            if frame.shape[1] != width or frame.shape[0] != height:
                frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
            writer.write(frame)
            written += 1
    finally:
        writer.release()
    if not written:
        raise RuntimeError("no readable frames in %s" % job["src_dir"])
    os.replace(tmp, job["out_share"])
    return {"frames": written, "codec": codec}


def run_job(job):
    """Background-thread body. Never raises: the outcome goes to job["sidecar"]."""
    started = time.time()
    result = {"ok": False, "key": job.get("key")}
    try:
        out = conform(job, result)
        result.update(ok=True, frames=out["frames"], codec=out["codec"], out_share=job["out_share"],
                      out_container=job["out_container"])
    except Exception as exc:
        result["error"] = "%s: %s" % (type(exc).__name__, exc)
    result["seconds"] = round(time.time() - started, 2)
    try:
        sweep._write_json(job["sidecar"], result)
    except Exception:
        pass
    return result
