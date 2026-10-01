"""Cut a figure out of a plate drawn on a flat background (rembg isnet-anime, then the fringe and specks cleaned).
Taken from towerD's Tools/art/grok/heroine_process.py (2026-10-02): only the cutout, which key_poses.py pick and
live_layers.py scene use. Needs rembg (it downloads the isnet-anime model on first use, about 170 MB).

    import cutout
    rgb, alpha, rgba = cutout.cutout(Image.open("plate.png"))
"""
import numpy as np
from PIL import Image
from scipy import ndimage

_SESSION = None


def get_session():
    global _SESSION
    if _SESSION is None:
        from rembg import new_session
        _SESSION = new_session("isnet-anime")
    return _SESSION


def _bg_color(rgb):
    """Median corner colour of a flat-background plate."""
    h, w = rgb.shape[:2]
    s = max(4, min(12, h // 20, w // 20))
    corners = np.concatenate([
        rgb[:s, :s].reshape(-1, 3),
        rgb[:s, -s:].reshape(-1, 3),
        rgb[-s:, :s].reshape(-1, 3),
        rgb[-s:, -s:].reshape(-1, 3),
    ]).astype(np.float32)
    return np.median(corners, axis=0)


def _saturation(rgb):
    mx = rgb.max(axis=2)
    mn = rgb.min(axis=2)
    return mx - mn


def clean_alpha(rgba, plate=None):
    """Drop the grey matte fringe rembg leaves, and floating specks.

    Edge pixels are a mix of the figure and the flat grey plate. Mask the contaminated band, then refill its
    colour from the neighbouring solid figure (nearest interior pixel) and
    zero alpha that is still just background. Small components that do not
    touch the body are discarded; a prop that merely sits a short gap away
    (staff orb, bow tip) is kept.
    """
    arr = np.asarray(rgba).astype(np.float32)
    rgb = arr[..., :3].copy()
    a = arr[..., 3].copy()
    alpha = np.clip(a / 255.0, 0.0, 1.0)
    transparent = a < 6
    if transparent.any():
        mean_t = float(rgb[transparent].mean())
        bg = np.median(rgb[transparent], axis=0) if mean_t > 15 else _bg_color(rgb)
    else:
        mean_t = 255.0
        bg = _bg_color(rgb)

    partial = (a >= 6) & (a < 248)
    if mean_t < 15:
        # rembg wrote premultiplied / black-filled RGB on the soft edge
        fg = rgb / np.maximum(alpha[..., None], 0.08)
    else:
        fg = (rgb - bg * (1.0 - alpha[..., None])) / np.maximum(alpha[..., None], 0.08)
    rgb[partial] = np.clip(fg[partial], 0, 255)

    opaque = a > 248
    interior = ndimage.binary_erosion(opaque, iterations=2) if opaque.any() else opaque
    if interior.any():
        dist, indices = ndimage.distance_transform_edt(~interior, return_indices=True)
        fringe = (opaque | partial) & ~interior & (dist <= 4)
        rgb[fringe] = rgb[indices[0][fringe], indices[1][fringe]]

    # soft matte only: never punch out solid pale hair (Yukino) just because
    # it sits near the grey plate
    dist_bg = np.linalg.norm(rgb - bg, axis=2)
    sat = _saturation(rgb)
    grey_edge = (a < 180) & (dist_bg < 24) & (sat < 18)
    a[grey_edge] = 0
    # solid patches of the flat plate that rembg kept (between a bow and its string): a large connected
    # area whose plate colour is the background itself is not the figure
    if plate is not None:
        prgb = np.asarray(plate, dtype=np.float32)[..., :3]
        pbg = _bg_color(prgb)
        flat = (a > 0) & (np.linalg.norm(prgb - pbg, axis=2) < 10) & (_saturation(prgb) < 8)
        lab, n = ndimage.label(flat)
        if n:
            sizes = ndimage.sum(np.ones(a.shape, np.float32), lab, range(1, n + 1))
            big = np.zeros(n + 1, dtype=bool)
            big[1:] = sizes > 300
            a[big[lab]] = 0
    a[a < 12] = 0

    # saturated glow rembg punches out, but only next to the body (fire orb),
    # not a full-silhouette aura
    near = ndimage.binary_dilation(a > 200, iterations=10)
    glow = near & (a > 8) & (a < 200) & (dist_bg > 42) & (sat > 50)
    a[glow] = np.maximum(a[glow], np.clip((dist_bg[glow] - 30) * 3.5, 0, 255))

    a = _keep_body_components(a)
    a, filled = _fill_pinholes(a, plate, _bg_color(np.asarray(plate, np.float32)[..., :3]) if plate is not None else None)
    if plate is not None and filled.any():
        # rembg zeroes RGB where it cut the matte, so refill from the plate, not black
        rgb[filled] = np.asarray(plate, dtype=np.float32)[..., :3][filled]

    out = np.zeros_like(arr)
    out[..., :3] = np.clip(rgb, 0, 255)
    out[..., 3] = np.clip(a, 0, 255)
    # fully transparent pixels carry no colour, so they cannot halo later
    out[out[..., 3] < 12, :3] = 0
    out[out[..., 3] < 12, 3] = 0
    return out.astype(np.uint8)


def _keep_body_components(a):
    mask = a > 24
    lab, n = ndimage.label(mask)
    if n <= 1:
        return a
    sizes = ndimage.sum(np.ones_like(a, dtype=np.float32), lab, range(1, n + 1))
    main_id = int(np.argmax(sizes)) + 1
    main = lab == main_id
    near = ndimage.binary_dilation(main, iterations=28)
    keep = np.zeros(n + 1, dtype=bool)
    keep[main_id] = True
    for i, sz in enumerate(sizes):
        comp = lab == (i + 1)
        if sz >= sizes.max() * 0.012 or (comp & near).any():
            keep[i + 1] = True
    drop = (lab > 0) & ~keep[lab]
    a = a.copy()
    a[drop] = 0
    return a


def _fill_pinholes(a, plate=None, bg=None):
    """Close small holes inside the silhouette. A hole whose plate pixels are
    mostly the flat grey background is a real gap (between ponytail strands,
    under an arm) and stays transparent; filling it used to paint an opaque
    black blob because rembg leaves RGB = 0 there."""
    solid = a > 32
    holes = ndimage.binary_fill_holes(solid) & ~solid
    lab, n = ndimage.label(holes)
    filled = np.zeros(a.shape, dtype=bool)
    if n == 0:
        return a, filled
    sizes = ndimage.sum(np.ones(a.shape, np.float32), lab, range(1, n + 1))
    a = a.copy()
    if plate is not None:
        prgb = np.asarray(plate, dtype=np.float32)[..., :3]
        bgish = (np.linalg.norm(prgb - np.asarray(bg, np.float32), axis=2) < 24) & (_saturation(prgb) < 18)
    for i, sz in enumerate(sizes):
        if sz > 800:
            continue
        comp = lab == (i + 1)
        if plate is not None and sz > 24 and bgish[comp].mean() > 0.5:
            continue
        a[comp] = 255
        filled |= comp
    return a, filled


def cutout(rgb_img, session=None):
    """RGB plate -> (rgb uint8, alpha uint8, rgba image). Alpha matches rgb."""
    from rembg import remove
    session = session or get_session()
    rgba = remove(rgb_img.convert("RGB"), session=session)
    if rgba.mode != "RGBA":
        rgba = rgba.convert("RGBA")
    cleaned = clean_alpha(np.asarray(rgba), np.asarray(rgb_img.convert("RGB")))
    return cleaned[..., :3], cleaned[..., 3], Image.fromarray(cleaned, "RGBA")
