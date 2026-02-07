import base64, sys
b64 = sys.stdin.read().strip()
with open(r"C:\BoundState\scripts\compare_miul.py", "wb") as f:
    f.write(base64.b64decode(b64))
print("Written.")
