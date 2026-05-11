import uharfbuzz as hb
import freetype

ft_face = freetype.Face("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
with open("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "rb") as f:
    fontdata = f.read()
hb_face = hb.Face(fontdata)
hb_font = hb.Font(hb_face)

text = "مرحبا" # Arabic RTL
buf = hb.Buffer()
buf.add_str(text)
buf.guess_segment_properties()
buf.direction = "rtl"

hb_font.scale = (72, 72)
hb.shape(hb_font, buf)

infos = buf.glyph_infos
positions = buf.glyph_positions

current_x = 0
for info, pos in zip(infos, positions):
    print(f"glyph: {info.codepoint}, x_adv: {pos.x_advance}, x_off: {pos.x_offset}")
    current_x += pos.x_advance
print(f"Total width: {current_x}")
