"""Capture screen region around cursor position.
Captures a 800x600 area centered on the mouse cursor for focused analysis.
Usage: python screenshot-cursor.py [crop_size]
"""
import sys, mss, base64, io, json, ctypes

# Get cursor position
class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

pt = POINT()
ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
cx, cy = pt.x, pt.y

crop_w = int(sys.argv[1]) if len(sys.argv) > 1 else 800
crop_h = int(crop_w * 0.75)  # 4:3 ratio

with mss.mss() as sct:
    # Find which monitor the cursor is on
    for i, m in enumerate(sct.monitors):
        if i == 0: continue
        if m["left"] <= cx < m["left"] + m["width"] and m["top"] <= cy < m["top"] + m["height"]:
            # Crop region centered on cursor
            left = max(m["left"], cx - crop_w // 2)
            top = max(m["top"], cy - crop_h // 2)
            right = min(m["left"] + m["width"], left + crop_w)
            bottom = min(m["top"] + m["height"], top + crop_h)

            region = {"left": left, "top": top, "width": right - left, "height": bottom - top}
            shot = sct.grab(region)

            from PIL import Image, ImageDraw
            img = Image.frombytes('RGB', (shot.width, shot.height), shot.rgb)

            # Draw crosshair at cursor position (relative to crop)
            draw = ImageDraw.Draw(img)
            rel_x = cx - left
            rel_y = cy - top
            cross_size = 15
            cross_color = (255, 50, 50)
            draw.line([(rel_x - cross_size, rel_y), (rel_x + cross_size, rel_y)], fill=cross_color, width=2)
            draw.line([(rel_x, rel_y - cross_size), (rel_x, rel_y + cross_size)], fill=cross_color, width=2)
            draw.ellipse([(rel_x - 5, rel_y - 5), (rel_x + 5, rel_y + 5)], outline=cross_color, width=2)

            buf = io.BytesIO()
            img.save(buf, format='JPEG', quality=85)
            b64 = base64.b64encode(buf.getvalue()).decode()

            print(json.dumps({
                "cursor_x": cx, "cursor_y": cy,
                "monitor": i,
                "crop": {"left": left, "top": top, "width": right - left, "height": bottom - top},
                "width": shot.width, "height": shot.height,
                "data": "data:image/jpeg;base64," + b64
            }))
            sys.exit(0)

    # Fallback: cursor not found on any monitor
    print(json.dumps({"error": "Cursor not found on any monitor"}))
