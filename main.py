#!/usr/bin/env python3
"""
FAULTY TEST CODE - Will crash immediately if Railway updates
"""

import os
import logging

# Intentional syntax error - missing quote
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN)

# This won't even run
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    logger.info("This will never print")

if __name__ == "__main__":
    main()
