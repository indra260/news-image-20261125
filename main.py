#!/usr/bin/env python3
"""Sum up 25 November's world news in one image.

Prints a one-page newspaper -- "THE WORLD TODAY", Wednesday
25 November 2026 -- onto a 1024x1024 canvas and saves it as
/output/entry.png (or $MAKEFUN_OUTPUT_DIR/entry.png when that
variable is set, for local runs).

Only the Python standard library is used, because that is all the
grading container provides.  The page is therefore drawn with a
small rasteriser written for the job: a flat RGB pixel buffer, a
PNG writer built on zlib, and bitmap letterforms carried in
fontdata.py (see tools/make_font.py).  Nothing is read from the
clock, the network or any random source, so two runs of this
program produce exactly the same bytes.

Every story below is data, compiled from the reporting of
Wednesday 25 November 2026; the sources are listed in README.md
and credited at the foot of the page.
"""

import os
import struct
import zlib

import fontdata

PAGE = 1024            # the canvas is square: PAGE x PAGE pixels
MARGIN = 40
WIDTH = PAGE - 2 * MARGIN

CREAM = (248, 244, 235)
BLACK = (22, 19, 15)
CRIMSON = (150, 24, 24)
SMOKE = (110, 101, 88)
HAIRLINE = (190, 182, 164)


# ------------------------------------------------------------ type

def unpack_fonts(blob):
    """Parse the blob fontdata.py carries into a dict of typefaces."""
    faces = {}
    pos = 0

    def grab(fmt):
        nonlocal pos
        values = struct.unpack_from(fmt, blob, pos)
        pos += struct.calcsize(fmt)
        return values

    (how_many,) = grab("<H")
    for _ in range(how_many):
        (name_len,) = grab("<B")
        name = blob[pos:pos + name_len].decode("ascii")
        pos += name_len
        ascent, line_px, glyph_total = grab("<HHH")
        glyphs = {}
        for _ in range(glyph_total):
            cp, adv, xo, yo, w, h, size = grab("<IHhhHHI")
            glyphs[cp] = (adv, xo, yo, w, h, blob[pos:pos + size])
            pos += size
        faces[name] = {"ascent": ascent, "line": line_px, "glyphs": glyphs}
    return faces


FACES = unpack_fonts(fontdata.FONT_BLOB)


def measure(text, face, tracking=0):
    """Pixel width of a string in the named face."""
    glyphs = FACES[face]["glyphs"]
    total = sum(glyphs[ord(ch)][0] for ch in text)
    if tracking and len(text) > 1:
        total += tracking * (len(text) - 1)
    return total


def line_px(face):
    return FACES[face]["line"]


# ------------------------------------------------------------ canvas

class Sheet:
    """A flat RGB pixel buffer with rect, type and wrapping helpers."""

    def __init__(self):
        self.px = bytearray(PAGE * PAGE * 3)

    def rect(self, x, y, w, h, colour):
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(PAGE, x + w), min(PAGE, y + h)
        if x1 <= x0 or y1 <= y0:
            return
        stripe = bytes(colour) * (x1 - x0)
        at = (y0 * PAGE + x0) * 3
        for _ in range(y1 - y0):
            self.px[at:at + len(stripe)] = stripe
            at += PAGE * 3

    def frame(self, x, y, w, h, colour, thick=1):
        self.rect(x, y, w, thick, colour)
        self.rect(x, y + h - thick, w, thick, colour)
        self.rect(x, y, thick, h, colour)
        self.rect(x + w - thick, y, thick, h, colour)

    def text(self, x, y, string, face, colour, tracking=0):
        """Print a string with the top of its ascender at y."""
        glyphs = FACES[face]["glyphs"]
        r, g, b = colour
        pen = x
        for ch in string:
            adv, xo, yo, w, h, bits = glyphs[ord(ch)]
            if w and h:
                left, top = pen + xo, y + yo
                n = 0
                for row in range(h):
                    yy = top + row
                    if 0 <= yy < PAGE:
                        base = (yy * PAGE + left) * 3
                        for col in range(w):
                            cell = bits[n >> 1]
                            level = (cell >> 4) if n % 2 == 0 else (cell & 15)
                            n += 1
                            if level:
                                xx = left + col
                                if 0 <= xx < PAGE:
                                    off = base + col * 3
                                    if level == 15:
                                        self.px[off] = r
                                        self.px[off + 1] = g
                                        self.px[off + 2] = b
                                    else:
                                        keep = 15 - level
                                        self.px[off] = (r * level + self.px[off] * keep) // 15
                                        self.px[off + 1] = (g * level + self.px[off + 1] * keep) // 15
                                        self.px[off + 2] = (b * level + self.px[off + 2] * keep) // 15
                    else:
                        n += w
            pen += adv + tracking
        return pen - (tracking if string else 0)

    def centred(self, cx, y, string, face, colour, tracking=0):
        return self.text(cx - measure(string, face, tracking) // 2,
                         y, string, face, colour, tracking)

    @staticmethod
    def wrap(string, face, max_w, tracking=0):
        lines, current = [], ""
        for word in string.split():
            trial = word if not current else current + " " + word
            if measure(trial, face, tracking) <= max_w or not current:
                current = trial
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines

    def paragraph(self, x, y, w, string, face, lh, colour,
                  tracking=0, align="left"):
        for line in self.wrap(string, face, w, tracking):
            if align == "centre":
                self.centred(x + w // 2, y, line, face, colour, tracking)
            else:
                self.text(x, y, line, face, colour, tracking)
            y += lh
        return y

    def png(self):
        """Encode the buffer as a PNG: filterless rows, one IDAT."""
        rows = bytearray()
        stride = PAGE * 3
        for yy in range(PAGE):
            rows.append(0)
            rows += self.px[yy * stride:(yy + 1) * stride]

        def chunk(tag, payload):
            return (struct.pack(">I", len(payload)) + tag + payload +
                    struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))

        header = struct.pack(">IIBBBBB", PAGE, PAGE, 8, 2, 0, 0, 0)
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) +
                chunk(b"IDAT", zlib.compress(bytes(rows), 9)) +
                chunk(b"IEND", b""))


