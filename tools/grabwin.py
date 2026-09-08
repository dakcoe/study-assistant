"""주어진 PID의 창만 골라 찍는다 (시스템 python3의 Quartz 사용)."""
import subprocess, sys
import Quartz

pid, out = int(sys.argv[1]), sys.argv[2]
wins = Quartz.CGWindowListCopyWindowInfo(
    Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
    Quartz.kCGNullWindowID)
cand = [w for w in wins if w.get("kCGWindowOwnerPID") == pid
        and w.get("kCGWindowBounds", {}).get("Width", 0) > 50]
if not cand:
    sys.exit(f"pid {pid} 창을 못 찾음")
wid = cand[0]["kCGWindowNumber"]
subprocess.run(["screencapture", "-x", "-o", "-l", str(wid), out], check=True)
print("captured window", wid)
