#!/usr/bin/env python
#
# (c) Copyright 2018 by Coinkite Inc. This file is covered by license found in COPYING-CC.
#
# Simulate the hardware of a Coldcard. Particularly the OLED display (128x32) and 
# the number pad. 
#
# This is a normal python3 program, not micropython. It communicates with a running
# instance of micropython that simulates the micropython that would be running in the main
# chip.
#
# Limitations:
# - USB light not fully implemented, because happens at irq level on real product
#
import os, sys, tty, pty, termios, time, pdb, tempfile, struct, zlib
import subprocess
import sdl2.ext
import PIL
from PIL import Image, ImageSequence, ImageOps
from select import select
import fcntl
from binascii import b2a_hex, a2b_hex
from bare import BareMetal
from sdl2.scancode import *     # SDL_SCANCODE_F1.. etc

MPY_UNIX = 'l-port/micropython'

UNIX_SOCKET_PATH = '/tmp/ckcc-simulator.sock'

current_led_state = 0x0

class SimulatedScreen:
    # a base class

    def snapshot(self, fn_in=None):
        # save to file
        fn = fn_in or time.strftime('../snapshot-%j-%H%M%S.png')
        with tempfile.NamedTemporaryFile() as tmp:
            sdl2.SDL_SaveBMP(self.sprite.surface, tmp.name.encode('ascii'))
            tmp.file.seek(0)
            img = Image.open(tmp.file)
            img.save(fn)

        if not fn_in:
            print("Snapshot saved: %s" % fn.split('/', 1)[1])

        return fn

    def movie_start(self):
        self.movie = []
        self.last_frame = time.time() - 0.1
        print("Movie recording started.")
        self.new_frame()

    def movie_end(self):
        fn = time.strftime('../movie-%j-%H%M%S.gif')

        if not self.movie: return

        dt0, img = self.movie[0]

        img.save(fn, save_all=True, append_images=[fr for _,fr in self.movie[1:]],
                        duration=[max(dt, 20) for dt,_ in self.movie], loop=50)

        print("Movie saved: %s (%d frames)" % (fn.split('/', 1)[1], len(self.movie)))

        self.movie = None

    def new_frame(self):
        dt = int((time.time() - self.last_frame) * 1000)
        self.last_frame = time.time()

        with tempfile.NamedTemporaryFile() as tmp:
            sdl2.SDL_SaveBMP(self.sprite.surface, tmp.name.encode('ascii'))
            tmp.file.seek(0)
            img = Image.open(tmp.file)
            img = img.convert('P')
            self.movie.append((dt, img))

