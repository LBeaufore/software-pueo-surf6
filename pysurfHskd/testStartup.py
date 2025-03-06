#!/usr/bin/env python3
# super simple early implementation of pysurfhskd
# to test stuff.

import os
import struct
import selectors
import signal
import argparse
from pueoTimer import HskTimer
from signalhandler import SignalHandler
from pyHskHandler import HskHandler
from surfStartupHandlerPi import StartupHandlerPi
from HskProcessor import HskProcessor

from pysoceeprom import PySOCEEPROM
from pyzynqmp import PyZynqMP
from pueo.surf import PueoSURF
from pueo.common.wbspi import WBSPI
from pueo.common.bf import bf
# from s6clk import SURF6Clock
from gpio import GPIO

import queue
import logging

#https://stackoverflow.com/questions/4984647/accessing-dict-keys-like-an-attribute
# For pretending eeprom
class AttrDict(dict):
    def __init__(self, *args, **kwargs):
        super(AttrDict, self).__init__(*args, **kwargs)
        self.__dict__ = self

parser = argparse.ArgumentParser()
parser.add_argument("-p", "--port", default=None)
args = parser.parse_args()

LOG_NAME = "testStartup"
RPI_PORT_NAME = "/dev/ttySC0"
RPI_BAUD = 115200
RPI_EEPROM_SOCID = 1 # Will eventually want this for packet sorting
RPI_EEPROM_LOCATION = {'crate':0, 'slot':0}

if (not args.port is None):
    RPI_PORT_NAME = args.port

# https://stackoverflow.com/questions/2183233/how-to-add-a-custom-loglevel-to-pythons-logging-facility/35804945
def addLoggingLevel(levelName, levelNum, methodName=None):
    if not methodName:
        methodName = levelName.lower()

    if hasattr(logging, levelName):
       raise AttributeError('{} already defined in logging module'.format(levelName))
    if hasattr(logging, methodName):
       raise AttributeError('{} already defined in logging module'.format(methodName))
    if hasattr(logging.getLoggerClass(), methodName):
       raise AttributeError('{} already defined in logger class'.format(methodName))

    # This method was inspired by the answers to Stack Overflow post
    # http://stackoverflow.com/q/2183233/2988730, especially
    # http://stackoverflow.com/a/13638084/2988730
    def logForLevel(self, message, *args, **kwargs):
        if self.isEnabledFor(levelNum):
            self._log(levelNum, message, args, **kwargs)
    def logToRoot(message, *args, **kwargs):
        logging.log(levelNum, message, *args, **kwargs)

    logging.addLevelName(levelNum, levelName)
    setattr(logging, levelName, levelNum)
    setattr(logging.getLoggerClass(), methodName, logForLevel)
    setattr(logging, methodName, logToRoot)

# the logging stuff might be farmed off into
# a separate thread using the QueueHandler stuff
addLoggingLevel('TRACE', logging.DEBUG-5)
addLoggingLevel('DETAIL', logging.INFO-5)
logger = logging.getLogger(LOG_NAME)
logging.basicConfig(level=10)

# eeprom = PySOCEEPROM(mode='AUTO')
# if eeprom.socid is None:
#     logger.error("cannot start up without an SOCID!")
#     exit(1)
# eeprom = PySOCEEPROM(mode=None)
eeprom = AttrDict({'socid': RPI_EEPROM_SOCID, 'location': RPI_EEPROM_LOCATION}) # Pretending to be the pySOCEEPROM class

try:
    logger.info("starting up with unique ID 0x%2.2x" % eeprom.socid)
except Exception as e:
    logger.info("This is a Raspberry Pi and doesn't have EEPROM info")
    
# zynq = PyZynqMP()
    
# surf = PueoSURF(WBSPI.find_device('osu,surf6revB'),'SPI')
# clk = SURF6Clock()
# clk.trenzClock.powerdown(True)
# clkrst = GPIO(GPIO.get_gpio_pin(3),'out')

