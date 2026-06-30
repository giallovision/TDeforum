import json
import os
import traceback

# Initialize memory bank to prevent double-loading
if 'last_loaded_timestamp' not in me.storage:
    me.storage['last_loaded_timestamp'] = ""

def check_and_load(filepath, attempt=1):
    """
    Recursively tests if the file is locked by Windows/FFmpeg.
    If locked, schedules another check in 30 frames (0.5 seconds).
    """
    if attempt > 20:
        print(f"❌ Timeout (10 seconds): Gave up waiting for file lock on {filepath}")
        return
        
    try:
        # 🛡️ THE POKE: Attempt to open the file in append mode. 
        with open(filepath, 'a'):
            pass
            
        # If we made it here, the lock is gone. The file is fully written!
        movie_in = op('moviefilein1')
        folder_monitor = op('folder_monitor')
        
        if movie_in:
            movie_in.par.file = filepath
            movie_in.par.reloadpulse.pulse()
            
        # 💡 THE FIX: Tell TouchDesigner's folder DAT to rescan the directory now that it's safe
        if folder_monitor:
            folder_monitor.par.refresh.pulse()
            
        print(f"🎬 Safe-Load Successful on attempt {attempt}: {filepath}")
            
    except (PermissionError, IOError):
        # File is still locked by the network or container. Wait 0.5s and try again.
        run_cmd = f"op('{me.path}').module.check_and_load('{filepath}', {attempt + 1})"
        run(run_cmd, delayFrames=30)
    except Exception as e:
        print(f"⚠️ Unexpected error polling file: {e}")

def onResponse(webClientDAT, statusCode, headerDict, data):
    if statusCode['code'] != 200:
        return
        
    try:
        json_string = data.decode('utf-8') if isinstance(data, bytes) else data
        job_data = json.loads(json_string)
        
        if not job_data:
            return
            
        batch_key = list(job_data.keys())[0]
        job_status = job_data[batch_key].get("status", "UNKNOWN")
        job_phase = job_data[batch_key].get("phase", "UNKNOWN")
        
        if job_status == "SUCCEEDED" or job_phase == "DONE":
            timestring = job_data[batch_key].get("timestring")
            linux_outdir = job_data[batch_key].get("outdir")
            
            if not timestring or not linux_outdir:
                return
                
            # 🛑 MEMORY LOCK: Stop immediately if we already kicked off a loader for this batch
            if me.storage['last_loaded_timestamp'] == timestring:
                return
            
            # Immediately log this run so subsequent API responses don't spawn duplicate checkers
            me.storage['last_loaded_timestamp'] = timestring
                
            win_outdir = linux_outdir.replace('/opt/a1111/', 'T:/')
            video_filename = f"{timestring}.mp4"
            target_video_path = os.path.join(win_outdir, video_filename).replace('\\', '/')
            
            # Kick off the recursive lock-checker in the background
            check_and_load(target_video_path, attempt=1)
                    
    except Exception as e:
        pass