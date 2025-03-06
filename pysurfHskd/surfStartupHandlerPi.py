from enum import Enum
import logging
import os
from pueo.common.bf import bf

# the startup handler actually runs in the main
# thread. it either writes a byte to a pipe to
# indicate that it should be called again,
# or it pushes its run function into the tick FIFO
# if it wants to be called when the tick FIFO
# expires.
# the tick FIFO takes closures now
# god this thing is a headache
class StartupHandlerPi:
        
    LMK_FILE = "/usr/local/share/SURF6_LMK.txt"
    class StartupState(int, Enum):
        STARTUP_BEGIN = 0
        WAIT_CLOCK = 1
        RESET_CLOCK = 2
        RESET_CLOCK_DELAY = 3
        PROGRAM_ACLK = 4
        WAIT_ACLK_LOCK = 5
        ENABLE_ACLK = 6
        WAIT_PLL_LOCK = 7
        ALIGN_RXCLK = 8
        LOCATE_EYE = 9
        TURFIO_LOCK = 10
        WAIT_TURFIO_LOCKED = 11
        ENABLE_TRAIN = 12
        WAIT_TURFIO = 13
        DISABLE_TRAIN = 14
        STARTUP_FAILURE = 255

        def __index__(self) -> int:
            return self.value

    def __init__(self,
                 logName,
                 autoHaltState,
                 tickFifo):
        self.state = self.StartupState.STARTUP_BEGIN
        self.logger = logging.getLogger(logName)
        self.endState = autoHaltState        
        self.tick = tickFifo
        self.rfd, self.wfd = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
        if self.endState is None:
            self.endState = self.StartupState.STARTUP_BEGIN

    def _runNextTick(self):
        if not self.tick.full():
            self.tick.put(self.run)
        else:
            raise RuntimeError("tick FIFO became full in handler!!")

    def _runImmediate(self):
        toWrite = (self.state).to_bytes(1, 'big')
        nb = os.write(self.wfd, toWrite)
        if nb != len(toWrite):
            raise RuntimeError("could not write to pipe!")
        
    def run(self):
        # whatever dumb debugging
        self.logger.trace("startup state: %s", self.state)
        # endState is used to allow us to single-step
        # so if you set startup to 0 in the EEPROM, you can
        # set the end state via HSK and single-step through
        # startup.
        if self.state == self.endState or self.state == self.StartupState.STARTUP_FAILURE:
            self._runNextTick()
            return
        elif self.state == self.StartupState.STARTUP_BEGIN:
            id = b'RPI'
            if id != b'RPI':
                self.logger.error("failed identifying RPI: %s", id.hex())
                self.state == self.StartupState.STARTUP_FAILURE
                self._runNextTick()
                return
            else:
                dv = "Raspberry Pi"
                self.logger.info("this is 'SURF' %s", str(dv))
                self.state = self.StartupState.WAIT_CLOCK
                self._runImmediate()
                return
        elif self.state == self.StartupState.WAIT_CLOCK:
            r = [False for x in range(32)]
            if not r[31]:
                r[31] = True
                self._runNextTick()
                return
            else:
                self.logger.info("Fake RACKCLK is ready.")                
                self.state = self.StartupState.RESET_CLOCK
                self._runImmediate()
                return
        elif self.state == self.StartupState.RESET_CLOCK:
            if not os.path.exists(self.LMK_FILE):
                self.logger.error("failed locating %s", self.LMK_FILE)
                self.state = self.StartupState.STARTUP_FAILURE
                self._runNextTick()
            self.state = self.StartupState.RESET_CLOCK_DELAY
            self._runNextTick()
            return
        elif self.state == self.StartupState.RESET_CLOCK_DELAY:    
            self.state = self.StartupState.PROGRAM_ACLK
            self._runNextTick()
            return
        elif self.state == self.StartupState.PROGRAM_ACLK:
            # debugging
            st = 0
            self.logger.detail("Clock status before programming: %2.2x", st)
            # self.clock.surfClock.configure(self.LMK_FILE)
            self.state = self.StartupState.WAIT_ACLK_LOCK
            self._runImmediate()
            return
        elif self.state == self.StartupState.WAIT_ACLK_LOCK:
            self.logger.detail("Clock status now: %2.2x", st)
            if st & 0x2 == 0:
                self._runNextTick()
                st = 0xFF
                return
            else:
                self.logger.info("ACLK is ready.")
                self.state = self.StartupState.ENABLE_ACLK
                self._runImmediate()
                return
        elif self.state == self.StartupState.ENABLE_ACLK:
            self.state = self.StartupState.WAIT_PLL_LOCK
            self._runImmediate()
            return
        elif self.state == self.StartupState.WAIT_PLL_LOCK:
            if not r[14]:
                r[14] = True
                self._runNextTick()
                return
            self.state = self.StartupState.ALIGN_RXCLK
            self._runImmediate()
            return
        elif self.state == self.StartupState.ALIGN_RXCLK:
            # use firmware parameters for this eventually!!!
            # this needs to freaking do something if it fails!!
            av = "0.8675309"
            self.logger.info("RXCLK aligned at offset %f", av)
            self.state = self.StartupState.LOCATE_EYE
            self._runImmediate()
            return
        elif self.state == self.StartupState.LOCATE_EYE:
            # use firmware parameters for this eventually!!!
            self.state = self.StartupState.TURFIO_LOCK
            self._runImmediate()
            return
        elif self.state == self.StartupState.TURFIO_LOCK:
            self.state = self.StartupState.WAIT_TURFIO_LOCKED
            self._runImmediate()
            return
        elif self.state == self.StartupState.WAIT_TURFIO_LOCKED:
            self.state = self.StartupState.ENABLE_TRAIN
            self._runImmediate()
            return
        elif self.state == self.StartupState.ENABLE_TRAIN:
            # dangit lookup what to do here
            self.state = self.StartupState.WAIT_TURFIO
            self._runImmediate()
            return
        elif self.state == self.StartupState.WAIT_TURFIO:
            # figure out what to do here too!!!
            self._runNextTick()
            return
