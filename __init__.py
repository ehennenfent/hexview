from __future__ import print_function
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *

import os
import collections
from math import *
import time

from cursor import *
from selection import *

# Use the same orange highlight for changed memory values
dirtycolor = QColor(255, 153, 51)

class HexDisplay(QAbstractScrollArea):
    """
    Modified from https://github.com/csarn/qthexedit/blob/master/hexwidget.py
    Most of the dead code should be gone, but there could be something I missed.
    Does all sorts of nasty unmaintanable things, but the most important thing
    to know is that the memory contents are just stored as a string, and addresses
    are 0-index internally, with the offset corresponding to the actual memory addresses
    added after-the-fact during rendering.
    """
    selectionChanged = pyqtSignal()
    def __init__(self, parent=None, filename=None, starting_address=0):
        super(HexDisplay, self).__init__(parent)
        if filename is not None:
            self.filename = filename
            self.data = open(filename, 'rb').read()
        else:
            self.data = ""
            self.filename = "<buffer>"
        self.old_data = self.data
        self.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.charWidth = self.fontMetrics().width("2")
        self.charHeight = self.fontMetrics().height()
        self.magic_font_offset = 2
        self.starting_address = starting_address # Stores the memory address to start numbering from
        self.dirty = [] # Stores whether a given byte should be highlighted

        self.viewport().setCursor(Qt.IBeamCursor)
        # constants
        self.addr_width = 16
        self.bpl = 32
        self.addr_start = 1
        self.gap2 = 2
        self.gap3 = 2
        self.data_width = self.maxWidth()
        self.data_start = self.addr_start + self.addr_width + self.gap2
        self.code_start = self.data_start + self.data_width + self.gap3

        self.pos = 0
        self.blink = False

        self.selection = Selection(active=False)

        self.highlights = []
        self._cursor = Cursor(32,1)

        self.cursor.changed.connect(self.cursorMove)
        self.setMinimumWidth((self.code_start + self.bpl + 5) * self.charWidth)
        self.setMaximumWidth((self.code_start + self.bpl + 5) * self.charWidth)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.adjust()

    @property
    def cursor(self):
        return self._cursor

    @cursor.setter
    def cursor(self, value):
        self._cursor.update(value)

    @property
    def raw_data(self):
        return self.data

    def redraw(self):
        # self.viewport().repaint()
        self.viewport().update() # update is apparently cheaper than repaint
        self.adjust()

    def clear(self):
        self.data = ""
        # self.redraw()

    def set_new_offset(self, newoffset):
        """ Sets a new starting offset. Has to be this complicated to make sure
        highlighting doesn't get weird """
        old = self.starting_address
        if(self.starting_address != newoffset):
            # print("Changing starting address from {0} to {1}".format(hex(self.starting_address), hex(newoffset)))
            self.starting_address = newoffset
        self.dirty = []
        if(newoffset > old):
            dif = newoffset - old
            for l, r in zip(self.old_data[dif:], self.data):
                self.dirty.append(l != r)
        elif(newoffset < old): # Stack *growing*
            dif = old - newoffset
            for _ in range(dif):
                self.dirty.append(True)
            for l, r in zip(self.old_data, self.data[dif:]):
                self.dirty.append(l != r)
        else:
            for l, r in zip(self.old_data, self.data):
                self.dirty.append(l != r)
        # self.redraw()

    def highlight_address(self, address, length, color=Qt.darkRed, name="*"):
        """ Uses named selections, which track absolute addresses instead of indexes.
        This means this will move if the offset is changed, and that .contains will work
        properly on addresses instead of indices. """
        select = NamedSelection(self, name, address, address + length - 1, color)
        self.highlights.append(select)
        # self.redraw()

    def clear_highlight(self, address):
        """ Deletes all the highlights that contain a given address """
        adj_addr = address - self.starting_address
        self.highlights = [s for s in filter(lambda h: not h.contains(adj_addr), self.highlights)]
        # self.redraw()

    def clear_named_highlight(self, name):
        """ Deletes all the highlights with the given name """
        new_highlights = []
        for h in self.highlights:
            if hasattr(h, 'name'):
                if h.name == name:
                    pass
                else:
                    new_highlights.append(h)
            else:
                new_highlights.append(h)
        self.highlights = new_highlights

    def update_addr(self, addr, newval):
        """ Updates the display. Works a lot better if you just pass in the entire
        new block of memory at address 0x0 rather than try to be precise about it.
        It strips off anything following the new memory, so updating in the above way
        is probably in your best interest anyway."""
        length = len(self.data)
        # print("Writing",len(newval),"bytes at", hex(addr))
        if (addr > length):
            raise ValueError("Attempted to display data outside the contiguous bounds of this memory segment!")
        part_one = self.data[0:(addr - self.starting_address)] + newval
        #newdata = part_one + self.data[len(part_one):] # Overwrite, don't append
        self.old_data = self.data
        self.data = part_one #newdata
        # self.redraw()

    def is_dirty(self, index):
        """ Figures out if a given index was modified in the last update """
        if len(self.dirty) <= index:
            return False
        return self.dirty[index]

    # I didn't write most of the following code, so I'm afraid it's mostly undocumented.
    # However, it should continue to Just Work(TM) so long as the 0-based indexing scheme isn't messed up.
    def toAscii(self, string):
        return "".join([x if ord(x) >= 33 and ord(x) <= 126 else "." for x in string])

    def getLines(self, pos=0):
        while pos < len(self.raw_data)-self.bpl:
            yield (pos, self.bpl, self.toAscii(self.raw_data[pos:pos+self.bpl]))
            pos += self.bpl
        yield (pos, len(self.raw_data)-pos, self.toAscii(self.raw_data[pos:]))

    def maxWidth(self):
        return self.bpl * 3 - 1

    def numLines(self):
        return int(ceil(float(len(self.raw_data))/ self.bpl))

    def visibleColumns(self):
        ret = int(ceil(float(self.viewport().width())/self.charWidth))
        return ret

    def visibleLines(self):
        return int(ceil(float(self.viewport().height())/self.charHeight))

    def totalCharsPerLine(self):
        ret = self.bpl * 4 + self.addr_width + self.addr_start + self.gap2 + self.gap3
        return ret

    def adjust(self):
        self.horizontalScrollBar().setRange(0, self.totalCharsPerLine() - self.visibleColumns() + 1)
        self.horizontalScrollBar().setPageStep(self.visibleColumns())
        self.verticalScrollBar().setRange(0, self.numLines() - self.visibleLines() + 1)
        self.verticalScrollBar().setPageStep(self.visibleLines())

    def goto(self, address):
        self.cursor.nibble = 0
        self.cursor.address = address

    # =====================  Coordinate Juggling  ============================

    def pxToCharCoords(self, px, py):
        cx = int(px / self.charWidth)
        cy = int((py-self.magic_font_offset) / self.charHeight)
        return (cx, cy)

    def charToPxCoords(self, cx, cy):
        "return upper left corder of the rectangle containing the char at position cx, cy"
        px = cx * self.charWidth
        py = cy * self.charHeight + self.magic_font_offset
        return QPoint(px, py)

    def pxCoordToCursor(self, coord):
        column, row = self.pxToCharCoords(coord.x()+self.charWidth/2, coord.y())
        if column >= self.data_start and column < self.code_start:
            rel_column = column-self.data_start
            line_index = rel_column - (rel_column / 3)
            addr = self.pos + line_index/2 + row * self.bpl
            return Cursor(addr, 1 if rel_column % 3 == 1 else 0)

    def indexToHexCharCoords(self, index):
        rel_index = index - self.pos
        cy = rel_index / self.bpl
        line_index = rel_index % self.bpl
        rel_column = line_index * 3
        cx = rel_column + self.data_start
        return (cx, cy)

    def indexToAsciiCharCoords(self, index):
        rel_index = index - self.pos
        cy = rel_index / self.bpl
        line_index = rel_index % self.bpl
        cx = line_index + self.code_start
        return (cx, cy)

    def charAtCursor(self, cursor):
        code_char = self.raw_data[cursor.address]
        hexcode = "{:02x}".format(ord(code_char))
        hex_char = hexcode[cursor.nibble]
        return (hex_char, code_char)

    # ====================  Event Handling  ==============================
    def cursorMove(self):
        x, y = self.indexToAsciiCharCoords(self.cursor.address)
        if y > self.visibleLines() - 4:
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() + y - self.visibleLines() + 4)
        if y < 4:
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() + y - 4)

    def mousePressEvent(self, event):
        cur = self.pxCoordToCursor(event.pos())
        if cur is not None:
            if self.selection.active:
                self.selection.active = False
                self.selection.start = self.selection.end = cur.address
                self.viewport().update()
            self.blink = False
            self.cursor = cur

    def mouseMoveEvent(self, event):
        self.selection.start = self.cursor.address
        new_cursor = self.pxCoordToCursor(event.pos())
        if new_cursor is None:
            return
        self.selection.end = new_cursor.address
        self.selection.active = True
        self.viewport().update()
        self.selectionChanged.emit()

    def mouseReleaseEvent(self, event):
        cur = self.pxCoordToCursor(event.pos())
        if cur is not None:
            self.cursor = cur

    def resizeEvent(self, event):
        self.adjust()

    def paintHighlight(self, painter, line, selection):
        if self.selection.active:
            cx_start_hex, cy_start_hex = self.indexToHexCharCoords(self.selection.start)
            cx_end_hex, cy_end_hex = self.indexToHexCharCoords(self.selection.end)
            cx_start_ascii, cy_start_ascii = self.indexToAsciiCharCoords(self.selection.start)
            cx_end_ascii, cy_end_ascii = self.indexToAsciiCharCoords(self.selection.end)
            if line == cy_start_hex:
                topleft_hex = QPoint(self.charToPxCoords(cx_start_hex, line))
                topleft_ascii = QPoint(self.charToPxCoords(cx_start_ascii, line))
                if line == cy_end_hex: # single line selection
                    bottomright_hex = QPoint(self.charToPxCoords(cx_end_hex, line))
                    bottomright_ascii = QPoint(self.charToPxCoords(cx_end_ascii, line))
                else:
                    bottomright_hex = QPoint(self.charToPxCoords(self.code_start - self.gap2, line))
                    bottomright_ascii = QPoint(self.charToPxCoords(self.code_start + self.bpl, line))
                bottomright_hex += QPoint(0, self.charHeight)
                bottomright_ascii += QPoint(0, self.charHeight)
                painter.fillRect(QRect(topleft_hex, bottomright_hex), selection.color)
                painter.fillRect(QRect(topleft_ascii, bottomright_ascii), selection.color)
            elif line > cy_start_hex and line <= cy_end_hex:
                topleft_hex = QPoint(self.charToPxCoords(self.data_start, line))
                topleft_ascii = QPoint(self.charToPxCoords(self.code_start, line))
                if line == cy_end_hex:
                    bottomright_hex = QPoint(self.charToPxCoords(cx_end_hex, line))
                    bottomright_ascii = QPoint(self.charToPxCoords(cx_end_ascii, line))
                else:
                    bottomright_hex = QPoint(self.charToPxCoords(self.code_start - self.gap2, line))
                    bottomright_ascii = QPoint(self.charToPxCoords(self.code_start + self.bpl, line))
                bottomright_hex += QPoint(0, self.charHeight)
                bottomright_ascii += QPoint(0, self.charHeight)
                painter.fillRect(QRect(topleft_hex, bottomright_hex), selection.color)
                painter.fillRect(QRect(topleft_ascii, bottomright_ascii), selection.color)


    def paintHex(self, painter, row, column):
        addr = self.pos + row * self.bpl + column
        topleft = self.charToPxCoords(column*3 + self.data_start, row)
        bottomleft = topleft + QPoint(0, self.charHeight-self.magic_font_offset)
        byte = "{:02x}".format(ord(self.raw_data[addr]))
        size = QSize(self.charWidth*3, self.charHeight)
        rect = QRect(topleft, size)
        dirty = self.is_dirty(addr)
        for sel in [self.selection] + self.highlights:
            if sel.active and sel.contains(addr):
                painter.fillRect(rect, sel.color)
                if not dirty:
                    painter.setPen(self.palette().color(QPalette.HighlightedText))
                else:
                    painter.setPen(dirtycolor)
                painter.drawText(bottomleft, byte)
                painter.setPen(self.palette().color(QPalette.WindowText))
                break
        else:
            if row % 2 == 0:
                painter.fillRect(rect, self.palette().color(QPalette.AlternateBase))
            if not dirty:
                painter.setPen(self.palette().color(QPalette.WindowText))
            else:
                painter.setPen(dirtycolor)
            painter.drawText(bottomleft, byte)


    def paintAscii(self, painter, row, column):
        addr = self.pos + row * self.bpl + column
        topleft = self.charToPxCoords(column + self.code_start, row)
        bottomleft = topleft + QPoint(0, self.charHeight-self.magic_font_offset)
        byte = self.toAscii(self.raw_data[addr])
        size = QSize(self.charWidth, self.charHeight)
        rect = QRect(topleft, size)
        dirty = self.is_dirty(addr)
        for sel in [self.selection] + self.highlights:
            if sel.active and sel.contains(addr):
                painter.fillRect(rect, sel.color)
                if not dirty:
                    painter.setPen(self.palette().color(QPalette.HighlightedText))
                else:
                    painter.setPen(dirtycolor)
                painter.drawText(bottomleft, byte)
                painter.setPen(self.palette().color(QPalette.WindowText))
                break
        else:
            if row % 2 == 0:
                painter.fillRect(rect, self.palette().color(QPalette.AlternateBase))
            if not dirty:
                painter.setPen(self.palette().color(QPalette.WindowText))
            else:
                painter.setPen(dirtycolor)
            painter.drawText(bottomleft, byte)


    def paintEvent(self, event):
        start = time.time()
        painter = QPainter(self.viewport())
        palette = self.viewport().palette()

        charh = self.charHeight
        charw = self.charWidth
        charw3 = 3*charw
        data_width = self.data_width
        addr_width = self.addr_width
        addr_start = self.addr_start
        gap2 = self.gap2
        gap3 = self.gap3

        data_start = addr_start + addr_width + gap2
        code_start = data_start + data_width + gap3

        hs = self.horizontalScrollBar().value()
        addr_start -= hs
        code_start -= hs
        data_start -= hs

        addr_start *= charw
        data_start *= charw
        code_start *= charw

        self.pos = self.verticalScrollBar().value() * self.bpl

        for i, line in enumerate(self.getLines(self.pos)):
            if i > self.visibleLines():
                break

            if i % 2 == 0:
                painter.fillRect(0, (i)*charh+self.magic_font_offset,
                                 self.viewport().width(), charh,
                                 self.palette().color(QPalette.AlternateBase))
            (address, length, _ascii) = line

            data = self.raw_data[address:address+length]


            # selection highlight
            self.paintHighlight(painter, i, self.selection)
            for h in self.highlights:
                self.paintHighlight(painter, i, h)

            # address
            painter.setPen(QColor(0xA2, 0xD9, 0xAF))
            painter.drawText(addr_start, (i+1)*charh, "{:016x}".format(address+self.starting_address))
            painter.setPen(self.palette().color(QPalette.WindowText))

            # hex data
            for j, _byte in enumerate(data):
                self.paintHex(painter, i, j)
                self.paintAscii(painter, i, j)

        painter.setPen(Qt.gray)
        painter.drawLine(data_start-charw, 0, data_start-charw, self.height())
        painter.drawLine(code_start-charw, 0, code_start-charw, self.height())

        duration = time.time()-start
        if duration > 0.1: # reasonably this should be something like 1/60th of a second,
        # but since we repaint the entire window frequently I don't think it's possible
        # to get that fast without a substantial redesign.
            print("painting took:", duration, 'seconds')
