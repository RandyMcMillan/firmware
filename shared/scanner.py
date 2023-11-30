# (c) Copyright 2023 by Coinkite Inc. This file is covered by license found in COPYING-CC.
#
# scanner.py - QR scanner submodule. Low level hardware stuff only.
#
import utime
import uasyncio as asyncio
from struct import pack, unpack
from utils import B2A
from imptask import IMPT
from queues import Queue
from bbqr import BBQrState

def calc_bcc(msg):
    bcc = 0
    for c in msg:
        bcc ^= c
    return bytes([bcc])

def wrap(body, fid=0):
    # wrap w/ their weird serial framing
    # - serial port doesn't always need this! just send the string, but
    #   then response is unwrapped as well, so no checksums.
    body = body if isinstance(body, bytes) else body.encode('ascii')
    rv = pack('>bH', fid, len(body)) + body
    return b'\x5A' + rv + calc_bcc(rv) + b'\xA5'       # STX ... ETX

def unwrap_hdr(packed):
    # just get out the length, no exceptions
    stx, fid, mlen = unpack('>bbH', packed[0:4])
    if stx != 0x5A or fid not in (1, 2):
        return -1
    return mlen + 6

def unwrap(packed):
    # read back values
    stx, fid, mlen = unpack('>bbH', packed[0:4])
    assert stx == 0x5A, 'framing: STX'
    assert fid == 1, 'not resp'

    body = packed[4:4+mlen]
    got_bcc, etx = packed[4+mlen:4+mlen+2]

    assert etx == 0xA5, 'framing: ETX'
    expect = calc_bcc(packed[1:4+mlen])
    assert got_bcc == expect[0], 'bad BCC'

    # return decoded body, and any extra bytes following it
    return body, packed[4+mlen+2:]

# this is wrap(b'\x90\x00', fid=1) ... 9000 is ACK. silence is NACK
OKAY = b'Z\x01\x00\x02\x90\x00\x93\xa5'
RAW_OKAY = b'\x90\x00'
LEN_OKAY = const(8)
            

# TODO: constructor should leave it in reset for simple lower-power usage; then after
#       login we can do full setup (2+ seconds) and then sleep again until needed.

