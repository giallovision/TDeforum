# Text DAT `export_toe` (right-click > Run Script).
# Saves the project, then copies the .toe to the share root for git tracking.
#
# Safe when the project is already opened from the share: the old version
# opened the target for writing before reading the source, which truncates the
# file to 0 bytes when source and target are the same file.

import os
import shutil


def _same_file(a, b):
    try:
        return os.path.samefile(a, b)
    except OSError:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def export_toe_only():
    project.save()

    try:
        target_folder = os.path.dirname(os.path.dirname(me.par.file.eval())) or 'T:/'
    except Exception:
        target_folder = 'T:/'
    if not os.path.isdir(target_folder):
        print('[TDeforum] export_toe: cannot reach %s' % target_folder)
        return

    source = os.path.join(project.folder, project.name)
    target = os.path.join(target_folder, project.name)
    if not os.path.isfile(source):
        print('[TDeforum] export_toe: source not found: %s' % source)
        return
    if os.path.exists(target) and _same_file(source, target):
        print('[TDeforum] export_toe: project is already on the share (%s); saved, nothing to copy' % target)
        return

    temp = target + '.partial'
    try:
        shutil.copyfile(source, temp)
        os.replace(temp, target)
        print('[TDeforum] export_toe: %s -> %s' % (source, target))
    except Exception as exc:
        print('[TDeforum] export_toe failed: %s' % exc)
        try:
            os.remove(temp)
        except OSError:
            pass


export_toe_only()
