# Mirrors the TouchDesigner textport (stdout/stderr) to <share>/runtime/td_console.log
# so it can be tailed in VS Code. Run once per session (e.g. from an Execute DAT
# onStart, or right-click > Run Script). Re-running re-points the log cleanly.
#
# Keeps one line-buffered handle open instead of opening the file over SMB for
# every write.

import os
import sys


class VSCodeLogger(object):
    def __init__(self, log_file, original_stream, handle):
        self.log_file = log_file
        self.original_stream = original_stream
        self._handle = handle

    def write(self, message):
        self.original_stream.write(message)
        try:
            self._handle.write(message)
        except Exception:
            pass

    def flush(self):
        try:
            self.original_stream.flush()
            self._handle.flush()
        except Exception:
            pass

    def __getattr__(self, name):
        return getattr(self.original_stream, name)


def _unwrap(stream):
    while hasattr(stream, 'log_file') and hasattr(stream, 'original_stream'):
        stream = stream.original_stream
    return stream


def onStart():
    try:
        share_root = os.path.dirname(os.path.dirname(me.par.file.eval())) or 'T:/'
    except Exception:
        share_root = 'T:/'
    log_dir = os.path.join(share_root, 'runtime')
    log_path = os.path.join(log_dir, 'td_console.log').replace('\\', '/')

    try:
        os.makedirs(log_dir, exist_ok=True)
        handle = open(log_path, 'w', encoding='utf-8', buffering=1)
        handle.write('--- TouchDesigner live console stream ---\n\n')
    except Exception as exc:
        print('Failed to initialise VS Code log %s: %s' % (log_path, exc))
        return

    sys.stdout = VSCodeLogger(log_path, _unwrap(sys.stdout), handle)
    sys.stderr = VSCodeLogger(log_path, _unwrap(sys.stderr), handle)
    print('[TDeforum] console mirrored to %s' % log_path)


onStart()
