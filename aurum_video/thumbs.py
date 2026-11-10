"""thumbs: 3 variants, 1280x720 PNG < 2 MB, from the Remotion 'Thumb' template (<= 4 words)."""
from __future__ import annotations

from .common import ROOT, PhaseError, load_json, run, save_json
from .maps import map_for_slug
from .render import remotion_common

MAX_BYTES = 2 * 1024 * 1024


def word_count(text: str) -> int:
    return len(text.replace("\n", " ").split())


def shrink_png(path) -> None:
    from PIL import Image

    if path.stat().st_size < MAX_BYTES:
        return
    img = Image.open(path).convert("RGB")
    img.quantize(colors=256, method=Image.Quantize.MEDIANCUT).save(path, optimize=True)


def run_phase(ctx) -> dict:
    meta = load_json(ctx.paths.video / "video.json")
    texts = meta["thumbnails"]
    if len(texts) != 3:
        raise PhaseError("video.json needs exactly 3 thumbnail texts")
    for t in texts:
        if word_count(t["text"]) + word_count(t.get("kicker", "")) > 4:
            raise PhaseError(f"thumbnail text over 4 words: {t['text']!r}")
    map_data = map_for_slug(ctx.paths.video)
    out = []
    for i, t in enumerate(texts, 1):
        props = ctx.paths.build / f"thumb-{i}.json"
        save_json(props, {"variant": i, "text": t["text"], "kicker": t.get("kicker", ""), "focus": t.get("focus"),
                          "map": map_data, "brand": "AURUM TRANSFERS"})
        png = ctx.paths.out / f"thumb-{i}.png"
        run(["npx", "remotion", "still", "src/index.ts", "Thumb", str(png), f"--props={props}",
             "--image-format=png", "--log=warn", *remotion_common(ctx)], cwd=ROOT / "remotion")
        shrink_png(png)
        out.append(str(png.relative_to(ROOT)))
    return {"thumbnails": out}