class QRScanner:

    def __init__(self):

        self.busy_scanning = False
        self.scan_light = False     # is light on during scanning?
        self.version = None
        self.setup_done = False

        # hodl this lock when communicating w/ QR scanner
        self.lock = asyncio.Lock()

        start_delay = self.hardware_setup()

        # from https://github.com/peterhinch/micropython-async/blob/master/v3/as_demos/auart_hd.py
        self.stream = asyncio.StreamReader(self.serial, {})

        # needs 2+ seconds of recovery time after reset, so watch that
        asyncio.create_task(self.setup_task(start_delay))

    def hardware_setup(self):
        # setup hardware, reset scanner and return time to delay until ready
        from machine import UART, Pin
        self.serial = UART(2, 9600)
        self.reset = Pin('QR_RESET', Pin.OUT_OD, value=0)
        self.trigger = Pin('QR_TRIG', Pin.OUT_OD, value=1)      # wasn't needed

        # NOTE: reset is active low (open drain)
        self.reset(0)
        utime.sleep_ms(10)
        self.reset(1)

        # needs full 2 seconds of recovery time
        return 2

    async def setup_task(self, start_delay):
        # Task to setup device, and then die.
        await asyncio.sleep(start_delay)

        async with self.lock: 

            # get b'V2.3.0.7\r\n' or similar
            # might need to repeat a few time to get into right state
            for retry in range(3):
                try:
                    rx = await self.txrx('T_OUT_CVER')
                    await self.txrx('S_CMD_FFFF')         # factory reset of settings
                    self.version = rx.decode().strip()
                    break
                except:
                    pass
            else:
                print("QR Scanner: missing")
                return

            # configure it like we want it
            await self.txrx('S_CMD_MTRS5000')     # 5s to read before fail (unused)
            await self.txrx('S_CMD_MT11')         # trigger is edge-based (not level)
            await self.txrx('S_CMD_MT30')         # Same code reading without delay
            await self.txrx('S_CMD_MT20')         # Enable automatic sleep when idle
            await self.txrx('S_CMD_MTRF500')      # Idle time: 500ms
            await self.txrx('S_CMD_059A')         # add CR LF after QR data (important)
            await self.txrx('S_CMD_03L0')         # light off all the time by default

            # ??
            await self.txrx('S_CMD_MSRI0000')     # Modify the same code reading delay: 0ms

            # settings under continuous scan mode
            await self.txrx('S_CMD_MARS0000')    # "Modify the duration of single code reading" (ms)
            await self.txrx('S_CMD_MARR000')       # "Modify the time of the reading interval 0ms"
            await self.txrx('S_CMD_MA30')          # "Same code reading without delay"
            await self.txrx('S_CMD_MARI0000')      # "Modify the same code reading delay 0ms"
            await self.txrx('S_CMD_MS30')          # "Duplicate detection-off"

            # these aren't useful (yet?) and just make things harder to decode.
            #await self.txrx('S_CMD_05F1')         # add all information on
            #await self.txrx('S_CMD_05L1')         # output decoding length info on
            #await self.txrx('S_CMD_05S1')         # STX start char
            #await self.txrx('S_CMD_05C1')         # CodeID+prefix
            #await self.txrx('S_CMD_0501')         # prefix on
            #await self.txrx('S_CMD_0506')         # suffix
            #await self.txrx('S_CMD_05D0')         # tx total data


            self.setup_done = True
            print("QR scanner setup done.")

            await self.goto_sleep()
            
    async def scan_once(self):
        # blocks until something is scanned. returns it
        self.scan_light = False

        # wait for reset process to complete (can be an issue right after boot)
        while not self.setup_done:
            await asyncio.sleep(.25)

        bbqr = BBQrState()

        async with self.lock: 
            self.busy_scanning = True

            await self.wakeup()

            # begin scan, in continuous mode
            await self.tx('S_CMD_020E')         # Continuous scanning mode start

            try:
                while 1:
                    rv = await self._readline()
                    if not rv: continue

                    if rv[0:2] == 'B$' and bbqr.collect(rv):
                        # BBQr protocol detected; collect more data
                        continue

                    break 
            except asyncio.CancelledError:
                return None
            finally:
                # Problem: another valid scan can come in just as we are trying
                # to get out of scanner mode
                for retry in range(3):
                    try:
                        await self.txrx('S_CMD_020D')         # return to "Command mode"
                        await self.txrx('S_CMD_03L0')         # turn off light
                        break
                    except: pass

                await self.goto_sleep()
                self.busy_scanning = False

        if bbqr.is_valid():
            # return object instead of string
            return bbqr

        return rv

    async def _readline(self):
        # overridden in simulator
        # - blocks for QR to be seen
        # - must trim newline(s)
        # - must convert to str
        rv = await self.stream.readline()

        # must remove OKAY response we see, these happen
        # in response to light on/off cmds during scanning
        # - because binary, won't happen in body of QR
        rv = rv.replace(RAW_OKAY, b'')

        print("Sc: " + repr(rv))
        return rv.rstrip().decode()

    async def wakeup(self):
        # send specific command until it responds
        # - it will wake on any command, but not instant
        # - first one seems to fail 100%
        await self.tx('SRDF0051')       # blindly at first

        for retry in range(5):
            try:
                await self.txrx('SRDF0051', timeout=50)       # 50 ok, 20 too short
                return
            except: 
                # first try usually fails, that's okay... its asleep and groggy
                pass

    async def goto_sleep(self):
        # Had to decode hex to get this command! Does work tho, current consumption
        # is near zero, and wakeup is near instant
        #await self.txrx('SRDF0050')
        await self.tx('SRDF0050')

    async def flush_junk(self):
        while n := self.stream.s.any():
            junk = await self.stream.readexactly(n)
            #print('Scan << (junk)  ' + B2A(junk))

    async def tx(self, msg):
        # Send a command, don't wait for response
        # - by sending these without binary wrapper, we get back a shorter reply
        # - just RAW_OKAY
        # - which we can easily filter out of any QR data we get back at the same time
        #self.stream.write(msg)
        #await self.stream.drain()
        print('tx >> ' + msg)
        self.serial.write(msg)

    async def txrx(self, msg, timeout=250):
        # Send a command, get the corresponding response.
        # - has a long timeout, collects rx based on framing
        # - but optimized for normal case, which is just "ok" back
        # - out going messages are text, and we wrap that w/ binary framing
        # - doing the binary wrap will cause the longer response w/ framing
        # - ignore QR data (text+\r\n) and RAW_OKAY packets ... they are not us

        # flush pending (but QR could still happen)
        await self.flush_junk()

        # Send the command
        print('txrx >> ' + msg)
        self.stream.write(wrap(msg))
        await self.stream.drain()

        # Read until the first response is consumed
        expect = LEN_OKAY
        rx = b''
        while 1:
            try:
                rx += await asyncio.wait_for_ms(self.stream.readexactly(expect), timeout)
            except asyncio.TimeoutError:
                if timeout is None:
                    continue
                raise RuntimeError("no rx after %s" % msg)

            print('txrx << ' + B2A(rx))

            if rx == OKAY:
                # good path
                return

            # attempt to unframe
            mlen = unwrap_hdr(rx)

            if mlen < 0:
                # framing issue, but we can fix maybe.
                if b'\r\n' in rx:
                    # trim QR code(s) that might be at beginning of buffer
                    pos = rx.rindex(b'\n')
                    rx = rx[pos+1:]

                if RAW_OKAY in rx:
                    # earlier bare commands' ACK's, remove them
                    rx = rx.replace(RAW_OKAY, b'')

                mlen = unwrap_hdr(rx)

            if mlen < 0:
                # framing issue, must be part way thru a QR
                print('Framing prob (cmd=%s): %s=%s' % (msg, rx, B2A(rx)))
                rx = b''
                expect = LEN_OKAY
                continue

            more = mlen - len(rx)
            if more > 0:
                expect = more
                continue

            try:
                body, extra = unwrap(rx)
                if extra:
                    raise RuntimeError("extra at end")
                return body
            except Exception as exc:
                print("Bad Rx: %s=%r" % (B2A(rx), rx))
                print("   exc: %s" % exc)
                raise

    def torch_control_sync(self, on):
        # sync wrapper
        asyncio.create_task(self.torch_control(on))

    async def torch_control(self, on):
        # be an expensive flashlight
        # - S_CMD_03L1 => always light
        # - S_CMD_03L2 => when needed
        # - S_CMD_03L0 => no
        print("torch=%d" % on)
        if not self.version:
            return

        if self.busy_scanning:
            # during scanning, toggle light state, so they don't need to hold it down
            if on:
                self.scan_light = not self.scan_light
                await self.tx('S_CMD_03L%d' % (2 if self.scan_light else 0))
            return

        async with self.lock: 

            await self.wakeup()
            await self.txrx('S_CMD_03L%d' % (1 if on else 0))

            if not on:
                # sleep module too
                await self.goto_sleep()

# EOF
