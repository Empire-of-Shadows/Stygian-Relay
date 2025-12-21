#!/usr/bin/env python3
"""
Minimal health check for StygianRelay Discord bot.
If this script runs, the container is healthy.
"""

import sys
import os

# Just check if we can access the /app directory
# If the container is running and we got this far, we're healthy
if os.path.exists('/app'):
    print("HEALTHY", flush=True)
    sys.exit(0)
else:
    print("UNHEALTHY", flush=True)
    sys.exit(1)
