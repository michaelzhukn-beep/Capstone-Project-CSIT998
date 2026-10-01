"""Read-only image statistics for a declared city ROI; not a similarity percentage."""
from pathlib import Path
import json,sys
import numpy as np
from PIL import Image
ROOT=Path(__file__).resolve().parent
def measure(path):
    a=np.asarray(Image.open(path).convert('RGBA'),dtype=np.float64)/255
    # Numerically composite alpha for measurement only; no edited raster is written.
    rgb=a[:,:,:3]*a[:,:,3:]+np.array([250,249,246])/255*(1-a[:,:,3:])
    h,w=rgb.shape[:2];p=rgb[int(.78*h):int(.91*h),int(.03*w):int(.97*w)]
    l=p@np.array([.2126,.7152,.0722])*255
    return dict(size=[w,h],luma_p10_p50_p90=np.percentile(l,[10,50,90]).round(3).tolist(),
                mean_R_minus_B=round(float(((p[:,:,0]-p[:,:,2])*255).mean()),3),
                near_white_fraction=round(float((p.min(axis=2)>.985).mean()),5))
stem='city-10-studio' if '--studio' in sys.argv else 'city-09-fixed'
report=dict(roi_normalized=[.03,.78,.97,.91],reference=measure(ROOT.parent/'assets/fixed-reference.png'),
    cycles=measure(ROOT/('renders/'+stem+'.png')),
    interpretation='Measures gross brightness and warmth only. Different geometry and local shadows remain; no visual-match score and no browser equivalence claim.')
(ROOT/('city-10-reference-tones.json' if '--studio' in sys.argv else 'city-09-reference-tones.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
