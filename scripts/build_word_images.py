"""Render original local vocabulary scenes from the explicit content catalog (no downloads)."""

import hashlib
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "content/word-practice/images.json"
OUT = ROOT / "public/word-illustrations"
INK = "#31594c"
COLORS = {
    "red": "#ec786e",
    "yellow": "#efc866",
    "green": "#73ac85",
    "blue": "#79add0",
    "black": "#46504f",
    "white": "#fffefa",
    "gold": "#e3b448",
}


def path(d, fill="none", stroke=INK, width=4):
    return (
        f'<path d="{d}" fill="{fill}" stroke="{stroke}" '
        f'stroke-width="{width}" stroke-linecap="round" '
        f'stroke-linejoin="round"/>'
    )


def circle(x, y, r, fill, stroke=INK):
    return f'<circle cx="{x}" cy="{y}" r="{r}" fill="{fill}" stroke="{stroke}" stroke-width="3"/>'


def rect(x, y, w, h, fill, rx=8):
    return (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" '
        f'fill="{fill}" stroke="{INK}" stroke-width="3"/>'
    )


def text(x, y, value, size=24):
    return (
        f'<text x="{x}" y="{y}" text-anchor="middle" fill="{INK}" '
        f'font-family="system-ui,sans-serif" font-weight="600" '
        f'font-size="{size}">{html.escape(str(value))}</text>'
    )


def group(parts, x=0, y=0, scale=1):
    return f'<g transform="translate({x} {y}) scale({scale})">{parts}</g>'


def person(x=180, y=130, color="#84b5a0", mood="happy", scale=1):
    p = path("M-14 28L-21 67M14 28L21 67M-25-5L-46 22M25-5L46 22", width=7)
    p += path("M-25-10Q0-24 25-10L21 35H-21Z", color)
    p += circle(0, -42, 26, "#f4cfaa") + path("M-25-49Q-20-79 7-70Q28-66 26-46", "#685548")
    p += circle(-8, -43, 2, INK) + circle(8, -43, 2, INK)
    p += path("M-9-32Q0-24 9-32" if mood == "happy" else "M-9-27Q0-36 9-27", width=2)
    return group(p, x, y, scale)


def sun(x=279, y=47):
    return circle(x, y, 22, "#f2cf67") + "".join(
        path(f"M{x + dx} {y + dy}l{vx} {vy}", stroke="#dba94c", width=3)
        for dx, dy, vx, vy in [(0, -30, 0, -8), (0, 30, 0, 8), (-30, 0, -8, 0), (30, 0, 8, 0)]
    )


def cloud(x=90, y=64, color="#fffefa"):
    return group(
        path("M-45 15Q-63-5-40-16Q-35-43-9-31Q15-55 35-27Q65-22 53 8Q40 23-45 15Z", color), x, y
    )


def tree(x=180, y=125, kind="tree", scale=1):
    p = path("M-8 14L-9 80H10L7 9", "#b38a60")
    if kind == "willow":
        p += path("M-69 2Q-32-61 20-34Q60-45 75 9", "#83b794")
        for xx in [-60, -38, -15, 18, 40, 63]:
            p += path(f"M{xx} 0q-12 36-8 66", stroke="#6b9d76", width=6)
    elif kind == "bamboo":
        p = path("M-25 82V-75M19 82V-57", stroke="#78a581", width=10)
        for yy in [-48, -8, 32]:
            p += path(
                f"M-30 {yy}h12M14 {yy + 9}h12M-20 {yy}l-35-20M20 {yy}l35-20", stroke="#487c58"
            )
    else:
        p += (
            circle(-35, -10, 39, "#8dbb86")
            + circle(25, -20, 47, "#75a781")
            + circle(0, -50, 38, "#a7c68b")
        )
    return group(p, x, y, scale)


def animal(kind, x=180, y=130, scale=1):
    color = "#edd5ad"
    if kind in ["crow", "black-dog"]:
        color = "#59616b"
    if kind in ["frog", "worm"]:
        color = "#87bb83"
    if kind in ["rabbit", "sheep", "horse"]:
        color = "#fff8e9"
    if kind in ["yellow-dog", "chicken", "duck"]:
        color = "#f0cf70"
    p = ""
    if kind == "fish":
        p = (
            path("M57-8L95-42V22Z", "#eaa47d")
            + (
                f'<ellipse cx="0" cy="-10" rx="65" ry="38" fill="#8bbccc" '
                f'stroke="{INK}" stroke-width="3"/>'
            )
            + path("M-5-45L18-70L28-42", "#e8bb80")
            + circle(-33, -18, 5, INK)
        )
    elif kind == "worm":
        p = "".join(
            circle(-65 + i * 28, 12 - abs(2 - i) * 7, 20, color) for i in range(5)
        ) + circle(-73, 0, 4, INK)
    elif kind == "ant":
        p = "".join(circle(-40 + i * 35, 0, 17, "#956b58") for i in range(3))
        p += path("M-31 8l-20 28M-3 13v27M24 13l21 27M-45-16l-20-23M-32-17l-6-28", width=3)
    elif kind == "frog":
        p = (
            path("M-54 25Q-48-34 0-32Q48-34 54 25L74 44H-74Z", color)
            + circle(-28, -30, 17, color)
            + circle(28, -30, 17, color)
            + circle(-28, -33, 5, INK)
            + circle(28, -33, 5, INK)
            + path("M-20 5Q0 22 20 5", width=3)
        )
    elif kind in ["bird", "crow", "chicken", "duck"]:
        p = (
            (
                f'<ellipse cx="0" cy="5" rx="58" ry="39" fill="{color}" '
                f'stroke="{INK}" stroke-width="3"/>'
            )
            + circle(-36, -27, 28, color)
            + circle(-43, -32, 4, INK)
            + path("M-62-29L-85-15L-61-11", "#e5a263")
            + path("M-14 40v27M18 40v27M-27 67h23M7 67h23", width=4)
            + path("M-8 4Q16-27 35 8Q12 25-8 4Z", "#ceb38c")
        )
        if kind == "chicken":
            p += path("M-53-53Q-59-78-40-64Q-26-84-23-59", "#e47769")
    else:
        p = (
            (
                f'<ellipse cx="0" cy="10" rx="60" ry="35" fill="{color}" '
                f'stroke="{INK}" stroke-width="3"/>'
            )
            + circle(-44, -25, 29, color)
            + circle(-52, -30, 4, INK)
            + path("M-35 36v32M28 36v32M55 5q36-31 37-4", width=6)
        )
        if kind == "rabbit":
            p += path(
                "M-61-49Q-83-112-62-108Q-45-87-43-54M-35-52Q-32-110-13-104Q-5-81-21-43", color
            )
        elif kind in ["sheep", "cow"]:
            p += path("M-61-48Q-90-73-81-39M-29-49Q-12-78-6-47", "#ddc99e")
        elif kind in ["horse", "wooden-horse"]:
            p += path("M-33-51l-10-22-13 23M-22-50q17 40 47 42", stroke="#9d8061", width=9)
        else:
            p += path("M-64-44L-86-65L-81-17M-26-45L-12-65L-10-17", color)
    if kind == "wooden-horse":
        p += path("M-82 91Q-4 126 84 91", stroke="#ae8557", width=10)
    return group(p, x, y, scale)