# ------------------------------------------------------------ the news

LEAD_KICKER = "MIDDLE EAST — STRAIT OF HORMUZ"
LEAD_HEAD = "IRAN SAYS MINES HIT TANKERS IN HORMUZ; US DISPUTES IT"
LEAD_BODY = (
    "Tehran's Revolutionary Guard said tankers and an LNG carrier struck "
    "naval mines in the strait, and Iran's army said its defences had "
    "downed two American drones — an MQ-9 and a Lucas. American officials "
    "disputed the mines account, and reports differed on how many vessels "
    "were hit. Washington weighed new options against Tehran as the "
    "claims renewed fears for the waterway that carries a fifth of the "
    "world's oil."
)

STATS = [
    ("11", "wounded as a Houthi strike hit Riyadh's tower"),
    ("30+", "countries tell Russia: stop chemical arms"),
    ("30", "killed, at least, in Cairo's tanker fire"),
    ("$139", "Bangladesh's garment wage, up 36%"),
]

COLUMNS_A = [
    (
        "EUROPE — UKRAINE",
        "30 NATIONS TELL RUSSIA: STOP CHEMICAL ARMS",
        "More than 30 countries demanded Russia stop using toxic "
        "chemicals and riot agents in Ukraine, as Kyiv struck Russian "
        "energy sites and peace talks gathered pace.",
    ),
    (
        "MIDDLE EAST — RIYADH",
        "HOUTHI STRIKE WOUNDS 11 AT RIYADH TOWER",
        "A Houthi attack hit the Saudi capital's tallest tower in its "
        "financial district — the second strike in a week. The coalition "
        "then bombed Yemen's Hodeidah port.",
    ),
    (
        "SPACE — SHENZHOU-24",
        "PAKISTAN'S FIRST ASTRONAUT REACHES ORBIT",
        "China's Shenzhou-24 lifted off with two Chinese astronauts and "
        "Muhammad Zeeshan Ali, Pakistan's first person in space and the "
        "station's first foreign crew member.",
    ),
]

COLUMNS_B = [
    (
        "EGYPT — CAIRO",
        "TANKER FIRE KILLS AT LEAST 30 IN CAIRO",
        "A fuel tanker overturned on Cairo's ring road and burst into "
        "flames that spread to nearby vehicles. At least 30 people died "
        "and dozens were injured.",
    ),
    (
        "TECHNOLOGY — WASHINGTON",
        "HUANG BACK AT NVIDIA; HUAWEI CONVICTED",
        "Nvidia's board reinstated Jensen Huang as chief after President "
        "Trump's intervention; a US court convicted China's Huawei over "
        "its Iran business. AI shares slid.",
    ),
    (
        "PACIFIC — HONIARA",
        "AUSTRALIA SEALS SOLOMONS SECURITY PACT",
        "Australia and Solomon Islands signed a major treaty deepening "
        "Canberra's security role in the Pacific — a shift watched "
        "closely in Beijing.",
    ),
]

BRIEFS = [
    ("SPAIN", "Far-right parties lead polls before Sunday's snap election."),
    ("WASHINGTON", "CIA and ODNI suffer a cyber breach of unclassified systems."),
    ("TENNIS", "World No. 2 Jannik Sinner faces a long lay-off after knee surgery."),
    ("CAMBODIA", "China and Cambodia open their biggest Golden Dragon drills yet."),
    ("DHAKA", "Ousted premier Sheikh Hasina vows a 16 December homecoming."),
]

CREDIT = ("Compiled from the day's reporting by Reuters • Open Chronicle "
          "• Standard Topic • WebIndia • Radio Free")


