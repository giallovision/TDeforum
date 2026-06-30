import os
import json

def execute_preprocessor_payload():
    ui_node = op('Deforum_UI')
    web_client = op('webclient_comfyui')
    
    # 1. READ UI PARAMETERS
    raw_input_path = ui_node.par.Videoinitpath.eval()
    preprocessor = ui_node.par.Comfypreprocessor.eval()
    
    # Pulling generation metadata directly from the UI (No OpenCV needed)
    width = int(ui_node.par.Width.eval())
    height = int(ui_node.par.Height.eval())
    frames = int(ui_node.par.Maxframes.eval())
    
    base_name = os.path.splitext(os.path.basename(raw_input_path))[0]
    
    # 2. PATH TRANSLATION (Deforum Container -> ComfyUI Container)
    # Incoming: /opt/a1111/td_inputs/comfy_videos/archive/taichi_portrait.mp4
    # The VHS node inside ComfyUI expects paths relative to its input folder, or absolute.
    # We will give it the exact path relative to the input folder: "input/archive/..."
    comfy_input_path = str(raw_input_path).replace('/opt/a1111/td_inputs/comfy_videos/', 'input/')
    
    # 3. CONSTRUCT TARGET FILENAME & CHECK COLLISIONS
    ideal_name = f"{base_name}_{width}x{height}_{preprocessor}_{frames}f"
    
    # We check the masks folder on the Windows side just to prevent duplicate renders
    windows_mask_check = f"T:/td_masks/preprocessed_vids/{ideal_name}.mp4"
    
    if os.path.exists(windows_mask_check):
        print(f"✅ Found existing file: {ideal_name}.mp4")
        print("⏭️ Skipping ComfyUI. Routing directly to Deforum...")
        ui_node.par.Cn1vidpath = f"/opt/a1111/td_masks/preprocessed_vids/{ideal_name}.mp4"
        return

    print(f"🚀 Preprocessing {base_name} with {preprocessor} at {width}x{height} for {frames} frames...")
    print(f"🕵️ Injecting ComfyUI Path: {comfy_input_path}")

    # 4. LOAD & MODIFY THE JSON TEMPLATE
    template_path = r'T:\scripts\TD_CN_PreProc.json'
    try:
        with open(template_path, 'r', encoding='utf-8') as f:
            payload = json.load(f)
    except Exception as e:
        print(f"❌ Could not load JSON template: {e}")
        return

    # Node 10: Input Video (VHS Node)
    payload["10"]["inputs"]["video"] = comfy_input_path
    payload["10"]["inputs"]["frame_load_cap"] = frames
    
    # Node 11: Scaling
    payload["11"]["inputs"]["width"] = width
    payload["11"]["inputs"]["height"] = height
    
    # Node 19: Preprocessor Selection
    payload["19"]["inputs"]["preprocessor"] = preprocessor
    payload["19"]["inputs"]["resolution"] = min(width, height)
    
    # Node 21: Output Configuration
    exact_prefix = f"preprocessed_vids/{ideal_name}"
    payload["21"]["inputs"]["filename_prefix"] = exact_prefix
    
    # Note: VHS Node will default to its internal framerate logic since we aren't passing cv2 FPS
    
    # 5. DISPATCH TO COMFYUI API
    final_payload = json.dumps({"prompt": payload})
    headers = {'Content-Type': 'application/json'}
    
    web_client.request(web_client.par.url.eval(), 'POST', header=headers, data=final_payload)
    print("📡 Payload dispatched to ComfyUI port 8188.")

# Execute immediately on run
execute_preprocessor_payload()