def scene(kind, v):
    p = ""
    ground = path("M30 205Q180 190 330 205", stroke="#c8d7b9", width=4)
    if kind == "sky":
        if v == "night":
            p = (
                rect(24, 22, 312, 194, "#c3d1df", 20)
                + path("M211 43Q179 98 248 108Q207 137 181 105Q154 69 211 43Z", "#f8dd89")
                + "".join(
                    text(x, y, "✦", 24) for x, y in [(80, 65), (290, 64), (115, 144), (275, 173)]
                )
            )
        elif v == "colorful-cloud":
            p = (
                sun(275, 92)
                + cloud(96, 100, "#e5b5b1")
                + cloud(235, 139, "#e8cba0")
                + cloud(172, 63, "#c7c3da")
            )
        elif v == "both":
            p = sun(95, 80) + path(
                "M258 50Q222 106 289 112Q249 143 224 112Q202 78 258 50Z", "#f6dc91"
            )
        else:
            p = sun() + cloud(105, 75, "#bac8d2" if v in ["rain", "lightning"] else "#fffefa")
            if v in ["rain", "snow", "lightning"]:
                p += cloud(232, 84, "#b8c8d0")
                if v == "lightning":
                    p += path("M190 114L164 160H191L169 199L234 142H204L223 114Z", "#f2cd66")
                else:
                    for x, y in [
                        (70, 133),
                        (110, 166),
                        (150, 132),
                        (210, 170),
                        (260, 137),
                        (299, 180),
                    ]:
                        p += (
                            text(x, y, "❄", 22)
                            if v == "snow"
                            else path(f"M{x} {y}l-8 17", stroke="#79adc0")
                        )
            elif v == "wind" or v == "air":
                p += path("M45 145h180q40 0 27-24M88 177h205q29 0 13 17", stroke="#87b0b2", width=5)
            elif v == "sun":
                p += path("M24 167Q180 129 336 167", stroke="#91b89a")
    elif kind == "calendar":
        p = (
            rect(73, 32, 214, 177, "#fffdf4")
            + rect(73, 32, 214, 44, "#96baa0")
            + path("M111 23v24M249 23v24", width=7)
        )
        for row in range(3):
            for col in range(5):
                p += circle(108 + col * 36, 103 + row * 36, 6, "#9bb2a0")
        p += circle(180, 139, 20, "none") + text(180, 147, "✓", 21)
        if v in ["year", "festival"]:
            p += text(180, 65, "年", 25)
        if v == "festival":
            p += rect(19, 100, 37, 51, "#e58a71", 15) + path("M37 151v24", stroke="#d4ad65")
    elif kind == "clock":
        p = circle(171, 117, 79, "#fffdf4") + path("M171 59v59l40 24", width=7) + sun(291, 61)
        for x, y, n in [(171, 62, 12), (227, 125, 3), (171, 183, 6), (113, 125, 9)]:
            p += text(x, y, n, 20)
    elif kind == "land":
        p = ground
        if v in ["soil", "stone"]:
            p += path("M25 152Q90 95 145 134Q240 90 335 152V212H25Z", "#bda080") + "".join(
                path(f"M{x} {y}l11-10 20 5 3 14-25 4Z", "#d5c5ab")
                for x, y in [(72, 165), (173, 145), (251, 183)]
            )
        elif v == "field":
            p += path("M23 114L328 101V207H23Z", "#e4cda0")
            for x in range(60, 320, 50):
                p += path(
                    f"M{x} 195l30-64M{x + 9} 169l-15-9M{x + 15} 156l24-5", stroke="#7e9e5b", width=5
                )
        elif v == "grass":
            p += path("M24 185Q180 110 336 185V215H24Z", "#a8c49a")
            for x in range(50, 330, 37):
                p += path(f"M{x} 192l-9-22m9 22 6-30m-6 30 18-17", stroke="#6b9e75")
        elif v == "park":
            p += (
                tree(100, 110, scale=0.7)
                + rect(160, 150, 120, 24, "#c7a576")
                + path("M174 172v32M266 172v32", width=6)
            )
        else:
            p += (
                path("M25 157L115 40L193 157Z", "#a3bfa7")
                + path("M133 156L241 34L337 156Z", "#bdd0ba")
                + path("M115 40L92 72L134 69Z", "#fffefa")
            )
            if v == "volcano":
                p += path("M98 62L113 30L130 61M114 26q-25-13-6-19", stroke="#e78464", width=7)
            else:
                p += path(
                    "M194 146Q112 174 199 193Q246 203 165 227H254Q294 203 227 183Q172 166 218 146Z",
                    "#94c1d0",
                )
    elif kind == "tree":
        if v == "forest":
            p = tree(85, 110, scale=0.8) + tree(271, 115, scale=0.8) + tree(179, 126, scale=1)
        elif v == "leaf":
            p = path("M62 181Q71 54 293 46Q286 193 62 181Z", "#92b791") + path(
                "M64 181L277 59M115 144l-5-47M159 114l46 13", stroke="#497b5e"
            )
        else:
            p = tree(kind="willow" if v == "willow" else "bamboo" if v == "bamboo" else "tree")
            if v == "autumn":
                p = p.replace("#8dbb86", "#e0b86b").replace("#75a781", "#dca976").replace(
                    "#a7c68b", "#ecd185"
                ) + path("M278 145q-15 33-34 16q-10-23 34-16Z", "#d3a668")
            if v == "shade":
                p += person(76, 154, scale=0.55)
            if v == "plant":
                p = (
                    tree(225, 129, scale=0.65)
                    + person(113, 145, scale=0.7)
                    + path("M144 160l40 18 13-35", stroke="#7ca5b0", width=7)
                )
        p += ground
    elif kind == "flower":
        if v in ["lotus", "summer"]:
            p += (
                path("M24 188Q180 174 337 188V218H24Z", "#9dc5cf")
                + '<ellipse cx="180" cy="177" rx="80" ry="16" fill="#9cbe8f"/>'
            )
        p += path("M180 185V108M180 153Q126 111 118 145Q140 175 180 166", "#96b58a")
        c = "#e9a2aa" if v in ["pink", "lotus", "summer", "plum"] else "#e98b78"
        for x, y in [(155, 72), (180, 55), (205, 72), (198, 100), (164, 100)]:
            p += circle(x, y, 23, c)
        p += circle(180, 82, 15, "#f0d181")
    elif kind == "food":
        if v == "seeds":
            p = path("M47 90Q102 50 158 90L131 164H75Z", "#96b082")
            for xx, yy in [(80, 91), (120, 91), (81, 126), (119, 126)]:
                p += circle(xx, yy, 7, "#e5d2a5")
            for xx, yy in [(211, 138), (257, 174), (296, 120)]:
                p += circle(xx, yy, 17, "#e6d4ad")
        elif v == "wintermelon":
            p = path(
                "M58 113Q70 48 183 46Q293 49 307 116Q314 185 187 192Q62 189 58 113Z", "#b1c59b"
            ) + path("M89 84Q173 63 260 90", stroke="#dae0bf", width=6)
        elif v in ["apple", "peach", "pear", "pumpkin", "melon"]:
            c = {
                "apple": "#e98c77",
                "peach": "#efb4a6",
                "pear": "#e8cf81",
                "pumpkin": "#e8ac6e",
                "melon": "#98b783",
            }[v]
            p = (
                path(
                    (
                        "M180 65Q128 26 100 79Q59 147 116 190Q153 213 180 194Q215 "
                        "216 250 190Q296 149 263 86Q242 30 180 65Z"
                    ),
                    c,
                )
                + path("M180 65q-12-33 10-47", stroke="#8d8054", width=7)
                + path("M185 49q25-34 52-9q-19 25-52 9Z", "#89ad7f")
            )
            if v == "melon":
                p = (
                    path("M54 86H306Q288 231 180 220Q70 218 54 86Z", "#89b382")
                    + path("M70 90H290Q267 201 180 204Q91 204 70 90Z", "#e99c8d")
                    + "".join(
                        circle(x, y, 4, INK)
                        for x, y in [(110, 122), (151, 158), (214, 163), (253, 122)]
                    )
                )
        elif v in ["carrot", "cucumber", "cabbage", "fungus"]:
            if v == "carrot":
                p = path("M145 73Q206 44 237 91L116 211Z", "#e6a06d") + path(
                    "M184 66l-25-40m37 35 12-44m-1 50 40-31", stroke="#87ac74", width=10
                )
            elif v == "cucumber":
                p = path(
                    "M93 178Q127 70 240 55Q279 56 265 91Q177 121 131 196Z", "#89b083"
                ) + "".join(
                    circle(x, y, 3, "#527b59") for x, y in [(141, 151), (182, 108), (229, 82)]
                )
            elif v == "cabbage":
                p = path(
                    (
                        "M180 212Q71 212 80 130Q89 43 132 76Q170 10 196 75Q266 31 "
                        "284 129Q288 211 180 212Z"
                    ),
                    "#a4c390",
                ) + path("M180 207V77M180 172l-57-42M180 154l55-47", stroke="#e8e7ba", width=6)
            else:
                p = path(
                    (
                        "M182 200Q79 171 92 107Q110 62 151 104Q151 34 204 47Q265 77 "
                        "229 121Q301 156 233 202Z"
                    ),
                    "#8f776c",
                )
        else:
            p = rect(114, 84, 128, 111, "#fff8e9", 18) + path("M243 106q70-12 35 58h-35", width=6)
            if v in ["water", "tea", "cola"]:
                p += path(
                    "M124 121h109", stroke="#9cbec0" if v == "water" else "#b28e6c", width=6
                ) + path("M146 62q-13-19 0-32M183 62q-13-19 0-32", stroke="#b9c7bc", width=3)
            elif v == "milk":
                p += rect(228, 63, 54, 128, "#b1c8d6") + text(255, 136, "奶", 23)
            elif v == "bun":
                p = path(
                    (
                        "M75 172Q58 105 130 92Q145 35 180 81Q217 52 238 101Q295 119 "
                        "281 172Q180 217 75 172Z"
                    ),
                    "#efdbb9",
                ) + path("M158 98l20 33 20-31", stroke="#bd9873")
    elif kind == "animal":
        p = (
            animal("cow", 105, 147, 0.67) + animal("sheep", 255, 147, 0.67)
            if v == "herd"
            else animal(v)
        )
        p += ground
    elif kind == "body":
        p = person(180, 141, scale=1.2)
        if v in ["hands", "feet", "claw"]:
            p = (
                path(
                    (
                        "M112 195V99Q114 80 126 97V55Q135 40 143 55V105V36Q155 22 "
                        "163 37V102V48Q175 31 183 49V111V73Q198 56 204 74L219 "
                        "142Q214 206 164 209Z"
                    ),
                    "#f1cba7",
                )
                if v == "hands"
                else path(
                    "M95 178Q87 128 112 91Q124 66 141 82Q163 109 148 156L156 191Q132 217 95 199Z",
                    "#f0cba8",
                )
                + path(
                    (
                        "M204 194Q191 154 213 109Q225 78 242 91Q268 114 250 164L269 "
                        "197Q238 215 204 194Z"
                    ),
                    "#f0cba8",
                )
            )
        elif v in ["mouth", "mouth-hot", "teeth"]:
            p = (
                circle(180, 119, 88, "#f4d4b6")
                + path("M116 107Q181 155 244 107Q240 198 180 196Q122 194 116 107Z", "#b87269")
                + rect(137, 124, 86, 22, "#fffefa", 3)
            )
        elif v == "tail":
            p = animal("dog") + circle(270, 127, 34, "none")
        elif v == "head":
            p = (
                circle(180, 111, 80, "#f0cba8")
                + path(
                    "M104 94Q98 19 179 24Q261 24 257 94L231 63L211 82L183 53L155 79L128 66Z",
                    "#75604d",
                )
                + circle(151, 108, 5, INK)
                + circle(210, 108, 5, INK)
            )
        elif v == "missing":
            p = (
                person(88, 140, scale=0.8)
                + path("M188 123h100v68H188Z", stroke="#9bb8aa")
                + text(239, 104, "?", 48)
            )
        elif v in ["ears", "eyes"]:
            p += circle(138 if v == "ears" else 169, 90, 27, "none") + circle(
                222 if v == "ears" else 191, 90, 27, "none"
            )
    elif kind == "family":
        if v in ["relatives", "brother", "sister", "we"]:
            p = (
                person(100, 135, scale=0.85)
                + person(181, 161, "#d7ae82", scale=0.62)
                + person(261, 137, "#9cb8cd", scale=0.83)
            )
        elif v in ["father", "mother", "grandfather", "grandmother"]:
            p = person(
                136, 137, "#b1a7bb" if v in ["mother", "grandmother"] else "#88a8b1", scale=1
            ) + person(241, 163, scale=0.62)
        else:
            p = person(
                180,
                143,
                "#d3a5b6" if v in ["girl", "princess"] else "#8fbaa7",
                scale=0.9 if v != "baby" else 0.65,
            )
        if v in ["grandfather", "grandmother"]:
            p += path("M112 70q27-23 49 0", stroke="#dfded2", width=11)
        if v in ["king", "princess"]:
            p += path("M150 65L144 31L168 45L181 19L193 46L217 31L210 65Z", "#e4c66c")
        if v in ["mine", "yours", "theirs"]:
            p += (
                rect(246 if v in ["yours", "theirs"] else 69, 126, 56, 66, "#e8b981")
                + text(180, 42, "他" if v == "theirs" else "你" if v == "yours" else "我", 25)
                + path("M183 49l45 37" if v == "yours" else "M169 49L120 86", stroke="#c99b5c")
            )
        if v == "youme":
            p = (
                person(100, 146, scale=0.85)
                + person(260, 146, scale=0.85)
                + text(100, 49, "我", 26)
                + text(260, 49, "你", 26)
            )
        if v == "we":
            p += path("M40 209Q180 238 320 209", stroke="#cda461", width=5) + text(
                180, 40, "我们", 26
            )
        if v == "self":
            p += (
                '<ellipse cx="180" cy="139" rx="68" ry="81" fill="none" '
                'stroke="#d4af65" stroke-width="4" stroke-dasharray="6 7"/>'
            )
        if v == "dark-skin":
            p = p.replace("#f4cfaa", "#b78262")
        if v == "introvert":
            p += rect(215, 148, 57, 43, "#e0c5a0")
    elif kind == "school":
        p = (
            rect(60, 78, 240, 129, "#d5dfc4")
            + path("M43 78L180 26L317 78Z", "#9ab69c")
            + rect(151, 145, 57, 62, "#c4a57a")
        )
        for x in [83, 233]:
            p += rect(x, 103, 43, 39, "#b4d4dc")
        if v == "hospital":
            p += text(180, 118, "+", 44)
        elif v == "capital":
            p = (
                rect(55, 108, 250, 95, "#dc9d82")
                + path("M35 107L90 76H270L324 107Z", "#c89c63")
                + rect(159, 140, 45, 63, "#9b7b5b")
            )
        elif v == "factory":
            p = (
                rect(45, 115, 210, 95, "#d8c6aa")
                + path("M45 115l65-45v45l65-45v45", "#b6c6b3")
                + rect(248, 48, 35, 162, "#b5a28d")
                + person(300, 167, scale=0.5)
            )
            for xx in [75, 130, 185]:
                p += rect(xx, 142, 30, 32, "#9cb8c0", 2)
        elif v == "judge":
            p = (
                person(180, 117, "#686f76", scale=0.9)
                + rect(65, 150, 230, 57, "#c5a581")
                + path("M224 130l40-39", stroke="#9d7c5b", width=7)
                + path("M251 76l29 24", stroke="#9d7c5b", width=18)
            )
        elif v in ["class", "meeting", "tidy"]:
            p = (
                rect(62, 38, 235, 97, "#8ca998")
                + person(95, 151, scale=0.7)
                + person(228, 160, scale=0.6)
                + rect(126, 158, 115, 22, "#d1b28b")
            )
        elif v == "gate":
            p += person(100, 163, scale=0.6)
    elif kind == "house":
        p = (
            rect(72, 86, 217, 120, "#e5d0ad")
            + path("M46 88L180 25L316 88Z", "#bd9278")
            + rect(104, 111, 48, 43, "#b7d2d2")
            + rect(195, 116, 53, 90, "#ab9579")
        )
        if v in ["open", "enter", "leave"]:
            p += (
                path("M196 116L228 130V202L196 207Z", "#f9f1dc")
                + person(263, 174, scale=0.45)
                + path("M285 159h-63l18-14m-18 14 18 14", stroke="#d19e5d", width=5)
            )
        if v == "leave":
            p += path("M225 172h77l-17-14m17 14-17 14", stroke="#d19e5d", width=6)
    elif kind == "book":
        p = path(
            "M40 70Q110 46 178 72Q247 46 320 70V197Q247 172 180 199Q111 173 40 197Z", "#fffdf3"
        ) + path("M180 75V198", stroke="#8ea58c")
        for y in [102, 126, 150]:
            p += path(f"M65 {y}q40-13 88 0M205 {y}q42-13 88 0", stroke="#b7c6b3", width=4)
        if v in ["write", "paint"]:
            p += path("M204 171L268 57L286 68L222 183L200 191Z", "#e1b779")
        if v == "name":
            p = (
                rect(70, 59, 220, 145, "#fff9ec")
                + person(124, 135, scale=0.5)
                + text(229, 109, "姓名", 24)
                + path("M193 135h70M193 160h70", stroke="#b4c5b3")
            )
        if v == "newspaper":
            p += text(180, 41, "新闻", 24)
    elif kind == "tool":
        if v == "switch":
            p = (
                rect(44, 50, 110, 160, "#d8c3a0", 3)
                + rect(207, 50, 110, 160, "#d8c3a0", 3)
                + path("M55 60L127 82V205L55 210Z", "#f7e6c5")
                + circle(295, 139, 4, INK)
            )
        elif v in ["paper", "origami"]:
            p = path("M94 28H264V211H94Z", "#fffdf5")
            if v == "origami":
                p += (
                    path("M94 126L180 211H94Z", "#e7d0a0")
                    + path("M100 124L181 203", stroke="#b69e77", width=2)
                    + path("M48 175q-10-66 43-81l-16-10m16 10-7 20", stroke="#d0a063")
                )
        elif v == "wipe":
            p = (
                person(94, 125, scale=0.8)
                + rect(128, 147, 185, 24, "#d6b38b")
                + path("M142 172v48M295 172v48", width=6)
                + path("M149 140l28-20 33 21Z", "#a0bdc3")
                + path("M213 125h50M232 108h48", stroke="#c2cbb1", width=3)
            )
        elif v in ["traffic-red", "traffic-green"]:
            p = rect(133, 20, 94, 173, "#64746c", 19) + path("M180 193v34", width=7)
            for yy, c in [(55, "#e68e79"), (106, "#e4c578"), (156, "#8db993")]:
                lit = (v == "traffic-red" and yy == 55) or (v == "traffic-green" and yy == 156)
                p += circle(180, yy, 19, c if lit else "#929d8e")
        elif v == "sharpener":
            p = (
                rect(83, 82, 194, 116, "#a5bdc7", 18)
                + circle(176, 139, 36, "#ece7cf")
                + circle(176, 139, 17, "#64796b")
                + path("M190 119L265 33L284 49L207 136Z", "#e0bc85")
            )
        elif v in ["brush", "paintbrush"]:
            p = path("M139 151L226 28L244 41L157 166Z", "#c5a277") + path(
                "M139 151Q112 151 102 214Q160 203 157 166Z",
                "#6a7167" if v == "brush" else "#ca8e7f",
            )
        elif v == "tape":
            p = (
                circle(145, 124, 69, "#e4c58e")
                + circle(145, 124, 43, "#fff9e9")
                + path("M142 191H309V152H199", "#ead2a0")
                + path("M222 153v20M250 153v20M278 153v20", width=3)
            )
        elif v == "mop":
            p = (
                person(98, 143, scale=0.7)
                + path("M229 36L182 180", stroke="#b69a79", width=10)
                + path("M181 166Q141 153 133 213H229Q219 155 181 166Z", "#bdc8b4")
            )
        elif v == "bag":
            p = (
                rect(111, 69, 138, 139, "#a0b8c4", 25)
                + path("M138 69V43q40-27 81 0v26", width=7)
                + rect(137, 133, 86, 57, "#e8c49b")
            )
        elif v == "ruler":
            p = rect(36, 99, 288, 57, "#e9cf9c", 5) + "".join(
                path(f"M{x} 100v{30 if i % 5 == 0 else 17}", width=3)
                for i, x in enumerate(range(50, 320, 17))
            )
        elif v == "knife":
            p = path("M64 145L191 54Q225 119 166 158L96 177Z", "#c2d0ce") + path(
                "M165 158L247 211Q272 216 278 191L197 128Z", "#c49678"
            )
        elif v == "umbrella":
            p = path(
                "M52 112Q180-23 308 112Q276 88 245 112Q212 88 180 112Q148 88 116 112Q84 88 52 112Z",
                "#9ab5c9",
            ) + path("M180 111V189q-4 37-29 13", width=6)
        elif v == "shoes":
            p = (
                path("M52 158L72 98H124L139 155Q183 187 146 201H55Z", "#a0b6c3")
                + path("M210 158L230 98H280L295 155Q339 187 302 201H213Z", "#a0b6c3")
                + path("M77 130h45M235 130h45", stroke="#fffefa", width=5)
            )
        elif v == "block":
            p = (
                rect(73, 143, 63, 64, "#dba98d")
                + rect(138, 143, 63, 64, "#9bb9cd")
                + rect(107, 78, 63, 64, "#b3c697")
            )
        elif v == "chess":
            p = rect(65, 32, 230, 180, "#d7b98d")
            for x in range(90, 280, 32):
                p += path(f"M{x} 45V200M77 {x - 32}H281", stroke="#a08868", width=2)
            p += circle(150, 100, 17, "#fff9ec") + circle(215, 163, 17, "#55665c")
        elif v == "table":
            p = (
                rect(53, 106, 247, 28, "#d5b790")
                + path("M75 134v75M276 134v75", width=8)
                + rect(120, 77, 77, 26, "#9bbbc1")
            )
        else:
            p = (
                path("M95 188L222 34L248 59L122 213L86 221Z", "#e5c184")
                + path("M95 188L122 213L86 221Z", "#f5dfb5")
                + path("M86 221l9-18 8 9Z", INK)
            )
    elif kind == "transport":
        p = ground
        if v == "plane":
            p += path(
                (
                    "M44 107L146 96L183 38L202 43L191 96L286 117L316 102L329 "
                    "114L299 141L191 134L188 184L170 184L143 130L44 125Z"
                ),
                "#a0bfcb",
            ) + cloud(99, 54)
        elif v == "boat":
            p += (
                path("M50 139H311L271 194H99Z", "#c7a27e")
                + path("M177 135V30L252 121H182Z", "#e5c996")
                + path("M30 206q35-20 70 0t70 0t70 0t80 0", stroke="#8db6c2")
            )
        elif v == "bridge":
            p += (
                path("M30 146Q180 33 330 146V176H30Z", "#c5b39a")
                + path("M102 176Q180 96 258 176", "#b6d0d1")
                + path("M30 147Q180 36 330 147", stroke="#957f63", width=8)
            )
        elif v == "road":
            p += path("M132 32H228L319 222H41Z", "#afbab3") + path(
                "M180 55v30m0 24v30m0 24v36", stroke="#fff9e7", width=6
            )
        else:
            p += (
                rect(61, 67, 238, 110, "#e3bc84", 19)
                + circle(105, 181, 26, "#596b61")
                + circle(259, 181, 26, "#596b61")
            )
            for x in [82, 139, 196, 253]:
                p += rect(x, 86, 36, 39, "#b7d2d6", 4)
            if v == "train":
                p += path(
                    "M34 218H326M67 202v25M121 202v25M175 202v25M229 202v25M283 202v25",
                    stroke="#9c927d",
                )
        if v == "black-pen":
            p = p.replace("#e5c184", "#526358")
    elif kind == "sport":
        p = person(181, 135, scale=0.8)
        if v == "bike":
            p += (
                circle(104, 180, 40, "none")
                + circle(263, 180, 40, "none")
                + path(
                    "M104 180L151 119L197 180H104L169 147L263 180L230 102H246",
                    stroke="#c79b6c",
                    width=6,
                )
            )
        elif v == "swim":
            p = (
                group(person(0, 0, scale=0.8), 180, 146)
                + path("M25 159q42-23 80 0t75 0t75 0t80 0", stroke="#91bac7", width=14)
                + path("M25 198q42-23 80 0t75 0t75 0t80 0", stroke="#91bac7", width=5)
            )
        elif v == "skate":
            p += path("M137 195l30 8M187 195l30 8", stroke="#84999a", width=7) + path(
                "M65 220h215", stroke="#b4d4d5", width=5
            )
        elif v == "football":
            p += circle(270, 188, 32, "#fffdf2") + path(
                "M268 163L288 180L280 202H257L248 180Z", "#6c8073"
            )
        elif v in ["horse-up", "horse-down"]:
            p = (
                animal("horse", 193, 153, 0.9)
                + person(196, 91, scale=0.53)
                + path(
                    "M60 95v84l-15-18m15 18 15-18"
                    if v == "horse-down"
                    else "M60 179V95L45 113m15-18 15 18",
                    stroke="#d49c59",
                    width=5,
                )
            )
        elif v == "parachute":
            p = (
                person(180, 171, scale=0.55)
                + path("M60 87Q180-25 300 87Z", "#e4bc8a")
                + path("M60 87L156 143M300 87L204 143M132 87L171 141M228 87L189 141", width=3)
            )
        elif v == "kite":
            p += path("M204 123Q285 122 286 55", stroke="#a39b78", width=2) + path(
                "M239 59L284 21L325 60L283 103Z", "#e6b884"
            )
        else:
            p += (
                rect(36, 148, 167, 22, "#a2bfab")
                + circle(269, 75, 9, "#fffefa")
                + path("M229 124L256 94", stroke="#bc9074", width=8)
            )
    elif kind == "music":
        p = person(111, 140, scale=0.85) + text(266, 99, "♫", 75)
        if v == "drum":
            p += rect(158, 136, 104, 58, "#dca17f", 14) + path(
                "M133 113l48 37M157 99l55 48", stroke="#a08562", width=7
            )
    elif kind == "emotion" and v in ["clever", "focus"]:
        p = person(114, 146, scale=0.9)
        if v == "clever":
            p += (
                circle(253, 79, 38, "#efcf76")
                + rect(235, 112, 36, 20, "#bac6ad", 3)
                + path("M253 30V15M208 52l-14-10M298 52l14-10", stroke="#d4ac5c")
                + text(253, 193, "✓", 47)
            )
        else:
            p += path(
                "M160 133Q208 111 247 132Q286 111 328 133V207Q280 188 247 207Q208 188 160 207Z",
                "#fff9e9",
            ) + path("M247 133V207", stroke="#9aac8f")
    elif kind in ["emotion", "speech"]:
        p = person(126, 149, mood="sad" if v in ["angry", "criticize"] else "happy", scale=0.9)
        if v in ["heart", "treasure"]:
            p += path(
                "M228 163Q166 109 202 82Q225 63 243 89Q265 62 287 82Q322 112 245 167Z", "#e6a09b"
            )
        else:
            p += path(
                (
                    "M194 33H303Q325 33 325 57V112Q325 133 303 133H236L205 "
                    "155L214 133H194Q173 133 173 110V56Q173 33 194 33Z"
                ),
                "#fffdf3",
            )
            label = {
                "question": "?",
                "think": "?",
                "yes": "✓",
                "happy": "✓",
                "no": "×",
                "angry": "!",
                "criticize": "!",
                "talk": "…",
                "choose": "?",
            }.get(v, "✓")
            p += text(250, 106, label, 62)
            if v == "think":
                p += sun(293, 169)
    elif kind == "action":
        p = person(173, 126, scale=1)
        if v == "sit":
            p += rect(121, 153, 122, 17, "#bd9a76") + path("M130 170v43M231 170v43", width=6)
        elif v == "wake":
            p = rect(43, 153, 272, 50, "#b5c7cb") + person(150, 120, scale=0.8) + sun(294, 53)
        elif v == "grow":
            p = (
                person(77, 175, scale=0.42)
                + person(176, 150, scale=0.7)
                + person(275, 120, scale=1)
            )
        elif v == "consequence":
            p = "".join(
                group(rect(0, 0, 24, 100, "#c8ad87"), 80 + i * 60, 110, 1) for i in range(4)
            ) + path("M58 64h208l-18-14m18 14-18 14", stroke="#d59c65")
        elif v == "allwork":
            p = (
                person(110, 147, scale=0.85)
                + rect(153, 133, 120, 22, "#cdb08c")
                + person(301, 157, scale=0.5)
            )
            for xx in [161, 195, 229]:
                p += rect(xx, 99, 26, 33, "#fff9ea", 2)
        elif v in ["effort", "weak"]:
            p = (
                person(87, 138, scale=0.85)
                + rect(184, 91, 119, 111, "#d6b990")
                + text(243, 77, "?" if v == "weak" else "✓", 31)
            )
        elif v == "return":
            p += path("M268 165Q329 74 255 56L269 42m-14 14 23 7", stroke="#c39d6c", width=5)
        else:
            p += path("M257 73v72l-14-14m14 14 14-14", stroke="#c29b66", width=5)
    elif kind == "flag":
        p = path("M89 215V24", width=6) + rect(92, 32, 192, 112, "#e48274", 2)
        if v == "japan":
            p = (
                path("M89 215V24", width=6)
                + rect(92, 32, 192, 112, "#fffefa", 2)
                + circle(188, 88, 29, "#d77c70")
            )
        elif v == "france":
            p += rect(93, 33, 62, 110, "#86a9c5", 0) + rect(155, 33, 64, 110, "#fffefa", 0)
        elif v == "china":
            p += text(128, 83, "★", 35) + "".join(
                text(x, y, "★", 12) for x, y in [(161, 53), (174, 68), (174, 87), (160, 102)]
            )
        else:
            p += text(177, 102, "★", 57)
    elif kind == "fire":
        p = path(
            (
                "M180 208Q98 207 103 146Q107 114 145 85Q131 125 164 130Q198 "
                "92 180 35Q259 84 259 150Q260 209 180 208Z"
            ),
            "#e8a078",
        ) + path("M182 199Q143 194 154 167L182 127Q222 170 204 196Z", "#efd181")
        if v == "torch":
            p = group(p, 70, -5, 0.63) + path("M184 130l-25 86", stroke="#9f7e56", width=17)
        if v == "off":
            p += path("M86 205L279 41", stroke="#718a7a", width=9)
    elif kind == "color":
        names = list(COLORS) if v == "rainbow" else [v]
        for i, c in enumerate(names):
            p += circle(
                180 if len(names) == 1 else 45 + i * 37,
                124,
                68 if len(names) == 1 else 24,
                COLORS[c],
            )
    elif kind in ["compare", "pattern"]:
        if v == "hero":
            p = person(180, 145)
            for xx in [131, 229]:
                p += (
                    circle(xx, 100, 24, "#f4cfaa")
                    + circle(xx - 7, 98, 2, INK)
                    + circle(xx + 7, 98, 2, INK)
                    + path(f"M{xx - 8} 109q8 8 16 0", width=2)
                )
            p += path(
                "M155 132L91 95M205 132l64-37M155 148l-63 27M205 148l63 27",
                stroke="#6d9d85",
                width=8,
            )
        elif v == "cow-hair":
            p = "".join(animal("cow", 52 + i % 3 * 48, 70 + i // 3 * 53, 0.2) for i in range(9))
            p += (
                circle(265, 118, 65, "#fff9eb")
                + path("M240 154q39-21 33-62", stroke="#ac9272", width=3)
                + path("M165 131l35-10", stroke="#b3bfae")
            )
        elif v == "long":
            p = rect(44, 77, 270, 27, "#bc9b77") + rect(44, 147, 144, 27, "#96b6c4")
        elif v in ["big", "small"]:
            p = circle(117, 134, 62, "#afc9a5") + circle(268, 156, 33, "#e5b88b")
        else:
            n = 3 if v == "same" else 10 if v == "perfect" else 12
            for i in range(n):
                p += circle(
                    70 + i % 4 * 73 if n > 3 else 75 + i * 105,
                    67 + i // 4 * 58 if n > 3 else 126,
                    18 if n > 3 else 35,
                    "#e4bd75" if (v in ["unique", "one", "few"] and i == 0) else "#a2c0ad",
                )
            if v == "perfect":
                p += text(180, 225, "✓ ✓ ✓", 23)
    elif kind == "direction":
        if v in ["inout", "reverse"]:
            p = (
                rect(103, 66, 156, 136, "#d5bb92")
                + circle(180, 128, 26, "#99b4c5")
                + circle(302, 174, 23, "#e1aa86")
            )
        elif v == "compass":
            p = (
                circle(180, 120, 80, "#fff9eb")
                + path("M180 51V190M110 120H250", width=4)
                + "".join(
                    text(x, y, t, 23)
                    for x, y, t in [
                        (180, 35, "北"),
                        (180, 224, "南"),
                        (70, 127, "西"),
                        (290, 127, "东"),
                    ]
                )
            )
        elif v == "center":
            p = circle(180, 120, 83, "#e4e7ce") + circle(180, 120, 24, "#e2ac7b")
        else:
            p = person(180, 132, scale=0.85)
            if v in ["leftright", "frontback"]:
                p += path(
                    "M40 118H110L93 102m17 16-17 16M320 118H250L267 102m-17 16 17 16",
                    stroke="#cd9f66",
                    width=5,
                )
            else:
                p += path("M285 188V54L269 72m16-18 16 18", stroke="#cd9f66", width=5)
    elif kind == "shape":
        if v == "curve":
            p = path("M45 182Q100 40 176 129Q255 212 315 54", stroke="#85ac9a", width=12)
        else:
            p = (
                rect(89, 35, 182, 174, "#b1c9b0", 2) + rect(125, 73, 110, 100, "#fff9e9", 2)
                if v == "space"
                else rect(95, 35, 170, 170, "#a5c1b5", 2)
            )
    elif kind == "shadow":
        p = (
            sun(290, 51)
            + '<ellipse cx="206" cy="207" rx="90" ry="17" fill="#b2b7a5"/>'
            + person(143, 136, scale=0.9)
        )
        if v == "movie":
            p = (
                rect(41, 26, 278, 162, "#dae2ce")
                + group(person(180, 130), 91, 26, 0.6)
                + path("M79 218v-24M153 218v-24M229 218v-24M301 218v-24", width=15)
            )
    elif kind == "number":
        n = int(v) if v.isdigit() else 10 if v == "ten" else 6 if v in ["each", "math"] else 1
        count = min(n, 80)
        cols = 10 if count > 15 else 5 if count > 5 else max(count, 1)
        r = 7 if count > 40 else 10 if count > 15 else 16
        for i in range(count):
            p += circle(
                180 - (cols - 1) * (2 * r + 7) / 2 + (i % cols) * (2 * r + 7),
                (45 if count > 40 else 75) + (i // cols) * (2 * r + 7),
                r,
                "#a8c1a1",
            )
        p += text(180, 221, "2 + 3 = 5" if v == "math" else str(n) if v.isdigit() else "一组", 30)
    else:
        raise ValueError(f"Unknown scene: {kind}/{v}")
    return p


def build():
    data = json.loads(CATALOG.read_text())
    OUT.mkdir(parents=True, exist_ok=True)
    for word, item in data["items"].items():
        body = scene(item["scene"], item["variant"])
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 360 240" role="img">'
            f"<title>{html.escape(word)}</title>"
            f"<desc>{html.escape(item['description'])}</desc>"
            "<!-- Original Love Pinyin vector illustration, MIT -->"
            '<rect width="360" height="240" rx="24" fill="#f8f5e9"/>'
            f"{body}</svg>\n"
        )
        item["sha256"] = hashlib.sha256(svg.encode()).hexdigest()
        destination = OUT / f"{item['id']}.svg"
        temporary = destination.with_suffix(".tmp")
        temporary.write_text(svg)
        temporary.replace(destination)
    temporary_catalog = CATALOG.with_suffix(".tmp")
    temporary_catalog.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    temporary_catalog.replace(CATALOG)
    print(f"Built {len(data['items'])} original local word illustrations")


if __name__ == "__main__":
    build()
