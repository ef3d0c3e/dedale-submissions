from collections import deque

import numpy as np

import dedale
from dedale import Move

NAME = "Clusters"
AUTHOR = "ef3d0c3e"
DESCRIPTION = "Heads for clusters of points, leaving the ones the opponent reaches first"
VERSION = 1

DECAY = 0.3  # Heat kept per step away from a point: it spreads about 1 / (1 - DECAY) steps
BLUR_PASSES = 20  # Enough passes for the heat to settle
HEAT_WEIGHT = 0.5  # Steps of detour one unit of heat is worth (0 = plain greedy)
HEAT_COLORS = ["blue", "teal", "green", "yellow", "orange", "red"]  # Cold to hot

KERNEL = np.array([[0, 1, 0],
                   [1, 1, 1],
                   [0, 1, 0]])  # A cell and its 4 neighbours

open_cells = None  # 1.0 on open cells, 0.0 on walls, indexed [y, x]
open_counts = None  # How many open cells each kernel covers


def init():
    global open_cells, open_counts
    open_cells = np.array([[float(dedale.maze.is_open(x, y)) for x in range(dedale.maze.width)]
                           for y in range(dedale.maze.height)])
    open_counts = np.maximum(convolve(open_cells, KERNEL), 1)


def convolve(grid, kernel):
    h, w = grid.shape
    padded = np.pad(grid, 1)
    return sum(kernel[dy, dx] * padded[dy:dy + h, dx:dx + w]
               for dy in range(3) for dx in range(3) if kernel[dy, dx])


# Compute heatmap: points clustered get high value, while the opponent lowers the value of cells around it
def heatmap(points):
    source = np.zeros_like(open_cells)
    if dedale.opponent != None:
        source[dedale.opponent.pos[1], dedale.opponent.pos[0]] = -1.0
        for _ in range(3):
            source = convolve(source, KERNEL)
    for x, y in points:
        source[y, x] = source[y, x] + 1.0

    heat = source
    for _ in range(BLUR_PASSES):
        heat = source + DECAY * open_cells * convolve(heat, KERNEL) / open_counts
    return heat


# Color cells based on their heatmap-assigned values
def mark_heatmap(heat):
    ys, xs = np.nonzero((heat >= 0.01) & (open_cells > 0))
    order = np.argsort(heat[ys, xs])
    for color, band in zip(HEAT_COLORS, np.array_split(order, len(HEAT_COLORS))):
        if len(band):
            low, high = heat[ys[band[0]], xs[band[0]]], heat[ys[band[-1]], xs[band[-1]]]
            dedale.mark(zip(xs[band].tolist(), ys[band].tolist()), label=f"heat {low:.2g}-{high:.2g}",
                        color=color)


def distances(start):
    steps = {start: 0}
    parent = {start: None}
    queue = deque([start])
    while queue:
        cell = queue.popleft()
        for _, next_cell in dedale.maze.neighbors(*cell):
            if next_cell not in steps:
                steps[next_cell] = steps[cell] + 1
                parent[next_cell] = cell
                queue.append(next_cell)
    return steps, parent


def path_to(cell, parent):
    path = []
    while cell is not None:
        path.append(cell)
        cell = parent[cell]
    return path[::-1]


def move():
    mine, parent = distances(dedale.me.pos)
    reachable = [p for p in dedale.points if p in mine]
    if not reachable:
        return Move.STAY
    heat = heatmap(dedale.points)
    mark_heatmap(heat)

    # Avoid the opponent: leave it the points it reaches first, unless that is all of them.
    if dedale.opponent is not None:
        theirs, _ = distances(dedale.opponent.pos)
        ours = [p for p in reachable if mine[p] <= theirs.get(p, float("inf"))]
        if ours:
            reachable = ours

    # Nearest point, with heat taking steps off the ones in a cluster.
    target = min(reachable, key=lambda p: mine[p] - HEAT_WEIGHT * heat[p[1], p[0]])
    path = path_to(target, parent)
    dedale.path(path, label="target", color="pink")
    if len(path) < 2:
        return Move.STAY
    return next(step for step, cell in dedale.maze.neighbors(*dedale.me.pos) if cell == path[1])
