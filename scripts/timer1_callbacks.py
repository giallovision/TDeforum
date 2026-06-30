"""
Timer CHOP Callbacks

me - this DAT

timerOp - the connected Timer CHOP
cycle - the cycle index
interrupt - True if the user initiated a premature, False if a result of a 
	normal timeout
fraction - the time in 0-1 fractional form

segment - an object describing the segment:
	can be automatically cast to its index: e.g.:  segment+3, segment==2, etc
	
	members of segment object:
		index     numeric order of the segment, from 0
		owner    Timer CHOP it belongs to
		
		lengthSeconds, lengthSamples, lengthFrames
		delaySeconds, delaySamples, delayFrames
		beginSeconds, beginSamples, beginFrames
		speed
"""
#      cycle, cycleLimit, maxCycles
#      cycleEndAlertSeconds, cycleEndAlertSamples, cycleEndAlertFrames
#
#      row - one validly named member per column:
#            column headings used to override parameters:
#                length, delay, speed, cyclelimit, maxcycles, 
#                cycleendalert
#            special column headings:
#                begin (time at which to start, independent of 
#                delays/lengths, overrides delay)
#
#    custom - dictionary of all columns that don't map to a built-in feature
#

# onInitialize(): if return value > 0, it will be
# called again after the returned number of frames.
# callCount increments with each attempt, starting at 1

def onInitialize(timerOp: timerCHOP, callCount: int) -> int:
	"""
	Called when the Timer CHOP is initialized.
	
	Args:
		timerOp: The connected Timer CHOP
		callCount: Increments with each attempt, starting at 1
		
	Returns:
		int: If > 0, will be called again after the returned number of frames
	"""
	return 0

def onReady(timerOp: timerCHOP):
	"""
	Called when the Timer CHOP is ready.
	
	Args:
		timerOp: The connected Timer CHOP
	"""
	return
	
def onStart(timerOp: timerCHOP):
	"""
	Called when the Timer CHOP starts.
	
	Args:
		timerOp: The connected Timer CHOP
	"""
	return
	
def onTimerPulse(timerOp: timerCHOP, segment: Segment):
	"""
	Called when the timer pulses.
	
	Args:
		timerOp: The connected Timer CHOP
		segment: The segment object describing the current segment
	"""
	return

def whileTimerActive(timerOp: timerCHOP, segment: Segment, cycle: int, 
                     fraction: float):
	"""
	Called while the timer is active.
	
	Args:
		timerOp: The connected Timer CHOP
		segment: The segment object describing the current segment
		cycle: The cycle index
		fraction: The time in 0-1 fractional form
	"""
	return

def onSegmentEnter(timerOp: timerCHOP, segment: Segment, 
                   interrupt: bool):
	"""
	Called when entering a segment.
	
	Args:
		timerOp: The connected Timer CHOP
		segment: The segment object being entered
		interrupt: True if user initiated, False if normal timeout
	"""
	return
	
def onSegmentExit(timerOp: timerCHOP, segment: Segment, 
                  interrupt: bool):
	"""
	Called when exiting a segment.
	
	Args:
		timerOp: The connected Timer CHOP
		segment: The segment object being exited
		interrupt: True if user initiated, False if normal timeout
	"""
	return

def onCycleStart(timerOp: timerCHOP, segment: Segment, cycle: int):
	"""
	Called when a cycle starts.
	
	Args:
		timerOp: The connected Timer CHOP
		segment: The segment object
		cycle: The cycle index
	"""
	return

def onCycleEndAlert(timerOp: timerCHOP, segment: Segment, cycle: int, 
                    alertSegment: Segment, alertDone: bool, 
                    interrupt: bool):
	"""
	Called when a cycle end alert occurs.
	
	Args:
		timerOp: The connected Timer CHOP
		segment: The segment object
		cycle: The cycle index
		alertSegment: The alert segment
		alertDone: True if alert is done
		interrupt: True if user initiated, False if normal timeout
	"""
	return
	
def onCycle(timerOp: timerCHOP, segment: Segment, cycle: int):
	"""
	Called when a cycle completes.
	
	Args:
		timerOp: The connected Timer CHOP
		segment: The segment object
		cycle: The cycle index
	"""
	return

def onDone(timerOp: timerCHOP, segment: Segment, interrupt: bool):
	"""
	Called when the timer is done.
	
	Args:
		timerOp: The connected Timer CHOP
		segment: The segment object
		interrupt: True if user initiated, False if normal timeout
	"""
	return

def onSubrangeStart(timerOp: timerCHOP):
	return
