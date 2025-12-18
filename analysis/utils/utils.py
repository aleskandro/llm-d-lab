
def step_to_xperiod(step: str) -> int:
    units = {
        "s": 1000,
        "m": 60_000,
        "h": 3_600_000,
        "d": 86_400_000,
    }
    value, unit = int(step[:-1]), step[-1]
    return value * units[unit]

def hex_with_opacity(hex_color: str, alpha: float) -> str:
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"

def luminance(rgb):
    # rgb in [0, 1]
    r, g, b = rgb[:3]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b

