import json
import os
import cv2

def dump_debug_payload():
    ui_node = op('Deforum_UI')
    map_table = op('deforum_api_map')
    prompt_dat = op('deforum_prompts')
    model_list_dat = op('available_models') or me.parent().op('available_models') or op('/project1/available_models')
    
    if not ui_node or not map_table or not prompt_dat:
        print("❌ Essential framework nodes missing.")
        return

    # 1. Prompts
    prompt_disk_path = r'T:\scripts\prompt.txt'
    try:
        with open(prompt_disk_path, 'r', encoding='utf-8') as f:
            timeline_prompts = json.load(f)
    except:
        try: timeline_prompts = json.loads(prompt_dat.text)
        except: timeline_prompts = {"0": "Debug fallback prompt"}

    payload = {
        "deforum_settings": {"prompts": timeline_prompts, "override_settings": {}},
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
    
    # 2. Main Parameter Loop
    for param in ui_node.customPars:
        if param.name in ['Promptstart', 'Promptmorph'] or param.name.startswith('Cn1') or param.name == 'Videoframemode':
            continue
            
        cell_match = map_table.findCell(param.name, cols=[0])
        if cell_match:
            api_name = map_table[cell_match.row, 1].val
            param_value = str(param.eval()).strip()
            
            if param_value == "": continue

            if api_name == "border":
                payload["deforum_settings"]["border"] = param_value
                if param_value == "zeros": payload["deforum_settings"]["padding_mode"] = "zeros"
                elif param_value == "wrap": payload["deforum_settings"]["padding_mode"] = "reflection"
                else: payload["deforum_settings"]["padding_mode"] = "border"
                continue

            if api_name == "sd_model_checkpoint":
                payload["deforum_settings"]["enable_checkpoint_scheduling"] = True
                val = param_value
                if ":" not in param_value and param_value.isdigit() and model_list_dat:
                    match_cell = model_list_dat.findCell(val, cols=[0])
                    val = model_list_dat[match_cell.row, 1].val if match_cell else "angraRealflexLCMV6_v10.safetensors"
                payload["deforum_settings"]["checkpoint_schedule"] = f'0: "{val}"' if ":" not in val else val
                continue

            if api_name.startswith("sd_"):
                payload["override_settings"][api_name] = param_value
                payload["deforum_settings"][api_name] = param_value
                payload["deforum_settings"]["override_settings"][api_name] = param_value
                continue

            if api_name in schedule_keys:
                payload["deforum_settings"][api_name] = param_value if ":" in param_value else f"0:({param_value})"
            else:
                if param_value.lower() == 'true': payload["deforum_settings"][api_name] = True
                elif param_value.lower() == 'false': payload["deforum_settings"][api_name] = False
                else:
                    try: payload["deforum_settings"][api_name] = float(param_value) if '.' in param_value else int(param_value)
                    except ValueError: payload["deforum_settings"][api_name] = param_value
                
    # 3. ControlNet Unit 1
    def get_cn_val(par_name, default):
        par = getattr(ui_node.par, par_name, None)
        return par.eval() if par else default

    payload["deforum_settings"].update({
        "cn_1_enabled": bool(get_cn_val('Cn1enabled', False)),
        "cn_1_module": str(get_cn_val('Cn1module', "none")).strip(),
        "cn_1_model": str(get_cn_val('Cn1model', "none")).strip(),
        "cn_1_processor_res": int(get_cn_val('Cn1processorres', 512)),
        "cn_1_threshold_a": float(get_cn_val('Cn1thresholda', 0.5)),
        "cn_1_threshold_b": float(get_cn_val('Cn1thresholdb', 0.5)),
        "cn_1_vid_path": str(get_cn_val('Cn1vidpath', "")).strip(),
        "cn_1_mask_vid_path": str(get_cn_val('Cn1maskvidpath', "")).strip(),
        "cn_1_guidance_start": "0:(0.0)",
        "cn_1_guidance_end": "0:(1.0)",
        "cn_1_low_vram": False,
        "cn_1_pixel_perfect": True,
        "cn_1_overwrite_frames": True,
        "cn_1_resize_mode": "Inner Fit (Scale to Fit)",
        "cn_1_control_mode": "Balanced",
        "cn_1_loopback_mode": False,
        "overlay_mask": False
    })
    
    cn1_w = str(get_cn_val('Cn1weight', "1.0")).strip()
    payload["deforum_settings"]["cn_1_weight"] = cn1_w if ":" in cn1_w else f"0:({cn1_w})"

    # 4. Path Enforcement & Failsafes
    payload["deforum_settings"]["store_frames_in_ram"] = True 
    payload["deforum_settings"]["skip_video_creation"] = False  
    payload["deforum_settings"]["image_format"] = "png"         
    
    ui_mask_enabled = payload["deforum_settings"].get("use_mask_video", False)
    payload["deforum_settings"]["use_mask"] = ui_mask_enabled

    if ui_mask_enabled:
        payload["deforum_settings"]["video_mask_path"] = str(ui_node.par.Videomaskpath.eval()).strip()
        
    payload["deforum_settings"]["video_init_path"] = str(ui_node.par.Videoinitpath.eval()).strip()

    for i in range(2, 6):
        payload["deforum_settings"].update({
            f"cn_{i}_enabled": False, f"cn_{i}_module": "none", f"cn_{i}_model": "none",
            f"cn_{i}_weight": "0:(1.0)", f"cn_{i}_guidance_start": "0:(0.0)", f"cn_{i}_guidance_end": "0:(1.0)",
            f"cn_{i}_processor_res": 512, f"cn_{i}_threshold_a": 0.5, f"cn_{i}_threshold_b": 0.5,
            f"cn_{i}_low_vram": False, f"cn_{i}_pixel_perfect": True,
            f"cn_{i}_resize_mode": "Inner Fit (Scale to Fit)", f"cn_{i}_control_mode": "Balanced"
        })
        
    # 5. Write to Disk
    debug_path = r'T:\scripts\current_deforum_payload.json'
    try:
        with open(debug_path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=4)
        print(f"✅ DEBUG DUMP SUCCESSFUL: Saved perfectly formatted JSON to {debug_path}")
    except Exception as e:
        print(f"❌ DEBUG DUMP FAILED: {e}")

dump_debug_payload()