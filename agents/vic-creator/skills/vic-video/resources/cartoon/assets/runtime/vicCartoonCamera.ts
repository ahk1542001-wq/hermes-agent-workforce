import type {Ctx} from './core';
export type CameraPose={zoom:number;dx:number;dy:number};
export function applyWorldCamera(c:Ctx,p:CameraPose){c.translate(p.dx,p.dy);c.scale(p.zoom,p.zoom);}
export function drawDepthForeground(c:Ctx,p:CameraPose){c.save();c.globalAlpha=.18;c.fillStyle='#B4BEAE';const x=p.dx*.32;c.beginPath();c.moveTo(-60+x,620);c.lineTo(105+x,604);c.lineTo(194+x,622);c.closePath();c.fill();c.beginPath();c.moveTo(1160+x,622);c.lineTo(1268+x,607);c.lineTo(1340+x,622);c.closePath();c.fill();c.restore();}
