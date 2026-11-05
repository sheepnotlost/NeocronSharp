"""Two clients at once: the job loop on one, blueprint research on the other (the user's ask, 5 Nov).

Windows sends the mouse and keyboard to the window in front only, so one loop at a time may use them. The job loop has
them. Between its steps (never inside a conversation, walk or click) it gives way to research waiting to click Start:
research brings its client to the front, clicks, and puts the job client back. Research watches its Processor from
behind the job client the rest of the time, read with PrintWindow, which needs no focus.
"""
import threading
import time

import clients
from macro_core import Interrupted
from windows_backend import WindowsBackend

SETTLE = .35            # seconds for a client brought to the front to take input
FRONT_MOST = 3          # seconds to wait for Windows to put it there


class Turns:
    def __init__(self, bring=None, clock=time.monotonic, sleep=time.sleep):
        self.bring = bring or clients.bring     # puts a window in front; True if it is
        self.clock, self.sleep = clock, sleep
        self.cond = threading.Condition()
        self.holder = None      # "jobs" or "research" while it uses the input
        self.waiting = 0        # research loops asking for a turn
        self.home = None        # the job client's window, put back in front after research's turn
        self.turns_given = 0

    def wait_for(self, ready, stopped):
        """Under the lock: until ready(), or Stop."""
        while not ready():
            if stopped.is_set():
                raise Interrupted("Stopped.")
            self.cond.wait(.05)

    def hold(self, name, stopped, home=None):
        with self.cond:
            self.wait_for(lambda: self.holder is None, stopped)
            self.holder = name
            if home is not None:
                self.home = home

    def release(self, name):
        with self.cond:
            if self.holder == name:
                self.holder = None
                self.cond.notify_all()

    def give_way(self, stopped):
        """The job loop, at a safe gap between steps: let any waiting research have its turn, then carry on in front."""
        with self.cond:
            if not self.waiting or self.holder != "jobs":
                return False
            self.holder = None
            self.cond.notify_all()
            self.wait_for(lambda: self.holder is None and not self.waiting, stopped)
            self.holder = "jobs"
            home = self.home
        if home is not None:
            self.front(home, stopped)
        return True

    def front(self, hwnd, stopped):
        ends = self.clock()+FRONT_MOST
        while not self.bring(hwnd):
            if stopped.is_set():
                raise Interrupted("Stopped.")
            if self.clock() >= ends:
                raise Interrupted("Windows would not bring the client to the front.")
            self.sleep(.1)
        self.sleep(SETTLE)

    def turn(self, hwnd, stopped):
        return Turn(self, hwnd, stopped)


class Turn:
    """with turns.turn(hwnd, stopped): research's client is in front, and the job client is put back after."""
    def __init__(self, turns, hwnd, stopped):
        self.turns, self.hwnd, self.stopped = turns, hwnd, stopped

    def __enter__(self):
        turns = self.turns
        with turns.cond:
            turns.waiting += 1
            try:
                turns.wait_for(lambda: turns.holder is None, self.stopped)
            finally:
                turns.waiting -= 1
            turns.holder = "research"
        try:
            turns.front(self.hwnd, self.stopped)
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *exc):
        turns = self.turns
        try:
            if turns.home is not None:
                turns.bring(turns.home)
        finally:
            with turns.cond:
                turns.turns_given += 1
                turns.holder = None
                turns.cond.notify_all()
        return False


class BackgroundBackend(WindowsBackend):
    """Bound to one client's window, which need not be in front: read with PrintWindow, used for input only on its turn."""
    def __init__(self, hwnd, pid, capture=None):
        super().__init__()
        self.hwnd, self.pid = hwnd, pid
        self.in_turn = False
        self.print_window = capture or clients.capture

    def check_focus(self, expected_size):
        if self.in_turn:
            return super().check_focus(expected_size)
        if not self.user.IsWindow(self.hwnd):
            raise Interrupted("The research client closed.")
        if self.user.IsIconic(self.hwnd):
            raise Interrupted("The research client is minimized: leave it open behind the job client.")
        if self.client_size() != list(expected_size):
            raise Interrupted("The research client changed size. Start again.")

    def capture(self):
        if self.in_turn:
            return super().capture()
        frame = self.print_window(self.hwnd)
        if not getattr(frame, "size", 0) or not frame.any():
            raise Interrupted("The research client shows nothing from behind: is it minimized?")
        return frame

    def capture_region(self, box):
        return self.capture()
