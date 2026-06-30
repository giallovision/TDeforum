# par - the Par object that has changed
# prev - the previous value

def onValueChange(par, prev):
	if not parent().panel.select :
		parent().panel.state = par.eval()
	return