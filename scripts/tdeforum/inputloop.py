"""COMP output 3: the init video conformed to the render, frame for frame.

TouchDesigner's Movie File In cannot open every file Deforum can (AV1 / VP9 / HEVC / 10-bit
mp4s fail with "Failed to open file"), and Deforum does not use the video as-is anyway: it
takes frames ``start, start + stride, ...`` and stretches them to W x H. So at Queue a
background thread (OpenCV, which reads what Deforum reads) writes exactly those frames, one
per render frame, at render size, to ``td_masks/feeds/input_loop_<key>.mp4`` with the codec
the sweep videos use (TD opens those). The loop player then plays that file with the same
playhead maths as the render. Same video + size + frames = cache hit.
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


def read_result(sidecar):
    return sweep.read_result(sidecar)


def ready(job):
    done = read_result(job["sidecar"])
    return bool(done and done.get("ok") and os.path.isfile(job["out_share"]))


def conform(job):
    """Write the conformed video. Returns {"frames", "codec", "source_frames"}."""
    import cv2
    width, height = job["size"]
    capture = cv2.VideoCapture(job["src"])
    if not capture.isOpened():
        raise RuntimeError("OpenCV cannot open %s" % job["src"])
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


def run_job(job):
    """Background-thread body. Never raises: the outcome goes to job["sidecar"]."""
    started = time.time()
    result = {"ok": False, "key": job.get("key")}
    try:
        out = conform(job)
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
