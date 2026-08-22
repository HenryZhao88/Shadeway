"""Pure functions: geometry and weather in, degrees out.

NOTHING in this package may touch the filesystem, the network, or the clock.
`contracts/tests/test_layering.py` enforces that. Weather IO lives one level up
at shadeway/weather.py.
"""
