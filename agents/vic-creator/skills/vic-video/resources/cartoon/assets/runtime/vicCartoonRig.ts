import type {Ctx,Env} from './core';
type Bounds={x:number,y:number,w:number,h:number,label:string};
let auditFrame=-1,actors:Bounds[]=[],words:Bounds[]=[];
function bounds(c:Ctx,x:number,y:number,w:number,h:number,label:string):Bounds{const m=c.getTransform(),ps=[[x,y],[x+w,y],[x,y+h],[x+w,y+h]].map(([xx,yy])=>({x:m.a*xx+m.c*yy+m.e,y:m.b*xx+m.d*yy+m.f}));const xs=ps.map(p=>p.x),ys=ps.map(p=>p.y);return {x:Math.min(...xs),y:Math.min(...ys),w:Math.max(...xs)-Math.min(...xs),h:Math.max(...ys)-Math.min(...ys),label}}
export function beginLayoutAudit(frame:number){auditFrame=frame;actors=[];words=[];}
export function finishLayoutAudit(){for(const a of actors)for(const w of words){const dx=Math.min(a.x+a.w,w.x+w.w)-Math.max(a.x,w.x),dy=Math.min(a.y+a.h,w.y+w.h)-Math.max(a.y,w.y);if(dx>4&&dy>4)throw new Error(`Text/actor overlap at frame ${auditFrame}: ${a.label} / ${w.label}`);}}
const ease=(v:number)=>{v=Math.max(0,Math.min(1,v));return v*v*(3-2*v)};
function box(c:Ctx,x:number,y:number,w:number,h:number,col:string,r=18){c.fillStyle=col;c.strokeStyle='#474B60';c.lineWidth=3;c.beginPath();c.roundRect(x,y,w,h,r);c.fill();c.stroke()}
function text(c:Ctx,s:string,x:number,y:number,size=30){c.fillStyle='#343A50';c.font=`600 ${size}px VICMyanmar,Arial,sans-serif`;c.textAlign='center';c.fillText(s,x,y);const m=c.measureText(s);words.push(bounds(c,x-m.width/2,y-m.actualBoundingBoxAscent,m.width,m.actualBoundingBoxAscent+m.actualBoundingBoxDescent,s));}
function avatar(c:Ctx,env:Env,name:string,x:number,feet:number,h:number,blink=false,motion=0,talk=0){actors.push(bounds(c,x-h*(name==='reading'?1006/1564:712/1107)/2,feet-h,h*(name==='reading'?1006/1564:712/1107),h,'VIC avatar'));const im=env.image(name);if(!im)throw new Error(`missing ${name}`);const ratio=name==='reading'?1006/1564:712/1107;c.save();c.translate(x-h*ratio/2,feet-h);c.scale(h*ratio/1006,h/1564);if(name==='point'){
const head='M0 0H548V392L491 468L398 501L158 503L41 450L0 350Z',arm='M419 493L472 479L530 455L578 432L695 430L712 447L708 477L660 501L633 531L582 548L555 587L520 613L469 615L434 582Z';
c.save();c.scale(1006/712,1564/1107);c.save();c.clip(new Path2D('M0 0H712V1107H0Z '+head+' '+arm),'evenodd');c.drawImage(im,0,0,712,1107);c.restore();
const gesture=ease((motion-.3)/.5)-ease((motion-1.5)/.6);
for(const part of [{path:head,x:274,y:488,angle:-.022*gesture},{path:arm,x:434,y:530,angle:-.07*gesture}]){c.save();c.translate(part.x,part.y);c.rotate(part.angle);c.translate(-part.x,-part.y);c.clip(new Path2D(part.path));c.drawImage(im,0,0,712,1107);if(part.path===head&&talk>.24){const mouth=env.image('speaking');if(!mouth)throw new Error('missing speaking cel');c.save();const m=new Path2D();m.ellipse(299,398,53,29,0,0,Math.PI*2);c.clip(m);c.drawImage(mouth,0,0,712,1107);c.restore();}c.restore();}c.restore();
}else c.drawImage(im,0,0,1006,1564);
if(name==='reading'&&blink){const closed=env.image('blink');if(!closed)throw new Error('missing blink');c.save();const lenses=new Path2D('M329 424 Q397 402 466 417 Q478 449 450 487 Q395 517 349 491 Z M543 407 Q600 382 677 393 L662 465 Q607 496 552 479 Z');c.clip(lenses);c.drawImage(closed,0,0,1006,1564);c.restore();}c.restore();}