class LCDSimulator(SimulatedScreen):
    # Simulate the LCD found on the Q1: 320x240xRGB565
    # - written with little-endian (16 bit) data

    background_img = 'q1-images/background.png'

    TEXT_PALETTE = [0x0000, 0x0861, 0x18e3, 0x2965, 0x39e7, 0x4a69, 0x5aeb, 0x6b6d,
                    0x7bef, 0x8c71, 0x9cf3, 0xad75, 0xbdf7, 0xdefb, 0xef7d, 0xffff]
    TEXT_PALETTE_INV = list(reversed(TEXT_PALETTE))

    # where the simulated screen is, relative to fixed background
    TOPLEFT = (65, 60)

    # see stm32/COLDCARD_Q1/modckcc.c where this pallet is defined.
    palette_colours = [
            '#000', '#fff',             # black/white, must be 0/1
            '#f00', '#0f0', '#00f',     # RGB demos
            # some greys: 5 .. 12
            '#555', '#999', '#ddd', '#111111', '#151515', '#191919', '#1d1d1d',
            # tbd/unused
            '#200', '#400', '#800',
            # #15: Coinkite brand
            '#f16422'
        ]

    def __init__(self, factory):
        self.movie = None

        self.sprite = s = factory.create_software_sprite( (320,240), bpp=16)
        s.x, s.y = self.TOPLEFT
        s.depth = 100

        self.palette = [sdl2.ext.prepare_color(code, s) for code in self.palette_colours]
        assert len(self.palette) == 16

        # selftest
        try:
            assert sdl2.ext.prepare_color('#0f0', s) == 0x07e0, 'need RGB565 sprite (got 555?)'
            assert sdl2.ext.prepare_color('#f00', s) == 0xf800, 'need RGB565 sprite (got RGB?)'
        except:
            print('red = ' + hex(sdl2.ext.prepare_color('#f00', s)))
            print('grn = ' + hex(sdl2.ext.prepare_color('#0f0', s)))
            print('blu = ' + hex(sdl2.ext.prepare_color('#00f', s)))
            raise

        sdl2.ext.fill(s, self.palette[0])

        self.mv = sdl2.ext.pixels2d(self.sprite)
    
        # for any LED's .. no position implied
        self.led_red = factory.from_image("q1-images/led-red.png")
        self.led_green = factory.from_image("q1-images/led-green.png")

    def new_contents(self, readable):
        # got bytes for new update. expect a header and packed pixels
        while 1:
            prefix = readable.read(11)
            if not prefix: return
            mode, X,Y, w, h, count = struct.unpack('<s5H', prefix)
            mode = mode.decode('ascii')
            here = readable.read(count)

            if mode == 's':
                # trigger a snapshot, data is filename to save PNG into
                self.snapshot(here.decode())
                continue

            try:
                assert X>=0 and Y>=0
                assert X+w <= 320
                assert Y+h <= 240
                assert len(here) == count
            except AssertionError:
                print(f"Bad LCD update: x,y={X},{Y} w,h={w}x{h} mode={mode}")
                continue

            pos = 0
            if mode == 'p':
                # palette lookup mode (fixed, limited; obsolete)
                assert w*h == count

                for y in range(Y, Y+h):
                    for x in range(X, X+w):
                        val = here[pos]
                        pos += 1
                        self.mv[x][y] = self.palette[val & 0xf]

            elif mode in 'ti':
                # palette lookup mode for text: packed 4-bit / pixel
                # cheat: palette is not repeated over link
                assert w*h == count*2, [w,h,count]

                pal = self.TEXT_PALETTE if mode == 't' else self.TEXT_PALETTE_INV

                unpacked = bytearray()
                for b in here:
                    unpacked.append(b >> 4)
                    unpacked.append(b & 0xf)

                for y in range(Y, Y+h):
                    for x in range(X, X+w):
                        val = unpacked[pos]
                        self.mv[x][y] = pal[val & 0xf]
                        pos += 1

            elif mode == 'z':
                # compressed RGB565 pixels
                raw = zlib.decompress(here, wbits=-12)
                assert w*h*2 == len(raw)
                for y in range(Y, Y+h):
                    for x in range(X, X+w):
                        #val = (raw[pos] << 8) + raw[pos+1]
                        #val = raw[pos+1] + (raw[pos] << 8)
                        val, = struct.unpack('>H', raw[pos:pos+2])
                        self.mv[x][y] = val
                        pos += 2

            elif mode == 'q':
                # 8-bit packed black vs. white values for QR's
                # - we do the expansion
                # - we add one unit of whitespace around
                expand = h
                h = w
                scan_w = (w+7)//8
                print(f'QR: {scan_w=} {expand=} {w=}')
                assert 21 <= w < 177 and (w%2) == 1, w

                # use PIL to resize and add border
                # - but pasting img into sprite is too hard, so use self.mv instead
                W = (w+2) * expand
                tmp = Image.frombytes('1', (w, w), here).resize( (w*expand, w*expand),
                                                        resample=Image.Resampling.NEAREST)
                qr = ImageOps.expand(tmp, expand, 0)
                assert qr.size == (W, W)

                pos = 0
                pixels = list(qr.getdata(0))
                for y in range(Y, Y+W):
                    for x in range(X, X+W):
                        self.mv[x][y] = 0x0000 if pixels[pos] else 0xffff
                        pos += 1

            elif mode == 'r':
                # raw RGB565 pixels (not compressed, packed)
                # slow, avoid
                assert count == w * h * 2, [count, w, h]
                for y in range(Y, Y+h):
                    for x in range(X, X+w):
                        val, = struct.unpack('<H', here[pos:pos+2])
                        self.mv[x][y] = val
                        pos += 2

            elif mode == 'f':
                # fill a region to single pixel value
                px, = struct.unpack("<H", here)
                for y in range(Y, Y+h):
                    for x in range(X, X+w):
                        self.mv[x][y] = px

        if self.movie is not None:
            self.new_frame()

    def click_to_key(self, x, y):
        # take a click on image => keypad key if valid
        # - not planning to support, tedious
        return None

    def draw_single_led(self, spriterenderer, x, y, red=False):
        sp = self.led_red if red else self.led_green
        sp.position = (x, y)
        spriterenderer.render(sp)

    def draw_leds(self, spriterenderer, active_set=0):
        # redraw all LED's in their current state, indicated
        SE1_LED = 0x1
        SD1_LED = 0x2
        USB_LED = 0x4
        SD2_LED = 0x8
        NFC_LED = 0x10

        if active_set & SE1_LED:
            self.draw_single_led(spriterenderer, 17, 0, red=False)
        else:
            self.draw_single_led(spriterenderer, 65, 0, red=True)

        if active_set & SD1_LED:
            self.draw_single_led(spriterenderer, -10, 125)
        if active_set & SD2_LED:
            self.draw_single_led(spriterenderer, -10, 215)
        if active_set & USB_LED:
            self.draw_single_led(spriterenderer, 195, 705)
        if active_set & NFC_LED:
            self.draw_single_led(spriterenderer, 400, 275)

