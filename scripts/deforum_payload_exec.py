import json
import os
import cv2

def execute_payload():
    web_client = op('webclient_deforum')
    ui_node = op('Deforum_UI')
    map_table = op('deforum_api_map')
    prompt_dat = op('deforum_prompts')
    disk_monitor = op('folder_monitor')
    
    model_list_dat = op('available_models') or me.parent.op('available_models') or op('/project1/available_models')
    
    if not ui_node or not map_table or not prompt_dat:
        print("❌ Essential framework nodes missing from the current layout.")
        return

    prompt_disk_path = r'T:\scripts\prompt.json'
    try:
        with open(prompt_disk_path, 'r', encoding='utf-8') as f:
            timeline_prompts = json.load(f)
    except Exception as e:
        print(f"⚠️ Direct disk read un-synchronized, parsing node text: {e}")
        try:
            timeline_prompts = json.loads(prompt_dat.text)
        except Exception as e2:
            print(f"❌ Structural error processing prompt JSON layout file: {e2}")
            timeline_prompts = {"0": "A cinematic macro shot of liquid gold morphing, biomorphic shapes"}

    payload = {
        "deforum_settings": {
            "prompts": timeline_prompts,
            "override_settings": {}
        },
        "override_settings": {},
        "override_settings_restore_afterwards": False
    }
    
    schedule_keys = [
        'zoom', 'angle', 'translation_x', 'translation_y', 'translation_z',
        'rotation_3d_x', 'rotation_3d_y', 'rotation_3d_z',
        'transform_center_x', 'transform_center_y',
        'perspective_flip_theta', 'perspective_flip_phi', 'perspective_flip_gamma', 'perspective_flip_fv',
        'cfg_scale_schedule', 'strength_schedule', 'noise_schedule',
        'contrast_schedule', 'fov_schedule', 'steps_schedule'
    ]
    
    for param in ui_node.customPars:
        if param.name in ['Promptstart', 'Promptmorph'] or param.name.startswith('Cn1') or param.name == 'Videoframemode':
            continue
            
        cell_match = map_table.findCell(param.name, cols=[0])
        if cell_match:
            api_name = map_table[cell_match.row, 1].val
            raw_val = param.eval()
            param_value = str(raw_val).strip()
            
            if param_value == "":
                continue

            # 💡 THE 3D vs 2D EDGE FIX
            if api_name == "border":
                payload["deforum_settings"]["border"] = param_value
                if param_value == "zeros":
                    payload["deforum_settings"]["padding_mode"] = "zeros"
                elif param_value == "wrap":
                    payload["deforum_settings"]["padding_mode"] = "reflection"
                else:
                    payload["deforum_settings"]["padding_mode"] = "border"
                continue

            # 💡 THE NATIVE STRING MODEL SCHEDULE PARSER (Titanium Edition)
            if api_name == "sd_model_checkpoint":
                payload["deforum_settings"]["enable_checkpoint_scheduling"] = True
                default_model = "angraRealflexLCMV6_v10.safetensors"
                
                if not model_list_dat:
                    print("⚠️ Warning: 'available_models' table missing or disconnected!")
                
                if ":" in param_value:
                    clean_str = param_value.replace('{', '').replace('}', '').strip()
                    sched_elements = []
                    
                    for pair in clean_str.split(','):
                        if ':' in pair:
                            frame_part, val_part = pair.split(':', 1)
                            frame = frame_part.strip().strip('"').strip("'")
                            val = val_part.strip().strip('"').strip("'")
                            
                            if val.isdigit():
                                if model_list_dat:
                                    match_cell = model_list_dat.findCell(val, cols=[0])
                                    if match_cell: 
                                        val = model_list_dat[match_cell.row, 1].val
                                    else: 
                                        val = default_model
                                else: 
                                    val = default_model
                            
                            sched_elements.append(f'{frame}: "{val}"')
                    
                    payload["deforum_settings"]["checkpoint_schedule"] = ", ".join(sched_elements)
                
                else:
                    val = param_value
                    if val.isdigit():
                        if model_list_dat:
                            match_cell = model_list_dat.findCell(val, cols=[0])
                            if match_cell: 
                                val = model_list_dat[match_cell.row, 1].val
                            else: 
                                val = default_model
                        else: 
                            val = default_model
                    
                    payload["deforum_settings"]["checkpoint_schedule"] = f'0: "{val}"'
                
                print(f"🎬 Compiled Checkpoint Schedule sent to API: {payload['deforum_settings']['checkpoint_schedule']}")
                
                payload["override_settings"][api_name] = param_value
                payload["deforum_settings"][api_name] = param_value
                continue

            if api_name.startswith("sd_"):
                payload["override_settings"][api_name] = param_value
                payload["deforum_settings"][api_name] = param_value
                payload["deforum_settings"]["override_settings"][api_name] = param_value
                continue

            if api_name in schedule_keys:
                if ":" in param_value: payload["deforum_settings"][api_name] = param_value
                else: payload["deforum_settings"][api_name] = f"0:({param_value})"
            else:
                if param_value.lower() == 'true': payload["deforum_settings"][api_name] = True
                elif param_value.lower() == 'false': payload["deforum_settings"][api_name] = False
                else:
                    try:
                        if '.' in param_value: payload["deforum_settings"][api_name] = float(param_value)
                        else: payload["deforum_settings"][api_name] = int(param_value)
                    except ValueError:
                        payload["deforum_settings"][api_name] = param_value
                
    # 3. CONTROLNET UNIT 1
    cn1_enabled = getattr(ui_node.par, 'Cn1enabled', None)
    payload["deforum_settings"]["cn_1_enabled"] = bool(cn1_enabled.eval()) if cn1_enabled else False
    
    cn1_module = getattr(ui_node.par, 'Cn1module', None)
    payload["deforum_settings"]["cn_1_module"] = str(cn1_module.eval()).strip() if cn1_module else "none"
    
    cn1_model = getattr(ui_node.par, 'Cn1model', None)
    payload["deforum_settings"]["cn_1_model"] = str(cn1_model.eval()).strip() if cn1_model else "none"
    
    cn1_weight = getattr(ui_node.par, 'Cn1weight', None)
    cn1_weight_str = str(cn1_weight.eval()).strip() if cn1_weight else "1.0"
    payload["deforum_settings"]["cn_1_weight"] = cn1_weight_str if ":" in cn1_weight_str else f"0:({cn1_weight_str})"

    cn1_res = getattr(ui_node.par, 'Cn1processorres', None)
    payload["deforum_settings"]["cn_1_processor_res"] = int(cn1_res.eval()) if cn1_res else 512
    
    cn1_a = getattr(ui_node.par, 'Cn1thresholda', None)
    payload["deforum_settings"]["cn_1_threshold_a"] = float(cn1_a.eval()) if cn1_a else 0.5
    
    cn1_b = getattr(ui_node.par, 'Cn1thresholdb', None)
    payload["deforum_settings"]["cn_1_threshold_b"] = float(cn1_b.eval()) if cn1_b else 0.5

    cn1_vid = getattr(ui_node.par, 'Cn1vidpath', None)
    payload["deforum_settings"]["cn_1_vid_path"] = str(cn1_vid.eval()).strip() if cn1_vid else ""
    
    cn1_mask_vid = getattr(ui_node.par, 'Cn1maskvidpath', None)
    payload["deforum_settings"]["cn_1_mask_vid_path"] = str(cn1_mask_vid.eval()).strip() if cn1_mask_vid else ""

    payload["deforum_settings"]["cn_1_guidance_start"] = "0:(0.0)"
    payload["deforum_settings"]["cn_1_guidance_end"] = "0:(1.0)"
    payload["deforum_settings"]["cn_1_low_vram"] = False
    payload["deforum_settings"]["cn_1_pixel_perfect"] = True
    payload["deforum_settings"]["cn_1_overwrite_frames"] = True
    payload["deforum_settings"]["cn_1_resize_mode"] = "Inner Fit (Scale to Fit)"
    payload["deforum_settings"]["cn_1_control_mode"] = "Balanced"
    payload["deforum_settings"]["cn_1_loopback_mode"] = False
    payload["deforum_settings"]["overlay_mask"] = False

    # --- 🚀 UNIVERSAL TIMELINE & EXTRACTION CONTROLLER ---
    ui_max_frames = int(payload["deforum_settings"].get("max_frames", 240))
    current_mode = str(ui_node.par.Animationmode.eval())
    
    payload["deforum_settings"]["store_frames_in_ram"] = True 
    payload["deforum_settings"]["skip_video_creation"] = False  
    payload["deforum_settings"]["image_format"] = "png"         
    
    ui_mask_enabled = payload["deforum_settings"].get("use_mask_video", False)
    payload["deforum_settings"]["use_mask"] = ui_mask_enabled

    def get_true_frame_count(file_path):
        if not os.path.exists(file_path): return None
        video_capture = cv2.VideoCapture(file_path)
        total_frames = int(video_capture.get(cv2.CAP_PROP_FRAME_COUNT))
        video_capture.release()
        return total_frames if total_frames > 0 else None

    final_clip_cap = ui_max_frames

    # 💡 DIRECT ALIGNMENT FIX FOR THE GLOBALS MASK PATH
    if ui_mask_enabled:
        container_mask_path = str(ui_node.par.Videomaskpath.eval()).strip()
        
        # Inject the clean container path strictly into the Deforum out-box
        payload["deforum_settings"]["video_mask_path"] = container_mask_path
        
        # Build local Windows path for OpenCV validation
        win_mask_path = container_mask_path.replace('/opt/a1111/', 'T:/')
        mask_frames = get_true_frame_count(win_mask_path)
        if mask_frames:
            final_clip_cap = min(final_clip_cap, mask_frames)

    # 💡 DIRECT COMPONENT BOUNDARY ENFORCEMENT FOR THE MASTER INITIALIZATION PATH
    container_init_path = str(ui_node.par.Videoinitpath.eval()).strip()
    payload["deforum_settings"]["video_init_path"] = container_init_path

    if current_mode == 'Video Input':
        win_in_path = container_init_path.replace('/opt/a1111/', 'T:/')
        in_video_frames = get_true_frame_count(win_in_path)
        if in_video_frames:
            final_clip_cap = min(final_clip_cap, in_video_frames)
            
        frame_mode_par = getattr(ui_node.par, 'Videoframemode', None)
        frame_mode = str(frame_mode_par.eval()) if frame_mode_par else 'trim'
        
        if frame_mode == 'trim':
            payload["deforum_settings"]["max_frames"] = final_clip_cap
            payload["deforum_settings"]["extract_to_frame"] = final_clip_cap - 1
            payload["deforum_settings"]["extract_nth_frame"] = 1
        elif frame_mode == 'stride':
            asset_len = in_video_frames or ui_max_frames
            calculated_stride = max(1, asset_len // ui_max_frames)
            payload["deforum_settings"]["max_frames"] = ui_max_frames
            payload["deforum_settings"]["extract_to_frame"] = asset_len - 1
            payload["deforum_settings"]["extract_nth_frame"] = calculated_stride
            
        if ui_mask_enabled:
            payload["deforum_settings"]["max_mask_frames"] = final_clip_cap

    elif current_mode in ['2D', '3D']:
        payload["deforum_settings"]["max_frames"] = final_clip_cap - 1
        
        if ui_mask_enabled:
            payload["deforum_settings"]["max_mask_frames"] = final_clip_cap
            payload["deforum_settings"]["extract_to_frame"] = final_clip_cap - 1
            payload["deforum_settings"]["extract_nth_frame"] = 1

    # 4. BACKGROUND FAILSAFES: Units 2-5
    for i in range(2, 6):
        payload["deforum_settings"][f"cn_{i}_enabled"] = False
        payload["deforum_settings"][f"cn_{i}_module"] = "none"
        payload["deforum_settings"][f"cn_{i}_model"] = "none"
        payload["deforum_settings"][f"cn_{i}_weight"] = "0:(1.0)"
        payload["deforum_settings"][f"cn_{i}_guidance_start"] = "0:(0.0)"
        payload["deforum_settings"][f"cn_{i}_guidance_end"] = "0:(1.0)"
        payload["deforum_settings"][f"cn_{i}_processor_res"] = 512
        payload["deforum_settings"][f"cn_{i}_threshold_a"] = 0.5
        payload["deforum_settings"][f"cn_{i}_threshold_b"] = 0.5
        payload["deforum_settings"][f"cn_{i}_low_vram"] = False
        payload["deforum_settings"][f"cn_{i}_pixel_perfect"] = True
        payload["deforum_settings"][f"cn_{i}_resize_mode"] = "Inner Fit (Scale to Fit)"
        payload["deforum_settings"][f"cn_{i}_control_mode"] = "Balanced"
        
    json_payload = json.dumps(payload)
    
    # --- 🐛 DEBUG: SAVE PAYLOAD TO DISK ---
    debug_path = r'T:\scripts\current_deforum_payload.json'
    try:
        with open(debug_path, 'w', encoding='utf-8') as f:
            # We use indent=4 here so it is human-readable!
            json.dump(payload, f, indent=4)
        print(f"💾 Debug payload successfully saved to {debug_path}")
    except Exception as e:
        print(f"⚠️ Failed to write debug payload: {e}")
    # --------------------------------------

    headers = {'Content-Type': 'application/json'}
    web_client.request(web_client.par.url.eval(), 'POST', header=headers, data=json_payload)
    web_client.request(web_client.par.url.eval(), 'POST', header=headers, data=json_payload)
    print(f"⚡ Dispatched unconstrained UI-driven payload. Locked timeline to {final_clip_cap} frames.")
    
    if disk_monitor:
        disk_monitor.par.refresh.pulse()


def onOffToOn(channel, sampleIndex, val, prev):
    # Rip out the buggy sync toggles and just fire the payload instantly
    execute_payload()