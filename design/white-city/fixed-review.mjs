// Same normalized crop for both images. No retouching, independent zoom or camera motion.
const config=document.body.dataset.reviewConfig?await fetch(document.body.dataset.reviewConfig).then(r=>{if(!r.ok)throw Error('Review configuration unavailable');return r.json();}):{};
const review=document.createElement('section');review.className='review';review.hidden=true;
review.setAttribute('aria-label','固定机位环境与光照对照');
review.innerHTML=`<header class="review-head"><div><p class="review-kicker">NESTWISE / FIXED VIEW STUDY 02</p><h2 id="review-title"></h2><p class="review-intro" id="review-intro"></p></div><button class="review-close">返回真实模型 ↗</button></header>
<div class="review-options"><button data-layout="stack" aria-pressed="true">上下对照</button><button data-layout="wipe" aria-pressed="false">滑动对齐</button><label class="range-wrap" hidden>对照位置 <input type="range" min="0" max="100" value="50" aria-label="对照分界位置"></label></div>
<div id="review-stack"><figure><figcaption id="current-caption"></figcaption><div class="city-strip"><img id="review-current" alt="本轮固定机位模型的 Cycles 渲染"></div></figure><figure><figcaption id="other-caption"></figcaption><div class="city-strip"><img id="review-other"></div></figure></div>
<figure id="review-wipe" hidden><figcaption id="wipe-caption"></figcaption><div class="city-strip review-wipe"><img id="wipe-current" alt="本轮固定机位模型的 Cycles 渲染"><div class="upper"><img id="wipe-other"></div><div class="review-divider"></div></div></figure>
<div class="review-notes" id="review-notes"></div><p class="review-footnote">两幅图均展示原画面下方 44%，按同一比例显示。这里的模型图为真实场景的 Cycles 对照，网页三维效果请返回「真实模型」查看。布局仍在核对，尚未完成逐栋复刻。</p>`;
document.body.append(review);
const current=config.current??'./blender/renders/city-10-studio.png?v=2';
const modes={
 environment:{title:'先看环境，逐处对齐。',intro:'机位、建筑与树的位置保持上一版。用相同取景检查河湾、天际线与绿化的差距；本轮只调整材质和灯光。',other:'./assets/fixed-reference.png',label:'目标效果图',small:'原始参考 / 未作修饰',notes:[['01 / 河湾与前景','当前河湾较窄，前景弧形建筑露出的比例、桥与两岸的关系，还没有达到参考图的空间层次。'],['02 / 天际线与建筑','右高左低的大关系已建立；重点楼的体块、裙房和楼群疏密仍需逐栋校准，重复立面依然明显。'],['03 / 地形与绿化','当前地势偏平，背景山体与连贯的树群不足。原图右侧坡地和密集植被形成的层叠感尚未还原。']]},
 lighting:{title:'同一场景，只比较光照。',intro:'相机矩阵与模型顶点保持不变。重点看白色立面、屋檐暗部、河岸反光和室内暖光；上下图使用相同裁切。',other:'./blender/renders/city-09-fixed.png?v=7',label:'上一版 · 固定机位',small:'09 / Cycles 对照',notes:[['01 / 白色材质','区分粉白屋顶、缎面立面和较浅的窗洞；保持细微反射，减少大片灰色玻璃的厚重感。'],['02 / 光与影','调整侧向主光与背部轮廓光，保留立面的朝向差异。曝光保持不变，避免整幅简单提亮。'],['03 / 隐藏暖光','加强藏在檐口后的室内照明，光源本体保持隐藏。仍需以真实模型与 Cycles 的分别验收为准。']]}
};
Object.assign(modes,config.modes??{});
if(config.kicker)review.querySelector('.review-kicker').textContent=config.kicker;
let returnFocus=null;
function layout(mode){
 review.querySelector('#review-stack').hidden=mode!=='stack';review.querySelector('#review-wipe').hidden=mode!=='wipe';review.querySelector('.range-wrap').hidden=mode!=='wipe';
 for(const b of review.querySelectorAll('[data-layout]'))b.setAttribute('aria-pressed',String(b.dataset.layout===mode));
}
function open(kind){
 const d=modes[kind];returnFocus=document.activeElement;
 review.querySelector('#review-title').textContent=d.title;review.querySelector('#review-intro').textContent=d.intro;
 for(const id of ['review-current','wipe-current'])review.querySelector('#'+id).src=current;
 for(const id of ['review-other','wipe-other']){const img=review.querySelector('#'+id);img.src=d.other;img.alt=d.label;}
 review.querySelector('#current-caption').innerHTML=config.caption??'本轮 · 固定机位<span>10 / Cycles 对照</span>';
 review.querySelector('#other-caption').innerHTML=`${d.label}<span>${d.small}</span>`;
 review.querySelector('#wipe-caption').textContent=`左侧：${d.label}　/　右侧：本轮 Cycles`;
 review.querySelector('#review-notes').innerHTML=d.notes.map(([h,p])=>`<article><h3>${h}</h3><p>${p}</p></article>`).join('');
 review.dataset.kind=kind;review.hidden=false;review.scrollTop=0;layout('stack');
 document.querySelector('#stage').inert=true;document.querySelector('.toolbar').inert=true;document.querySelector('.status').hidden=true;
 review.querySelector('.review-close').focus();
}
function close(){review.hidden=true;document.querySelector('#stage').inert=false;document.querySelector('.toolbar').inert=false;document.querySelector('.status').hidden=false;document.querySelector('[data-mode="live"]').click();returnFocus?.focus();}
review.querySelector('.review-close').addEventListener('click',close);
review.addEventListener('keydown',e=>{if(e.key==='Escape')close();});
for(const b of review.querySelectorAll('[data-layout]'))b.addEventListener('click',()=>layout(b.dataset.layout));
review.querySelector('input').addEventListener('input',e=>review.querySelector('.review-wipe').style.setProperty('--split',e.target.value+'%'));
document.querySelector('#environment-review').addEventListener('click',()=>open('environment'));
document.querySelector('#lighting-review').addEventListener('click',()=>open('lighting'));
if(new URLSearchParams(location.search).get('view')==='environment')open('environment');
