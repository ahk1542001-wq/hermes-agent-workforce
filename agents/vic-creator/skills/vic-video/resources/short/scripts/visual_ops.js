// First-party semantic operations on the retained Canvas renderer; no topic, plot or palette defaults.
function drawStructuredVisual(shot,t){
 const row=visualPlan.shots[shot.index],dt=t-shot.start,c=vCtx;
 window.VISUAL_TRACE={shot:row.id,objects:[],actions:[]};
 const states={};
 for(const o of row.objects)states[o.id]={...o,ink:o.ink===false?0:1,open:0,alpha:1};
 for(const a of row.actions){
  const p=ease(Math.max(0,Math.min(1,(dt-a.at)/a.duration))),o=states[a.object];
  if(a.op==='move'||a.op==='transfer'){
   if(dt>=a.at){o.x=o.x+(a.to[0]-o.x)*p;o.y=o.y+(a.to[1]-o.y)*p;}
   if(a.op==='transfer'&&dt>=a.at)o.alpha=1-.55*p;
  }else if(a.op==='write'&&dt>=a.at)o.ink=p;
  else if(a.op==='erase'&&dt>=a.at)o.ink=1-p;
  else if(a.op==='open'&&dt>=a.at)o.open=p;
  window.VISUAL_TRACE.actions.push({op:a.op,object:a.object,progress:p,result:a.result});
 }
 function rect(x,y,w,h,r,fill,stroke){c.beginPath();c.roundRect(x,y,w,h,r);c.fillStyle=fill;c.fill();c.lineWidth=4;c.strokeStyle=stroke;c.stroke();}
 for(const o of Object.values(states)){
  c.save();c.globalAlpha=o.alpha;const x=o.x,y=o.y,w=o.w,h=o.h,col=o.color||VOX.green,ink=VOX.ink;
  let bounds={x,y,w,h};
  if(o.kind==='sprite'){
   const im=loadedImages[o.asset],iw=im.naturalWidth||im.width,ih=im.naturalHeight||im.height;
   const dw=Math.min(w,h*iw/ih),dh=dw*ih/iw,dx=x+(w-dw)/2,dy=y+(h-dh)/2;
   drawCartoon(c,o.asset,dx,dy,dw,t);bounds={x:dx,y:dy,w:dw,h:dh};
  }else if(o.kind==='folder'){
   rect(x,y+h*.18,w,h*.78,18,col,ink);rect(x+w*.05,y+h*.08,w*.4,h*.2,10,col,ink);
   c.save();c.translate(x,y+h*.35);c.rotate(-.12*o.open);rect(0,0,w,h*.61,16,o.paper||'#FFF9E9',ink);c.restore();
  }else if(o.kind==='device'){
   rect(x,y,w,h,24,col,ink);rect(x+w*.05,y+h*.07,w*.9,h*.84,12,o.paper||'#FFFFFF',ink);
   c.fillStyle=ink;c.beginPath();c.arc(x+w/2,y+h*.96,4,0,7);c.fill();
  }else if(o.kind==='token'){
   c.fillStyle=col;c.strokeStyle=ink;c.lineWidth=4;c.beginPath();c.ellipse(x+w/2,y+h/2,w/2,h/2,0,0,7);c.fill();c.stroke();
  }else{
   rect(x,y,w,h,12,o.paper||'#FFFEF8',ink);
   if(o.kind==='notebook'){
    c.fillStyle=col;c.fillRect(x,y,w*.12,h);c.strokeStyle=ink;c.lineWidth=4;c.beginPath();c.moveTo(x+w*.5,y+8);c.lineTo(x+w*.5,y+h-8);c.stroke();
    if(o.open>0){c.save();c.translate(x+w*.5,y);c.rotate(-.1*o.open);c.strokeStyle=col;c.strokeRect(0,0,w*.48,h);c.restore();}
   }
  }
  if(['sheet','notebook','device'].includes(o.kind)){
   c.save();c.beginPath();c.rect(x+w*.16,y+h*.2,w*.68*o.ink,h*.6);c.clip();c.strokeStyle=col;c.lineWidth=Math.max(4,w*.012);
   for(let k=0;k<5;k++){c.beginPath();c.moveTo(x+w*.18,y+h*(.24+k*.11));c.lineTo(x+w*(k===4?.65:.82),y+h*(.24+k*.11));c.stroke();}c.restore();
  }
  c.restore();window.VISUAL_TRACE.objects.push({id:o.id,kind:o.kind,asset:o.asset||null,...bounds,ink:o.ink,open:o.open,alpha:o.alpha});
 }
 for(const l of row.labels||[])label(c,l.text,l.x,l.y,l.size,l.color||VOX.ink);
}
function drawJobVisual(shot,t){drawStructuredVisual(shot,t);}
