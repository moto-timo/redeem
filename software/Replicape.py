#!/usr/bin/python
'''
Replicape main program. This should run on the BeagleBone.

Author: Elias Bakken
email: elias.bakken@gmail.com
Website: http://www.hipstercircuits.com
License: BSD

You can use and change this, but keep this heading :)
'''

import bbio as io
from math import sqrt

from Mosfet import Mosfet
from Smd import SMD
from Thermistor import Thermistor
from Fan import Fan
from USB import USB
from Gcode import Gcode
import sys
from Extruder import Extruder, HBP
from Options import Options
from Pru import Pru
from Path import Path
from Path_planner import Path_planner
    
class Replicape:
    ''' Init '''
    def __init__(self):
        # Init the IO library 
        io.bbio_init()

        # Make a list of steppers
        self.steppers = {}

        # Init the 5 Stepper motors
        self.steppers["X"]  = SMD(io.GPIO1_12, io.GPIO1_13, io.GPIO1_7,  7, "X")  # Fault_x should be PWM2A?
        self.steppers["Y"]  = SMD(io.GPIO1_31, io.GPIO1_30, io.GPIO1_15, 1, "Y")  
        self.steppers["Z"]  = SMD(io.GPIO1_1,  io.GPIO2_2,  io.GPIO0_27, 2, "Z")  
        self.steppers["E"]  = SMD(io.GPIO3_21, io.GPIO3_19, io.GPIO2_3,  4, "Ext1")

        # Enable the steppers and set current,  
        self.steppers["X"].setCurrentValue(2.0) # 2A
        self.steppers["X"].setEnabled() 
        self.steppers["X"].set_steps_pr_mm(6.105)         
        self.steppers["X"].set_microstepping(2) 
        self.steppers["X"].set_pru(0)

        self.steppers["Y"].setCurrentValue(2.0) # 2A
        self.steppers["Y"].setEnabled() 
        self.steppers["Y"].set_steps_pr_mm(5.95)
        self.steppers["Y"].set_microstepping(2) 
        self.steppers["Y"].set_pru(1)

        self.steppers["Z"].setCurrentValue(1.0) # 2A
        self.steppers["Z"].setEnabled() 
        self.steppers["Z"].set_steps_pr_mm(149.25)
        self.steppers["Z"].set_microstepping(0) 

        self.steppers["E"].setCurrentValue(1.0) # 2A        
        self.steppers["E"].setEnabled()
        self.steppers["E"].set_steps_pr_mm(5.0)
        self.steppers["E"].set_microstepping(2)
        self.steppers["E"].set_pru(0)

        # init the 3 thermistors
        self.therm_ext1 = Thermistor(io.AIN4, "Ext_1", chart_name="QU-BD")
        self.therm_hbp  = Thermistor(io.AIN6, "HBP", chart_name="B57560G104F")

        # init the 3 heaters
        self.mosfet_ext1 = Mosfet(io.PWM1A) # PWM2B on rev1
        self.mosfet_hbp  = Mosfet(io.PWM1B) # PWM1B on rev1 
        # Make extruder 1
        self.ext1 = Extruder(self.steppers["E"], self.therm_ext1, self.mosfet_ext1)
        self.ext1.setPvalue(0.5)
        self.ext1.setDvalue(0.1)     
        self.ext1.setIvalue(0.001)
     
        self.hbp = HBP( self.therm_hbp, self.mosfet_hbp)        # Make Heated Build platform 
        #self.hbp.debugLevel(1)

        # Init the three fans
        self.fan_1 = Fan(1)
        self.fan_2 = Fan(2)
        self.fan_3 = Fan(3)

        # Make a queue of commands
        self.queue = list()

        # Set up USB, this receives messages and pushes them on the queue
        self.usb = USB(self.queue)		

        # Get all options 
        self.options = Options()

        # Make the positioning vector
        self.position = {"x": 0, "y": 0, "z": 0}
        
        self.movement = "RELATIVE"
        self.feed_rate = 3000.0

        # Init the path planner
        self.path_planner = Path_planner(self.steppers)         
        self.path_planner.set_acceleration(300.0/1000.0) 
	
    ''' When a new gcode comes in, excute it '''
    def loop(self):
        try:
            while True:
                if len(self.queue) > 0:
                    gcode = Gcode(self.queue.pop(0), self)
                    self._execute(gcode)
                    self.usb.send_message(gcode.getAnswer())
                else:
                    io.delay(10)
        except KeyboardInterrupt:
            print "Caught signal, exiting" 
            return
        finally:
            self.cleanUp()  
		
    ''' Execute a G-code '''
    def _execute(self, g):
        if g.code() == "G1":                                        # Move (G1 X0.1 Y40.2 F3000)                        
            if g.hasLetter("F"):                                    # Get the feed rate                 
                feed_rate = float(g.getValueByLetter("F"))
                g.removeTokenByLetter("F")
            else:                                                   # If no feed rate is set in the command, use the default. 
                feed_rate = self.feed_rate                         
            smds = {}                                               # All steppers 
            for i in range(g.numTokens()):                          # Run through all tokens
                axis = g.tokenLetter(i)                             # Get the axis, X, Y, Z or E
                smds[axis] = float(g.tokenValue(i))                 # Get tha value, new position or vector             
            path = Path(smds, feed_rate, self.movement)             # Make a path segment from the axes
            while self.path_planner.nr_of_paths() > 4:              # If the queue is full, wait. 
                io.delay(100)                                       # This is the waiting part
            self.path_planner.add_path(path)                        # Ok, add the path to the planner queue
        elif g.code() == "G21":                                     # Set units to mm
            self.factor = 1.0
        elif g.code() == "G28":                                     # Home the steppers
            if g.numTokens() == 0:                                  # If no token is given, home all
                g.setTokens(["X", "Y", "Z"])
            for i in range(g.numTokens()):                          # Run through all tokens
                axis = g.tokenLetter(i)                             # Get the axis, X, Y, Z or E
                val = -self.path_planner.get_pos(axis)*1000.0
                self.steppers[axis].move(val, self.movement)        # Get tha value, new position or vector             
            self.path_planner.reset_pos()
        elif g.code() == "G90":                                     # Absolute positioning
            self.movement = "ABSOLUTE"
        elif g.code() == "G91":                                     # Relative positioning 
            self.movement = "RELATIVE"		
        elif g.code() == "G92":                                     # Set the current position of the following steppers
            if g.numTokens() == 0:
                 g.setTokens(["X0", "Y0", "Z0", "E0"])              # If no token is present, do this for all
            for i in range(g.numTokens()):
                axis = g.tokenLetter(i)
                val = float(g.tokenValue(i))
                self.path_planner.set_pos(axis, val)
        elif g.code() == "M17":                                     # Enable all steppers
            self.enableAllSteppers()
        elif g.code() == "M30":                                     # Set microstepping (Propietary to Replicape)
            for i in range(g.numTokens()):
                self.steppers[g.tokenLetter(i)].set_microstepping(int(g.tokenValue(i)))            
        elif g.code() == "M84":                                     # Disable all steppers
            self.disableAllSteppers()
        elif g.code() == "M104":                                    # Set extruder temperature
            self.ext1.setTargetTemperature(float(g.tokenValue(0)))
        elif g.code() == "M105":                                    # Get Temperature
            answer = "ok T:"+str(self.ext1.getTemperature())
            answer += " B:"+str(int(self.hbp.getTemperature()))
            g.setAnswer(answer)
        elif g.code() == "M106":                                    # Fan on
            self.fan_1.setPWMFrequency(100)
            self.fan_1.setValue(float(g.tokenValue(0)))	
        elif g.code() == "M110":                                    # Reset the line number counter 
            Gcode.line_number = 0       
        elif g.code() == "M130":                                    # Set PID P-value, Format (M130 P0 S8.0)
            pass
            #if int(self.tokens[0][1]) == 0:
            #    self.ext1.setPvalue(float(self.tokens[1][1::]))
        elif g.code() == "M131":                                    # Set PID I-value, Format (M131 P0 S8.0) 
            pass
            #if int(self.tokens[0][1]) == 0:
            #    self.p.ext1.setPvalue(float(self.tokens[1][1::]))
        elif g.code() == "M132":                                    # Set PID D-value, Format (M132 P0 S8.0)
            pass
            #if int(self.tokens[0][1]) == 0:
            #    self.p.ext1.setPvalue(float(self.tokens[1][1::]))
        elif g.code() == "M140":                                    # Set bed temperature
            self.hbp.setTargetTemperature(float(g.tokenValue(0)))
        else:
            print "Unknown command: "+g.message	

    ''' Stop all threads '''
    def cleanUp(self):
        self.ext1.disable()
        self.hbp.disable()
        self.usb.close() 
        self.path_planner.exit()

    ''' Move the stepper motors '''
    def moveTo(self, stepper, pos):
        print "Moving "+stepper+" to "+str(pos)
        self.steppers[stepper].moveTo(pos)

    ''' Move the stepper motors '''
    def move(self, stepper, amount, feed_rate):
        print "Moving "+stepper+" "+str(amount)+"mm @ F:"+str(feed_rate)
        self.steppers[stepper].setFeedRate(feed_rate)
        self.steppers[stepper].move(amount)

    ''' Set the current position of each of the steppers is '''
    def setCurrentPosition(self, stepper, pos):
        self.steppers[stepper].setCurrentPosition(pos)

    ''' Disable all steppers '''
    def disableAllSteppers(self):
        for name, stepper in self.steppers.iteritems():
            stepper.setDisabled()

    ''' Enable all steppers '''
    def enableAllSteppers(self):		
        for name, stepper in self.steppers.iteritems():
            stepper.setEnabled()
		
    ''' Given an X and Y vector and a feed_rate, 
    calculate the feed_rates of the two vectors.''' 
    def decompose_vector(self, x, y, e, feed_rate_hyp):
        hyp = sqrt(x**2+y**2)
        feed_rate_ratio = feed_rate_hyp/hyp        
        feed_rate_y = feed_rate_ratio*abs(y)
        feed_rate_x = feed_rate_ratio*abs(x)
        feed_rate_e = feed_rate_ratio*abs(e)
        
        return (feed_rate_x, feed_rate_y, feed_rate_e)
          

r = Replicape()
r.loop()
