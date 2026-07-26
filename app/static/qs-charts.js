/* qs-charts.js — 清数智算图表引擎层：统一色板与共用 canvas 绘制函数。
 * 通过 window.QSCharts 暴露；须在 high-fidelity-demo.js 之前加载（均为 defer，按文档顺序执行）。 */
window.QSCharts=(function(){
  var colors={up:'#f3262d',down:'#079a56',flat:'#bcc3ce',primary:'#1768ef',compare:'#10a25d'};
  function setup(canvas){var r=window.devicePixelRatio||1,w=canvas.clientWidth||300,h=canvas.clientHeight||120;canvas.width=w*r;canvas.height=h*r;var c=canvas.getContext('2d');c.setTransform(r,0,0,r,0,0);c.clearRect(0,0,w,h);return {c:c,w:w,h:h}}
  function line(canvas,points,color,fill){
    if(!canvas.offsetParent)return;var s=setup(canvas),c=s.c,w=s.w,h=s.h,arr=points.map(Number),min=Math.min.apply(null,arr),max=Math.max.apply(null,arr),range=max-min||1,pad=4;
    c.beginPath();arr.forEach(function(v,i){var x=pad+i*(w-pad*2)/(arr.length-1),y=h-pad-(v-min)*(h-pad*2)/range;i?c.lineTo(x,y):c.moveTo(x,y)});
    c.strokeStyle=color;c.lineWidth=2;c.lineJoin='round';c.lineCap='round';c.stroke();
    if(fill){c.lineTo(w-pad,h-pad);c.lineTo(pad,h-pad);c.closePath();var g=c.createLinearGradient(0,0,0,h);g.addColorStop(0,color+'2e');g.addColorStop(1,color+'00');c.fillStyle=g;c.fill()}
  }
  function radar(cv){
    if(!cv.offsetParent)return;var s=setup(cv),c=s.c,w=s.w,h=s.h,labels=(cv.getAttribute('data-labels')||'A,B,C,D,E').split(','),values=(cv.getAttribute('data-values')||'80,80,80,80,80').split(',').map(Number),values2=cv.getAttribute('data-values2')?cv.getAttribute('data-values2').split(',').map(Number):null,n=labels.length,cx=w/2,cy=h/2+4,r=Math.min(w,h)*.32;
    function point(i,rr){var a=-Math.PI/2+i*Math.PI*2/n;return [cx+Math.cos(a)*rr,cy+Math.sin(a)*rr]}
    c.font='11px Microsoft YaHei';c.textAlign='center';c.textBaseline='middle';
    for(var level=1;level<=5;level++){c.beginPath();for(var i=0;i<n;i++){var pt=point(i,r*level/5);i?c.lineTo(pt[0],pt[1]):c.moveTo(pt[0],pt[1])}c.closePath();c.strokeStyle='#dfe7f3';c.stroke()}
    for(var j=0;j<n;j++){var end=point(j,r);c.beginPath();c.moveTo(cx,cy);c.lineTo(end[0],end[1]);c.strokeStyle='#e5ebf4';c.stroke();
      var cosA=Math.cos(-Math.PI/2+j*Math.PI*2/n),lp=point(j,r+22),label=labels[j],tw=c.measureText(label).width;
      c.textAlign=cosA>.3?'left':cosA<-.3?'right':'center';
      var lx=lp[0];if(c.textAlign==='left')lx=Math.max(6,Math.min(lx,w-6-tw));else if(c.textAlign==='right')lx=Math.min(w-6,Math.max(lx,6+tw));else lx=Math.max(6+tw/2,Math.min(w-6-tw/2,lx));
      var ly=Math.max(10,Math.min(h-10,lp[1]));
      c.fillStyle='#344a6a';c.fillText(label,lx,ly)}
    c.textAlign='center';
    function area(vals,color,fill){c.beginPath();vals.forEach(function(v,i){var pnt=point(i,r*v/100);i?c.lineTo(pnt[0],pnt[1]):c.moveTo(pnt[0],pnt[1])});c.closePath();c.fillStyle=fill;c.fill();c.strokeStyle=color;c.lineWidth=2;c.stroke();vals.forEach(function(v,i){var pnt=point(i,r*v/100);c.fillStyle=color;c.beginPath();c.arc(pnt[0],pnt[1],2.4,0,Math.PI*2);c.fill()})}
    if(values2)area(values2,colors.compare,'rgba(16,162,93,.07)');area(values,colors.primary,'rgba(23,104,239,.11)')
    function annotate(vals,color,out){
      c.font='10px Microsoft YaHei';vals.forEach(function(v,i){
        if(!Number.isFinite(v)||v===0)return;
        var rrOut=r*v/100+12,rr=out?(rrOut>r+9?Math.max(10,r*v/100-12):rrOut):Math.max(10,r*v/100-12),pnt=point(i,rr),a=Math.cos(-Math.PI/2+i*Math.PI*2/n),txt=String(Math.round(v)),tw=c.measureText(txt).width;
        c.textAlign=a>.3?'left':a<-.3?'right':'center';
        var lx=pnt[0];if(c.textAlign==='left')lx=Math.max(6,Math.min(lx,w-6-tw));else if(c.textAlign==='right')lx=Math.min(w-6,Math.max(lx,6+tw));else lx=Math.max(6+tw/2,Math.min(w-6-tw/2,lx));
        var ly=Math.max(10,Math.min(h-10,pnt[1]));
        c.fillStyle=color;c.fillText(txt,lx,ly);
      });
    }
    if(values2)annotate(values2,colors.compare,false);annotate(values,colors.primary,true);
    c.textAlign='center';
  }
  return {colors:colors,setup:setup,line:line,radar:radar};
})();
