#!/usr/bin/env python3
"""The common native-API fixture with vLLM's no-upstream-credential contract."""
import os
import sys
import threading

sys.path.insert(0, '/fixtures')
from provider import Provider

fixture = Provider(host='0.0.0.0', local=True)
if 'MOCK_STREAM_DELAY' in os.environ:
    fixture.mode = 'delayed'
    fixture.delay = float(os.environ['MOCK_STREAM_DELAY'])
fixture.start()
threading.Event().wait()
