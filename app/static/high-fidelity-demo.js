window.QSTodayConfig={
  baseURL:window.location.origin,
  credentials:'same-origin',
  endpoints:{
    indexQuote:'/api/v1/market/index-quote',
    marketOverview:'/api/v1/market/overview',
    industryRotation:'/api/v1/market/industry-rotation',
    riseFallDistribution:'/api/v1/market/rise-fall-distribution',
    hotThemes:'/api/v1/market/hot-themes',
    tradingActivity:'/api/v1/market/trading-activity',
    sectorFundFlow:'/api/v1/market/sector-fund-flow'
  }
};
window.QSStockConfig={
  baseURL:window.location.origin,
  credentials:'same-origin',
  endpoints:{
    search:'/api/v1/stocks/search',
    scoreCard:'/api/v1/stocks/{symbol}/score-card',
    kline:'/api/v1/market/kline'
  }
};
window.QSKlineConfig={
  baseURL:window.location.origin,
  endpoint:'/api/v1/market/kline',
  headers:{},
  symbol:'300750.SZ',
  adjust:'qfq'
};
(function(){
  var $=function(s){return document.querySelector(s)}, $$=function(s){return Array.prototype.slice.call(document.querySelectorAll(s))};
  var toastTimer;
  function toast(msg){var t=$('#toast');t.textContent=msg;t.classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(function(){t.classList.remove('show')},1900)}
  function showPage(name){
    if(name!=='score')toggleKlineExpand(false);
    $$('.page').forEach(function(p){p.classList.remove('active')});
    var target=$('#page-'+name);if(target)target.classList.add('active');
    $$('[data-page]').forEach(function(b){b.classList.toggle('active',b.getAttribute('data-page')===name)});
    if(name==='watch')loadWatchlist();
    window.scrollTo({top:0,behavior:'smooth'});
    setTimeout(drawAll,30);
  }
  $$('[data-page]').forEach(function(b){b.addEventListener('click',function(){showPage(b.getAttribute('data-page'))})});
  $$('[data-toast]').forEach(function(b){b.addEventListener('click',function(){toast(b.getAttribute('data-toast'))})});
  $$('.tab-btn').forEach(function(b){b.addEventListener('click',function(){
    $$('.tab-btn').forEach(function(x){x.classList.remove('active')});b.classList.add('active');
    $$('.review-pane').forEach(function(x){x.classList.remove('active')});$('#review-'+b.getAttribute('data-review')).classList.add('active');setTimeout(drawAll,20)
  })});
  var watchStatuses=['holding','watching','researching','cleared'];
  var watchStatusLabels={holding:'持仓中',watching:'观望中',researching:'研究中',cleared:'已清仓'};
  var watchStatusColors={holding:'#11a45f',watching:'#ff960f',researching:'#2e80ef',cleared:'#bcc3ce'};
  var watchState={items:[],actions:[],selected:new Set(),filter:'all',candidate:null,searchItems:[],searchSequence:0,searchTimer:null,sessionPromise:null,loadingPromise:null};
  function watchStatusLabel(value){return watchStatusLabels[value]||watchStatusLabels.watching}
  function comparableWatchSymbol(value){return String(value||'').trim().toUpperCase().replace(/\.SH$/,'.SS')}
  function watchRequest(path,options){
    options=options||{};var headers=Object.assign({},options.headers||{});
    if(options.body&&!(options.body instanceof FormData))headers['Content-Type']='application/json';
    return fetch(path,Object.assign({},options,{credentials:'same-origin',headers:headers})).then(function(response){
      return response.json().catch(function(){return {}}).then(function(body){
        if(!response.ok)throw new Error(body.detail||('请求失败：'+response.status));return body;
      });
    });
  }
  function ensureWatchlistSession(){
    if(watchState.sessionPromise)return watchState.sessionPromise;
    watchState.sessionPromise=watchRequest('/session').catch(function(){
      return watchRequest('/users',{method:'POST',body:JSON.stringify({name:'网页体验用户'})});
    }).catch(function(error){watchState.sessionPromise=null;throw error});
    return watchState.sessionPromise;
  }
  function watchQuote(item){
    var quote=item.current_quote||{},metrics=item.metrics||{};
    return {
      price:quote.price!==undefined&&quote.price!==null?Number(quote.price):Number(metrics.latest_close),
      change:quote.pct_change!==undefined&&quote.pct_change!==null?Number(quote.pct_change):Number(metrics.return_1d_pct),
      timestamp:quote.market_timestamp||item.market_timestamp||item.updated_at
    };
  }
  function watchNumber(value){
    var number=Number(value);return Number.isFinite(number)?number.toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2}):'—';
  }
  function watchPercent(value){
    var number=Number(value);return Number.isFinite(number)?(number>0?'+':'')+number.toFixed(2)+'%':'—';
  }
  function watchTone(value){var number=Number(value);return Number.isFinite(number)?(number>0?'up':number<0?'down':''):''}
  function watchTime(value){
    if(!value)return '—';var date=new Date(value);return Number.isNaN(date.getTime())?String(value):date.toLocaleString('zh-CN',{hour12:false,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});
  }
  function primaryWatchAction(actionItem){
    var actions=actionItem&&Array.isArray(actionItem.actions)?actionItem.actions:[];
    return actions.find(function(item){return item.status==='triggered'})
      ||actions.find(function(item){return item.status==='pending_data'})
      ||actions[0]||null;
  }
  function watchStatusOptions(selected){
    return watchStatuses.map(function(value){return '<option value="'+value+'"'+(value===selected?' selected':'')+'>'+watchStatusLabel(value)+'</option>'}).join('');
  }
  function updateWatchBatchButton(){
    var button=$('#batchDeleteWatch');button.disabled=!watchState.selected.size;button.textContent=watchState.selected.size?'批量删除（'+watchState.selected.size+'）':'批量删除';
  }
  function applyWatchFilter(){
    var visible=0;
    $$('#watchRows tr[data-status]').forEach(function(row){
      var show=watchState.filter==='all'||row.getAttribute('data-status')===watchState.filter;row.style.display=show?'':'none';if(show)visible+=1;
    });
    $('#watchRecordCount').textContent='共 '+visible+' 条记录';
    var visibleRows=$$('#watchRows tr[data-status]').filter(function(row){return row.style.display!=='none'});
    $('#watchSelectAll').checked=visibleRows.length>0&&visibleRows.every(function(row){return watchState.selected.has(row.getAttribute('data-symbol'))});
  }
  function renderWatchSummary(){
    var counts={holding:0,watching:0,researching:0,cleared:0};
    watchState.items.forEach(function(item){counts[item.focus_status||'watching']=(counts[item.focus_status||'watching']||0)+1});
    $('#watchTotalCount').textContent=watchState.items.length;$('#watchHoldingCount').textContent=counts.holding;$('#watchWatchingCount').textContent=counts.watching;$('#watchResearchingCount').textContent=counts.researching;
    var total=Math.max(1,watchState.items.length),cursor=0,stops=[];
    watchStatuses.forEach(function(status){var start=cursor;cursor+=counts[status]/total*100;stops.push(watchStatusColors[status]+' '+start+'% '+cursor+'%')});
    if(!watchState.items.length)stops=['#e5e9ef 0 100%'];
    var donut=$('#watchStatusDonut');donut.dataset.count=watchState.items.length;donut.style.background='conic-gradient('+stops.join(',')+')';
    $('#watchStatusLegend').innerHTML=watchStatuses.map(function(status){
      var count=counts[status],rate=watchState.items.length?count/watchState.items.length*100:0;
      return '<p style="color:'+watchStatusColors[status]+'"><i class="dot"></i>'+watchStatusLabel(status)+'　'+count+' ('+rate.toFixed(2)+'%)</p>';
    }).join('');
    var actionMap=new Map(watchState.actions.map(function(item){return [item.symbol,item]}));
    var todos=watchState.items.map(function(item){var actionItem=actionMap.get(item.symbol),action=primaryWatchAction(actionItem);return {item:item,actionItem:actionItem,action:action}}).filter(function(entry){return entry.action||entry.actionItem}).slice(0,4);
    $('#watchTodoList').innerHTML=todos.map(function(entry){
      var item=entry.item,copy=entry.action&&(entry.action.next_step||entry.action.title)||entry.actionItem.headline||'继续观察行情与新增证据';
      return '<div class="todo-item"><span class="pill">'+escapeHTML(watchStatusLabel(item.focus_status||'watching'))+'</span><span><b>'+escapeHTML(item.name||item.symbol)+'（'+escapeHTML(item.symbol)+'）</b><br><small>'+escapeHTML(copy)+'</small></span><small>'+escapeHTML(entry.actionItem.data_as_of?String(entry.actionItem.data_as_of).slice(5,10):'待更新')+'</small></div>';
    }).join('')||'<p class="muted">暂无待处理动作。</p>';
  }
  function renderWatchlist(){
    var symbols=new Set(watchState.items.map(function(item){return item.symbol}));
    watchState.selected=new Set(Array.from(watchState.selected).filter(function(symbol){return symbols.has(symbol)}));
    $('#watchRows').innerHTML=watchState.items.map(function(item){
      var quote=watchQuote(item),status=item.focus_status||'watching';
      var industry=item.industry||'行业待更新',board=item.board||item.market||'板块待更新';
      return '<tr data-symbol="'+escapeHTML(item.symbol)+'" data-status="'+status+'">'
        +'<td><input class="watch-row-select" type="checkbox" aria-label="选择 '+escapeHTML(item.name||item.symbol)+'"'+(watchState.selected.has(item.symbol)?' checked':'')+'></td>'
        +'<td><b>'+escapeHTML(item.name||item.symbol)+'</b><br><span class="muted">'+escapeHTML(item.symbol)+'</span></td>'
        +'<td class="'+watchTone(quote.change)+'"><b>'+watchNumber(quote.price)+'</b></td>'
        +'<td class="'+watchTone(quote.change)+'">'+watchPercent(quote.change)+'</td>'
        +'<td><select class="watch-inline-status" aria-label="'+escapeHTML(item.name||item.symbol)+' 的关注状态">'+watchStatusOptions(status)+'</select></td>'
        +'<td><textarea class="watch-reason-input" rows="2" maxlength="1000" aria-label="'+escapeHTML(item.name||item.symbol)+' 的关注理由" placeholder="填写关注理由">'+escapeHTML(item.thesis||'')+'</textarea></td>'
        +'<td><b>'+escapeHTML(industry)+'</b><br><span class="muted">'+escapeHTML(board)+'</span></td><td>'+escapeHTML(watchTime(quote.timestamp))+'</td>'
        +'<td class="watch-operation-cell"><button class="watch-op-btn danger" type="button" data-watch-delete title="删除关注" aria-label="删除 '+escapeHTML(item.name||item.symbol)+' 关注">⌫</button></td></tr>';
    }).join('');
    if(!watchState.items.length)$('#watchRows').innerHTML='<tr class="watch-empty"><td colspan="9">还没有关注股票，请在上方搜索并添加。</td></tr>';
    renderWatchSummary();applyWatchFilter();updateWatchBatchButton();
  }
  function renderWatchlistError(message){
    $('#watchRows').innerHTML='<tr class="watch-empty"><td colspan="9">'+escapeHTML(message)+'</td></tr>';$('#watchRecordCount').textContent='关注列表暂不可用';
  }
  function loadWatchlist(){
    if(watchState.loadingPromise)return watchState.loadingPromise;
    watchState.loadingPromise=ensureWatchlistSession().then(function(){
      return Promise.all([watchRequest('/me/watchlist/brief'),watchRequest('/me/research-actions').catch(function(){return {items:[]}})]);
    }).then(function(results){
      watchState.items=unwrapList(results[0]);watchState.actions=unwrapList(results[1]);renderWatchlist();return watchState.items;
    }).catch(function(error){renderWatchlistError('关注列表加载失败：'+error.message);return []}).finally(function(){watchState.loadingPromise=null});
    return watchState.loadingPromise;
  }
  function updateWatchItem(symbol,patch,control){
    var item=watchState.items.find(function(entry){return entry.symbol===symbol});if(!item)return Promise.reject(new Error('关注股票不存在'));
    if(control)control.disabled=true;
    return watchRequest('/me/watchlist',{method:'POST',body:JSON.stringify({
      symbol:item.symbol,name:item.name||null,market:item.market||'A股',
      thesis:Object.prototype.hasOwnProperty.call(patch,'thesis')?patch.thesis:null,
      focus_status:Object.prototype.hasOwnProperty.call(patch,'focus_status')?patch.focus_status:null
    })}).then(function(saved){Object.assign(item,saved);toast('关注信息已保存');return loadWatchlist()}).catch(function(error){toast('保存失败：'+error.message);throw error}).finally(function(){if(control)control.disabled=false});
  }
  $$('.watch-filters button').forEach(function(button){button.addEventListener('click',function(){
    $$('.watch-filters button').forEach(function(item){item.classList.toggle('active',item===button)});watchState.filter=button.getAttribute('data-filter')||'all';applyWatchFilter();
  })});
  $('#watchSelectAll').addEventListener('change',function(){
    var checked=this.checked;$$('#watchRows tr[data-symbol]').forEach(function(row){if(row.style.display==='none')return;var symbol=row.getAttribute('data-symbol');checked?watchState.selected.add(symbol):watchState.selected.delete(symbol);var box=row.querySelector('.watch-row-select');if(box)box.checked=checked});updateWatchBatchButton();
  });
  $('#watchRows').addEventListener('change',function(event){
    var row=event.target.closest('tr[data-symbol]');if(!row)return;var symbol=row.getAttribute('data-symbol');
    if(event.target.matches('.watch-row-select')){event.target.checked?watchState.selected.add(symbol):watchState.selected.delete(symbol);applyWatchFilter();updateWatchBatchButton()}
    else if(event.target.matches('.watch-inline-status')){var previous=row.getAttribute('data-status');updateWatchItem(symbol,{focus_status:event.target.value},event.target).catch(function(){event.target.value=previous})}
    else if(event.target.matches('.watch-reason-input')){var item=watchState.items.find(function(entry){return entry.symbol===symbol}),previous=item&&item.thesis||'',reason=event.target.value.trim();if(reason!==String(previous).trim())updateWatchItem(symbol,{thesis:reason},event.target).catch(function(){event.target.value=previous})}
  });
  $('#watchRows').addEventListener('click',function(event){
    var remove=event.target.closest('[data-watch-delete]');if(!remove)return;var row=remove.closest('tr[data-symbol]'),symbol=row.getAttribute('data-symbol'),item=watchState.items.find(function(entry){return entry.symbol===symbol});
    if(!window.confirm('确定删除“'+(item&&item.name||symbol)+'”的关注吗？'))return;
    remove.disabled=true;watchRequest('/me/watchlist/'+encodeURIComponent(symbol),{method:'DELETE'}).then(function(){watchState.selected.delete(symbol);toast('已删除关注');return loadWatchlist()}).catch(function(error){toast('删除失败：'+error.message);remove.disabled=false});
  });
  $('#batchDeleteWatch').addEventListener('click',function(){
    var symbols=Array.from(watchState.selected);if(!symbols.length||!window.confirm('确定删除选中的 '+symbols.length+' 只关注股票吗？'))return;
    var button=this;button.disabled=true;Promise.allSettled(symbols.map(function(symbol){return watchRequest('/me/watchlist/'+encodeURIComponent(symbol),{method:'DELETE'})})).then(function(results){
      var failed=0;results.forEach(function(result,index){if(result.status==='fulfilled')watchState.selected.delete(symbols[index]);else failed+=1});toast(failed?'部分股票删除失败，请重试':'已批量删除关注');return loadWatchlist();
    });
  });
  function hideWatchSearch(){$('#watchSearchResults').classList.remove('show');$('#watchSearchInput').setAttribute('aria-expanded','false')}
  function renderWatchSearch(items,message){
    watchState.searchItems=items||[];var results=$('#watchSearchResults');
    if(message)results.innerHTML='<div class="watch-search-empty">'+escapeHTML(message)+'</div>';
    else if(!watchState.searchItems.length)results.innerHTML='<div class="watch-search-empty">没有找到匹配的 A 股</div>';
    else results.innerHTML=watchState.searchItems.map(function(item,index){
      var symbol=item.internalSymbol||item.symbol,exists=watchState.items.some(function(entry){return comparableWatchSymbol(entry.symbol)===comparableWatchSymbol(symbol)});
      return '<button class="watch-search-result" type="button" role="option" data-watch-search-index="'+index+'"'+(exists?' disabled':'')+'><strong>'+escapeHTML(item.name||symbol)+'</strong><span>'+escapeHTML(item.symbol||symbol)+(exists?' · 已关注':'')+'</span><small>'+escapeHTML(item.market||'A股')+(item.industry?' · '+escapeHTML(item.industry):'')+'</small></button>';
    }).join('');
    results.classList.add('show');$('#watchSearchInput').setAttribute('aria-expanded','true');
  }
  function runWatchSearch(query){
    query=String(query||'').trim();if(!query){hideWatchSearch();return}
    var sequence=++watchState.searchSequence;renderWatchSearch([],'正在搜索股票…');
    stockRequest(stockConfig.endpoints.search,{q:query,limit:10}).then(function(payload){if(sequence===watchState.searchSequence)renderWatchSearch(unwrapList(payload))}).catch(function(error){if(sequence===watchState.searchSequence)renderWatchSearch([],'搜索暂不可用：'+error.message)});
  }
  function selectWatchCandidate(item){
    if(!item)return;watchState.candidate=item;$('#watchAddSymbol').value=item.internalSymbol||item.symbol;$('#watchAddName').value=item.name||'';$('#watchSearchInput').value=(item.name||'')+' '+(item.symbol||item.internalSymbol||'');$('#watchAddSubmit').disabled=false;hideWatchSearch();$('#watchAddReason').focus();
  }
  $('#watchSearchInput').addEventListener('input',function(){watchState.candidate=null;$('#watchAddSymbol').value='';$('#watchAddSubmit').disabled=true;clearTimeout(watchState.searchTimer);var query=this.value;watchState.searchTimer=setTimeout(function(){runWatchSearch(query)},180)});
  $('#watchSearchInput').addEventListener('keydown',function(event){if(event.isComposing)return;if(event.key==='Escape')hideWatchSearch();else if(event.key==='Enter'&&!watchState.candidate){event.preventDefault();var button=$('#watchSearchResults [data-watch-search-index]:not(:disabled)');if(button)selectWatchCandidate(watchState.searchItems[Number(button.dataset.watchSearchIndex)]);else runWatchSearch(this.value)}});
  $('#watchSearchResults').addEventListener('click',function(event){var button=event.target.closest('[data-watch-search-index]');if(button&&!button.disabled)selectWatchCandidate(watchState.searchItems[Number(button.dataset.watchSearchIndex)])});
  $('#watchAddForm').addEventListener('submit',function(event){
    event.preventDefault();if(!watchState.candidate||!$('#watchAddSymbol').value){toast('请先从搜索结果中选择股票');return}
    var button=$('#watchAddSubmit');button.disabled=true;watchRequest('/me/watchlist',{method:'POST',body:JSON.stringify({symbol:$('#watchAddSymbol').value,name:$('#watchAddName').value||null,market:watchState.candidate.market||'A股',thesis:$('#watchAddReason').value.trim(),focus_status:$('#watchAddStatus').value})}).then(function(){
      toast('已加入关注');event.target.reset();watchState.candidate=null;$('#watchAddSymbol').value='';$('#watchAddName').value='';return loadWatchlist();
    }).catch(function(error){toast('添加失败：'+error.message);button.disabled=false});
  });
  document.addEventListener('click',function(event){if(!event.target.closest('.watch-search-box'))hideWatchSearch()});
  $('#watchRows').innerHTML='<tr class="watch-loading"><td colspan="9">正在读取关注股票…</td></tr>';
  var accountInfo=$('.account-info');
  if(accountInfo){
    var purchaseCard=accountInfo.closest('.card');
    purchaseCard.classList.add('purchase-card');
    purchaseCard.innerHTML='<h3>会员购买</h3><div class="purchase-layout"><div class="purchase-plans"><button class="purchase-plan active" type="button" data-plan="month" data-price="98"><span class="purchase-check">✓</span><strong>月会员</strong><b>¥98 / 月</b><small>畅享会员全部权益</small></button><button class="purchase-plan" type="button" data-plan="year" data-price="980"><span class="recommend">推荐</span><span class="purchase-check">✓</span><strong>年会员</strong><b>¥980 / 年</b><small>折合 ¥81.7 / 月，省 ¥196</small></button></div><div class="payment-box"><div class="payment-head"><span>支付方式</span><span class="alipay"><i class="alipay-icon">支</i>支付宝</span></div><div class="payment-total"><span>应付金额</span><strong id="paymentAmount">¥98.00</strong></div><button class="btn primary block" id="purchaseNow" type="button">立即购买</button><p class="payment-security">本服务由支付宝提供安全支付保障</p></div></div>';
    var selectedPlan='month',selectedPrice=98;
    $$('.purchase-plan').forEach(function(button){button.addEventListener('click',function(){
      $$('.purchase-plan').forEach(function(item){item.classList.toggle('active',item===button)});
      selectedPlan=button.dataset.plan;selectedPrice=Number(button.dataset.price);$('#paymentAmount').textContent='¥'+selectedPrice.toFixed(2);
    })});
    window.QSPaymentAPI=window.QSPaymentAPI||{createOrder:function(payload){return Promise.resolve({demo:true,order:payload})}};
    $('#purchaseNow').addEventListener('click',function(){
      var button=this;button.disabled=true;button.textContent='正在创建订单…';
      Promise.resolve(window.QSPaymentAPI.createOrder({plan:selectedPlan,amount:selectedPrice,paymentMethod:'alipay'})).then(function(result){
        toast(result&&result.demo?'支付接口尚未接入，已生成演示订单':'订单已创建，正在前往支付宝');button.disabled=false;button.textContent='立即购买';
      }).catch(function(error){toast(error&&error.message?error.message:'订单创建失败，请稍后重试');button.disabled=false;button.textContent='立即购买'});
    });
  }
  /* ============ AI研究页：真实接口接入 ============ */
  var researchState={conversationId:null,symbol:null,question:'',busy:false,dims:{},evidenceAt:null,parallel:false};
  var DIM_META={
    fundamentals:{name:'基本面分析'},technical:{name:'技术面分析'},industry:{name:'行业分析'},
    valuation:{name:'估值分析'},risk:{name:'风险分析'}
  };
  /* 五维提示词边界：后续可直接替换 template（{target}/{question} 为占位符）。
     leave template 为空则使用兜底问句。 */
  var DIMENSION_PROMPTS={
    fundamentals:{model_tier:'deep',template:''},
    technical:{model_tier:'economy',template:''},
    industry:{model_tier:'deep',template:''},
    valuation:{model_tier:'deep',template:''},
    risk:{model_tier:'deep',template:''}
  };
  function researchRequest(path,options){
    options=options||{};var headers=Object.assign({},options.headers||{});
    if(options.body&&!(options.body instanceof FormData))headers['Content-Type']='application/json';
    return fetch(path,Object.assign({},options,{credentials:'same-origin',headers:headers})).then(function(r){
      return r.json().catch(function(){return {}}).then(function(body){
        if(!r.ok)throw new Error(body.detail||('请求失败：'+r.status));return body;
      });
    });
  }
  var researchSessionPromise=null;
  function ensureResearchSession(){
    if(researchSessionPromise)return researchSessionPromise;
    researchSessionPromise=researchRequest('/session').catch(function(){researchSessionPromise=null;return {}});
    return researchSessionPromise;
  }
  function parseResearchTarget(raw){
    var v=String(raw||'').trim();if(!v)return {name:'',symbol:null};
    var m=v.match(/([0-9]{6}\.(?:SZ|SS|SH)|[A-Za-z]{1,6}(?:\.[A-Za-z]{1,4})?)\s*$/);
    var symbol=null;if(m){symbol=m[1].toUpperCase().replace(/\.SH$/,'.SS');}
    var name=symbol?v.slice(0,v.length-m[0].length).trim():v;
    return {name:name||v,symbol:symbol};
  }
  function chatPayload(message,tier){
    var t=parseResearchTarget($('#researchTarget')?$('#researchTarget').value:'');
    var body={message:message,model_tier:tier||'economy',execute_agent:false,prefer_precomputed:true};
    if(t.symbol)body.symbol=t.symbol;
    if(researchState.conversationId)body.conversation_id=researchState.conversationId;
    return body;
  }
  function callChat(message,tier){
    return ensureResearchSession().then(function(){
      return researchRequest('/me/chat',{method:'POST',body:JSON.stringify(chatPayload(message,tier))});
    }).then(function(data){
      if(data&&data.conversation_id)researchState.conversationId=data.conversation_id;
      var gen=data&&data.evidence&&data.evidence.generated_at;
      if(gen){researchState.evidenceAt=gen;var em=$('#researchEvidenceMeta');if(em)em.textContent='证据快照 '+String(gen).replace('T',' ').slice(0,16);}
      return data;
    });
  }
  function renderAnswer(data){
    var copy=$('#assistantCopy');if(!copy)return;
    var answer=escapeHtml((data&&data.answer)||'（无回答内容）');
    var meta=$('#researchAssistantMeta');if(meta)meta.textContent=new Date().toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'});
    copy.innerHTML='<div class="research-answer">'+answer+'</div>'+
      '<div class="research-meta">主回答保持精简，右侧五维可深化；结论仅供参考，不构成投资建议。</div>';
  }
  function setResearchBusy(busy){
    researchState.busy=busy;
    var sr=$('#startResearch'),sf=$('#researchSend'),rf=$('#researchFollowup');
    if(sr)sr.disabled=busy;if(sf)sf.disabled=busy;
    if(rf&&busy)rf.setAttribute('disabled','disabled');else if(rf)rf.removeAttribute('disabled');
  }
  function runMainResearch(question){
    if(researchState.busy)return;
    var q=String(question||'').trim();if(!q){toast('请先填写研究问题');return;}
    var t=parseResearchTarget($('#researchTarget')?$('#researchTarget').value:'');
    researchState.symbol=t.symbol;researchState.question=q;
    var full=t.name?(t.name+(t.symbol?('（'+t.symbol+'）'):'')+'：'+q):q;
    var copy=$('#assistantCopy');if(copy)copy.innerHTML='<p class="muted">AI 正在读取证据并生成精简回答…</p>';
    setResearchBusy(true);refreshDimensionAvailability();
    callChat(full,'economy').then(function(data){renderAnswer(data);toast('研究回答已生成');})
      .catch(function(err){if(copy)copy.innerHTML='<p class="muted">生成失败：'+escapeHtml(err.message)+'</p>';toast('研究失败：'+err.message);})
      .then(function(){setResearchBusy(false);refreshDimensionAvailability();});
  }
  function dimStatusEl(dim){var card=document.querySelector('.dimension[data-dim="'+dim+'"]');return card?card.querySelector('.dim-status'):null;}
  function setDimState(dim,st,label){
    var card=document.querySelector('.dimension[data-dim="'+dim+'"]');if(!card)return;
    card.classList.remove('is-running','is-done','is-failed');
    if(st)card.classList.add('is-'+st);
    var s=card.querySelector('.dim-status');if(s)s.textContent=label||'●　未启动';
    var btn=card.querySelector('.dim-start');
    if(btn){btn.textContent=st==='running'?'分析中…':(st==='done'?'查看结果':'启动分析');}
  }
  function buildDimMessage(dim){
    var cfg=DIMENSION_PROMPTS[dim]||{};var t=parseResearchTarget($('#researchTarget')?$('#researchTarget').value:'');
    var target=t.name+(t.symbol?('（'+t.symbol+'）'):'');var question=researchState.question||'';
    if(cfg.template&&cfg.template.trim()){
      return cfg.template.replace(/\{target\}/g,target).replace(/\{question\}/g,question);
    }
    var fallback={
      fundamentals:'请对'+target+'做基本面分析：财务表现、盈利质量、成长能力、经营效率，并说明数据依据与结论边界。',
      technical:'请对'+target+'做技术面分析：趋势、量价结构、关键技术指标与支撑阻力，并说明可确认与不可确认之处。',
      industry:'请对'+target+'做行业分析：行业格局、市场空间、竞争态势与产业链位置，并给出数据依据。',
      valuation:'请对'+target+'做估值分析：当前估值水平、历史分位、相对估值与合理区间，并说明假设与边界。',
      risk:'请对'+target+'做风险分析：经营、财务、政策与市场风险，并区分已发生事实与前瞻判断。'
    };
    return fallback[dim]||('请对'+target+'做'+((DIM_META[dim]||{}).name||dim)+'。');
  }
  function runDimension(dim){
    var t=parseResearchTarget($('#researchTarget')?$('#researchTarget').value:'');
    if(!t.name){toast('请先填写研究标的');return Promise.reject(new Error('no-target'));}
    if(researchState.dims[dim]&&researchState.dims[dim].status==='running')return Promise.resolve();
    var cfg=DIMENSION_PROMPTS[dim]||{};
    researchState.dims[dim]={status:'running'};setDimState(dim,'running','●　正在分析');
    return callChat(buildDimMessage(dim),cfg.model_tier||'deep').then(function(data){
      var answer=(data&&data.answer)||'（无内容）';
      researchState.dims[dim]={status:'done',answer:answer,at:new Date().toISOString()};
      setDimState(dim,'done','●　分析完成');return {dim:dim,answer:answer};
    }).catch(function(err){
      researchState.dims[dim]={status:'failed',error:err.message};
      setDimState(dim,'failed','●　分析失败');throw err;
    });
  }
  function openDimModal(dim){
    var meta=DIM_META[dim]||{name:dim};var rec=researchState.dims[dim]||{};
    $('#researchModalTitle').textContent=meta.name;
    var body=$('#researchModalBody');
    if(rec.status==='done')body.textContent=rec.answer;
    else if(rec.status==='running')body.textContent='正在分析中，请稍候…';
    else if(rec.status==='failed')body.textContent='分析失败：'+(rec.error||'未知错误');
    else body.textContent='尚未启动该维度分析。';
    $('#researchModal').classList.add('show');
  }
  function handleDimClick(dim){
    var rec=researchState.dims[dim]||{};
    if(rec.status==='done'||rec.status==='failed'){openDimModal(dim);
      if(rec.status==='failed')runDimension(dim).then(function(){openDimModal(dim);}).catch(function(){openDimModal(dim);});
      return;}
    if(rec.status==='running'){openDimModal(dim);return;}
    runDimension(dim).then(function(){toast(((DIM_META[dim]||{}).name||dim)+'已完成');openDimModal(dim);})
      .catch(function(err){if(err&&err.message!=='no-target')toast('分析失败：'+err.message);});
  }
  function refreshDimensionAvailability(){
    var t=parseResearchTarget($('#researchTarget')?$('#researchTarget').value:'');
    var enabled=!!t.name;
    document.querySelectorAll('.dimension').forEach(function(card){
      card.classList.toggle('is-disabled',!enabled&&!(researchState.dims[card.getAttribute('data-dim')]||{}).status);
      var btn=card.querySelector('.dim-start');if(btn)btn.disabled=!enabled;
    });
    var pa=$('#startParallelAnalysis');if(pa)pa.disabled=!enabled||researchState.parallel;
  }
  function runParallel(){
    var t=parseResearchTarget($('#researchTarget')?$('#researchTarget').value:'');
    if(!t.name){toast('请先填写研究标的');return;}
    if(researchState.parallel)return;
    researchState.parallel=true;var pa=$('#startParallelAnalysis');if(pa){pa.disabled=true;pa.textContent='并行分析进行中…';}
    toast('五大维度已并行启动');
    var dims=Object.keys(DIM_META);
    Promise.all(dims.map(function(d){return runDimension(d).catch(function(){return null;});})).then(function(){
      researchState.parallel=false;if(pa){pa.disabled=false;pa.textContent='启动并行分析';}
      toast('并行分析完成');refreshDimensionAvailability();
    });
  }
  (function initResearch(){
    document.querySelectorAll('.dim-start').forEach(function(b){
      b.addEventListener('click',function(){handleDimClick(b.getAttribute('data-dim'));});
    });
    $$('.chips .chip').forEach(function(b){b.addEventListener('click',function(){
      var box=$('#researchQuestion');if(box){box.value=b.textContent+'，请给出数据依据和结论边界。';toast('问题已填入研究框');}
    });});
    var sr=$('#startResearch');if(sr)sr.addEventListener('click',function(){runMainResearch($('#researchQuestion')?$('#researchQuestion').value:'');});
    var pa=$('#startParallelAnalysis');if(pa)pa.addEventListener('click',runParallel);
    var rf=$('#researchFollowup'),send=$('#researchSend');
    function sendFollow(){if(!rf)return;var v=rf.value.trim();if(!v){toast('请输入追问内容');return;}rf.value='';runMainResearch(v);}
    if(send)send.addEventListener('click',sendFollow);
    if(rf)rf.addEventListener('keydown',function(e){if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendFollow();}});
    var tgt=$('#researchTarget');if(tgt)tgt.addEventListener('input',refreshDimensionAvailability);
    if(!document.getElementById('researchModal')){
      var modal=document.createElement('div');modal.className='research-modal';modal.id='researchModal';
      modal.innerHTML='<div class="research-modal-card"><div class="research-modal-head"><h3 id="researchModalTitle" style="margin:0">维度分析</h3><button class="research-modal-close" id="researchModalClose" type="button">×</button></div><div class="research-modal-body" id="researchModalBody"></div></div>';
      document.body.appendChild(modal);
      modal.addEventListener('click',function(e){if(e.target===modal)modal.classList.remove('show');});
      $('#researchModalClose').addEventListener('click',function(){modal.classList.remove('show');});
    }
    refreshDimensionAvailability();
  })();

  function setup(canvas){var r=window.devicePixelRatio||1,w=canvas.clientWidth||300,h=canvas.clientHeight||120;canvas.width=w*r;canvas.height=h*r;var c=canvas.getContext('2d');c.setTransform(r,0,0,r,0,0);c.clearRect(0,0,w,h);return {c:c,w:w,h:h}}
  function line(canvas,points,color,fill){
    if(!canvas.offsetParent)return;var s=setup(canvas),c=s.c,w=s.w,h=s.h,arr=points.map(Number),min=Math.min.apply(null,arr),max=Math.max.apply(null,arr),range=max-min||1,pad=4;
    c.beginPath();arr.forEach(function(v,i){var x=pad+i*(w-pad*2)/(arr.length-1),y=h-pad-(v-min)*(h-pad*2)/range;i?c.lineTo(x,y):c.moveTo(x,y)});
    c.strokeStyle=color;c.lineWidth=2;c.lineJoin='round';c.lineCap='round';c.stroke();
    if(fill){c.lineTo(w-pad,h-pad);c.lineTo(pad,h-pad);c.closePath();var g=c.createLinearGradient(0,0,0,h);g.addColorStop(0,color+'2e');g.addColorStop(1,color+'00');c.fillStyle=g;c.fill()}
  }
  function grid(c,w,h,pad){c.strokeStyle='#e7edf6';c.lineWidth=1;for(var i=1;i<5;i++){var y=pad+i*(h-pad*2)/5;c.beginPath();c.moveTo(pad,y);c.lineTo(w-pad,y);c.stroke()}}
  /*
   * 今日观察接口预留
   *
   * 在本脚本执行前设置 window.QSTodayConfig 即可接入真实接口：
   * {
   *   baseURL:'https://your-api.example.com',
   *   headers:{Authorization:'Bearer ...'},
   *   endpoints:{
   *     indexQuote:'/api/v1/market/index-quote',
   *     marketOverview:'/api/v1/market/overview',
   *     industryRotation:'/api/v1/market/industry-rotation',
   *     riseFallDistribution:'/api/v1/market/rise-fall-distribution',
   *     hotThemes:'/api/v1/market/hot-themes',
   *     tradingActivity:'/api/v1/market/trading-activity',
   *     sectorFundFlow:'/api/v1/market/sector-fund-flow'
   *   }
   * }
   *
   * 也可以分别覆盖 window.QSTodayAPI.fetchIndex / fetchMarketOverview /
   * fetchIndustryRotation / fetchRiseFallDistribution / fetchHotThemes /
   * fetchTradingActivity / fetchSectorFundFlow。
   */
  var todayConfig=Object.assign({
    baseURL:'',
    headers:{},
    credentials:'same-origin',
    endpoints:{}
  },window.QSTodayConfig||{});
  todayConfig.endpoints=Object.assign({
    indexQuote:'/api/v1/market/index-quote',
    marketOverview:'/api/v1/market/overview',
    industryRotation:'/api/v1/market/industry-rotation',
    riseFallDistribution:'/api/v1/market/rise-fall-distribution',
    hotThemes:'/api/v1/market/hot-themes',
    tradingActivity:'/api/v1/market/trading-activity',
    sectorFundFlow:'/api/v1/market/sector-fund-flow'
  },todayConfig.endpoints||{});
  var todayDemo={
    indices:[
      {code:'000001.SH',name:'上证主板',value:3426.18,changePct:.68,turnover:3842.56,limitUp:68,limitDown:6,trend:[20,32,29,41,24,27,38,33,44,36,46,48,45,53,48,56,57,72]},
      {code:'399001.SZ',name:'深证主板',value:10894.21,changePct:.92,turnover:4872.35,limitUp:92,limitDown:9,trend:[25,35,29,43,21,28,32,30,39,34,41,45,43,50,46,55,57,65]},
      {code:'399006.SZ',name:'创业板',value:2268.67,changePct:1.35,turnover:2156.74,limitUp:56,limitDown:7,trend:[18,31,28,42,26,24,36,33,43,41,47,53,50,58,56,64,63,66]},
      {code:'000688.SH',name:'科创板',value:1152.34,changePct:1.20,turnover:598.12,limitUp:23,limitDown:3,trend:[30,42,38,51,49,27,31,43,39,29,40,36,44,40,47,43,55,66]}
    ],
    marketOverview:{total:5237,limitUp:239,limitUpRate:4.57,limitDown:25,limitDownRate:.48},
    industryRotation:[
      {rank:1,name:'电子',changePct:2.48,fiveDayChangePct:5.12,turnover:1953.37,trend:[18,20,24,23,30,29,37]},
      {rank:2,name:'电力设备',changePct:2.10,fiveDayChangePct:4.37,turnover:1428.86,trend:[12,15,14,20,22,26,29]},
      {rank:3,name:'有色金属',changePct:1.88,fiveDayChangePct:3.06,turnover:1122.45,trend:[8,15,13,17,19,25,23]},
      {rank:4,name:'医药生物',changePct:1.35,fiveDayChangePct:2.21,turnover:986.12,trend:[8,9,12,11,15,14,18]},
      {rank:5,name:'计算机',changePct:1.12,fiveDayChangePct:2.85,turnover:835.64,trend:[4,8,7,13,12,15,18]}
    ],
    riseFallDistribution:{
      rising:2398,risingRate:45.80,flat:316,flatRate:6.04,falling:2523,fallingRate:48.16,
      bins:[{label:'涨停',count:68,type:'up'},{label:'>7%',count:317,type:'up'},{label:'3~7%',count:625,type:'up'},{label:'0~3%',count:1388,type:'up'},{label:'平盘',count:316,type:'flat'},{label:'0~-3%',count:1476,type:'down'},{label:'-3~-7%',count:786,type:'down'},{label:'<-7%',count:236,type:'down'},{label:'跌停',count:25,type:'down'}]
    },
    hotThemes:[
      {rank:1,name:'AI算力',changePct:3.21,leader:'中际旭创',tags:['算力','光模块']},
      {rank:2,name:'机器人',changePct:2.75,leader:'埃斯顿',tags:['人形机器人','执行器']},
      {rank:3,name:'固态电池',changePct:2.33,leader:'当升科技',tags:['固态电池','电池材料']},
      {rank:4,name:'消费电子',changePct:1.98,leader:'立讯精密',tags:['苹果链','AI终端']},
      {rank:5,name:'低空经济',changePct:1.74,leader:'万丰奥威',tags:['eVTOL','通航制造']}
    ],
    tradingActivity:{period:'近7日',average:12460,changePct:8.10,points:[{date:'5/13',value:12846},{date:'5/14',value:12102},{date:'5/15',value:11635},{date:'5/16',value:12987},{date:'5/19',value:13421},{date:'5/20',value:12758},{date:'5/21',value:13469}]},
    sectorFundFlow:[
      {name:'电子',value:48.72},{name:'电力设备',value:36.41},{name:'计算机',value:23.87},{name:'医药生物',value:18.34},{name:'有色金属',value:14.62},{name:'银行',value:-15.42},{name:'非银金融',value:-19.83},{name:'食品饮料',value:-22.17},{name:'房地产',value:-28.56},{name:'交通运输',value:-31.24}
    ]
  };
  function todayRequest(endpoint,params){
    var url=new URL(endpoint,todayConfig.baseURL),headers=typeof todayConfig.headers==='function'?todayConfig.headers():todayConfig.headers;
    Object.keys(params||{}).forEach(function(key){if(params[key]!==undefined&&params[key]!==null)url.searchParams.set(key,params[key])});
    return fetch(url.toString(),{method:'GET',headers:headers||{},credentials:todayConfig.credentials}).then(function(response){
      if(!response.ok)throw new Error('今日观察接口请求失败：'+response.status);
      return response.json();
    }).then(function(payload){return payload&&payload.data!==undefined?payload.data:payload});
  }
  window.QSTodayAPI=window.QSTodayAPI||{
    fetchIndex:function(params){
      if(!todayConfig.baseURL)return Promise.resolve(todayDemo.indices.find(function(item){return item.code===params.code}));
      return todayRequest(todayConfig.endpoints.indexQuote,params);
    },
    fetchMarketOverview:function(){
      if(!todayConfig.baseURL)return Promise.resolve(todayDemo.marketOverview);
      return todayRequest(todayConfig.endpoints.marketOverview);
    },
    fetchIndustryRotation:function(){
      if(!todayConfig.baseURL)return Promise.resolve(todayDemo.industryRotation);
      return todayRequest(todayConfig.endpoints.industryRotation,{standard:'SW1',limit:5});
    },
    fetchRiseFallDistribution:function(){
      if(!todayConfig.baseURL)return Promise.resolve(todayDemo.riseFallDistribution);
      return todayRequest(todayConfig.endpoints.riseFallDistribution);
    },
    fetchHotThemes:function(){
      if(!todayConfig.baseURL)return Promise.resolve(todayDemo.hotThemes);
      return todayRequest(todayConfig.endpoints.hotThemes,{limit:5});
    },
    fetchTradingActivity:function(){
      if(!todayConfig.baseURL)return Promise.resolve(todayDemo.tradingActivity);
      return todayRequest(todayConfig.endpoints.tradingActivity,{days:7});
    },
    fetchSectorFundFlow:function(){
      if(!todayConfig.baseURL)return Promise.resolve(todayDemo.sectorFundFlow);
      return todayRequest(todayConfig.endpoints.sectorFundFlow,{limit:10});
    }
  };
  function escapeHTML(value){return String(value===undefined||value===null?'':value).replace(/[&<>"']/g,function(char){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]})}
  var escapeHtml=escapeHTML;
  function numberText(value,digits){if(value===undefined||value===null||value==='')return '--';var n=Number(value);return Number.isFinite(n)?n.toLocaleString('zh-CN',{minimumFractionDigits:digits||0,maximumFractionDigits:digits||0}):'--'}
  function signedText(value,suffix,digits){var n=Number(value);if(!Number.isFinite(n))return '--';return (n>0?'+':'')+numberText(n,digits===undefined?2:digits)+(suffix||'')}
  function trendClass(value){return Number(value)>=0?'up':'down'}
  function unwrapList(value){if(Array.isArray(value))return value;if(value&&Array.isArray(value.items))return value.items;if(value&&Array.isArray(value.list))return value.list;return []}
  /*
   * 个股评分库“新闻资讯 / AI精选”接口预留
   *
   * 在本脚本执行前配置：
   * window.QSStockIntelConfig = {
   *   baseURL:'https://your-api.example.com',
   *   symbol:'300750.SZ',
   *   headers:{Authorization:'Bearer ...'},
   *   endpoints:{
   *     news:'/api/v1/stocks/news',
   *     curatedInsights:'/api/v1/stocks/curated-insights',
   *     adminPush:'/api/v1/admin/stocks/curated-insights'
   *   },
   *   allowedProtocols:['http:','https:']
   * };
   *
   * 新闻接口返回：[{id,title,source,category,publishedAt,url,appUrl}, ...]
   * appUrl 可用于唤起东方财富、同花顺等客户端；需把对应协议加入 allowedProtocols。
   * AI精选接口返回：[{id,type,title,summary,source,publishedAt,priority,isTop}, ...]
   * 管理后台可向 adminPush 对应接口 POST，前台再调用 QSReloadStockIntelligence() 刷新。
   * 也可以直接覆盖 window.QSStockIntelAPI.fetchNews / fetchCuratedInsights。
   */
  var stockIntelConfig=Object.assign({
    baseURL:'',symbol:'300750.SZ',headers:{},credentials:'same-origin',allowedProtocols:['http:','https:'],endpoints:{}
  },window.QSStockIntelConfig||{});
  stockIntelConfig.endpoints=Object.assign({
    news:'/api/v1/stocks/news',
    curatedInsights:'/api/v1/stocks/curated-insights',
    adminPush:'/api/v1/admin/stocks/curated-insights'
  },stockIntelConfig.endpoints||{});
  function stockIntelRequest(endpoint,params){
    var url=new URL(endpoint,stockIntelConfig.baseURL),headers=typeof stockIntelConfig.headers==='function'?stockIntelConfig.headers():stockIntelConfig.headers;
    Object.keys(params||{}).forEach(function(key){if(params[key]!==undefined&&params[key]!==null)url.searchParams.set(key,params[key])});
    return fetch(url.toString(),{method:'GET',headers:headers||{},credentials:stockIntelConfig.credentials}).then(function(response){
      if(!response.ok)throw new Error('个股资讯接口请求失败：'+response.status);
      return response.json();
    }).then(function(payload){return payload&&payload.data!==undefined?payload.data:payload});
  }
  var stockIntelDefaults={
    fetchNews:function(params){if(!stockIntelConfig.baseURL)return Promise.resolve([]);return stockIntelRequest(stockIntelConfig.endpoints.news,params)},
    fetchCuratedInsights:function(params){if(!stockIntelConfig.baseURL)return Promise.resolve([]);return stockIntelRequest(stockIntelConfig.endpoints.curatedInsights,params)}
  };
  window.QSStockIntelAPI=Object.assign(stockIntelDefaults,window.QSStockIntelAPI||{});
  function trustedStockLink(value){
    if(!value)return '#';
    try{var parsed=new URL(value,location.href);return stockIntelConfig.allowedProtocols.indexOf(parsed.protocol)>-1?parsed.href:'#'}catch(error){return '#'}
  }
  function sourceStyle(source){source=String(source||'');if(source.indexOf('同花顺')>-1)return {label:'同花',className:'ths'};if(source.indexOf('财联社')>-1)return {label:'财联',className:'cls'};if(source.indexOf('证券时报')>-1)return {label:'证券',className:'stcn'};return {label:'东财',className:''}}
  function insightPillClass(type){type=String(type||'');if(type.indexOf('政策')>-1)return 'purple';if(type.indexOf('行业')>-1)return 'green';if(type.indexOf('公司')>-1)return 'orange';return 'blue'}
  function renderStockNews(payload){
    var list=$('#stockNewsList'),items=unwrapList(payload);if(!list)return;
    if(!items.length){list.innerHTML='<div class="empty-state">暂时没有可展示的外部新闻</div>';return}
    list.innerHTML=items.map(function(item){var source=sourceStyle(item.source),target=trustedStockLink(item.appUrl)||'#';if(target==='#')target=trustedStockLink(item.url);return '<a class="news-item" href="'+escapeHTML(target)+'" target="_blank" rel="noopener noreferrer" data-news-id="'+escapeHTML(item.id)+'"><span class="source-mark '+source.className+'">'+source.label+'</span><span class="news-copy"><b class="news-title">'+escapeHTML(item.title)+'</b><span class="news-meta"><span>'+escapeHTML(item.source)+'</span><span>'+escapeHTML(item.category||'个股资讯')+'</span><time>'+escapeHTML(item.publishedAt||'--')+'</time></span></span><span class="external-arrow">↗</span></a>'}).join('');
  }
  function renderStockInsights(payload){
    var list=$('#stockInsightList'),items=unwrapList(payload);if(!list)return;
    if(!items.length){list.innerHTML='<div class="empty-state">管理员暂未推送AI精选内容</div>';return}
    list.innerHTML=items.map(function(item){var top=item.isTop||item.priority==='high';return '<article class="insight-item'+(top?' priority':'')+'" data-insight-id="'+escapeHTML(item.id)+'"><div class="insight-top"><span class="pill '+insightPillClass(item.type)+'">'+escapeHTML(item.type||'AI精选')+'</span><span class="admin-badge">● 已推送</span></div><h4 class="insight-title">'+escapeHTML(item.title)+'</h4><p class="insight-summary">'+escapeHTML(item.summary)+'</p><div class="insight-foot"><span>'+escapeHTML(item.source||'AI综合分析')+'</span><time>'+escapeHTML(item.publishedAt||'--')+'</time></div></article>'}).join('');
  }
  window.QSUpdateStockIntelligence=function(payload){payload=payload||{};if(payload.news)renderStockNews(payload.news);if(payload.curatedInsights)renderStockInsights(payload.curatedInsights);return payload};
  window.QSReloadStockIntelligence=function(options){
    options=Object.assign({symbol:stockIntelConfig.symbol},options||{});
    return Promise.allSettled([
      Promise.resolve(window.QSStockIntelAPI.fetchNews(options)).then(renderStockNews),
      Promise.resolve(window.QSStockIntelAPI.fetchCuratedInsights(options)).then(renderStockInsights)
    ]);
  };
  var todayRenderers={
    indices:function(items){
      unwrapList(items).forEach(function(item){
        var card=document.querySelector('[data-index-code="'+item.code+'"]');if(!card)return;var ps=card.querySelectorAll('p'),feet=card.querySelectorAll('.index-foot b'),canvas=card.querySelector('canvas'),change=Number(item.changePct);
        card.querySelector('h3').textContent=item.name||item.code;card.querySelector('strong').textContent=numberText(item.value,2);card.querySelector('strong').className=trendClass(change);
        if(ps[0]){ps[0].textContent=signedText(change,'%',2);ps[0].className=trendClass(change)}if(ps[1])ps[1].textContent='成交额 '+numberText(item.turnover,2)+' 亿元';
        if(feet[0])feet[0].textContent=numberText(item.limitUp,0);if(feet[1])feet[1].textContent=numberText(item.limitDown,0);
        if(canvas&&Array.isArray(item.trend)&&item.trend.length>1){canvas.setAttribute('data-points',item.trend.join(','));canvas.setAttribute('data-color',change>=0?'#f3262d':'#079a56');line(canvas,item.trend,change>=0?'#f3262d':'#079a56',true)}
      });
    },
    marketOverview:function(data){
      var card=$('#marketOverviewCard');if(!card||!data)return;var sides=card.querySelectorAll('.overview-wrap>div'),total=Number(data.total)||0,risingRate=Number(data.risingRate)||0,flatRate=Number(data.flatRate)||0,flatEnd=Math.min(100,risingRate+flatRate),donut=card.querySelector('.donut'),meta=$('#marketOverviewMeta');
      if(sides[0]){sides[0].querySelector('strong').textContent=numberText(data.rising,0);sides[0].querySelector('small').textContent=numberText(risingRate,2)+'%'}
      card.querySelector('.donut-center strong').textContent=numberText(total,0);
      if(sides[2]){sides[2].querySelector('strong').textContent=numberText(data.falling,0);sides[2].querySelector('small').textContent=numberText(data.fallingRate,2)+'%'}
      donut.style.background='conic-gradient(#f3262d 0 '+risingRate+'%,#d6dbe4 '+risingRate+'% '+flatEnd+'%,#079a56 '+flatEnd+'% 100%)';
      if(meta)meta.textContent='市场快照 '+(data.marketDate||'--')+'：平盘 '+numberText(data.flat,0)+' 只（'+numberText(data.flatRate,2)+'%） · 涨停 '+numberText(data.limitUp,0)+' / 跌停 '+numberText(data.limitDown,0)+'（涨跌停截至 '+(data.limitDataAsOf||'--')+'）';
    },
    industryRotation:function(items){
      var list=$('#industryRotationList');if(!list)return;list.innerHTML=unwrapList(items).map(function(item,index){var change=Number(item.changePct),five=Number(item.fiveDayChangePct),trend=Array.isArray(item.trend)&&item.trend.length>1?item.trend:[0,change];return '<div class="rank-row"><i class="rank-no">'+escapeHTML(item.rank||index+1)+'</i><b>'+escapeHTML(item.name)+'</b><span class="'+trendClass(change)+'">'+signedText(change,'%',2)+'</span><canvas class="sparkline mini-line" data-color="'+(change>=0?'#f3262d':'#079a56')+'" data-points="'+trend.map(Number).join(',')+'"></canvas><span class="'+trendClass(five)+'">'+signedText(five,'%',2)+'</span><span>'+numberText(item.turnover,2)+'</span></div>'}).join('');list.querySelectorAll('canvas').forEach(function(canvas){line(canvas,canvas.getAttribute('data-points').split(','),canvas.getAttribute('data-color'),false)});
    },
    riseFallDistribution:function(data){
      var card=$('#riseFallCard');if(!card||!data)return;var head=card.querySelector('.dist-head'),chart=card.querySelector('.dist-chart'),bins=unwrapList(data.bins),max=Math.max.apply(null,bins.map(function(item){return Number(item.count)||0}).concat([1]));
      head.innerHTML='<span>上涨　<b class="up">'+numberText(data.rising,0)+'</b>　'+numberText(data.risingRate,2)+'%</span><span>平盘　<b>'+numberText(data.flat,0)+'</b>　'+numberText(data.flatRate,2)+'%</span><span>下跌　<b class="down">'+numberText(data.falling,0)+'</b>　'+numberText(data.fallingRate,2)+'%</span>';
      chart.innerHTML=bins.map(function(item){var type=item.type==='down'?' green':item.type==='flat'?' gray':'';return '<div class="dist-col'+type+'"><b>'+numberText(item.count,0)+'</b><i style="height:'+Math.max(4,(Number(item.count)||0)/max*88)+'%"></i><small>'+escapeHTML(item.label)+'</small></div>'}).join('');
    },
    hotThemes:function(items){
      var list=$('#hotThemesList');if(!list)return;list.innerHTML=unwrapList(items).map(function(item,index){var change=Number(item.changePct),tags=unwrapList(item.tags).map(function(tag){return '<span class="pill blue">'+escapeHTML(tag)+'</span>'}).join(' ');return '<div class="rank-row" style="grid-template-columns:30px 86px 65px 1fr"><i class="rank-no">'+escapeHTML(item.rank||index+1)+'</i><b>'+escapeHTML(item.name)+'</b><span class="'+trendClass(change)+'">'+signedText(change,'%',2)+'</span><span>'+escapeHTML(item.leader)+'　 '+tags+'</span></div>'}).join('');
    },
    tradingActivity:function(data){
      var card=$('#tradingActivityCard');if(!card||!data)return;var points=unwrapList(data.points),max=Math.max.apply(null,points.map(function(item){return Number(item.value)||0}).concat([1])),bar=card.querySelector('.bar-chart'),summary=card.querySelector('.chart-summary'),period=card.querySelector('.card-title .muted');
      if(period)period.textContent=(data.period||'近7日')+'　⌄';
      bar.innerHTML=points.map(function(item,index){return '<div><b>'+numberText(item.value,0)+'</b><i style="height:'+Math.max(8,(Number(item.value)||0)/max*88)+'%;'+(index===points.length-1?'background:linear-gradient(#2076fa,#0e62eb)':'')+'"></i><small>'+escapeHTML(item.date)+'</small></div>'}).join('');
      summary.innerHTML='<span>'+escapeHTML(data.period||'近7日')+'平均成交额　<b class="blue" style="font-size:18px">'+numberText(data.average,0)+'</b> 亿元</span><span>较前周期　<b class="'+trendClass(data.changePct)+'">'+signedText(data.changePct,'%',2)+'</b></span>';
    },
    sectorFundFlow:function(items){
      var list=$('#sectorFundFlowList');if(!list)return;items=unwrapList(items);var max=Math.max.apply(null,items.map(function(item){return Math.abs(Number(item.value)||0)}).concat([1]));list.innerHTML=items.map(function(item){var value=Number(item.value)||0,positive=value>=0;return '<div class="flow-row"><span>'+escapeHTML(item.name)+'</span><div class="flowbar '+(positive?'positive':'negative')+'"><span class="flow-axis"></span><i style="width:'+Math.max(2,Math.abs(value)/max*48)+'%"></i></div><b class="'+trendClass(value)+'">'+signedText(value,'',2)+'</b></div>'}).join('');
    }
  };
  var todayLoaders={
    indices:function(){return Promise.all(todayDemo.indices.map(function(item){return window.QSTodayAPI.fetchIndex({code:item.code})})).then(todayRenderers.indices)},
    marketOverview:function(){return Promise.resolve(window.QSTodayAPI.fetchMarketOverview()).then(todayRenderers.marketOverview)},
    industryRotation:function(){return Promise.resolve(window.QSTodayAPI.fetchIndustryRotation()).then(todayRenderers.industryRotation)},
    riseFallDistribution:function(){return Promise.resolve(window.QSTodayAPI.fetchRiseFallDistribution()).then(todayRenderers.riseFallDistribution)},
    hotThemes:function(){return Promise.resolve(window.QSTodayAPI.fetchHotThemes()).then(todayRenderers.hotThemes)},
    tradingActivity:function(){return Promise.resolve(window.QSTodayAPI.fetchTradingActivity()).then(todayRenderers.tradingActivity)},
    sectorFundFlow:function(){return Promise.resolve(window.QSTodayAPI.fetchSectorFundFlow()).then(todayRenderers.sectorFundFlow)}
  };
  window.QSUpdateTodayDashboard=function(payload){
    Object.keys(payload||{}).forEach(function(key){if(todayRenderers[key])todayRenderers[key](payload[key])});
    return payload;
  };
  window.QSReloadTodayCard=function(cardName){
    if(!todayLoaders[cardName])return Promise.reject(new Error('未知的今日观察卡片：'+cardName));
    return todayLoaders[cardName]().catch(function(error){console.warn(error);throw error});
  };
  window.QSReloadTodayDashboard=function(){
    var status=$('#todayDataStatus');
    if(status)status.textContent='正在更新市场数据…';
    return Promise.allSettled(Object.keys(todayLoaders).map(function(key){return todayLoaders[key]()})).then(function(results){
      var success=results.filter(function(item){return item.status==='fulfilled'}).length;
      if(status)status.textContent=success===results.length?'市场数据已更新 · '+new Date().toLocaleTimeString('zh-CN',{hour12:false}):'已更新 '+success+'/'+results.length+' 个数据模块，其余模块稍后重试';
      return results;
    });
  };
  var stockConfig=Object.assign({
    baseURL:window.location.origin,
    credentials:'same-origin',
    endpoints:{}
  },window.QSStockConfig||{});
  stockConfig.endpoints=Object.assign({
    search:'/api/v1/stocks/search',
    scoreCard:'/api/v1/stocks/{symbol}/score-card',
    industryComparison:'/api/v1/stocks/{symbol}/industry-comparison',
    kline:'/api/v1/market/kline'
  },stockConfig.endpoints||{});
  var stockState={symbol:'300750.SZ',name:'宁德时代',searchItems:[],activeSearchIndex:-1,searchSequence:0,loadSequence:0,loading:false};
  var topMetricComparisonState={series:[]};
  function stockRequest(endpoint,params){
    var url=new URL(endpoint,stockConfig.baseURL);
    Object.keys(params||{}).forEach(function(key){if(params[key]!==undefined&&params[key]!==null)url.searchParams.set(key,params[key])});
    return fetch(url.toString(),{method:'GET',credentials:stockConfig.credentials}).then(function(response){
      if(!response.ok)return response.json().catch(function(){return {}}).then(function(body){throw new Error(body.detail||('请求失败：'+response.status))});
      return response.json();
    });
  }
  function stockEndpoint(template,symbol){return String(template).replace('{symbol}',encodeURIComponent(symbol))}
  function setStockField(name,value){
    $$('[data-stock-field="'+name+'"]').forEach(function(node){node.textContent=value===undefined||value===null||value===''?'--':String(value)});
  }
  function stockMoney(value){
    var amount=Number(value);return Number.isFinite(amount)?numberText(amount/100000000,2)+' 亿':'--';
  }
  function stockVolume(value){
    var shares=Number(value);return Number.isFinite(shares)?numberText(shares/1000000,2)+' 万手':'--';
  }
  function stockTime(value){
    if(!value)return '--';var date=new Date(value);if(Number.isNaN(date.getTime()))return String(value);
    return date.toLocaleString('zh-CN',{hour12:false,month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});
  }
  function stockMetric(name,value,suffix){
    $$('[data-stock-metric="'+name+'"]').forEach(function(node){var number=value===null||value===undefined||value===''?NaN:Number(value);node.textContent=Number.isFinite(number)?numberText(number,2)+(suffix||''):'--'});
  }
  function renderStockCard(data){
    var identity=data.identity||{},quote=data.quote||{},metrics=data.metrics||{},change=Number(quote.changePct),changeValue=Number(quote.change),price=Number(quote.price),priceNode=document.querySelector('[data-stock-field="price"]');
    stockState.symbol=data.symbol||stockState.symbol;stockState.name=identity.name||stockState.symbol;
    setStockField('name',stockState.name);setStockField('symbol',stockState.symbol);setStockField('market',identity.market||'A股');setStockField('industry',identity.industry||'行业待更新');setStockField('intelSymbol',stockState.name+' '+stockState.symbol);
    if(priceNode){
      priceNode.className='quote '+(Number.isFinite(change)?trendClass(change):'');
      priceNode.innerHTML=(Number.isFinite(price)?numberText(price,2):'--')+' <small>'+(Number.isFinite(changeValue)?signedText(changeValue,'',2):'--')+'　'+(Number.isFinite(change)?signedText(change,'%',2):'--')+'</small>';
    }
    setStockField('quoteMeta','最新行情　'+stockTime(quote.marketTimestamp)+'　数据来源：'+(quote.source||'后端聚合接口'));
    setStockField('open',numberText(quote.open,2));setStockField('previousClose',numberText(quote.previousClose,2));setStockField('turnoverRatePct',quote.turnoverRatePct===null||quote.turnoverRatePct===undefined?'--':numberText(quote.turnoverRatePct,2)+'%');
    setStockField('high',numberText(quote.high,2));setStockField('low',numberText(quote.low,2));setStockField('heroPeTtm',numberText(metrics.peTtm,2));setStockField('volumeShares',stockVolume(quote.volumeShares));setStockField('amountCny',stockMoney(quote.amountCny));setStockField('totalMarketCapCny',stockMoney(quote.totalMarketCapCny));
    stockMetric('peTtm',metrics.peTtm,'');stockMetric('pbLf',metrics.pbLf,'');stockMetric('roeWeightedReport',metrics.roeWeightedReport,'%');stockMetric('revenueYoy',metrics.revenueYoy,'%');stockMetric('parentNetProfitYoy',metrics.parentNetProfitYoy,'%');
    setStockField('reportName',metrics.reportName||metrics.reportDate||'最新财报');
    setStockField('valuationSource','估值：'+(metrics.valuationSource||'暂不可用')+' · '+stockTime(metrics.valuationTimestamp));
    setStockField('financialSource','财务：'+(metrics.financialSource||'暂不可用'));
    setStockField('reportBasis','报告期：'+(metrics.reportName||metrics.reportDate||'--')+(metrics.periodBasis==='year_to_date_cumulative'?' · 年初至报告期累计':''));
    setStockField('statusTitle','真实数据已更新');
    setStockField('statusTime','行情时间 '+stockTime(quote.marketTimestamp));
    var warnings=unwrapList(data.warnings);setStockField('warningSummary',warnings.length?warnings.slice(0,2).join('；'):'暂无额外提示');
    var status=$('#stockDataStatus');if(status){status.classList.remove('stock-error');status.textContent=stockState.name+' · '+stockState.symbol+' · 数据更新于 '+new Date().toLocaleTimeString('zh-CN',{hour12:false})}
    var priceChartNode=$('#priceChart'),volumeChartNode=$('#volumeChart');if(priceChartNode)priceChartNode.setAttribute('aria-label',stockState.name+'K线图');if(volumeChartNode)volumeChartNode.setAttribute('aria-label',stockState.name+'成交量图');
    stockIntelConfig.symbol=stockState.symbol;
  }
  function industryNumber(value,digits){
    var number=Number(value);return Number.isFinite(number)?numberText(number,digits===undefined?2:digits):'--';
  }
  function industryFactorStateClass(factor){
    return factor&&factor.status==='available'?'':factor&&factor.score!==null&&factor.score!==undefined?'partial':'unavailable';
  }
  function comparisonShortLabel(metric){
    return {
      peTtm:'PE (TTM)',
      pbLf:'PB (LF)',
      roeWeightedReport:'加权ROE',
      revenueYoy:'营收同比',
      parentNetProfitYoy:'净利润同比'
    }[metric.key]||metric.label||metric.key;
  }
  function drawTopMetricComparison(){
    var cv=$('#topMetricComparisonChart'),series=topMetricComparisonState.series||[];
    if(!cv||!cv.offsetParent)return;
    var s=setup(cv),c=s.c,w=s.w,h=s.h;
    if(!series.length){c.fillStyle='#8b99ad';c.font='12px Microsoft YaHei';c.textAlign='center';c.fillText('同行统计数据暂不可用',w/2,h/2);return}
    var left=8,right=8,top=25,bottom=h-40,plotHeight=Math.max(50,bottom-top),groupWidth=(w-left-right)/series.length,colors=['#1768ef','#72a7f5','#10a25d'];
    c.font='9px Microsoft YaHei';c.textAlign='center';c.textBaseline='middle';
    series.forEach(function(metric,index){
      var groupLeft=left+index*groupWidth,groupCenter=groupLeft+groupWidth/2,values=[metric.subject,metric.industryMedian,metric.industryP75].map(function(value){var number=Number(value);return Number.isFinite(number)?number:null}),valid=values.filter(function(value){return value!==null});
      c.fillStyle=index%2?'rgba(245,248,253,.58)':'rgba(251,253,255,.68)';c.fillRect(groupLeft+2,top-9,groupWidth-4,plotHeight+18);
      if(!valid.length){c.fillStyle='#9aa7b9';c.fillText('--',groupCenter,top+plotHeight/2)}
      else{
        var min=Math.min.apply(null,[0].concat(valid)),max=Math.max.apply(null,[0].concat(valid));if(max===min){max=min+1}
        var zeroY=top+(max/(max-min))*plotHeight,barWidth=Math.max(7,Math.min(13,(groupWidth-18)/3)),gap=Math.max(2,Math.min(5,barWidth*.34)),clusterWidth=barWidth*3+gap*2,startX=groupCenter-clusterWidth/2;
        c.strokeStyle='#dce5f1';c.lineWidth=1;c.beginPath();c.moveTo(groupLeft+7,zeroY+.5);c.lineTo(groupLeft+groupWidth-7,zeroY+.5);c.stroke();
        values.forEach(function(value,valueIndex){
          var x=startX+valueIndex*(barWidth+gap);if(value===null){c.fillStyle='#aab5c4';c.fillText('--',x+barWidth/2,zeroY-8);return}
          var valueY=top+(max-value)/(max-min)*plotHeight,barTop=Math.min(valueY,zeroY),barHeight=Math.max(2,Math.abs(zeroY-valueY));c.fillStyle=colors[valueIndex];c.fillRect(x,barTop,barWidth,barHeight);
          c.fillStyle='#526680';var label=numberText(value,Math.abs(value)>=100?0:1);var labelY=value>=0?Math.max(8,barTop-7):Math.min(h-30,barTop+barHeight+8);c.fillText(label,x+barWidth/2,labelY);
        });
      }
      c.fillStyle='#243957';c.font='10px Microsoft YaHei';c.fillText(comparisonShortLabel(metric),groupCenter,h-17);c.font='9px Microsoft YaHei';
    });
  }
  function renderTopMetricComparison(payload){
    payload=payload||{};topMetricComparisonState.series=unwrapList(payload.series);
    var status=$('#valuationCompareStatus'),meta=$('#valuationCompareMeta'),available=topMetricComparisonState.series.filter(function(item){return item.status==='available'}).length,samples=topMetricComparisonState.series.map(function(item){return Number(item.sampleSize)||0}).filter(Boolean);
    if(status){status.className='pill '+(available===5?'green':'');status.textContent=available===5?'真实数据':'部分可用'}
    if(meta)meta.textContent=(payload.industryName||'申万二级同行')+' · 有效样本 '+(samples.length?Math.min.apply(null,samples):0)+'–'+(samples.length?Math.max.apply(null,samples):0)+' 家 · 估值 '+(payload.valuationTradeDate||'--')+' · 财报 '+(payload.financialReportPeriod||'--');
    setTimeout(drawTopMetricComparison,0);
  }
  function setIndustryLoading(){
    var card=$('#industryFactorCard'),status=$('#industryFactorStatus'),body=$('#industryFactorBody');
    if(card)card.classList.add('industry-factor-loading');if(body)body.setAttribute('aria-busy','true');
    if(status){status.className='pill';status.textContent='正在计算'}
    var compareStatus=$('#valuationCompareStatus'),compareMeta=$('#valuationCompareMeta');topMetricComparisonState.series=[];if(compareStatus){compareStatus.className='pill';compareStatus.textContent='正在加载'}if(compareMeta)compareMeta.textContent='正在读取申万二级同行统计…';
    var meta=$('#industryFactorMeta');if(meta)meta.textContent='正在匹配申万二级同行并计算五个维度…';
    var item=$('#industryStatusItem');if(item){item.className='stock-status-item pending';item.textContent='行业五维对比正在计算'}
  }
  function renderIndustryComparison(data){
    var factors=unwrapList(data.factors),industry=data.industry||{},coverage=data.coverage||{},radarData=data.radar||{},card=$('#industryFactorCard'),body=$('#industryFactorBody'),status=$('#industryFactorStatus');
    if(card)card.classList.remove('industry-factor-loading');if(body)body.setAttribute('aria-busy','false');
    if(status){status.className='pill '+(data.status==='available'?'green':'');status.textContent=data.status==='available'?'真实数据已更新':'部分数据可用'}
    setStockField('industry',industry.name||industry.l1Name||'行业待更新');
    var meta=$('#industryFactorMeta'),dateNode=$('#industryFactorDate');
    if(meta)meta.textContent=(industry.name||'申万二级行业')+' · '+industryNumber(coverage.industryMembers,0)+' 家同行 · '+industryNumber(coverage.availableFactors,0)+' / '+industryNumber(coverage.totalFactors,0)+' 个维度可评分';
    if(dateNode)dateNode.textContent='财报 '+(data.reportPeriod||'--')+' · 估值 '+(data.valuationTradeDate||'--');
    renderTopMetricComparison(data.topMetricComparison);
    var radarCanvas=$('#industryFactorRadar'),scores=unwrapList(radarData.subject).map(function(value){var number=Number(value);return Number.isFinite(number)?Math.max(0,Math.min(100,number)):0});
    if(radarCanvas){radarCanvas.setAttribute('data-labels',unwrapList(radarData.labels).join(',')||'成长性,估值水平,盈利能力,财务稳健性,经营效率');radarCanvas.setAttribute('data-values',scores.join(','));radarCanvas.setAttribute('data-values2','50,50,50,50,50');radar(radarCanvas)}
    var cards=$('#industryFactorCards');
    if(cards)cards.innerHTML=factors.map(function(factor){
      var available=factor.score!==null&&factor.score!==undefined;
      return '<article class="industry-factor-score '+industryFactorStateClass(factor)+'"><span>'+escapeHTML(factor.label||factor.key)+'</span><strong>'+(available?industryNumber(factor.score,1):'--')+' <small>/ 100</small></strong><p>'+escapeHTML(factor.state||'数据不足')+' · 覆盖 '+industryNumber(factor.coveragePct,0)+'%</p></article>';
    }).join('')||'<div class="industry-factor-empty">暂无可展示的维度数据</div>';
    var warnings=unwrapList(data.warnings),note=$('#industryFactorNote');
    if(note)note.textContent='分数表示公司在同一申万二级行业内的相对位置，50分约为行业中位。'+(warnings.length?' '+warnings[0]:'');
    var item=$('#industryStatusItem');if(item){item.className='stock-status-item '+(data.status==='available'?'ok':'pending');item.textContent=(data.status==='available'?'✓ ':'')+'行业五维对比使用申万二级同行真实数据'}
  }
  function renderIndustryComparisonError(error){
    var card=$('#industryFactorCard'),body=$('#industryFactorBody'),status=$('#industryFactorStatus'),meta=$('#industryFactorMeta'),cards=$('#industryFactorCards'),compareStatus=$('#valuationCompareStatus'),compareMeta=$('#valuationCompareMeta');
    if(card)card.classList.remove('industry-factor-loading');if(body)body.setAttribute('aria-busy','false');
    if(status){status.className='pill';status.textContent='暂不可用'}if(meta)meta.textContent='五维行业对比暂不可用：'+error.message;
    if(cards)cards.innerHTML='<div class="industry-factor-empty">没有使用模拟分数，请稍后刷新真实数据</div>';
    topMetricComparisonState.series=[];if(compareStatus){compareStatus.className='pill';compareStatus.textContent='暂不可用'}if(compareMeta)compareMeta.textContent='估值对比暂不可用：'+error.message;drawTopMetricComparison();
    var item=$('#industryStatusItem');if(item){item.className='stock-status-item pending';item.textContent='行业五维对比暂不可用'}
  }
  function loadIndustryComparison(symbol,options){
    options=options||{};
    return stockRequest(stockEndpoint(stockConfig.endpoints.industryComparison,symbol),{refresh:options.refresh===true}).then(function(data){
      if(options.loadSequence&&options.loadSequence!==stockState.loadSequence)return null;
      renderIndustryComparison(data);return data;
    }).catch(function(error){
      if(!options.loadSequence||options.loadSequence===stockState.loadSequence)renderIndustryComparisonError(error);
      throw error;
    });
  }
  function updateStockURL(){
    try{var url=new URL(location.href);url.searchParams.set('symbol',stockState.symbol);url.hash='score';history.replaceState(null,'',url.toString())}catch(error){}
  }
  function loadStock(symbol,options){
    options=options||{};if(stockState.loading&&!options.force)return Promise.resolve(null);
    var loadSequence=++stockState.loadSequence;stockState.loading=true;stockState.symbol=symbol||stockState.symbol;var hero=$('#stockHero'),status=$('#stockDataStatus');if(hero)hero.classList.add('stock-loading');setIndustryLoading();if(status){status.classList.remove('stock-error');status.textContent='正在加载 '+stockState.symbol+' 的真实行情、财务与行业对比数据…'}
    return stockRequest(stockEndpoint(stockConfig.endpoints.scoreCard,stockState.symbol)).then(function(data){
      if(loadSequence!==stockState.loadSequence)return null;
      renderStockCard(data);if($('#page-score').classList.contains('active'))updateStockURL();klineState.symbol=stockState.symbol;
      return Promise.allSettled([loadKline(klineState.period||'1d',{force:options.refresh===true}),loadIndustryComparison(stockState.symbol,{refresh:options.refresh===true,loadSequence:loadSequence})]);
    }).catch(function(error){
      if(loadSequence!==stockState.loadSequence)return null;
      if(status){status.classList.add('stock-error');status.textContent='个股数据暂不可用：'+error.message}setStockField('statusTitle','数据加载失败');setStockField('warningSummary',error.message);throw error;
    }).finally(function(){if(loadSequence===stockState.loadSequence){stockState.loading=false;if(hero)hero.classList.remove('stock-loading')}});
  }
  window.QSLoadStock=loadStock;
  function hideStockSearch(){
    var results=$('#stockSearchResults'),input=$('#searchInput');if(results)results.classList.remove('show');if(input)input.setAttribute('aria-expanded','false');stockState.activeSearchIndex=-1;
  }
  function renderStockSearch(items,message){
    var results=$('#stockSearchResults'),input=$('#searchInput');if(!results)return;stockState.searchItems=items||[];stockState.activeSearchIndex=-1;
    if(message){results.innerHTML='<div class="search-message">'+escapeHTML(message)+'</div>'}
    else if(!stockState.searchItems.length){results.innerHTML='<div class="search-message">没有找到匹配的 A 股</div>'}
    else{results.innerHTML=stockState.searchItems.map(function(item,index){return '<button class="search-result" type="button" role="option" data-search-index="'+index+'"><strong>'+escapeHTML(item.name)+'</strong><small>'+escapeHTML(item.market||'A股')+(item.industry?' · '+escapeHTML(item.industry):'')+'</small><span class="result-code">'+escapeHTML(item.symbol)+'</span></button>'}).join('')}
    results.classList.add('show');input.setAttribute('aria-expanded','true');
  }
  function activateSearchResult(index){
    var buttons=$$('#stockSearchResults .search-result');if(!buttons.length)return;stockState.activeSearchIndex=(index+buttons.length)%buttons.length;buttons.forEach(function(button,i){button.classList.toggle('active',i===stockState.activeSearchIndex);button.setAttribute('aria-selected',String(i===stockState.activeSearchIndex))});buttons[stockState.activeSearchIndex].scrollIntoView({block:'nearest'});
  }
  function chooseStock(item){
    if(!item)return;var input=$('#searchInput');input.value=(item.name||'')+' '+item.symbol;hideStockSearch();showPage('score');loadStock(item.symbol,{force:true}).catch(function(){});
  }
  function runStockSearch(query,selectFirst){
    query=String(query||'').trim();if(!query){hideStockSearch();return Promise.resolve([])}
    var sequence=++stockState.searchSequence;renderStockSearch([],'正在搜索全市场股票…');
    return stockRequest(stockConfig.endpoints.search,{q:query,limit:10}).then(function(payload){
      if(sequence!==stockState.searchSequence)return [];var items=unwrapList(payload);renderStockSearch(items);if(selectFirst&&items.length)chooseStock(items[0]);return items;
    }).catch(function(error){if(sequence===stockState.searchSequence)renderStockSearch([],'股票搜索暂不可用：'+error.message);return []});
  }
  var stockSearchTimer,input=$('#searchInput');
  input.addEventListener('input',function(){clearTimeout(stockSearchTimer);var query=this.value;stockSearchTimer=setTimeout(function(){runStockSearch(query,false)},180)});
  input.addEventListener('keydown',function(event){
    if(event.isComposing)return;
    if(event.key==='ArrowDown'){event.preventDefault();activateSearchResult(stockState.activeSearchIndex+1)}
    else if(event.key==='ArrowUp'){event.preventDefault();activateSearchResult(stockState.activeSearchIndex-1)}
    else if(event.key==='Escape'){hideStockSearch()}
    else if(event.key==='Enter'){event.preventDefault();if(stockState.activeSearchIndex>-1)chooseStock(stockState.searchItems[stockState.activeSearchIndex]);else runStockSearch(this.value,true)}
  });
  $('#stockSearchResults').addEventListener('click',function(event){var button=event.target.closest('[data-search-index]');if(button)chooseStock(stockState.searchItems[Number(button.getAttribute('data-search-index'))])});
  document.addEventListener('click',function(event){if(!event.target.closest('.search'))hideStockSearch()});
  $('#refreshStockData').addEventListener('click',function(){loadStock(stockState.symbol,{force:true,refresh:true}).catch(function(){})});
  /*
   * K线接口预留
   * 方式一：在本脚本前设置 window.QSKlineConfig：
   * { baseURL:'https://your-api.example.com', endpoint:'/api/v1/market/kline',
   *   headers:{Authorization:'Bearer ...'} }
   * 方式二：直接覆盖 window.QSMarketAPI.fetchKline(params)。
   * params: {symbol, period, limit, adjust}
   * 返回值：[{time, open, high, low, close, volume}, ...]，按时间升序。
   */
  var klineConfig=Object.assign({
    baseURL:'',
    endpoint:'/api/v1/market/kline',
    headers:{},
    symbol:'300750.SZ',
    adjust:'qfq'
  },window.QSKlineConfig||{});
  var periodNames={'1m':'分时','1d':'日K','1w':'周K','1M':'月K','1Y':'年K'};
  var klineState={symbol:klineConfig.symbol,period:'1d',data:[],loading:false,meta:{},requestSequence:0};
  function normalizeKlines(payload){
    var source=payload&&payload.data?payload.data:payload;
    if(source&&source.items)source=source.items;
    if(source&&source.list)source=source.list;
    if(!Array.isArray(source))throw new Error('K线接口返回格式不正确');
    return source.map(function(item){
      return {
        time:item.time||item.date||item.datetime||item.timestamp,
        open:Number(item.open),
        high:Number(item.high),
        low:Number(item.low),
        close:Number(item.close),
        volume:Number(item.volume||item.vol||0)
      };
    }).filter(function(item){return item.time&&[item.open,item.high,item.low,item.close].every(Number.isFinite)}).sort(function(a,b){return new Date(a.time)-new Date(b.time)});
  }
  window.QSMarketAPI=window.QSMarketAPI||{
    fetchKline:function(params){
      if(!klineConfig.baseURL)return Promise.reject(new Error('K线接口未配置'));
      var url=new URL(klineConfig.endpoint,klineConfig.baseURL);
      Object.keys(params).forEach(function(key){if(params[key]!==undefined&&params[key]!==null)url.searchParams.set(key,params[key])});
      var headers=typeof klineConfig.headers==='function'?klineConfig.headers():klineConfig.headers;
      return fetch(url.toString(),{method:'GET',headers:headers||{}}).then(function(response){
        if(!response.ok)throw new Error('K线接口请求失败：'+response.status);
        return response.json();
      }).then(function(payload){if(params.symbol===klineState.symbol&&params.period===klineState.period)klineState.meta=payload||{};return normalizeKlines(payload)});
    }
  };
  function movingAverage(rows,size){
    return rows.map(function(_,i){
      if(i<size-1)return null;
      var sum=0;for(var j=i-size+1;j<=i;j++)sum+=rows[j].close;
      return sum/size;
    });
  }
  function formatKlineTime(value,period){
    var d=new Date(value),pad=function(n){return String(n).padStart(2,'0')};
    if(period==='1m')return pad(d.getHours())+':'+pad(d.getMinutes());
    if(period==='1Y')return d.getFullYear()+'年';
    if(period==='1M')return d.getFullYear()+'/'+pad(d.getMonth()+1);
    return pad(d.getMonth()+1)+'/'+pad(d.getDate());
  }
  function latestValue(arr){
    for(var i=arr.length-1;i>=0;i--)if(arr[i]!==null&&Number.isFinite(arr[i]))return arr[i];
    return null;
  }
  function updateMALabels(rows){
    var groups=[[5,'#ma5Label'],[10,'#ma10Label'],[20,'#ma20Label']];
    groups.forEach(function(group){var value=latestValue(movingAverage(rows,group[0])),el=$(group[1]);el.textContent='MA'+group[0]+' '+(value===null?'--':value.toFixed(2))});
  }
  function priceChart(){
    var cv=$('#priceChart');if(!cv||!cv.offsetParent||!klineState.data.length)return;var s=setup(cv),c=s.c,w=s.w,h=s.h,p={l:48,r:12,t:12,b:25},maxBars=$('#klineCard').classList.contains('expanded')?120:58,rows=klineState.data.slice(-maxBars),plotW=w-p.l-p.r,plotH=h-p.t-p.b,high=Math.max.apply(null,rows.map(function(x){return x.high})),low=Math.min.apply(null,rows.map(function(x){return x.low})),margin=(high-low)*.08||1;
    high+=margin;low-=margin;var range=high-low,mapY=function(v){return p.t+(high-v)/range*plotH},step=plotW/rows.length,bodyW=Math.max(2,Math.min(10,step*.62));
    c.font='10px Microsoft YaHei';c.textAlign='right';c.textBaseline='middle';
    for(var level=0;level<5;level++){var y=p.t+level*plotH/4,value=high-level*range/4;c.strokeStyle='#e7edf6';c.lineWidth=1;c.beginPath();c.moveTo(p.l,y);c.lineTo(w-p.r,y);c.stroke();c.fillStyle='#8290a6';c.fillText(value.toFixed(2),p.l-5,y)}
    rows.forEach(function(row,i){var x=p.l+step*(i+.5),color=row.close>=row.open?'#f3262d':'#079a56',top=mapY(Math.max(row.open,row.close)),bottom=mapY(Math.min(row.open,row.close));c.strokeStyle=color;c.fillStyle=color;c.beginPath();c.moveTo(x,mapY(row.high));c.lineTo(x,mapY(row.low));c.stroke();c.fillRect(x-bodyW/2,top,bodyW,Math.max(2,bottom-top))});
    [[5,'#f3262d'],[10,'#2774ed'],[20,'#795add']].forEach(function(def){var values=movingAverage(rows,def[0]),started=false;c.beginPath();values.forEach(function(v,i){if(v===null)return;var x=p.l+step*(i+.5),y=mapY(v);if(started)c.lineTo(x,y);else{c.moveTo(x,y);started=true}});c.strokeStyle=def[1];c.lineWidth=1.4;c.stroke()});
    c.textAlign='center';c.textBaseline='top';c.fillStyle='#8290a6';var ticks=Math.min(5,rows.length);for(var t=0;t<ticks;t++){var idx=Math.round(t*(rows.length-1)/(ticks-1||1)),x=p.l+step*(idx+.5);c.fillText(formatKlineTime(rows[idx].time,klineState.period),x,h-p.b+7)}
  }
  function volumeChart(){
    var cv=$('#volumeChart');if(!cv||!cv.offsetParent||!klineState.data.length)return;var s=setup(cv),c=s.c,w=s.w,h=s.h,p={l:48,r:12,t:7,b:5},maxBars=$('#klineCard').classList.contains('expanded')?120:58,rows=klineState.data.slice(-maxBars),plotW=w-p.l-p.r,step=plotW/rows.length,max=Math.max.apply(null,rows.map(function(x){return x.volume}))||1,bodyW=Math.max(2,Math.min(10,step*.62));
    c.strokeStyle='#edf1f6';c.beginPath();c.moveTo(p.l,p.t);c.lineTo(w-p.r,p.t);c.stroke();c.font='10px Microsoft YaHei';c.fillStyle='#8290a6';c.textAlign='right';c.fillText('成交量',p.l-5,p.t+3);
    rows.forEach(function(row,i){var x=p.l+step*(i+.5),bh=row.volume/max*(h-p.t-p.b);c.fillStyle=row.close>=row.open?'rgba(243,38,45,.72)':'rgba(7,154,86,.72)';c.fillRect(x-bodyW/2,h-p.b-bh,bodyW,bh)})
  }
  function clearKlineCharts(){
    ['#priceChart','#volumeChart'].forEach(function(selector){var canvas=$(selector);if(!canvas)return;var context=canvas.getContext('2d');context.clearRect(0,0,canvas.width,canvas.height)});
    ['#ma5Label','#ma10Label','#ma20Label'].forEach(function(selector,index){var label=$(selector);if(label)label.textContent='MA'+[5,10,20][index]+' --'});
  }
  var klineCache=new Map();
  function loadKline(period,options){
    options=options||{};
    var requestSequence=++klineState.requestSequence;klineState.period=period;klineState.loading=true;
    $$('.chart-tabs [data-period]').forEach(function(button){var active=button.getAttribute('data-period')===period;button.classList.toggle('active',active);button.setAttribute('aria-selected',String(active))});
    var cacheKey=klineState.symbol+'|'+period+'|'+klineConfig.adjust;
    if(!options.force){
      var cached=klineCache.get(cacheKey);
      if(cached&&(Date.now()-cached.at)<60000){
        klineState.data=cached.rows;klineState.loading=false;updateMALabels(cached.rows);
        var cachedMeta=cached.meta||{};
        $('#klineStatus').textContent=(periodNames[period]||period)+' · '+(cachedMeta.adjustment||'真实行情')+' · '+(cachedMeta.source||'后端聚合接口');
        priceChart();volumeChart();return Promise.resolve(cached.rows);
      }
    }
    $('#klineStatus').textContent=(periodNames[period]||period)+' · 正在加载…';
    return Promise.resolve(window.QSMarketAPI.fetchKline({symbol:klineState.symbol,period:period,limit:period==='1Y'?12:period==='1M'?48:period==='1m'?120:80,adjust:klineConfig.adjust})).then(function(rows){
      if(requestSequence!==klineState.requestSequence)return [];
      rows=normalizeKlines(rows);if(!rows.length)throw new Error('暂无K线数据');klineState.data=rows;klineState.loading=false;updateMALabels(rows);var meta=klineState.meta||{};klineCache.set(cacheKey,{at:Date.now(),rows:rows,meta:meta});$('#klineStatus').textContent=(periodNames[period]||period)+' · '+(meta.adjustment||'真实行情')+' · '+(meta.source||'后端聚合接口');priceChart();volumeChart();return rows;
    }).catch(function(error){
      if(requestSequence!==klineState.requestSequence)return [];
      klineState.data=[];klineState.loading=false;clearKlineCharts();$('#klineStatus').textContent=(periodNames[period]||period)+' · 真实行情暂不可用';console.warn(error);throw error;
    });
  }
  window.QSReloadKline=function(options){
    options=options||{};if(options.symbol)klineState.symbol=options.symbol;
    return loadKline(options.period||klineState.period);
  };
  function toggleKlineExpand(force){
    var card=$('#klineCard'),backdrop=$('#klineBackdrop'),button=$('#klineExpand');if(!card||!backdrop||!button)return;
    var expanded=typeof force==='boolean'?force:!card.classList.contains('expanded');card.classList.toggle('expanded',expanded);backdrop.classList.toggle('show',expanded);backdrop.setAttribute('aria-hidden',String(!expanded));document.body.classList.toggle('kline-open',expanded);button.setAttribute('aria-expanded',String(expanded));button.setAttribute('aria-label',expanded?'还原K线图':'放大K线图');button.title=expanded?'还原K线图':'放大K线图';button.innerHTML=(expanded?'×':'⛶')+'<span class="kline-expand-label">'+(expanded?'还原':'放大')+'</span>';setTimeout(function(){priceChart();volumeChart()},40);
  }
  $$('.chart-tabs [data-period]').forEach(function(button){button.addEventListener('click',function(){loadKline(button.getAttribute('data-period'))})});
  $('#klineExpand').addEventListener('click',function(){toggleKlineExpand()});
  $('#klineBackdrop').addEventListener('click',function(){toggleKlineExpand(false)});
  document.addEventListener('keydown',function(event){if(event.key==='Escape')toggleKlineExpand(false)});
  function radar(cv){
    if(!cv.offsetParent)return;var s=setup(cv),c=s.c,w=s.w,h=s.h,labels=(cv.getAttribute('data-labels')||'A,B,C,D,E').split(','),values=(cv.getAttribute('data-values')||'80,80,80,80,80').split(',').map(Number),values2=cv.getAttribute('data-values2')?cv.getAttribute('data-values2').split(',').map(Number):null,n=labels.length,cx=w/2,cy=h/2+4,r=Math.min(w,h)*.32;
    function point(i,rr){var a=-Math.PI/2+i*Math.PI*2/n;return [cx+Math.cos(a)*rr,cy+Math.sin(a)*rr]}
    c.font='11px Microsoft YaHei';c.textAlign='center';c.textBaseline='middle';
    for(var level=1;level<=5;level++){c.beginPath();for(var i=0;i<n;i++){var pt=point(i,r*level/5);i?c.lineTo(pt[0],pt[1]):c.moveTo(pt[0],pt[1])}c.closePath();c.strokeStyle='#dfe7f3';c.stroke()}
    for(var j=0;j<n;j++){var end=point(j,r);c.beginPath();c.moveTo(cx,cy);c.lineTo(end[0],end[1]);c.strokeStyle='#e5ebf4';c.stroke();var lp=point(j,r+22);c.fillStyle='#344a6a';c.fillText(labels[j],lp[0],lp[1])}
    function area(vals,color,fill){c.beginPath();vals.forEach(function(v,i){var pnt=point(i,r*v/100);i?c.lineTo(pnt[0],pnt[1]):c.moveTo(pnt[0],pnt[1])});c.closePath();c.fillStyle=fill;c.fill();c.strokeStyle=color;c.lineWidth=2;c.stroke();vals.forEach(function(v,i){var pnt=point(i,r*v/100);c.fillStyle=color;c.beginPath();c.arc(pnt[0],pnt[1],2.4,0,Math.PI*2);c.fill()})}
    if(values2)area(values2,'#10a25d','rgba(16,162,93,.07)');area(values,'#1768ef','rgba(23,104,239,.11)')
  }
  function marketLine(){
    var cv=$('#marketLine');if(!cv||!cv.offsetParent)return;var s=setup(cv),c=s.c,w=s.w,h=s.h,p=20;grid(c,w,h,p);var a=[45,55,43,52,41,59,47],b=[9000,11000,9700,10500,9200,13000,11200];
    [[a,'#1768ef'],[b,'#08a05a']].forEach(function(d){var min=Math.min.apply(null,d[0]),max=Math.max.apply(null,d[0]),range=max-min||1;c.beginPath();d[0].forEach(function(v,i){var x=p+i*(w-p*2)/(d[0].length-1),y=h-p-(v-min)*(h-p*2)/range;i?c.lineTo(x,y):c.moveTo(x,y)});c.strokeStyle=d[1];c.lineWidth=2;c.stroke();d[0].forEach(function(v,i){var x=p+i*(w-p*2)/(d[0].length-1),y=h-p-(v-min)*(h-p*2)/range;c.fillStyle=d[1];c.beginPath();c.arc(x,y,3,0,Math.PI*2);c.fill()})})
  }
  function drawAll(){
    $$('.sparkline').forEach(function(cv){line(cv,cv.getAttribute('data-points').split(','),cv.getAttribute('data-color')||'#1768ef',cv.getAttribute('data-fill'))});
    $$('.radar').forEach(radar);drawTopMetricComparison();priceChart();volumeChart();marketLine()
  }
  window.addEventListener('resize',function(){clearTimeout(window._drawTimer);window._drawTimer=setTimeout(drawAll,90)});
  drawAll();
  window.QSReloadTodayDashboard();
  var refreshTodayButton=$('#refreshTodayData');if(refreshTodayButton)refreshTodayButton.addEventListener('click',function(){window.QSReloadTodayDashboard()});
  window.setInterval(function(){if(document.visibilityState==='visible'&&$('#page-today').classList.contains('active'))window.QSReloadTodayDashboard()},30000);
  ensureWatchlistSession().then(function(){return loadWatchlist()}).catch(function(error){renderWatchlistError('关注列表加载失败：'+error.message)});
  var initialStockSymbol='300750.SZ';try{initialStockSymbol=new URL(location.href).searchParams.get('symbol')||initialStockSymbol}catch(error){}
  loadStock(initialStockSymbol,{force:true}).catch(function(){});
  var initialPage=location.hash.replace('#','');if(['today','score','research','watch','review','profile'].indexOf(initialPage)>-1)showPage(initialPage);
})();
