import sys
import os

class VSCodeLogger(object):
    def __init__(self, log_file, original_stream):
        self.log_file = log_file
        self.original_stream = original_stream

    def write(self, message):
        self.original_stream.write(message)
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(message)
        except:
            pass

    def flush(self):
        self.original_stream.flush()

def onStart():
    log_path = 'T:/td_dump/td_console.log'
    
    try:
        with open(log_path, 'w', encoding='utf-8') as f:
            f.write("🚀 --- TouchDesigner Live Console Stream Active ---\n\n")
    except Exception as e:
        print(f"Failed to initialize VS Code logging file: {e}")
        return

    # DEFENSIVE CHECK: Use a signature property string to detect our logger safely
    if not hasattr(sys.stdout, 'log_file'):
        sys.stdout = VSCodeLogger(log_path, sys.stdout)
    if not hasattr(sys.stderr, 'log_file'):
        sys.stderr = VSCodeLogger(log_path, sys.stderr)
        
    print("⚡ System standard output cleanly duplicated to T:/td_dump/td_console.log")

onStart()