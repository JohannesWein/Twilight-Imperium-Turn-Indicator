import json, subprocess, sys
seed = sys.argv[1]
cmd = [sys.executable, r"c:\Git\Twilight-Imperium-Turn-Indicator\Versuch3\live_random_flow_check.py", "--broker-host", "192.168.178.141", "--broker-port", "1883", "--seed", str(seed)]
result = {"seed": int(seed), "timeout": False, "exit_code": None, "stdout": "", "stderr": ""}
try:
    cp = subprocess.run(cmd, capture_output=True, text=True, timeout=360)
    result["exit_code"] = cp.returncode
    result["stdout"] = cp.stdout
    result["stderr"] = cp.stderr
except subprocess.TimeoutExpired as e:
    result["timeout"] = True
    result["exit_code"] = "TIMEOUT"
    result["stdout"] = e.stdout or ""
    result["stderr"] = e.stderr or ""
print(json.dumps(result))
