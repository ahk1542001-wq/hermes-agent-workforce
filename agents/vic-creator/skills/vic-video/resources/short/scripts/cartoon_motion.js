  // Deterministic 2D puppet deformation of the retained artwork; no new bitmap or AI video.
  const puppetCache={};
  const puppetRigs=__RIGS__;
  function action(t,start,length){let p=(t-start)/length;return p>0&&p<1?Math.sin(Math.PI*p)**2:0;}
  function cue(rig,kind,t){const list=rig.cues?.[kind]||[];let best=0;for(const e of list)best=Math.max(best,action(t,e.start,e.duration));return best;}
  function cueWave(rig,kind,t){for(const e of rig.cues?.[kind]||[])if(t>=e.start&&t<=e.start+e.duration)return Math.sin(2*Math.PI*(t-e.start)/e.duration);return 0;}
  function influence(x,y,cx,cy,rx,ry){return Math.exp(-Math.pow((x-cx)/rx,4)-Math.pow((y-cy)/ry,4));}
  function puppetPoint(x,y,rig,t){
    let px=x,py=y;
    // Skin stretches continuously around closing eyes; no pasted-on lids or fixed face patch.
    function blink(eyes,b){for(const [cx,cy,rx,ry] of eyes){const w=Math.exp(-Math.pow((x-cx)/rx,6)-Math.pow((y-cy)/(ry*1.25),6));py-=b*.94*(y-cy)*w;}}
    blink(rig.eyes, cue(rig,'blink',t));if(rig.robotEyes)blink(rig.robotEyes,cue(rig,'robotBlink',t));
    const nod=cue(rig,'nod',t),angle=.043*cueWave(rig,'nod',t)*nod;
    const [hx,hy,rx,ry]=rig.head;const hw=influence(x,y,hx,hy-ry*.52,rx,ry*.72);
    const dx=px-hx,dy=py-hy;px+=hw*(Math.cos(angle)*dx-Math.sin(angle)*dy-dx);py+=hw*(Math.sin(angle)*dx+Math.cos(angle)*dy-dy+3*nod);
    if(rig.hand){const [ex,ey,cx,cy,rx,ry]=rig.hand,w=influence(x,y,cx,cy,rx,ry),a=-.12*cue(rig,'hand',t),dx=x-ex,dy=y-ey;px+=w*(Math.cos(a)*dx-Math.sin(a)*dy-dx);py+=w*(Math.sin(a)*dx+Math.cos(a)*dy-dy);}
    if(rig.finger){const [cx,cy,rx,ry]=rig.finger,w=influence(x,y,cx,cy,rx,ry),a=cue(rig,'finger',t);px+=18*w*a;py+=5*w*a;}
    if(rig.page){const [cx,cy,rx,ry]=rig.page,w=influence(x,y,cx,cy,rx,ry),a=cue(rig,'page',t);px-=7*w*a;py-=13*w*a;}
    if(rig.file){const [cx,cy,rx,ry]=rig.file,w=influence(x,y,cx,cy,rx,ry),a=cue(rig,'file',t);py-=25*w*a;px+=6*w*a;}
    if(rig.robot){const [cx,cy,rx,ry]=rig.robot,w=influence(x,y,cx,cy-ry*.5,rx,ry*.6),a=-.035*cue(rig,'robot',t),dx=x-cx,dy=y-cy;px+=w*(Math.cos(a)*dx-Math.sin(a)*dy-dx);py+=w*(Math.sin(a)*dx+Math.cos(a)*dy-dy);}
    const scale=rig.motionScale??1;return [x+(px-x)*scale,y+(py-y)*scale];
  }
  function makePuppet(im,rig){
    const w=im.naturalWidth,h=im.naturalHeight,xs=new Set([0,w]),ys=new Set([0,h]);
    for(let x=0;x<w;x+=70)xs.add(x);for(let y=0;y<h;y+=60)ys.add(y);
    // Dense topology only at the eyes: independent eyes can actually close in the raster.
    for(const [x,y,rx,ry] of [...rig.eyes,...(rig.robotEyes||[])]){
      for(let i=-2;i<=2;i++){xs.add(Math.max(0,Math.min(w,x+i*rx*.55)));ys.add(Math.max(0,Math.min(h,y+i*ry*.62)));}
    }
    const xx=[...xs].sort((a,b)=>a-b),yy=[...ys].sort((a,b)=>a-b),points=[],tris=[];
    for(const y of yy)for(const x of xx)points.push([x,y]);const n=xx.length;
    for(let row=0;row<yy.length-1;row++)for(let col=0;col<n-1;col++){const i=row*n+col;tris.push([i,i+1,i+n],[i+1,i+n+1,i+n]);}
    const canvas=document.createElement('canvas');canvas.width=w;canvas.height=h;
    const gl=canvas.getContext('webgl',{alpha:true,antialias:false,premultipliedAlpha:false,preserveDrawingBuffer:true});
    if(!gl)throw Error('Character mesh needs WebGL; stop rather than produce seamed fallback');
    function shader(type,source){const sh=gl.createShader(type);gl.shaderSource(sh,source);gl.compileShader(sh);if(!gl.getShaderParameter(sh,gl.COMPILE_STATUS))throw Error(gl.getShaderInfoLog(sh));return sh;}
    const program=gl.createProgram();gl.attachShader(program,shader(gl.VERTEX_SHADER,`attribute vec2 position;attribute vec2 uv;uniform vec2 size;varying vec2 tex;void main(){gl_Position=vec4(position.x/size.x*2.0-1.0,1.0-position.y/size.y*2.0,0,1);tex=uv;}`));
    gl.attachShader(program,shader(gl.FRAGMENT_SHADER,`precision highp float;varying vec2 tex;uniform sampler2D image;void main(){gl_FragColor=texture2D(image,tex);}`));gl.linkProgram(program);if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw Error(gl.getProgramInfoLog(program));gl.useProgram(program);
    gl.uniform2f(gl.getUniformLocation(program,'size'),w,h);gl.uniform1i(gl.getUniformLocation(program,'image'),0);
    const uvbuf=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,uvbuf);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(points.flatMap(([x,y])=>[x/w,y/h])),gl.STATIC_DRAW);let at=gl.getAttribLocation(program,'uv');gl.enableVertexAttribArray(at);gl.vertexAttribPointer(at,2,gl.FLOAT,false,0,0);
    const positions=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,positions);gl.bufferData(gl.ARRAY_BUFFER,points.length*8,gl.DYNAMIC_DRAW);at=gl.getAttribLocation(program,'position');gl.enableVertexAttribArray(at);gl.vertexAttribPointer(at,2,gl.FLOAT,false,0,0);
    const indexes=gl.createBuffer();gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,indexes);const indices=new Uint16Array(tris.flat());gl.bufferData(gl.ELEMENT_ARRAY_BUFFER,indices,gl.STATIC_DRAW);
    gl.activeTexture(gl.TEXTURE0);const texture=gl.createTexture();gl.bindTexture(gl.TEXTURE_2D,texture);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL,false);gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,im);
    gl.disable(gl.BLEND);gl.disable(gl.DITHER);gl.clearColor(0,0,0,0);gl.viewport(0,0,w,h);
    return {points,tris,canvas,gl,positions,indices,im,rig};
  }
  function drawCartoon(c,key,x,y,w,t){
    const im=loadedImages[key],rig=puppetRigs[key];if(!rig){c.drawImage(im,x,y,w,w*im.height/im.width);return;}
    const m=puppetCache[key]||(puppetCache[key]=makePuppet(im,rig));
    const dst=new Float32Array(m.points.flatMap(([x,y])=>puppetPoint(x,y,rig,t)));const gl=m.gl;gl.bindBuffer(gl.ARRAY_BUFFER,m.positions);gl.bufferSubData(gl.ARRAY_BUFFER,0,dst);gl.clear(gl.COLOR_BUFFER_BIT);gl.drawElements(gl.TRIANGLES,m.indices.length,gl.UNSIGNED_SHORT,0);gl.flush();
    c.drawImage(m.canvas,x,y,w,w*im.height/im.width);
  }
