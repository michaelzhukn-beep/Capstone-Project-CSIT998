"""Pack the continuous Cycles shadow alpha losslessly for the showroom shader."""
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
source = ROOT / 'design/white-city/bake-v28/layer-shadow-house-clean.png'
target = ROOT / 'app/web/showroom/floor-shadow-house-clean.webp'
alpha = Image.open(source).convert('RGBA').getchannel('A')
assert alpha.getextrema()[0] == 0 and alpha.getextrema()[1] > 0, 'Shadow receiver must have a transparent background'
packed = Image.new('RGBA', alpha.size, (0, 0, 0, 0))
packed.putalpha(alpha)
packed.save(target, lossless=True, method=6)
assert Image.open(target).convert('RGBA').getchannel('A').tobytes() == alpha.tobytes()
print('CLEAN_SHADOW_PACKED', alpha.size, target.stat().st_size, target)
