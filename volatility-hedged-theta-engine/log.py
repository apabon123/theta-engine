"""
Lightweight logging helpers.
"""

def info(algo, msg: str):
    algo.Log(msg)

def debug(algo, msg: str):
    if getattr(algo, 'debug_mode', False):
        algo.Debug(msg)


