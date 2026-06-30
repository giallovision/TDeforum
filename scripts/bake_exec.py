def onOffToOn(channel, sampleIndex, val, prev):
    wave_node = op('wave_generator')
    dat_out = op('bake_out')
    quant_node = op('quantize_settings')
    
    if not wave_node or not dat_out:
        print("❌ Essential baking nodes missing from network layer.")
        return
        
    total_samples = wave_node.numSamples
    keyframes = []
    
    # 1. 🎛️ Read the quantization parameter
    points = 0
    if quant_node and quant_node.numChans > 0:
        points = int(quant_node[0][0])
        
    # 2. 🧠 Calculate Equidistant Sample Indices
    # If points is 0 or greater than total frames, fallback to baking every frame
    if points <= 0 or points >= total_samples:
        target_indices = list(range(total_samples))
    elif points == 1:
        target_indices = [0]
    else:
        # Distributes the requested points perfectly from frame 0 to the final frame
        target_indices = [int(round(i * (total_samples - 1) / (points - 1))) for i in range(points)]
        
    # 3. ⚡ Pull values only at the targeted indices
    for i in target_indices:
        v = wave_node[0][i]
        keyframes.append(f"{i}:({v:.4f})")
        
    # Flatten the array and dump the string into your text bin
    dat_out.text = ", ".join(keyframes)
    print(f"⚡ Serum Wavetable Success: Quantized and baked {len(target_indices)} explicit frame keys to '{dat_out.name}'")