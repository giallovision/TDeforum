# Shared callbacks DAT for webclient_deforum, webclient_progress and webclient_comfyui
# (setup_network.py points all three Web Client DATs here).
# Responses are routed by the Web Client DAT's name in td_controller.on_response.


def _ctl():
    import os
    import sys
    path = me.par.file.eval()
    scripts = os.path.dirname(path) if path else 'T:/scripts'
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from tdeforum import td_controller
    return td_controller


# *args keeps these compatible with TD builds that do / don't pass a request id.
def onConnect(webClientDAT, *args):
    return


def onDisconnect(webClientDAT, *args):
    return


def onResponse(webClientDAT, statusCode, headerDict, data, *args):
    _ctl().on_response(webClientDAT.parent(), webClientDAT, statusCode, data)
    return


def onError(webClientDAT, *args):
    _ctl().on_error(webClientDAT.parent(), webClientDAT,
                    ', '.join(str(a) for a in args) or 'TouchDesigner gave no details')
    return
