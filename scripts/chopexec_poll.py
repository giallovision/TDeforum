def whileOn(channel, sampleIndex, val, prev):
    if channel.name == 'cycles_pulse' and channel == 1:
        op('webclient_progress').par.request.pulse()