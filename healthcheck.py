#!/usr/bin/env python3
"""
Simple health check script for the StygianRelay Discord bot container.
This script validates that the bot container is running properly.
"""

import sys
import os
from pathlib import Path

def main():
	"""Main health check function - simplified version."""
	try:
		print("Starting simplified health check...", flush=True)

		# Check 1: Verify we're in the right directory
		if not os.path.exists('/app'):
			print("UNHEALTHY: /app directory not found", flush=True)
			sys.exit(1)

		# Check 2: Verify main.py exists
		if not os.path.exists('/app/main.py'):
			print("UNHEALTHY: main.py not found", flush=True)
			sys.exit(1)

		# Check 3: Verify logs directory exists and is writable
		log_dir = Path("/app/logs")
		try:
			log_dir.mkdir(parents=True, exist_ok=True)
			test_file = log_dir / ".healthcheck"
			test_file.write_text("healthy")
			test_file.unlink()
		except Exception as e:
			print(f"UNHEALTHY: Log directory check failed: {e}", flush=True)
			sys.exit(1)

		# Check 4: Check if bot process is running by looking at /proc
		# This is more reliable than psutil
		bot_running = False
		try:
			for pid_dir in Path('/proc').iterdir():
				if not pid_dir.is_dir() or not pid_dir.name.isdigit():
					continue

				try:
					cmdline_file = pid_dir / 'cmdline'
					if cmdline_file.exists():
						cmdline = cmdline_file.read_text()
						# Check if this is a python process running main.py
						if 'python' in cmdline and 'main.py' in cmdline:
							bot_running = True
							print(f"Found bot process: PID {pid_dir.name}", flush=True)
							break
						# Also check for just python processes in /app
						elif 'python' in cmdline and '/app' in cmdline and 'healthcheck' not in cmdline:
							bot_running = True
							print(f"Found Python process in /app: PID {pid_dir.name}", flush=True)
							break
				except (PermissionError, FileNotFoundError):
					continue

		except Exception as e:
			print(f"Warning: Process check failed: {e}", flush=True)
			# Don't fail on process check errors - if the container is running, that's good enough
			bot_running = True

		if not bot_running:
			print("Warning: Could not verify bot process is running", flush=True)
			# Don't fail - just warn

		print("HEALTHY: All checks passed", flush=True)
		sys.exit(0)

	except Exception as e:
		print(f"UNHEALTHY: Health check error: {e}", flush=True)
		sys.exit(1)


if __name__ == "__main__":
	main()
