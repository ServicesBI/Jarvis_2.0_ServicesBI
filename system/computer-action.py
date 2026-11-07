# -*- coding: utf-8 -*-
"""Execute mouse/keyboard action. Usage: python computer-action.py <json_args>"""
import sys, json
import pyautogui

pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.05

try:
    args = json.loads(sys.argv[1])
    action = args.get('action', '')

    if action == 'click':
        pyautogui.click(args['x'], args['y'], clicks=args.get('clicks', 1), button=args.get('button', 'left'))
    elif action == 'doubleclick':
        pyautogui.doubleClick(args['x'], args['y'])
    elif action == 'rightclick':
        pyautogui.rightClick(args['x'], args['y'])
    elif action == 'move':
        pyautogui.moveTo(args['x'], args['y'], duration=0.3)
    elif action == 'type':
        # Unicode-safe: copy to clipboard then paste
        import subprocess
        subprocess.run(['clip'], input=args.get('text', '').encode('utf-16-le'), check=True)
        pyautogui.hotkey('ctrl', 'v')
    elif action == 'hotkey':
        keys = [k.strip() for k in args.get('key', '').split('+')]
        pyautogui.hotkey(*keys)
    elif action == 'press':
        pyautogui.press(args.get('key', 'enter'))
    elif action == 'scroll':
        pyautogui.scroll(args.get('y', 3))
    elif action == 'drag':
        pyautogui.moveTo(args['x'], args['y'])
        pyautogui.drag(args['toX'] - args['x'], args['toY'] - args['y'], duration=0.5)
    else:
        print(json.dumps({"error": f"Unknown action: {action}"}))
        sys.exit(1)

    print(json.dumps({"success": True, "action": action}))

except (json.JSONDecodeError, IndexError) as e:
    print(json.dumps({"error": f"Invalid input: {e}"}))
    sys.exit(1)
except KeyError as e:
    print(json.dumps({"error": f"Missing required field: {e}"}))
    sys.exit(1)
except UnicodeDecodeError as e:
    print(json.dumps({"error": f"Encoding error: {e}"}))
    sys.exit(1)
except Exception as e:
    print(json.dumps({"error": f"{type(e).__name__}: {e}"}))
    sys.exit(1)
