"""Capture screen and output as base64 JSON.
Usage:
  python screenshot.py          → monitor 1 (primary)
  python screenshot.py 1        → monitor 1
  python screenshot.py 2        → monitor 2
  python screenshot.py all      → all monitors stitched side by side
  python screenshot.py info     → list monitors (no capture)
"""
import sys, mss, base64, io, json
from PIL import Image

mode = sys.argv[1] if len(sys.argv) > 1 else '1'

with mss.mss() as sct:
    monitors = sct.monitors  # [0] = virtual (all), [1] = primary, [2+] = others

    if mode == 'info':
        # Return monitor info without capturing
        info = []
        for i, m in enumerate(monitors):
            if i == 0: continue  # skip virtual
            info.append({"monitor": i, "left": m["left"], "top": m["top"], "width": m["width"], "height": m["height"]})
        print(json.dumps({"monitors": info, "count": len(monitors) - 1}))
        sys.exit(0)

    if mode == 'all':
        # Capture all monitors stitched horizontally
        imgs = []
        total_w = 0
        max_h = 0
        for i in range(1, len(monitors)):
            shot = sct.grab(monitors[i])
            img = Image.frombytes('RGB', (shot.width, shot.height), shot.rgb)
            imgs.append(img)
            total_w += shot.width
            max_h = max(max_h, shot.height)

        if not imgs:
            print(json.dumps({"error": "No monitors found"}))
            sys.exit(1)

        # Stitch side by side
        stitched = Image.new('RGB', (total_w, max_h), (0, 0, 0))
        x_offset = 0
        for img in imgs:
            stitched.paste(img, (x_offset, 0))
            x_offset += img.width

        # Add monitor labels
        from PIL import ImageDraw, ImageFont
        draw = ImageDraw.Draw(stitched)
        x_offset = 0
        for i, img in enumerate(imgs):
            label = f"Monitor {i+1}"
            draw.rectangle([x_offset, 0, x_offset + 120, 25], fill=(0, 0, 0))
            draw.text((x_offset + 5, 5), label, fill=(0, 228, 255))
            # Draw separator line
            if i > 0:
                draw.line([(x_offset, 0), (x_offset, max_h)], fill=(0, 228, 255), width=2)
            x_offset += img.width

        # Resize if too large
        if total_w > 3840:
            ratio = 3840 / total_w
            stitched = stitched.resize((3840, int(max_h * ratio)), Image.LANCZOS)

        buf = io.BytesIO()
        stitched.save(buf, format='JPEG', quality=75)
        b64 = base64.b64encode(buf.getvalue()).decode()
        print(json.dumps({
            "width": stitched.width,
            "height": stitched.height,
            "monitors": len(imgs),
            "data": "data:image/jpeg;base64," + b64
        }))
    else:
        # Single monitor
        idx = int(mode)
        idx = min(idx, len(monitors) - 1)
        idx = max(idx, 1)
        shot = sct.grab(monitors[idx])
        img = Image.frombytes('RGB', (shot.width, shot.height), shot.rgb)
        img.thumbnail((1920, 1080), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=75)
        b64 = base64.b64encode(buf.getvalue()).decode()
        print(json.dumps({"width": shot.width, "height": shot.height, "monitor": idx, "data": "data:image/jpeg;base64," + b64}))