function tick(c:Ctx,x:number,y:number,p:number,s=1){c.save();c.translate(x,y);c.scale(s,s);c.strokeStyle='#46836D';c.lineWidth=7;c.lineCap='round';c.lineJoin='round';c.beginPath();c.moveTo(-16,0);if(p<.35)c.lineTo(-16+14*p/.35,14*p/.35);else{c.lineTo(-2,14);c.lineTo(-2+31*(p-.35)/.65,14-38*(p-.35)/.65);}c.stroke();c.restore()}
function agent(c:Ctx,x:number,y:number,k:number,u:number,reach=0,mood='happy'){
actors.push(bounds(c,x-(139+47*reach)*k,y-112*k,2*(139+47*reach)*k,238*k,'cartoon agent'));
c.save();c.fillStyle='#60796A20';c.beginPath();c.ellipse(x,y+126*k,94*k,12*k,0,0,7);c.fill();c.restore();
const anticipate=ease((u-.2)/.3)-ease((u-.7)/.35),settle=Math.exp(-Math.max(0,u-.7)*3)*Math.sin(Math.max(0,u-.7)*14),jump=mood==='surprise'?22*(ease((u-.4)/.15)-ease((u-.7)/.3)):0;
c.save();c.translate(x,y-jump);c.rotate((mood==='effort'?-.08:.025)*reach);c.scale(k*(1+.04*anticipate-.025*settle),k*(1-.055*anticipate+.04*settle));
// Actual puppet feet, elbows, brows and expressions; these are not a UI card.
for(const side of [-1,1]){c.strokeStyle='#414D58';c.lineWidth=7;c.lineCap='round';c.beginPath();c.moveTo(side*49,79);c.lineTo(side*58,112);c.stroke();box(c,side*58-25,106,50,19,'#8DB6A2',9);const lift=side===1?reach:reach*.35;c.beginPath();c.moveTo(side*92,0);c.quadraticCurveTo(side*(125+21*lift),-25-27*lift,side*(139+47*lift),-15-50*lift);c.stroke();c.fillStyle='#C4DDCF';c.beginPath();c.arc(side*(139+47*lift),-15-50*lift,13,0,7);c.fill();c.stroke();}
box(c,-101,-96,202,190,'#C9DED0',38);box(c,-48,-112,66,22,'#C9DED0',9);const blink=(u%3.6)>3.43;
for(const xx of [-33,33]){c.fillStyle='#414D58';c.beginPath();c.ellipse(xx+reach*6,-25,9,blink?2:mood==='surprise'?19:14,0,0,7);c.fill();c.strokeStyle='#414D58';c.lineWidth=4;c.beginPath();c.moveTo(xx-13,-55+(mood==='effort'?8:0));c.lineTo(xx+13,-57);c.stroke();c.fillStyle='#D8B7A6';c.beginPath();c.ellipse(xx*1.65,7,13,7,0,0,7);c.fill();}
c.strokeStyle='#414D58';c.lineWidth=4;c.beginPath();if(mood==='surprise')c.ellipse(0,23,10,15,0,0,7);else if(mood==='effort'){c.moveTo(-14,27);c.quadraticCurveTo(0,15,14,27);}else c.arc(0,8,20,.15,Math.PI-.15);c.stroke();box(c,-31,59,62,14,'#99BAA7',5);c.restore();}


export {ease,box,text,avatar,tick,agent};
// Caption layout is separate from scene labels; words still enter the actor-overlap audit.
export function drawCaption(c:Ctx,copy:string){c.font='600 24px VICMyanmar,Arial,sans-serif';const words=Array.from(new Intl.Segmenter('my',{granularity:'word'}).segment(copy),(v:any)=>v.segment),lines:string[]=[];let current='';for(const word of words){if(current&&c.measureText(current+word).width>1060){lines.push(current);current=word;}else current+=word;}if(current)lines.push(current);if(lines.length>2)throw new Error('Caption exceeds two readable lines');c.save();c.fillStyle='#FFFFF8F2';c.beginPath();c.roundRect(80,633,1120,78,9);c.fill();c.fillStyle='#91B6A3';c.fillRect(100,708,1080,3);for(let i=0;i<lines.length;i++)text(c,lines[i],640,lines.length===1?681:662+i*32,24);c.restore();}
