#!/usr/bin/env python

import logging
from threading import Event, Lock

try:
    from Queue import Queue, Empty
except ImportError:
    from queue import Queue, Empty  # python 3.x

logger = logging.getLogger()

def debug(*args):
    logger.debug(" ".join(map(str, args)))

__all__ = ['OutputTranscoder']


class OutputTranscoder():
    def __init__(self):

        self.x = 0
        self.y = 0
        self.cursor = 0
        self.min_seq_cursor = 0
        self.max_seq_cursor = 0
        self.dirty_cursor = False
        self.last_clean_x = 0
        self.last_clean_y = 0

        self.content = []
        self.lines = [0]

        self.changed_event = Event()
        self.changed_content = ""
        self.content_size = 0
        self.last_content_size = 0
        self.flushed = True
        self.io_mutex = Lock()
        self.is_processing = Lock()

        self.max_lines = 5

        self.asb_mode = False
        self.saved_content = None
        self.saved_lines = None
        self.saved_cursor = None

    def set_size(self, w, h, pw, ph):
        self.max_lines = h

    def close(self):
        self.loop = False
        self.join()

    def convert_xy(self, offset):
        o = offset
        for (y, line) in enumerate(self.lines):
            if o < line or (o <= line and y == len(self.lines) - 1):
                return (o, y)
            else:
                o -= line
        debug("XY CONVERT", offset, o, y, self.lines)
        return (o, len(self.lines))

    def convert_offset(self, x, y):
        offset = x
        if y >= len(self.lines):
            raise Exception
        for line in self.lines[:y]:
            offset += line
        return offset

    def begin_sequence(self):
        with self.io_mutex:
            self.is_processing.acquire()
            if self.flushed:
                self.min_seq_cursor = self.cursor
                self.max_seq_cursor = self.cursor
                self.last_content_size = len(self.content)

    def end_sequence(self):
        self.clean_cursor()
        with self.io_mutex:
            self.changed_content = ''.join(self.content[self.min_seq_cursor:self.max_seq_cursor])
            debug("## {}".format(self.changed_content))
            # debug("TOUT :{}\n------".format(self.content))
            self.flushed = False
            self.changed_event.set()
            self.content_size = len(self.content)
            self.is_processing.release()

    def pop_output(self, timeout=-1):
        if (timeout < 0 and not self.changed_event.is_set()) or not self.changed_event.wait(timeout=timeout):
            raise Empty
        else:
            with self.io_mutex:
                self.changed_event.clear()
                self.flushed = True
                return (self.changed_content, self.min_seq_cursor, self.cursor, self.max_seq_cursor,
                        self.content_size - self.last_content_size, self.content_size)

    def get_between(self, begin, end):
        return ''.join(self.content[begin:end])

    def write_char(self, ch, insert_after=False):
        debug("\n<< PUT", repr(ch))
        debug("BEFORE -> X, Y :", self.x, self.y, "CURSOR (c, m, M):", self.cursor, self.min_seq_cursor, self.max_seq_cursor,
                  "LINES :", self.lines)
        self.clean_cursor()
        max_x = self.x_stat_line(self.y)
        if self.x >= max_x or insert_after:  # should be == if there were no problem in the computations before
            self.content.insert(self.cursor, ch)
            self.max_seq_cursor += 1
            self.lines[self.y] += 1
        else:
            self.content[self.cursor] = ch
            self.max_seq_cursor = max(self.cursor + 1, self.max_seq_cursor)  # only useful if max_seq_cursor == cursor

        if not insert_after:
            self.x += 1
            self.cursor += 1

        """
        We didn't do anything extravagant during those last lines,
        like changing line for example, thus we don't need to "clean" the cursor
        """
        self.last_clean_x = self.x
        debug("AFTER  -> X, Y :", self.x, self.y, "CURSOR (c, m, M):", self.cursor, self.min_seq_cursor, self.max_seq_cursor,
                  "LINES :", self.lines)

    #        debug("TOUT :{}\n------".format(self.content))

    def write(self, string, insert_after=False):
        if string == '\n':
            self.crlf()
        elif string == '\r':
            self.cr()
        else:
            for ch in string:
                self.write_char(ch, insert_after)

    def lf(self):
        debug("\n<< LF")
        debug("BEFORE -> X, Y :", self.x, self.y, "CURSOR (c, m, M):", self.cursor, self.min_seq_cursor, self.max_seq_cursor,
                  "LINES :", self.lines)
        self.move_down()
        self.clean_cursor()
        debug("AFTER  -> X, Y :", self.x, self.y, "CURSOR (c, m, M):", self.cursor, self.min_seq_cursor, self.max_seq_cursor,
                  "LINES :", self.lines)
        debug("TOUT :{}\n------".format(self.content))

    def cr(self):
        debug("\n<< CR")
        debug("BEFORE -> X, Y :", self.x, self.y, "CURSOR (c, m, M):", self.cursor, self.min_seq_cursor, self.max_seq_cursor,
                  "LINES :", self.lines)
        self.move_to(x=1)
        self.clean_cursor()
        debug("AFTER  -> X, Y :", self.x, self.y, "CURSOR (c, m, M):", self.cursor, self.min_seq_cursor, self.max_seq_cursor,
                  "LINES :", self.lines)
        debug("TOUT :{}\n------".format(self.content))

    def crlf(self):
        debug("\n<< CRLF")
        debug("BEFORE -> X, Y :", self.x, self.y, "CURSOR (c, m, M):", self.cursor, self.min_seq_cursor, self.max_seq_cursor,
                  "LINES :", self.lines)
        self.move_down()
        self.move_to(x=1)
        self.clean_cursor()
        debug("AFTER  -> X, Y :", self.x, self.y, "CURSOR (c, m, M):", self.cursor, self.min_seq_cursor, self.max_seq_cursor,
                  "LINES :", self.lines)
        debug("TOUT :{}\n------".format(self.content))

    def move_to(self, x=-1, y=-1):
        debug("MOVING TO", x, y)
        self.dirty_cursor = True
        if x >= 1: self.x = x - 1
        if y >= 1: self.y = y - 1

    def move_backward(self, n=1):
        debug("MOVING BACKWARD", n)
        self.dirty_cursor = True
        self.x -= n

    def move_forward(self, n=1):
        debug("MOVING FORWARD", n)
        self.dirty_cursor = True
        self.x += n

    def move_up(self, n=1):
        debug("MOVING UP", n)
        self.dirty_cursor = True
        self.y -= n

    def move_down(self, n=1):
        debug("MOVING DOWN", n)
        self.dirty_cursor = True
        self.y += n

    def x_stat_line(self, y, x=-1, cursor=-1):
        max_x = self.lines[y]
        last_one = len(self.lines) == y + 1
        if not last_one:
            max_x -= 1
        if x >= 0 > cursor:
            return (max_x, max_x - x)
        elif x >= 0:
            return (max_x, max_x - x, cursor + (max_x - x))
        else:
            return max_x

    def clean_cursor(self):
        if not self.dirty_cursor:
            return
        dirty_x = self.x
        dirty_y = self.y
        self.x = self.last_clean_x
        self.y = self.last_clean_y
        self.dirty_cursor = False

        debug("DIRTY Y, Y ", dirty_y, self.y)

        if dirty_x < 0:
            dirty_x = 0
        if dirty_y < 0:
            dirty_y = 0

        while self.y < dirty_y:
            self.cursor += self.lines[self.y]
            self.y += 1
            if self.y >= len(self.lines):
                self.cursor += 1  # We add a '\n' at the end of the previous line
                self.lines[-1] += 1
                self.content.append('\n')
                self.lines.append(0)

        while self.y > dirty_y:
            self.y -= 1
            self.cursor -= self.lines[self.y]

        debug("AFTER DIRTY_Y STUFF, CURSOR =", self.cursor)

        if self.asb_mode:
            if len(self.lines) > self.max_lines:
                debug("ASB -> TOP MANY LINES", len(self.lines), "FOR", self.max_lines)
                while len(self.lines) > self.max_lines:
                    end_line = self.lines[0]
                    del self.content[:end_line]
                    del self.lines[0]
                    self.y -= 1
                    self.cursor -= end_line
                self.min_seq_cursor = 0
                self.max_seq_cursor = len(self.content) - 1

        debug("DIRTY X, X", dirty_x, self.x)
        (max_x, remaining) = self.x_stat_line(self.y, dirty_x)

        if self.x < dirty_x < self.lines[self.y]:
            self.cursor += dirty_x - self.x

        elif dirty_x >= self.lines[self.y]:
            missing = dirty_x - self.lines[self.y]
            insert_pos = self.cursor + self.lines[self.y] - self.x
            if self.y < len(self.lines) - 1:
                missing += 1
                insert_pos -= 1

            debug("MISSING", missing, "DIRTY X", dirty_x, "X", self.x)

            self.content[insert_pos:insert_pos] = [" "] * missing

            self.cursor += dirty_x - self.x
            self.max_seq_cursor += missing
            self.lines[self.y] += missing

        elif dirty_x < self.x:
            if remaining < 0:
                self.x = max_x
            self.cursor += dirty_x - self.x
            self.x = dirty_x

            debug("DIRTY X < X ")

        self.x = dirty_x

        self.last_clean_x = self.x
        self.last_clean_y = self.y

        self.min_seq_cursor = min(self.cursor, self.min_seq_cursor)
        self.max_seq_cursor = max(self.cursor, self.max_seq_cursor)

        debug("CLEAN CURSOR", self.cursor, self.x, self.y)

    def erase_end_of_line(self):
        debug("ERASE END OF LINE")
        debug("BEFORE -> X, Y :", self.x, self.y, "CURSOR (c, m, M):", self.cursor, self.min_seq_cursor, self.max_seq_cursor,
                  "LINES :", self.lines)
        self.clean_cursor()

        (max_x, remaining, max_cursor) = self.x_stat_line(self.y, self.x, self.cursor)
        """
        If the max_cursor was close to the cursor, then it can pass before it
        when substracting (to - self.x)
        We should instead calculate (to - self.max_cursor_x) and substract
        this to m_c but doing max(self.cursor, self.max_seq_cursor) works fine
        """
        debug("REMAINING", self.max_seq_cursor, remaining, self.cursor)
        del self.content[self.cursor:max_cursor]
        self.max_seq_cursor = max(self.max_seq_cursor - remaining, self.cursor)
        self.lines[self.y] -= remaining
        debug("MAX_X = ", max_x)
        debug("AFTER -> X, Y :", self.x, self.y, "CURSOR (c, m, M):", self.cursor, self.min_seq_cursor, self.max_seq_cursor,
                  "LINES :", self.lines)
        debug("TOUT :{}\n------".format(self.content))

    def erase_start_of_line(self):
        debug("ERASE START OF LINE")
        self.clean_cursor()

        self.max_seq_cursor -= self.x
        fr = self.cursor - self.x
        self.lines[self.y] -= self.x
        self.x = 0
        self.min_seq_cursor = min(self.cursor, self.min_seq_cursor)
        del self.content[fr:self.cursor]
        self.cursor = fr

    def erase_line(self):
        debug("ERASE LINE")
        self.clean_cursor()

        fr = self.cursor - self.x
        to = self.cursor + (self.lines[self.y] - self.x)

        # if self.y < len(self.lines)-1:
        #    self.max_seq_cursor -= self.lines[self.y] - 1
        #    self.lines[self.y] = 1
        #    to -= 1
        # else:
        self.x = 0
        self.cursor = fr
        self.min_seq_cursor = min(self.cursor, self.min_seq_cursor)
        self.max_seq_cursor -= self.lines[self.y]
        self.max_seq_cursor = max(self.cursor, self.max_seq_cursor)
        if self.y > 0:
            del self.lines[self.y]
        del self.content[fr:to]

    def erase_screen(self):
        debug("ERASE SCREEN")
        self.cursor = 0
        self.y = 0
        self.x = 0
        self.last_clean_x = 0
        self.last_clean_y = 0
        self.dirty_cursor = False
        self.min_seq_cursor = 0
        self.max_seq_cursor = 0

        self.content = []
        self.lines = [0]

    def erase_forward(self, num):
        debug("ERASE FORWARD", num)
        debug("BEFORE -> X, Y :", self.x, self.y, "CURSOR (c, m, M):", self.cursor, self.min_seq_cursor, self.max_seq_cursor,
                  "LINES :", self.lines)
        self.clean_cursor()

        max_num = self.lines[self.y] - self.x
        if self.y < len(self.lines) - 1:
            max_num -= 1
        num = min(num, max_num)
        to = self.cursor + num
        self.max_seq_cursor -= num
        self.max_seq_cursor = max(self.cursor, self.max_seq_cursor)
        self.lines[self.y] -= num
        del self.content[self.cursor:to]
        debug("AFTER -> X, Y :", self.x, self.y, "CURSOR (c, m, M):", self.cursor, self.min_seq_cursor, self.max_seq_cursor,
                  "LINES :", self.lines)
        debug("TOUT :{}\n------".format(self.content))

    def erase_down(self):
        debug("ERASE DOWN")
        debug("BEFORE -> X, Y :", self.x, self.y, "CURSOR (c, m, M):", self.cursor, self.min_seq_cursor, self.max_seq_cursor,
                  "LINES :", self.lines)
        self.clean_cursor()
        if len(self.lines) - 1 == self.y:
            return
        # self.max_seq_cursor = min(self.cursor, self.max_seq_cursor)
        del self.content[self.cursor:]
        del self.lines[self.y + 1:]

        (max_x, remaining, cursor) = self.x_stat_line(self.y, self.x, self.cursor)
        debug("REMAINING max_x:{}, remaining:{}, end_line_cursor:{}".format(max_x, remaining, cursor))

        self.lines[self.y] -= remaining
        debug("AFTER -> X, Y :", self.x, self.y, "CURSOR (c, m, M):", self.cursor, self.min_seq_cursor, self.max_seq_cursor,
                  "LINES :", self.lines)
        debug("TOUT :{}\n------".format(self.content))

    def switchASBOn(self):
        if self.asb_mode:
            return

        debug("ASB MODE ACTIVATED")
        self.clean_cursor()
        self.asb_mode = True
        self.saved_content = self.content[:]
        self.saved_lines = self.lines[:]
        self.saved_cursor = self.cursor

        debug("SAVED LINES", self.saved_lines, "CURSOR", self.saved_cursor, "BEFORE X, Y", self.x, self.y)

    def switchASBOff(self):
        if not self.asb_mode:
            return

        debug("ASB MODE DESACTIVATED")

        self.asb_mode = False
        self.content = self.saved_content[:]
        self.lines = self.saved_lines[:]
        self.cursor = self.saved_cursor
        (self.x, self.y) = self.convert_xy(self.cursor)
        (self.last_clean_x, self.last_clean_y) = (self.x, self.y)
        self.min_seq_cursor = 0
        self.max_seq_cursor = len(self.content) - 1

        debug("RETRIEVED LINES", self.lines, "CURSOR", self.cursor, "X, Y", self.x, self.y)


# [0, 1, 2, '\n'] -> 4 [a, b, c, d, '\n'] -> 5
# cursor = 0, cursor += 6 : y += 1 et x = x - (len(line) - 1) = 6 - 4 + 1 = 3

if __name__ == '__main__':
    sm = OutputTranscoder()
    sm.begin_sequence()
    sm.write("a")
    sm.write("z")
    sm.write("e")
    sm.write("r")
    sm.write("t")

    sm.crlf()
    #    sm.move_backward(1)
    #    sm.move_backward(1)
    #    sm.lf()
    #    sm.move_left(2)
    #    sm.lf()

    sm.write("A")
    sm.write("Z")
    sm.write("E")
    sm.write("R")

    #    sm.move_up()
    #    sm.crlf()
    sm.move_backward(2)
    sm.erase_line()

    #    sm.lf()
    #    sm.move_left(2)
    #    sm.move_up()
    #    sm.write("a")
    #    sm.write("a")
    debug(sm.lines)
    sm.end_sequence()
    debug(sm.get_last_output(timeout=1))
    debug(sm.lines)