class OLEDSimulator(SimulatedScreen):
    # top-left coord of OLED area; size is 1:1 with real pixels... 128x64 pixels
    OLED_ACTIVE = (46, 85)

    # keypad touch buttons
    KEYPAD_LEFT = 52
    KEYPAD_TOP = 216
    KEYPAD_PITCH = 73

    background_img = 'mk4-images/background.png'

    def __init__(self, factory):
        self.movie = None

        s = factory.create_software_sprite( (128,64), bpp=32)
        self.sprite = s
        s.x, s.y = self.OLED_ACTIVE
        s.depth = 100

        self.fg = sdl2.ext.prepare_color('#ccf', s)
        self.bg = sdl2.ext.prepare_color('#111', s)
        sdl2.ext.fill(s, self.bg)

        self.mv = sdl2.ext.pixels2d(self.sprite, transpose=False)
    
        # for genuine/caution lights and other LED's
        self.led_red = factory.from_image("mk4-images/led-red.png")
        self.led_green = factory.from_image("mk4-images/led-green.png")
        self.led_sdcard = factory.from_image("mk4-images/led-sd.png")
        self.led_usb = factory.from_image("mk4-images/led-usb.png")

    def new_contents(self, readable):
        # got bytes for new update.

        # Must be bigger than a full screen update.
        buf = readable.read(1024*1000)
        if not buf:
            return

        buf = buf[-1024:]       # ignore backlogs, get final state
        assert len(buf) == 1024, len(buf)

        for y in range(0, 64, 8):
            line = buf[y*128//8:]
            for x in range(128):
                val = buf[(y*128//8) + x]
                mask = 0x01
                for i in range(8):
                    self.mv[y+i][x] = self.fg if (val & mask) else self.bg
                    mask <<= 1

        if self.movie is not None:
            self.new_frame()

    def click_to_key(self, x, y):
        # take a click on image => keypad key if valid
        col = ((x - self.KEYPAD_LEFT) // self.KEYPAD_PITCH)
        row = ((y - self.KEYPAD_TOP) // self.KEYPAD_PITCH)

        #print('rc= %d,%d' % (row,col))
        if not (0 <= row < 4): return None
        if not (0 <= col < 3): return None

        return '123456789x0y'[(row*3) + col]

    def draw_leds(self, spriterenderer, active_set=0):
        # always draw SE led, since one is always on
        GEN_LED = 0x1
        SD_LED = 0x2
        USB_LED = 0x4

        spriterenderer.render(self.led_green if (active_set & GEN_LED) else self.led_red)

        if active_set & SD_LED:
            spriterenderer.render(self.led_sdcard)
        if active_set & USB_LED:
            spriterenderer.render(self.led_usb)

def load_shared_mod(name, path):
    # load indicated file.py as a module
    # from <https://stackoverflow.com/questions/67631/how-to-import-a-module-given-the-full-path>
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

q1_charmap = load_shared_mod('charcodes', '../shared/charcodes.py')

def scancode_remap(sc):
    # return an ACSII (non standard) char to represent arrows and other similar
    # special keys on Q1 only.
    # - see ENV/lib/python3.10/site-packages/sdl2/scancode.py
    # - select/cancel/tab/bs all handled already 
    # - NFC, lamp, QR buttons in alt_up()

    m = {
        SDL_SCANCODE_RIGHT: q1_charmap.KEY_RIGHT,
        SDL_SCANCODE_LEFT: q1_charmap.KEY_LEFT,
        SDL_SCANCODE_DOWN: q1_charmap.KEY_DOWN,
        SDL_SCANCODE_UP: q1_charmap.KEY_UP,
        SDL_SCANCODE_HOME: q1_charmap.KEY_HOME,
        SDL_SCANCODE_END: q1_charmap.KEY_END,
        SDL_SCANCODE_PAGEDOWN: q1_charmap.KEY_PAGE_DOWN,
        SDL_SCANCODE_PAGEUP: q1_charmap.KEY_PAGE_UP,

        SDL_SCANCODE_F1: q1_charmap.KEY_F1,
        SDL_SCANCODE_F2: q1_charmap.KEY_F2,
        SDL_SCANCODE_F3: q1_charmap.KEY_F3,
        SDL_SCANCODE_F4: q1_charmap.KEY_F4,
        SDL_SCANCODE_F5: q1_charmap.KEY_F5,
        SDL_SCANCODE_F6: q1_charmap.KEY_F6,
    }

    return m[sc] if sc in m else None

def special_q1_keys(ch):
    # special keys on Q1 keyboard that do not have anything similar on
    # normal desktop.
    # Press META + key

    if ch == 'n':
        return q1_charmap.KEY_NFC
    if ch == 'r':               # cant be Q, sadly
        return q1_charmap.KEY_QR
    if ch == 'l':
        return q1_charmap.KEY_LAMP

    return None

q1_pressed = set()
def handle_q1_key_events(event, numpad_tx):
    # Map SDL2 (unix, desktop) keyscan code into keynumber on Q1
    # - allow Q1 to do shift logic
    # - support up to 5 keys down at once
    global q1_pressed

    assert event.type in { sdl2.SDL_KEYUP, sdl2.SDL_KEYDOWN}

    is_press = (event.type == sdl2.SDL_KEYDOWN)

    # first, see if we can convert to ascii char
    scancode = event.key.keysym.sym & 0xffff
    try:
        ch = chr(event.key.keysym.sym)
    except:
        ch = scancode_remap(scancode)

    #print(f'scan 0x{scancode:04x} mod=0x{event.key.keysym.mod:04x}=> char={ch}=0x{ord(ch) if ch else 0:02x}')

    shift_down = bool(event.key.keysym.mod & 0x3)         # left or right shift
    symbol_down = bool(event.key.keysym.mod & 0x200)      # right ALT
    special_down = bool(event.key.keysym.mod & 0xc00)     # left or right META

    #print(f"modifier = 0x{event.key.keysym.mod:04x} => shift={shift_down} symb={symbol_down} spec={special_down}")

    if special_down:
        ch = special_q1_keys(ch)
        if not ch:
            return

    # reverse char to a keynum, and perhaps the meta key too
    kn = None

    if ch:
        if ch in q1_charmap.DECODER:
            kn = q1_charmap.DECODER.find(ch)
        elif ch in q1_charmap.DECODER_SHIFT:
            kn = q1_charmap.DECODER_SHIFT.find(ch)
            shift_down = is_press
        elif ch in q1_charmap.DECODER_SYMBOL:
            kn = q1_charmap.DECODER_SYMBOL.find(ch)
            symbol_down = is_press

    #print(f" .. => keynum={kn} => shift={shift_down} symb={symbol_down}")

    if kn:
        if is_press:
            q1_pressed.add(kn)
        else:
            q1_pressed.discard(kn)

    q1_pressed.discard(q1_charmap.KEYNUM_SHIFT)
    q1_pressed.discard(q1_charmap.KEYNUM_SYMBOL)

    if shift_down: 
        q1_pressed.add(q1_charmap.KEYNUM_SHIFT)
    if symbol_down: 
        q1_pressed.add(q1_charmap.KEYNUM_SYMBOL)

    #print(f" .. => pressed: {q1_pressed}")

    # see variant/touch.py where this is decoded.
    assert len(q1_pressed) <= 5
    report = bytes(list(q1_pressed) + [ 255, 255, 255, 255, 255])[0:5]
    numpad_tx.write(report)


def start():
    is_q1 = ('--q1' in sys.argv)

    print('''\nColdcard Simulator: Commands (over simulated window):
  - Control-Q to quit
  - ^Z to snapshot screen.
  - ^S/^E to start/end movie recording
  - ^N to capture NFC data (tap it)'''
)
    if is_q1:
        print('''\
Q1 specials:
  Right-Alt = AltGr => Symb (symbol key, blue)
  Meta-L - Lamp button
  Meta-N - NFC button
  Meta-R - QR button
''')
    sdl2.ext.init()
    sdl2.SDL_EnableScreenSaver()


    factory = sdl2.ext.SpriteFactory(sdl2.ext.SOFTWARE)

    simdis = (OLEDSimulator if not is_q1 else LCDSimulator)(factory)
    bg = factory.from_image(simdis.background_img)

    window = sdl2.ext.Window("Coldcard Simulator", size=bg.size, position=(100, 100))
    window.show()

    ico = factory.from_image('program-icon.png')
    sdl2.SDL_SetWindowIcon(window.window, ico.surface)

    spriterenderer = factory.create_sprite_render_system(window)

    # initial state
    spriterenderer.render(bg)
    spriterenderer.render(simdis.sprite)
    simdis.draw_leds(spriterenderer)

    # capture exec path and move into intended working directory
    env = os.environ.copy()
    env['MICROPYPATH'] = ':' + os.path.realpath('../shared')

    display_r, display_w = os.pipe()      # fancy OLED display
    led_r, led_w = os.pipe()        # genuine LED
    numpad_r, numpad_w = os.pipe()  # keys

    # manage unix socket cleanup for client
    def sock_cleanup():
        import os
        fp = UNIX_SOCKET_PATH
        if os.path.exists(fp):
            os.remove(fp)
    sock_cleanup()
    import atexit
    atexit.register(sock_cleanup)

    # handle connection to real hardware, on command line
    # - open the serial device
    # - get buffering/non-blocking right
    # - pass in open fd numbers
    pass_fds = [display_w, numpad_r, led_w]

    if '--metal' in sys.argv:
        # bare-metal access: use a real Coldcard's bootrom+SE.
        metal_req_r, metal_req_w = os.pipe()
        metal_resp_r, metal_resp_w = os.pipe()

        bare_metal = BareMetal(metal_req_r, metal_resp_w)
        pass_fds.append(metal_req_w)
        pass_fds.append(metal_resp_r)
        metal_args = [ '--metal', str(metal_req_w), str(metal_resp_r) ]
        sys.argv.remove('--metal')
    else:
        metal_args = []
        bare_metal = None

    os.chdir('./work')
    cc_cmd = ['../coldcard-mpy', 
                        '-X', 'heapsize=9m',
                        '-i', '../sim_boot.py',
                        str(display_w), str(numpad_r), str(led_w)] \
                        + metal_args + sys.argv[1:]
    xterm = subprocess.Popen(['xterm', '-title', 'Coldcard Simulator REPL',
                                '-geom', '132x40+650+40', '-e'] + cc_cmd,
                                env=env,
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                pass_fds=pass_fds, shell=False)


    # reopen as binary streams
    display_rx = open(display_r, 'rb', closefd=0, buffering=0)
    led_rx = open(led_r, 'rb', closefd=0, buffering=0)
    numpad_tx = open(numpad_w, 'wb', closefd=0, buffering=0)

    # setup no blocking
    for r in [display_rx, led_rx]:
        fl = fcntl.fcntl(r, fcntl.F_GETFL)
        fcntl.fcntl(r, fcntl.F_SETFL, fl | os.O_NONBLOCK)

    readables = [display_rx, led_rx]
    if bare_metal:
        readables.append(bare_metal.request)

    running = True
    pressed = set()

    def send_event(ch, is_down):
        #print(f'{ch} down={is_down}')
        if is_down:
            if ch not in pressed:
                numpad_tx.write(ch.encode())
                pressed.add(ch)
        else:
            pressed.discard(ch)
            if not pressed:
                numpad_tx.write(b'\0')      # all up signal


    while running:
        events = sdl2.ext.get_events()
        for event in events:
            if event.type == sdl2.SDL_QUIT:
                # META-Q comes here for some SDL reason
                running = False
                break

            if is_q1 and event.type in { sdl2.SDL_KEYUP, sdl2.SDL_KEYDOWN} :
                if event.key.keysym.mod == 0x40:
                    # ctrl key down, not used on Q1, so process as simulator
                    # command, see lower.
                    pass
                else:
                    # all other key events for Q1 get handled here
                    handle_q1_key_events(event, numpad_tx)
                    continue

            if event.type == sdl2.SDL_KEYUP or event.type == sdl2.SDL_KEYDOWN:
                try:
                    ch = chr(event.key.keysym.sym)
                except:
                    # things like 'shift' by itself and anything not really ascii

                    scancode = event.key.keysym.sym & 0xffff
                    #print(f'keysym=0x%0x => {scancode}' % event.key.keysym.sym)
                    if SDL_SCANCODE_RIGHT <= scancode <= SDL_SCANCODE_UP:
                        # arrow keys remap for Mk4
                        ch = '9785'[scancode - SDL_SCANCODE_RIGHT]
                    else:
                        #print('Ignore: 0x%0x' % event.key.keysym.sym)
                        continue

                # control+KEY => for our use
                if event.key.keysym.mod == 0x40 and event.type == sdl2.SDL_KEYDOWN:
                    if ch == 'q':
                        # control-Q
                        running = False
                        break

                    if ch == 'n':
                        # see sim_nfc.py
                        try:
                            nfc = open('nfc-dump.ndef', 'rb').read()
                            fn = time.strftime('../nfc-%j-%H%M%S.bin')
                            open(fn, 'wb').write(nfc)
                            print(f"Simulated NFC read: {len(nfc)} bytes into {fn}")
                        except FileNotFoundError:
                            print("NFC not ready")

                    if ch in 'zse':
                        if ch == 'z':
                            simdis.snapshot()
                        if ch == 's':
                            simdis.movie_start()
                        if ch == 'e':
                            simdis.movie_end()
                        continue

                    if ch == 'm':
                        # do many OK's in a row ... for word nest menu
                        for i in range(30):
                            numpad_tx.write(b'y\n')
                            numpad_tx.write(b'\n')
                        continue

                if event.key.keysym.mod == 0x40 and event.type == sdl2.SDL_KEYUP:
                    # control key releases: ignore
                    continue

                # remap ESC/Enter 
                if not is_q1:
                    if ch == '\x1b':
                        ch = 'x'
                    elif ch == '\x0d':
                        ch = 'y'

                    if ch not in '0123456789xy':
                        if ch.isprintable():
                            print("Invalid key: '%s'" % ch)
                        continue
                    
                # need this to kill key-repeat
                send_event(ch, event.type == sdl2.SDL_KEYDOWN)

            if is_q1 and event.type in (sdl2.SDL_MOUSEBUTTONDOWN, sdl2.SDL_MOUSEBUTTONUP):
                print('NOTE: Click on sim keyboard not supported for Q1')
            else:
                if event.type == sdl2.SDL_MOUSEBUTTONDOWN:
                    #print('xy = %d, %d' % (event.button.x, event.button.y))
                    ch = simdis.click_to_key(event.button.x, event.button.y)
                    if ch is not None:
                        send_event(ch, True)

                if event.type == sdl2.SDL_MOUSEBUTTONUP:
                    for ch in list(pressed):
                        send_event(ch, False)

        rs, ws, es = select(readables, [], [], .001)
        for r in rs:

            if bare_metal and r == bare_metal.request:
                bare_metal.readable()
                continue
        
            if r is display_rx:
                simdis.new_contents(r)
                spriterenderer.render(simdis.sprite)
                window.refresh()
            elif r is led_rx:
                # was 4+4 bits, now two bytes: [active, mask]
                c = r.read(2)
                if not c:
                    break

                global current_led_state
                mask, lset = c
                current_led_state |= (mask & lset)
                current_led_state &= ~(mask & ~lset)
                #print(f'LED: mask={mask:x} lset={lset:x} => active={current_led_state:x}')

                spriterenderer.render(bg)
                spriterenderer.render(simdis.sprite)
                simdis.draw_leds(spriterenderer, current_led_state)

                window.refresh()
            else:
                pass

        if xterm.poll() != None:
            print("\r\n<xterm stopped: %s>\r\n" % xterm.poll())
            break

    xterm.kill()
    

if __name__ == '__main__':
    start()