# create the selector first
sel = selectors.DefaultSelector()
# now create our tick FIFO
tickFifo = queue.Queue()
# create a function for processing the tick FIFO
def runTickFifo(fd, mask):
    tick = os.read(fd, 1)
    logger.trace("tick %d", tick[0])
    # empty the tick FIFO before running them
    toDoList = []
    while not tickFifo.empty():
        toDoList.append(tickFifo.get())
    for task in toDoList:
        logger.trace("processing %s", task)
        try:
            task()
        except Exception as e:
            import traceback
            
            logger.error("callback threw an exception: %s", repr(e))
            logger.error(traceback.format_exc())
            
            handler.set_terminate()
            
        
# they all take the selector now
timer = HskTimer(sel, callback=runTickFifo, interval=1)
# this new version takes the selector
handler = SignalHandler(sel)
# spawn up the hsk handler
hsk = HskHandler(sel,
                 eeprom,
                 logName=LOG_NAME,
                 port=RPI_PORT_NAME,
                 baud=RPI_BAUD)
# and the surf startup handler
startup = StartupHandlerPi( LOG_NAME,
                            StartupHandlerPi.StartupState.LOCATE_EYE,
                            tickFifo)
# sigh stupidity
def runHandler(fd, mask):
    st = os.read(fd, 1)
    logger.trace("immediate run: handler in state %d", st[0])
    startup.run()

# double sigh    
sel.register(startup.rfd, selectors.EVENT_READ, runHandler)

# this is all pretty clean now
timer.start()

zynq = AttrDict({'NEXT': "./temp/a.txt"}) # Will complain if it has to do anything in the firmware
processor = HskProcessor(hsk,
                         zynq,
                         eeprom,
                         startup,
                         LOG_NAME,
                         handler.set_terminate,
                         plxVersionFile="/etc/petalinux/version",
                         versionFile="/usr/local/share/version.pkl")
                         
######################            
hsk.start(callback=processor.basicHandler)
######################

# need to call the startup handler once, but it can except
try:
    startup.run()
except Exception as e:
    import traceback
            
    logger.error("callback threw an exception: %s", repr(e))
    logger.error(traceback.format_exc())
    
    handler.set_terminate()    
    
# terminate is now inside the handler
while not handler.terminate:
    events = sel.select()
    for key, mask in events:
        callback = key.data
        logger.trace("processing %s", callback)
        try:
            callback(key.fileobj, mask)
        except Exception as e:
            import traceback
            
            logger.error("callback threw an exception: %s", repr(e))
            logger.error(traceback.format_exc())
            
            handler.set_terminate()

logger.info("Terminating!")
timer.cancel()
hsk.stop()
processor.stop()

# ok, this changed with plx 0.3.0's pueo-squashfs:
# there's only one termination option we can do (0x7E) - terminate no unmount
# plus we have 0x7F (reboot)
# we then have 5 restart combinations with pueo-squashfs
# 0: normal exit and restart (load next software, keep local changes)
# 1: hot restart (do not load next software, keep local changes)
# 2: normal exit, revert and restart (load next software, abandon local changes)
# 3: hot revert and restart (do not load next software, abandon local changes)
# 4: clean up and restart (restart from QSPI)
#
# this is implemented with 3 bitmasks and 2 magic numbers
# we have an additional bitmask which is for Our Eyes Only

# 0x01: bmKeepCurrentSoft
# 0x02: bmRevertChanges
# 0x04: bmCleanup
# 0x08: bmForceReprogram
# 0xFE: kTerminate
# 0xFF: kReboot
# note that eRestart checks if bit 7 is set: if it is,
# and the value is not one of kTerminate or kReboot, it is IGNORED.
if processor.restartCode:
    code = processor.restartCode
    if code & processor.bmMagicValue:
        code = code ^ processor.bmMagicValue        
    elif code & processor.bmForceReprogram:
        # os.unlink(zynq.CURRENT)
        logger.info("Would have unliked the zynq processor (If I HAD ONE!!!)")
        code = code ^ processor.bmForceReprogram
    exit(code)
exit(0)
