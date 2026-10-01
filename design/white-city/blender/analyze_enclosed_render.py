"""Read-only comparison of matched opaque pixels in the same camera Cycles views."""
from pathlib import Path
import json
import numpy as np
from PIL import Image
root=Path(__file__).resolve().parent
before=np.array(Image.open(root/'renders/city-07-studio.png').convert('RGBA'))
after=np.array(Image.open(root/'renders/city-08-enclosed.png').convert('RGBA'))
assert before.shape==after.shape
mask=(before[:,:,3]>250)&(after[:,:,3]>250)
mask[:int(mask.shape[0]*.2),:]=False
def metrics(data):
    rgb=data[:,:,:3][mask].astype(float);luma=rgb@np.array([.2126,.7152,.0722])
    return dict(luminance_percentiles_8bit=[round(float(x),2) for x in np.percentile(luma,[10,50,90])],
                fully_clipped_white_pct=round(float(np.mean(np.all(rgb>=254,axis=1))*100),4))
result=dict(method='Same-camera intersected opaque pixels, top 20% excluded. Read-only luminance analysis; not a visual acceptance metric.',
            sampled_pixels=int(mask.sum()),before=metrics(before),after=metrics(after))
(root/'city-08-tonal-review.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps(result))
