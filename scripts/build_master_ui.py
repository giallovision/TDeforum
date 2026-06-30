import os
import json

def run_ui_construction():
    preprocessor_options = [
        'DWPreprocessor',
        'DepthAnythingV2Preprocessor',
        'SAMPreprocessor',
        'LineArtPreprocessor',
        'CannyEdgePreprocessor',
        'HEDPreprocessor',
        'PiDiNetPreprocessor',
        'M-LSDPreprocessor'
    ]

    # Hardcoded master configurations - no external directory dependencies
    field_blocks = [
        ('sd_model_checkpoint', 'angraRealflexLCMV6_v10.safetensors'),
        ('sd_vae', 'Automatic'),
        ('W', '1024'), ('H', '576'),
        ('steps', '10'), ('max_frames', '240'),
        ('sampler', 'LCM'), ('animation_mode', 'Video Input'),
        ('seed_behavior', 'fixed'), ('seed', '8675309'),
        ('n_prompt', 'worst quality, low quality, glitch, deformed, mutated, ugly, messy, text, watermark'),
        ('use_mask_video', 'True'),
        ('video_init_path', '/opt/a1111/td_inputs/comfy_videos/archive/taichi_portrait.mp4'),
        ('comfy_preproc_enable', 'False'),
        ('comfy_preprocessor', 'PiDiNetPreprocessor'),
        ('video_mask_path', '/opt/a1111/td_masks/mask_01.mov'),
        ('video_frame_mode', 'Trim (Normal Speed)'),
        ('cn_1_enabled', 'False'),
        ('cn_1_module', 'none'),
        ('cn_1_model', 'ctrl_v1p_qr_monster_v2'),
        ('cn_1_vid_path', '/opt/a1111/td_masks/mask_01.mov'),
        ('cn_1_mask_vid_path', ''),
        ('cn_1_weight', '1.0'),
        ('cn_1_guidance_start', '0.0'),
        ('cn_1_guidance_end', '1.0'),
        ('cn_1_processor_res', '512'),
        ('cn_1_threshold_a', '0.5'),
        ('cn_1_threshold_b', '0.5'),
        ('cn_1_resize_mode', 'Inner Fit (Scale to Fit)'),
        ('cn_1_low_vram', 'False'),
        ('cn_1_pixel_perfect', 'True'),
        ('cn_1_control_mode', 'Balanced'),
        ('scale', '1.0'),
        ('cfg_scale', '2.0'),
        ('strength', '0.8'),
        ('diffusion_cadence', '2'),
        ('optical_flow_cadence', 'RAFT'),
        ('border', 'replicate'),
        ('zoom', '0:(1.0)'), ('angle', '0:(0)'), 
        ('translation_x', '0:(0)'), ('translation_y', '0:(0)'), ('translation_z', '0:(0)'),
        ('rotation_3d_x', '0:(0)'), ('rotation_3d_y', '0:(0)'), ('rotation_3d_z', '0:(0)'),
        ('transform_center_x', '0:(0.5)'), ('transform_center_y', '0:(0.5)'),
        ('perspective_flip_theta', '0:(0)'), ('perspective_flip_phi', '0:(0)'),
        ('perspective_flip_gamma', '0:(0)'), ('perspective_flip_fv', '0:(50)'),
        ('noise_schedule', '0: (0.065)'), ('strength_schedule', '0: (0.8)'),
        ('contrast_schedule', '0: (1.0)'), ('cfg_scale_schedule', '0: (2.0)'),
        ('fov_schedule', '0: (70)'), ('near_schedule', '0: (200)'), ('far_schedule', '0: (10000)')
    ]

    root_net = me.parent()
    ui_node = root_net.op('Deforum_UI') or root_net.create(baseCOMP, 'Deforum_UI')
    
    map_table = root_net.op('deforum_api_map') or root_net.create(tableDAT, 'deforum_api_map')
    map_table.clear()
    map_table.appendRow(['td_name', 'api_name'])
    
    for page in list(ui_node.customPages):
        page.destroy()
        
    global_keys = ['sd_model_checkpoint', 'sd_vae', 'W', 'H', 'steps', 'max_frames', 'sampler', 'animation_mode', 'seed_behavior', 'seed', 'n_prompt', 'use_mask_video', 'video_init_path', 'comfy_preproc_enable', 'comfy_preprocessor', 'video_mask_path', 'video_frame_mode']
    motion_keys = ['border', 'zoom', 'angle', 'translation_x', 'translation_y', 'translation_z', 'rotation_3d_x', 'rotation_3d_y', 'rotation_3d_z', 'transform_center_x', 'transform_center_y']
    schedule_keys = ['cfg_scale_schedule', 'strength_schedule', 'noise_schedule', 'contrast_schedule', 'pix2pix_img_cfg_scale_schedule']
    perspective_keys = ['perspective_flip_theta', 'perspective_flip_phi', 'perspective_flip_gamma', 'perspective_flip_fv', 'fov_schedule', 'near_schedule', 'far_schedule']
    
    pages = {
        'Globals': ui_node.appendCustomPage('Globals'),
        'Motion': ui_node.appendCustomPage('Motion (2D/3D)'),
        'Schedules': ui_node.appendCustomPage('Schedules'),
        'Perspective': ui_node.appendCustomPage('Perspective 3D'),
        'ControlNet': ui_node.appendCustomPage('ControlNet Unit 1'),
        'Advanced': ui_node.appendCustomPage('Advanced Setup')
    }
    
    print("🔨 Forging clean layout control surface...")
    for raw_name, default in field_blocks:
        raw_name = raw_name.strip()
        default = default.strip()
        
        if raw_name == 'sd_model_checkpoint':
            default = '0'
        
        if raw_name in global_keys: current_page = pages['Globals']
        elif raw_name in motion_keys: current_page = pages['Motion']
        elif raw_name in schedule_keys: current_page = pages['Schedules']
        elif raw_name in perspective_keys: current_page = pages['Perspective']
        elif raw_name.startswith('cn_1_'): current_page = pages['ControlNet']
        else: current_page = pages['Advanced']
        
        if raw_name == 'W': td_name = 'Width'
        elif raw_name == 'H': td_name = 'Height'
        else:
            clean = "".join([x for x in raw_name if x.isalnum()])
            td_name = clean[0].upper() + clean[1:].lower() if clean else ""
        
        if td_name and td_name[-1].isdigit(): td_name += 'val'
        if not td_name: continue
            
        label = raw_name.replace('_', ' ').title()
        if raw_name == 'W': label = 'Width'
        if raw_name == 'H': label = 'Height'
        if label.startswith('Cn 1 '): label = label.replace('Cn 1 ', '')
        if raw_name == 'n_prompt': label = 'Negative Prompt'
        
        map_table.appendRow([td_name, raw_name])
        
        if raw_name == 'animation_mode':
            p = current_page.appendMenu(td_name, label=label)[0]
            p.menuNames = ['2D', '3D', 'Video Input', 'Interpolation']
            p.menuLabels = ['2D', '3D', 'Video Input', 'Interpolation']
            p.val = 'Video Input'
        elif raw_name == 'seed_behavior':
            p = current_page.appendMenu(td_name, label=label)[0]
            p.menuNames = ['iter', 'fixed', 'random', 'schedule']
            p.menuLabels = ['Iterate (+1)', 'Fixed', 'Random', 'Schedule']
            p.val = default
        elif raw_name == 'video_frame_mode':
            p = current_page.appendMenu(td_name, label=label)[0]
            p.menuNames = ['trim', 'stride']
            p.menuLabels = ['Trim (Normal Speed)', 'Stride (Timelapse)']
            p.val = 'trim'
        elif raw_name == 'border':
            p = current_page.appendMenu(td_name, label=label)[0]
            p.menuNames = ['replicate', 'wrap', 'zeros']
            p.menuLabels = ['Clamp / Hold (Replicate)', 'Wrap / Tile', 'Black (Zeros)']
            p.val = 'replicate'
        elif raw_name == 'comfy_preprocessor':
            p = current_page.appendMenu(td_name, label=label)[0]
            p.menuNames = preprocessor_options
            p.menuLabels = preprocessor_options
            p.val = default
        elif default.lower() in ['true', 'false']:
            p = current_page.appendToggle(td_name, label=label)[0]
            p.val = (default.lower() == 'true')
        elif raw_name in motion_keys or raw_name in schedule_keys or raw_name in perspective_keys:
            p = current_page.appendStr(td_name, label=label)[0]
            p.val = default
        elif 'prompt' in raw_name or 'path' in raw_name or 'model' in raw_name or 'module' in raw_name or raw_name.startswith('sd_'):
            p = current_page.appendStr(td_name, label=label)[0]
            p.val = default
        elif default.replace('.', '', 1).isdigit() or raw_name in ['W', 'H', 'steps', 'max_frames', 'cn_1_processor_res', 'seed']:
            if raw_name in ['W', 'H', 'steps', 'max_frames', 'cn_1_processor_res', 'seed'] or (default.isdigit() and '.' not in default):
                if raw_name == 'seed': 
                    p = current_page.appendStr(td_name, label=label)[0]
                    p.val = default
                else:
                    p = current_page.appendInt(td_name, label=label)[0]
                    try: p.val = int(default)
                    except: p.val = 0
                    if raw_name in ['W', 'H']: p.normMax = 1920
                    elif raw_name == 'max_frames': 
                        p.normMax = 1000
                        p.expr = 'me.time.end'
            else:
                p = current_page.appendFloat(td_name, label=label)[0]
                try: p.val = float(default)
                except: p.val = 0.0
                p.normMin = -10.0
                p.normMax = 10.0
        else:
            p = current_page.appendStr(td_name, label=label)[0]
            p.val = default

    # Track target path to curate custom curated prompt frameworks
    prompt_file_path = r'T:\scripts\prompt.json'
    if not os.path.exists(prompt_file_path):
        default_prompt = {"0": "Biomorphic liquid gold morphing", "120": "Bioluminescent neural network blooming"}
        with open(prompt_file_path, 'w', encoding='utf-8') as f:
            json.dump(default_prompt, f, indent=4)

    prompt_dat = root_net.op('deforum_prompts') or root_net.create(textDAT, 'deforum_prompts')
    prompt_dat.par.file = 'T:/scripts/prompt.json'
    prompt_dat.par.syncfile = 1

    map_table.dock = ui_node
    map_table.viewer = False
    map_table.expose = False
    
    prompt_dat.dock = ui_node
    prompt_dat.viewer = True
    prompt_dat.nodeX = ui_node.nodeX
    prompt_dat.nodeY = ui_node.nodeY - 180
    prompt_dat.expose = False

run_ui_construction()