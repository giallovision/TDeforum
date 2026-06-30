import os

def export_toe_only():
    # 1. Save local project (Freezes TD for a split second)
    project.save()
    
    # 2. Target the ROOT directory, not td_dump
    target_folder = 'T:/'
    
    if not os.path.exists(target_folder):
        print(f"❌ Error: Cannot reach network drive {target_folder}")
        return
        
    source_toe = os.path.join(project.folder, project.name)
    target_toe = os.path.join(target_folder, project.name)
    
    print(f"🔍 DEBUG: Executing Raw Binary Copy for .toe only:")
    print(f"   Source: {source_toe}")
    print(f"   Target: {target_toe}")
    
    # 3. RAW BINARY COPY
    try:
        if os.path.exists(source_toe):
            with open(source_toe, 'rb') as src, open(target_toe, 'wb') as dst:
                dst.write(src.read())
            print(f"✅ Success: Project .toe forced via binary write to {target_toe}")
        else:
            print(f"❌ Error: Could not find the local source file at {source_toe}")
    except Exception as e:
        print(f"❌ Failed to copy .toe file. Reason: {e}")

export_toe_only()