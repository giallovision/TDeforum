import os

def onAdd(dat, row):
    new_file_path = dat[row, 'path'].val
    
    # If ComfyUI appended the annoying _00001 counter, strip it out!
    if "_00001.mp4" in new_file_path:
        clean_file_path = new_file_path.replace("_00001.mp4", ".mp4")
        
        try:
            os.rename(new_file_path, clean_file_path)
            clean_name = os.path.basename(clean_file_path)
            print(f"✨ Auto-renamed ComfyUI output to: {clean_name}")
            
            # Automatically route the pristine file to Deforum
            deforum_ui = op('Deforum_UI')
            if deforum_ui:
                deforum_ui.par.Cn1vidpath = f"/opt/a1111/td_masks/preprocessed_vids/{clean_name}"
                
        except Exception as e:
            print(f"⚠️ Could not rename file: {e}")