# ------------------------------------------------------------ the page

def story_block(sheet, x, y, w, item):
    kicker, head, body = item
    sheet.text(x, y, kicker, "kick", CRIMSON, tracking=1)
    y += 19
    y = sheet.paragraph(x, y, w, head, "headsm", 25, BLACK)
    y += 2
    return sheet.paragraph(x, y, w, body, "body", 20, BLACK)


def numbers_panel(sheet, x, y, w):
    """The day in numbers: a ruled box of big figures and captions."""
    height = 176
    sheet.frame(x, y, w, height, BLACK, thick=2)
    sheet.centred(x + w // 2, y + 10, "THE DAY IN NUMBERS", "kick",
                  BLACK, tracking=3)
    sheet.rect(x + 14, y + 33, w - 28, 1, HAIRLINE)
    cell_w = (w - 24) // 2
    for i, (figure, caption) in enumerate(STATS):
        cx = x + 12 + (i % 2) * cell_w
        cy = y + 38 + (i // 2) * 66
        sheet.centred(cx + cell_w // 2, cy, figure, "bignum", CRIMSON)
        sheet.paragraph(cx + 6, cy + 34, cell_w - 12, caption,
                        "small", 14, BLACK, align="centre")
    return y + height


def compose():
    sheet = Sheet()
    sheet.rect(0, 0, PAGE, PAGE, CREAM)

    y = 18
    sheet.rect(MARGIN, y, WIDTH, 1, BLACK)
    y += 7
    sheet.centred(PAGE // 2, y, "ONE PAGE — ALL THE NEWS THAT MATTERED",
                  "kick", BLACK, tracking=4)
    y += line_px("kick") + 3
    sheet.rect(MARGIN, y, WIDTH, 4, BLACK)
    y += 3
    sheet.rect(MARGIN, y, WIDTH, 1, BLACK)
    y += 8

    sheet.centred(PAGE // 2, y, "THE WORLD TODAY", "masthead", BLACK)
    y += line_px("masthead") - 13
    sheet.rect(MARGIN, y, WIDTH, 1, BLACK)
    y += 6

    band = 40
    sheet.rect(MARGIN, y, WIDTH, band, BLACK)
    ty = y + (band - line_px("dateline")) // 2
    sheet.text(MARGIN + 16, ty, "WEDNESDAY, 25 NOVEMBER 2026",
               "dateline", CREAM)
    tag = "THE DAY IN ONE IMAGE"
    sheet.text(MARGIN + WIDTH - 16 - measure(tag, "dateline"), ty,
               tag, "dateline", CREAM)
    y += band + 11

    # The lead: kicker and headline across the page, then the lead
    # text beside the numbers panel.
    sheet.text(MARGIN, y, LEAD_KICKER, "kick", CRIMSON, tracking=2)
    y += 20
    y = sheet.paragraph(MARGIN, y, WIDTH, LEAD_HEAD, "leadhead", 50, BLACK)
    y += 7
    panel_w = 336
    panel_x = PAGE - MARGIN - panel_w
    lead_bottom = sheet.paragraph(MARGIN, y, panel_x - MARGIN - 26,
                                  LEAD_BODY, "body", 21, BLACK)
    panel_bottom = numbers_panel(sheet, panel_x, y, panel_w)
    y = max(lead_bottom, panel_bottom) + 10
    sheet.rect(MARGIN, y, WIDTH, 1, BLACK)
    y += 10

    # Two rows of three columns.
    col_w = (WIDTH - 48) // 3
    col_x = [MARGIN, MARGIN + col_w + 24, MARGIN + 2 * (col_w + 24)]
    for row in (COLUMNS_A, COLUMNS_B):
        ends = [story_block(sheet, col_x[i], y, col_w, row[i])
                for i in range(3)]
        bottom = max(ends)
        for x in col_x[1:]:
            sheet.rect(x - 12, y, 1, bottom - y, HAIRLINE)
        y = bottom + 9
        sheet.rect(MARGIN, y, WIDTH, 1, BLACK)
        y += 10

    # Briefs, set as one flowing measure with bold place names.
    for place, text in BRIEFS:
        label = place + " — "
        sheet.text(MARGIN, y, label, "briefb", BLACK)
        lx = MARGIN + measure(label, "briefb")
        lines = Sheet.wrap(text, "brief", WIDTH - (lx - MARGIN))
        sheet.text(lx, y, lines[0], "brief", BLACK)
        y += 18
        for line in lines[1:]:
            sheet.text(MARGIN, y, line, "brief", BLACK)
            y += 18
        y += 1

    y += 1
    sheet.rect(MARGIN, y, WIDTH, 1, BLACK)
    y += 6
    sheet.centred(PAGE // 2, y, CREDIT, "small", SMOKE)
    return sheet


def main():
    png = compose().png()
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "entry.png"), "wb") as handle:
        handle.write(png)


if __name__ == "__main__":
    main()
