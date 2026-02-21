import math
import time
from PySide6.QtCore import QObject


def _lung_outline():
    """Generate a closed lung-shaped outline as (x, y) coordinate lists.

    The shape traces: right lung top -> right lung outer -> bottom ->
    left lung outer -> left lung top -> back to start via the trachea.
    Coordinates are normalized to fit within [-1, 1].
    """
    pts = []

    # Trachea top center
    pts.append((0.0, 0.95))

    # Right side of trachea down
    pts.append((0.06, 0.95))
    pts.append((0.06, 0.55))

    # Right bronchus flare out
    pts.append((0.15, 0.45))
    pts.append((0.30, 0.38))

    # Right lung dome (top of right lung)
    pts.append((0.50, 0.50))
    pts.append((0.68, 0.55))
    pts.append((0.78, 0.45))

    # Right lung outer curve down
    pts.append((0.82, 0.30))
    pts.append((0.84, 0.10))
    pts.append((0.82, -0.10))
    pts.append((0.78, -0.30))
    pts.append((0.70, -0.50))

    # Right lung base
    pts.append((0.55, -0.65))
    pts.append((0.35, -0.72))
    pts.append((0.15, -0.68))

    # Diaphragm center
    pts.append((0.06, -0.55))
    pts.append((0.0, -0.50))
    pts.append((-0.06, -0.55))

    # Left lung base
    pts.append((-0.15, -0.68))
    pts.append((-0.35, -0.72))
    pts.append((-0.55, -0.65))

    # Left lung outer curve up
    pts.append((-0.70, -0.50))
    pts.append((-0.78, -0.30))
    pts.append((-0.82, -0.10))
    pts.append((-0.84, 0.10))
    pts.append((-0.82, 0.30))
    pts.append((-0.78, 0.45))

    # Left lung dome
    pts.append((-0.68, 0.55))
    pts.append((-0.50, 0.50))

    # Left bronchus back to trachea
    pts.append((-0.30, 0.38))
    pts.append((-0.15, 0.45))
    pts.append((-0.06, 0.55))

    # Left side of trachea up
    pts.append((-0.06, 0.95))

    # Close at top
    pts.append((0.0, 0.95))

    x_coords = [p[0] for p in pts]
    y_coords = [p[1] for p in pts]
    return x_coords, y_coords


class Pacer(QObject):
    def __init__(self):
        super().__init__()

        self.lung_x, self.lung_y = _lung_outline()
        self.n_points = len(self.lung_x)

    def breathing_pattern(self, breathing_rate: float, time: float) -> float:
        return 0.5 + 0.5 * math.sin(2 * math.pi * breathing_rate / 60 * time)

    def update(self, breathing_rate: float) -> tuple[list[float], list[float]]:
        radius = self.breathing_pattern(breathing_rate, time.time())
        x: list[float] = [i * radius for i in self.lung_x]
        y: list[float] = [i * radius for i in self.lung_y]
        return (x, y)
