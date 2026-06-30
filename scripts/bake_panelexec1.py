# panelValue - the PanelValue object that changed
# Make sure the corresponding toggle is enabled in the Panel Execute DAT.

def onValueChange(panelValue):
	parent().par.value0 = panelValue
	return