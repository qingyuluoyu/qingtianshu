window.QSTodayConfig={
  baseURL:window.location.origin,
  credentials:'same-origin',
  endpoints:{
    dashboard:'/api/v1/dashboard/today',
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
  var toastTimer,profilePageRequested=false,todayPageRequested=false,marketReviewPageRequested=false,personalReviewPageRequested=false;
  /* 图表统一色板：上涨红/下跌绿/平盘灰/主题蓝/对比系列绿（COMPARE_GREEN 仅用于行业中位等对比系列，与下跌绿区分语义） */
  var CHART_UP_RED=QSCharts.colors.up,CHART_DOWN_GREEN=QSCharts.colors.down,CHART_FLAT_GRAY=QSCharts.colors.flat,CHART_PRIMARY_BLUE=QSCharts.colors.primary,CHART_COMPARE_GREEN=QSCharts.colors.compare;
  var setup=QSCharts.setup,line=QSCharts.line,radar=QSCharts.radar;
  function toast(msg){var t=$('#toast');t.textContent=msg;t.classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(function(){t.classList.remove('show')},1900)}
  function showPage(name){
    if(name!=='score')toggleKlineExpand(false);
    $$('.page').forEach(function(p){p.classList.remove('active')});
    var target=$('#page-'+name);if(target)target.classList.add('active');
    $$('[data-page]').forEach(function(b){b.classList.toggle('active',b.getAttribute('data-page')===name)});
    if(name==='watch')ensureWatchlistSession().then(function(){return Promise.all([loadWatchlist(),loadEvidenceTasks()])}).catch(function(error){renderWatchlistError('关注列表加载失败：'+error.message)});
    if(name==='profile'&&!profilePageRequested){profilePageRequested=true;loadProfileSummary().catch(function(){})}
    if(name==='today'&&!todayPageRequested){todayPageRequested=true;window.QSReloadTodayDashboard()}
    if(name==='score'&&!stockPageRequested){stockPageRequested=true;loadStock(stockState.symbol,{force:true}).catch(function(){})}
    if(name==='review'&&!personalReviewPageRequested){personalReviewPageRequested=true;loadPersonalReviews()}
    window.scrollTo({top:0,behavior:'smooth'});
    requestAnimationFrame(function(){requestAnimationFrame(drawAll)});
  }
  $$('[data-page]').forEach(function(b){b.addEventListener('click',function(){showPage(b.getAttribute('data-page'))})});
  $$('[data-toast]').forEach(function(b){b.addEventListener('click',function(){toast(b.getAttribute('data-toast'))})});
  $$('.tab-btn').forEach(function(b){b.addEventListener('click',function(){
    $$('.tab-btn').forEach(function(x){x.classList.remove('active')});b.classList.add('active');
    var reviewName=b.getAttribute('data-review');$$('.review-pane').forEach(function(x){x.classList.remove('active')});$('#review-'+reviewName).classList.add('active');if(reviewName==='market'&&!marketReviewPageRequested){marketReviewPageRequested=true;loadMarketReview(false).catch(function(){})}setTimeout(drawAll,20)
  })});
  function reviewMoney(value){var number=Number(value);return Number.isFinite(number)?number.toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2}):'—'}
  function loadPersonalReviews(){
    var panel=$('#review-personal');if(!panel)return;
    panel.innerHTML='<h2 style="font-size:18px">个人复盘</h2><div id="tradeReviewContent"><article class="card"><div class="card-body"><p class="muted">正在读取交易与持仓数据…</p></div></article></div><h2 style="font-size:18px;margin-top:18px">研究运行复盘</h2><div id="runReviewList"><article class="card"><div class="card-body"><p class="muted">正在读取研究复盘记录…</p></div></article></div>';
    ensureWatchlistSession().then(function(){return Promise.all([watchRequest('/api/v1/me/trade-reviews'),watchRequest('/me/run-reviews')])}).then(function(results){
      var trade=results[0]||{},summary=trade.summary||{},positions=trade.openPositions||[],closed=trade.closedTrades||[],history=trade.tradeHistory||[],tradeNode=$('#tradeReviewContent');
      var winRate=summary.winRatePct===null||summary.winRatePct===undefined?'—':Number(summary.winRatePct).toFixed(2)+'%';
      if(tradeNode)tradeNode.innerHTML='<article class="card"><div class="card-title"><h3>盈亏口径</h3></div><div class="card-body review-metrics"><div class="review-metric">已平仓交易<strong>'+Number(summary.closedTradeCount||0)+'</strong></div><div class="review-metric">当前持仓<strong>'+Number(summary.openPositionCount||0)+'</strong></div><div class="review-metric">已实现盈亏<strong>'+reviewMoney(summary.realizedPnlCny)+'</strong></div><div class="review-metric">未实现盈亏<strong>'+reviewMoney(summary.unrealizedPnlCny)+'</strong></div><div class="review-metric">交易费用<strong>'+reviewMoney(summary.feesCny)+'</strong></div><div class="review-metric">净盈亏<strong>'+reviewMoney(summary.netPnlCny)+'</strong></div><div class="review-metric">平仓胜率<strong>'+winRate+'</strong></div></div><p class="muted" style="padding:0 16px 14px">未平仓持仓不计入胜率，部分卖出计入已实现盈亏但不计入完整平仓次数。</p></article><article class="card personal-table"><div class="card-title"><h3>成交历史</h3></div><div class="card-body">'+(history.length?'<table><thead><tr><th>成交时间</th><th>证券</th><th>方向</th><th>成交价</th><th>数量</th><th>费用</th><th>已实现盈亏</th><th>是否完整平仓</th></tr></thead><tbody>'+history.map(function(item){return '<tr><td>'+escapeHTML(item.executed_at||'—')+'</td><td>'+escapeHTML(item.symbol||'—')+'</td><td>'+escapeHTML(item.side==='buy'?'买入':'卖出')+'</td><td>'+reviewMoney(item.price)+'</td><td>'+escapeHTML(item.quantity||'—')+'</td><td>'+reviewMoney(item.fee)+'</td><td>'+reviewMoney(item.realized_pnl)+'</td><td>'+escapeHTML(item.position_closed?'是':'否')+'</td></tr>'}).join('')+'</tbody></table>':'<p class="muted">暂无成交记录。</p>')+'</div></article><article class="card personal-table"><div class="card-title"><h3>完整平仓记录</h3></div><div class="card-body">'+(closed.length?'<table><thead><tr><th>成交时间</th><th>证券</th><th>平仓成交价</th><th>数量</th><th>费用</th><th>该持仓已实现盈亏</th></tr></thead><tbody>'+closed.map(function(item){return '<tr><td>'+escapeHTML(item.executed_at||'—')+'</td><td>'+escapeHTML(item.symbol||'—')+'</td><td>'+reviewMoney(item.price)+'</td><td>'+escapeHTML(item.quantity||'—')+'</td><td>'+reviewMoney(item.fee)+'</td><td>'+reviewMoney(item.position_realized_pnl)+'</td></tr>'}).join('')+'</tbody></table>':'<p class="muted">暂无完整平仓记录。</p>')+'</div></article><article class="card personal-table"><div class="card-title"><h3>当前持仓</h3></div><div class="card-body">'+(positions.length?'<table><thead><tr><th>证券</th><th>账户</th><th>数量</th><th>成本价</th><th>当前价</th><th>当前市值</th><th>未实现盈亏</th><th>数据截止时间</th></tr></thead><tbody>'+positions.map(function(item){return '<tr><td>'+escapeHTML((item.name||'')+' '+(item.symbol||''))+'</td><td>'+escapeHTML(item.account_type==='live'?'实盘':'模拟')+'</td><td>'+escapeHTML(item.quantity||'—')+'</td><td>'+reviewMoney(item.cost_price)+'</td><td>'+reviewMoney(item.current_price)+'</td><td>'+reviewMoney(item.currentMarketValueCny)+'</td><td>'+reviewMoney(item.unrealizedPnlCny)+'</td><td>'+escapeHTML(item.data_as_of||'—')+'</td></tr>'}).join('')+'</tbody></table>':'<p class="muted">暂无当前持仓。系统不会使用示例交易填充此处。</p>')+'</div></article>';
      var runs=results[1]&&results[1].items||[],runNode=$('#runReviewList');
      if(runNode)runNode.innerHTML=runs.length?runs.map(function(item){return '<article class="card" style="padding:12px;margin-bottom:8px"><b>'+escapeHTML(item.display_name||item.conversation_title||'研究运行')+'</b><p class="muted">'+escapeHTML(item.question||'已保存研究记录，可进入详情复核。')+'</p><small>'+escapeHTML(item.status||'—')+' · '+escapeHTML(item.created_at||'—')+'</small></article>'}).join(''):'<article class="card"><div class="card-body"><p class="muted">暂无可复盘的研究运行。</p></div></article>';
    }).catch(function(error){var tradeNode=$('#tradeReviewContent');if(tradeNode)tradeNode.innerHTML='<article class="card"><div class="card-body"><p class="muted">个人复盘读取失败：'+escapeHTML(error.message)+'</p></div></article>';});
  }
  var watchStatusLabels={active:'跟踪中',paused:'已暂停'};
  var researchStatusLabels={none:'未建立研究',draft:'研究草稿',researching:'研究中',concluded:'已有结论',expired:'结论已过期',invalidated:'结论已失效'};
  var positionStatusLabels={none:'未持仓',open:'当前持仓',history:'持仓历史'};
  var watchState={items:[],positions:new Map(),actions:[],selected:new Set(),filter:'all',candidate:null,searchItems:[],searchSequence:0,searchTimer:null,sessionPromise:null,loadingPromise:null,positionMode:null,positionAccountType:null};
  function watchStatusLabel(value){return watchStatusLabels[value]||watchStatusLabels.active}
  function comparableWatchSymbol(value){return String(value||'').trim().toUpperCase().replace(/\.SH$/,'.SS')}
  function watchRequest(path,options){
    options=options||{};var headers=Object.assign({},options.headers||{});
    if(options.body&&!(options.body instanceof FormData))headers['Content-Type']='application/json';
    return fetch(path,Object.assign({},options,{credentials:'same-origin',headers:headers})).then(function(response){
      return response.json().catch(function(){return {}}).then(function(body){
        if(!response.ok){var error=new Error(body.detail||('请求失败：'+response.status));error.status=response.status;throw error}return body;
      });
    });
  }
  function ensureWatchlistSession(){
    if(watchState.sessionPromise)return watchState.sessionPromise;
    watchState.sessionPromise=watchRequest('/session').catch(function(error){
      watchState.sessionPromise=null;
      throw new Error(error.status===401?'会话已失效，请重新登录':'会话校验失败：'+error.message);
    });
    return watchState.sessionPromise;
  }
  function renderEvidenceTasks(data){
    var summary=data&&data.summary||{},items=unwrapList(data),summaryNode=$('#evidenceTaskSummary'),list=$('#evidenceTaskList');
    if(!summaryNode||!list)return;
    summaryNode.textContent='共 '+(summary.total||0)+' 项 · '+(summary.pending||0)+' 项等待补齐 · '+(summary.collecting||0)+' 项正在采集 · '+(summary.resolved||0)+' 项已入库 · '+(summary.pending_external||0)+' 项等待外部资料';
    list.innerHTML=items.slice(0,8).map(function(item){
      var title=(item.symbol||item.market_key||'通用研究')+' · '+(item.title||'待补充研究证据');
      var lifecycle=item.resolution_document_id?'补齐结果已进入个人资料库':(item.resolution_note||'任务会保留并继续处理');
      return '<article class="card" style="padding:12px;margin-bottom:8px"><b>'+escapeHTML(title)+'</b><p class="muted" style="margin:5px 0">'+escapeHTML(item.description||'待补充研究证据')+'</p><small>'+escapeHTML(item.status_label||'等待处理')+' · '+escapeHTML(lifecycle)+'</small></article>';
    }).join('')||'<p class="muted">新的对话证据缺口会在这里形成后台补证任务。</p>';
  }
  function loadEvidenceTasks(){
    return ensureWatchlistSession().then(function(){return watchRequest('/me/evidence-tasks?limit=50');}).then(function(data){renderEvidenceTasks(data);return data;}).catch(function(error){var summary=$('#evidenceTaskSummary');if(summary)summary.textContent='补证任务暂不可用：'+error.message;throw error;});
  }
  function watchTime(value){
    if(!value)return '—';var date=new Date(value);return Number.isNaN(date.getTime())?String(value):date.toLocaleString('zh-CN',{hour12:false,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});
  }
  function primaryWatchAction(actionItem){
    var actions=actionItem&&Array.isArray(actionItem.actions)?actionItem.actions:[];
    return actions.find(function(item){return item.status==='triggered'})
      ||actions.find(function(item){return item.status==='pending_data'})
      ||actions[0]||null;
  }
  function updateWatchBatchButton(){
    var button=$('#batchDeleteWatch');button.disabled=!watchState.selected.size;button.textContent=watchState.selected.size?'批量删除（'+watchState.selected.size+'）':'批量删除';
  }
  function applyWatchFilter(){
    var visible=0;
    $$('#watchRows tr[data-symbol]').forEach(function(row){
      var show=watchState.filter==='all'||row.getAttribute('data-tracking')===watchState.filter||row.getAttribute('data-position')===watchState.filter;row.style.display=show?'':'none';if(show)visible+=1;
    });
    $('#watchRecordCount').textContent='共 '+visible+' 条记录';
    var visibleRows=$$('#watchRows tr[data-symbol]').filter(function(row){return row.style.display!=='none'});
    $('#watchSelectAll').checked=visibleRows.length>0&&visibleRows.every(function(row){return watchState.selected.has(row.getAttribute('data-symbol'))});
  }
  function renderWatchSummary(){
    var counts={active:0,paused:0,researching:0,open:0};
    watchState.items.forEach(function(item){counts[item.tracking_status||'active']+=1;if(item.research_status==='researching')counts.researching+=1;if(item.position_status==='open')counts.open+=1});
    $('#watchTotalCount').textContent=watchState.items.length;$('#watchActiveCount').textContent=counts.active;$('#watchResearchCount').textContent=counts.researching;$('#watchPositionCount').textContent=counts.open;
    var total=Math.max(1,watchState.items.length),activeRate=counts.active/total*100;
    var stops=['#1768ef 0 '+activeRate+'%','#bcc3ce '+activeRate+'% 100%'];
    if(!watchState.items.length)stops=['#e5e9ef 0 100%'];
    var donut=$('#watchStatusDonut');donut.dataset.count=watchState.items.length;donut.style.background='conic-gradient('+stops.join(',')+')';
    $('#watchStatusLegend').innerHTML='<p style="color:#1768ef"><i class="dot"></i>跟踪中　'+counts.active+'</p><p style="color:#7f8da4"><i class="dot"></i>已暂停　'+counts.paused+'</p><p style="color:#0b8d56"><i class="dot"></i>当前持仓　'+counts.open+'</p>';
    var actionMap=new Map(watchState.actions.map(function(item){return [item.symbol,item]}));
    var todos=watchState.items.map(function(item){var actionItem=actionMap.get(item.symbol),action=primaryWatchAction(actionItem);return {item:item,actionItem:actionItem,action:action}}).filter(function(entry){return entry.action||entry.actionItem}).slice(0,4);
    $('#watchTodoList').innerHTML=todos.map(function(entry){
      var item=entry.item,copy=entry.action&&(entry.action.next_step||entry.action.title)||entry.actionItem.headline||'继续观察行情与新增证据';
      return '<div class="todo-item"><span class="pill">'+escapeHTML(watchStatusLabel(item.tracking_status||'active'))+'</span><span><b>'+escapeHTML(item.name||item.symbol)+'（'+escapeHTML(item.symbol)+'）</b><br><small>'+escapeHTML(copy)+'</small></span><small>'+escapeHTML(entry.actionItem.data_as_of?String(entry.actionItem.data_as_of).slice(5,10):'待更新')+'</small></div>';
    }).join('')||'<p class="muted">暂无待处理动作。</p>';
  }
  function watchTrackingOptions(selected){
    return ['active','paused'].map(function(value){return '<option value="'+value+'"'+(value===selected?' selected':'')+'>'+watchStatusLabel(value)+'</option>'}).join('');
  }
  function renderWatchlist(){
    var symbols=new Set(watchState.items.map(function(item){return item.symbol}));
    watchState.selected=new Set(Array.from(watchState.selected).filter(function(symbol){return symbols.has(symbol)}));
    $('#watchRows').innerHTML=watchState.items.map(function(item){
      var tracking=item.tracking_status||'active',research=item.research_status||'none',position=item.position_status||'none',legacy=item.legacy_position_hint;
      var operation=position==='open'
        ?'<button class="btn small" type="button" data-position-action="trade">记录成交</button>'
        :'<button class="btn small" type="button" data-position-action="simulated">转为模拟持仓</button><button class="btn small" type="button" data-position-action="live">记录实盘持仓</button>';
      return '<tr data-symbol="'+escapeHTML(item.symbol)+'" data-tracking="'+tracking+'" data-position="'+position+'">'
        +'<td><input class="watch-row-select" type="checkbox" aria-label="选择 '+escapeHTML(item.name||item.symbol)+'"'+(watchState.selected.has(item.symbol)?' checked':'')+'></td>'
        +'<td><b>'+escapeHTML(item.name||item.symbol)+'</b><br><span class="muted">'+escapeHTML(item.symbol)+'</span></td>'
        +'<td><span class="status-text"><i aria-hidden="true">●</i> 关注状态：'+escapeHTML(watchStatusLabel(tracking))+'</span><br><select class="watch-tracking-status" aria-label="'+escapeHTML(item.name||item.symbol)+' 的关注状态">'+watchTrackingOptions(tracking)+'</select></td>'
        +'<td><span class="status-text">研究状态：'+escapeHTML(researchStatusLabels[research]||research)+'</span></td>'
        +'<td><span class="status-text">持仓状态：'+escapeHTML(positionStatusLabels[position]||position)+'</span>'+(legacy?'<br><small class="legacy-hint">发现历史持仓线索，待确认迁移</small>':'')+'</td>'
        +'<td><textarea class="watch-reason-input" rows="2" maxlength="1000" aria-label="'+escapeHTML(item.name||item.symbol)+' 的关注理由" placeholder="填写关注理由">'+escapeHTML(item.reason||'')+'</textarea></td>'
        +'<td><small>催化：'+escapeHTML(item.catalyst_condition||'—')+'<br>失效：'+escapeHTML(item.invalidation_condition||'—')+'<br>频率：'+escapeHTML(item.tracking_frequency||'—')+'</small></td>'
        +'<td>'+escapeHTML(watchTime(item.updated_at))+'</td>'
        +'<td class="watch-operation-cell"><div class="watch-lifecycle-actions">'+operation+'<button class="watch-op-btn danger" type="button" data-watch-delete title="删除关注" aria-label="删除 '+escapeHTML(item.name||item.symbol)+' 关注">⌫</button></div></td></tr>';
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
      return Promise.all([watchRequest('/api/v1/me/watchlist'),watchRequest('/api/v1/me/positions'),watchRequest('/me/research-actions').catch(function(){return {items:[]}})]);
    }).then(function(results){
      watchState.items=unwrapList(results[0]);watchState.positions=new Map(unwrapList(results[1]).filter(function(item){return item.status==='open'}).map(function(item){return [comparableWatchSymbol(item.symbol),item]}));watchState.actions=unwrapList(results[2]);renderWatchlist();return watchState.items;
    }).catch(function(error){renderWatchlistError('关注列表加载失败：'+error.message);return []}).finally(function(){watchState.loadingPromise=null});
    return watchState.loadingPromise;
  }
  function updateWatchItem(symbol,patch,control){
    var item=watchState.items.find(function(entry){return entry.symbol===symbol});if(!item)return Promise.reject(new Error('关注股票不存在'));
    if(control)control.disabled=true;
    return watchRequest('/api/v1/me/watchlist/'+encodeURIComponent(symbol),{method:'PATCH',body:JSON.stringify(patch)}).then(function(saved){Object.assign(item,saved);toast('关注信息已保存');return loadWatchlist()}).catch(function(error){toast('保存失败：'+error.message);throw error}).finally(function(){if(control)control.disabled=false});
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
    else if(event.target.matches('.watch-tracking-status')){var previous=row.getAttribute('data-tracking');updateWatchItem(symbol,{tracking_status:event.target.value},event.target).catch(function(){event.target.value=previous})}
    else if(event.target.matches('.watch-reason-input')){var item=watchState.items.find(function(entry){return entry.symbol===symbol}),previous=item&&item.reason||'',reason=event.target.value.trim();if(reason&&reason!==String(previous).trim())updateWatchItem(symbol,{reason:reason},event.target).catch(function(){event.target.value=previous})}
  });
  $('#watchRows').addEventListener('click',function(event){
    var row=event.target.closest('tr[data-symbol]');if(!row)return;var symbol=row.getAttribute('data-symbol'),item=watchState.items.find(function(entry){return entry.symbol===symbol});
    var action=event.target.closest('[data-position-action]');if(action){openPositionDialog(item,action.getAttribute('data-position-action'));return}
    var remove=event.target.closest('[data-watch-delete]');if(!remove)return;
    if(!window.confirm('确定删除“'+(item&&item.name||symbol)+'”的关注吗？持仓和交易不会被删除。'))return;
    remove.disabled=true;watchRequest('/api/v1/me/watchlist/'+encodeURIComponent(symbol),{method:'DELETE'}).then(function(){watchState.selected.delete(symbol);toast('已删除关注，持仓与交易保持不变');return loadWatchlist()}).catch(function(error){toast('删除失败：'+error.message);remove.disabled=false});
  });
  $('#batchDeleteWatch').addEventListener('click',function(){
    var symbols=Array.from(watchState.selected);if(!symbols.length||!window.confirm('确定删除选中的 '+symbols.length+' 只关注股票吗？'))return;
    var button=this;button.disabled=true;Promise.allSettled(symbols.map(function(symbol){return watchRequest('/api/v1/me/watchlist/'+encodeURIComponent(symbol),{method:'DELETE'})})).then(function(results){
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
      return '<div class="watch-search-result-row"><button class="watch-search-result" type="button" role="option" data-watch-search-index="'+index+'"'+(exists?' disabled':'')+'><strong>'+escapeHTML(item.name||symbol)+'</strong><span>'+escapeHTML(item.symbol||symbol)+(exists?' · 已关注':'')+'</span><small>'+escapeHTML(item.market||'A股')+(item.industry?' · '+escapeHTML(item.industry):'')+'</small></button><button class="watch-search-detail" type="button" data-watch-detail-index="'+index+'" aria-label="查看 '+escapeHTML(item.name||symbol)+' 的个股详情">查看详情</button></div>';
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
  function openWatchStockDetail(item){
    if(!item)return;var symbol=item.internalSymbol||item.symbol;if(!symbol)return;
    hideWatchSearch();chooseStock(Object.assign({},item,{symbol:symbol}));
  }
  $('#watchSearchInput').addEventListener('input',function(){watchState.candidate=null;$('#watchAddSymbol').value='';$('#watchAddSubmit').disabled=true;clearTimeout(watchState.searchTimer);var query=this.value;watchState.searchTimer=setTimeout(function(){runWatchSearch(query)},180)});
  $('#watchSearchInput').addEventListener('keydown',function(event){if(event.isComposing)return;if(event.key==='Escape')hideWatchSearch();else if(event.key==='Enter'&&!watchState.candidate){event.preventDefault();var button=$('#watchSearchResults [data-watch-search-index]:not(:disabled)');if(button)selectWatchCandidate(watchState.searchItems[Number(button.dataset.watchSearchIndex)]);else runWatchSearch(this.value)}});
  $('#watchSearchResults').addEventListener('click',function(event){
    var detail=event.target.closest('[data-watch-detail-index]');if(detail){openWatchStockDetail(watchState.searchItems[Number(detail.dataset.watchDetailIndex)]);return}
    var button=event.target.closest('[data-watch-search-index]');if(button&&!button.disabled)selectWatchCandidate(watchState.searchItems[Number(button.dataset.watchSearchIndex)]);
  });
  $('#watchAddForm').addEventListener('submit',function(event){
    event.preventDefault();if(!watchState.candidate||!$('#watchAddSymbol').value){toast('请先从搜索结果中选择股票');return}
    var button=$('#watchAddSubmit');button.disabled=true;watchRequest('/api/v1/me/watchlist',{method:'POST',body:JSON.stringify({symbol:$('#watchAddSymbol').value,name:$('#watchAddName').value||null,priority:$('#watchAddPriority').value,reason:$('#watchAddReason').value.trim(),catalyst_condition:$('#watchAddCatalyst').value.trim()||null,invalidation_condition:$('#watchAddInvalidation').value.trim()||null,tracking_frequency:$('#watchAddFrequency').value,tracking_status:'active'})}).then(function(){
      toast('已加入关注');event.target.reset();watchState.candidate=null;$('#watchAddSymbol').value='';$('#watchAddName').value='';return loadWatchlist();
    }).catch(function(error){toast('添加失败：'+error.message);button.disabled=false});
  });
  function lifecycleKey(prefix){return prefix+'-'+Date.now().toString(36)+'-'+Math.random().toString(36).slice(2,10)}
  function localDateTimeValue(){var now=new Date(),offset=now.getTimezoneOffset()*60000;return new Date(now.getTime()-offset).toISOString().slice(0,16)}
  function openPositionDialog(item,mode){
    if(!item)return;var dialog=$('#positionDialog'),position=watchState.positions.get(comparableWatchSymbol(item.symbol));
    watchState.positionMode=mode==='trade'?'trade':'create';watchState.positionAccountType=mode==='live'?'live':'simulated';
    $('#positionSymbol').value=item.symbol;$('#positionName').value=item.name||'';$('#positionId').value=position&&position.id||'';$('#positionVersion').value=position&&position.version||'';
    $('#positionExecutedAt').value=localDateTimeValue();$('#positionQuantity').value='';$('#positionPrice').value='';$('#positionFee').value='0';$('#positionCurrentPrice').value='';
    $('#positionSideWrap').style.display=watchState.positionMode==='trade'?'grid':'none';$('#positionCurrentPriceWrap').style.display=watchState.positionMode==='create'?'grid':'none';
    $('#positionDialogTitle').textContent=watchState.positionMode==='trade'?'记录成交':(watchState.positionAccountType==='live'?'记录实盘持仓':'转为模拟持仓');
    if(dialog.showModal)dialog.showModal();else dialog.setAttribute('open','');
  }
  function closePositionDialog(){var dialog=$('#positionDialog');if(dialog.close)dialog.close();else dialog.removeAttribute('open')}
  $('#positionDialogClose').addEventListener('click',closePositionDialog);$('#positionDialogCancel').addEventListener('click',closePositionDialog);
  $('#positionForm').addEventListener('submit',function(event){
    event.preventDefault();var button=$('#positionSubmit'),executedAt=new Date($('#positionExecutedAt').value).toISOString();button.disabled=true;
    var request;
    if(watchState.positionMode==='create'){
      request=watchRequest('/api/v1/me/positions',{method:'POST',body:JSON.stringify({symbol:$('#positionSymbol').value,name:$('#positionName').value||null,account_type:watchState.positionAccountType,quantity:$('#positionQuantity').value,price:$('#positionPrice').value,fee:$('#positionFee').value||'0',executed_at:executedAt,current_price:$('#positionCurrentPrice').value||null,data_as_of:$('#positionCurrentPrice').value?executedAt:null,idempotency_key:lifecycleKey('position')})});
    }else{
      var positionId=$('#positionId').value;
      request=watchRequest('/api/v1/me/positions/'+encodeURIComponent(positionId)+'/trades',{method:'POST',body:JSON.stringify({side:$('#positionSide').value,quantity:$('#positionQuantity').value,price:$('#positionPrice').value,fee:$('#positionFee').value||'0',executed_at:executedAt,idempotency_key:lifecycleKey('trade'),base_version:Number($('#positionVersion').value)})});
    }
    request.then(function(){toast(watchState.positionMode==='create'?'持仓已创建':'成交已记录');closePositionDialog();return loadWatchlist()}).then(function(){if(personalReviewPageRequested)loadPersonalReviews()}).catch(function(error){toast('保存失败：'+error.message)}).finally(function(){button.disabled=false});
  });
  document.addEventListener('click',function(event){if(!event.target.closest('.watch-search-box'))hideWatchSearch()});
  $('#watchRows').innerHTML='<tr class="watch-loading"><td colspan="9">正在读取关注股票…</td></tr>';
  var accountInfo=$('.account-info');
  if(false&&accountInfo){
    var purchaseCard=accountInfo.closest('.card');
    purchaseCard.classList.add('purchase-card');
    purchaseCard.innerHTML='<h3>会员购买</h3><div class="purchase-layout"><div class="purchase-plans"><button class="purchase-plan active" type="button" data-plan="month" data-price="98"><span class="purchase-check">✓</span><strong>月会员</strong><b>¥98 / 月</b><small>畅享会员全部权益</small></button><button class="purchase-plan" type="button" data-plan="year" data-price="980"><span class="recommend">推荐</span><span class="purchase-check">✓</span><strong>年会员</strong><b>¥980 / 年</b><small>折合 ¥81.7 / 月，省 ¥196</small></button></div><div class="payment-box"><div class="payment-head"><span>支付方式</span><span class="alipay"><i class="alipay-icon">支</i>支付宝</span></div><div class="payment-total"><span>应付金额</span><strong id="paymentAmount">¥98.00</strong></div><button class="btn primary block" id="purchaseNow" type="button">立即购买</button><p class="payment-security">本服务由支付宝提供安全支付保障</p></div></div>';
    var selectedPlan='month',selectedPrice=98;
    $$('.purchase-plan').forEach(function(button){button.addEventListener('click',function(){
      $$('.purchase-plan').forEach(function(item){item.classList.toggle('active',item===button)});
      selectedPlan=button.dataset.plan;selectedPrice=Number(button.dataset.price);$('#paymentAmount').textContent='¥'+selectedPrice.toFixed(2);
    })});
    var paymentDraftDisabled=true;
    $('#purchaseNow').addEventListener('click',function(){
      var button=this;button.disabled=true;button.textContent='正在创建订单…';
      Promise.resolve({disabled:paymentDraftDisabled}).then(function(result){
        toast(result&&result.demo?'支付接口尚未接入，已生成演示订单':'订单已创建，正在前往支付宝');button.disabled=false;button.textContent='立即购买';
      }).catch(function(error){toast(error&&error.message?error.message:'订单创建失败，请稍后重试');button.disabled=false;button.textContent='立即购买'});
    });
  }
  /* ============ AI研究页：持久化 run + 同快照五维 + 一次综合写作 ============ */
  if(false){
  var researchState={conversationId:null,runId:null,run:null,busy:false,pollTimer:null};
  var DIM_META={
    financial:{name:'基本面分析',icon:'▥',desc:'财务、盈利质量、现金流与经营驱动'},
    market:{name:'行情与量价',icon:'↗',desc:'价格、成交、波动与相对表现'},
    industry:{name:'行业与竞争',icon:'◫',desc:'行业位置、同业比较与竞争格局'},
    event:{name:'公告与事件',icon:'◒',desc:'公告、监管文件、新闻与催化'},
    risk:{name:'风险与反证',icon:'⬟',desc:'反方证据、风险、缺口与失效条件'}
  };
  function selectEvidenceDimensions(){return Object.keys(DIM_META);}
  function renderEvidenceDimensions(){
    var list=$('#dimensionList');if(!list)return;
    list.innerHTML=selectEvidenceDimensions().map(function(key){var meta=DIM_META[key];return '<article class="card dimension" data-dim="'+key+'"><div class="dim-icon">'+meta.icon+'</div><div><h4>'+escapeHTML(meta.name)+'</h4><p>'+escapeHTML(meta.desc)+'</p><small class="muted dim-status">●　未启动</small></div><button class="btn small dim-start" type="button" data-dim="'+key+'">启动分析</button></article>';}).join('');
    refreshDimensionAvailability();
  }
  function researchRequest(path,options){
    options=options||{};var headers=Object.assign({},options.headers||{});
    if(options.body&&!(options.body instanceof FormData))headers['Content-Type']='application/json';
    return fetch(path,Object.assign({},options,{credentials:'same-origin',headers:headers})).then(function(r){
      return r.json().catch(function(){return {}}).then(function(body){
        if(r.status===404&&path.indexOf('/me/ai-research/')===0&&body.detail==='Not Found')throw new Error('当前后端尚未加载 AI 研究接口，请重启服务并刷新页面');
        if(!r.ok)throw new Error(body.detail||('请求失败：'+r.status));return body;
      });
    });
  }
  function researchIdempotencyKey(){
    if(window.crypto&&typeof window.crypto.randomUUID==='function')return window.crypto.randomUUID();
    return 'research-'+Date.now().toString(36)+'-'+Math.random().toString(36).slice(2)+'-'+Math.random().toString(36).slice(2);
  }
  var researchSessionPromise=null;
  function ensureResearchSession(){
    if(researchSessionPromise)return researchSessionPromise;
    researchSessionPromise=researchRequest('/session').catch(function(){researchSessionPromise=null;return {}});
    return researchSessionPromise;
  }
  function parseResearchTargets(raw){
    return String(raw||'').split(/[，,；;\n]+/).map(function(part){
      var value=part.trim();if(!value)return null;
      var match=value.match(/([0-9]{6}(?:\.(?:SZ|SS|SH|BJ))?|[A-Za-z]{1,6}(?:\.[A-Za-z]{1,4})?)\s*$/i);
      if(!match)return null;
      var symbol=match[1].toUpperCase().replace(/\.SH$/,'.SS');
      var name=value.slice(0,value.length-match[0].length).trim();
      return {symbol:symbol,name:name||null};
    }).filter(Boolean).filter(function(item,index,list){return list.findIndex(function(other){return other.symbol===item.symbol})===index;});
  }
  function resolveResearchTargets(raw){
    var parts=String(raw||'').split(/[，,；;\n]+/).map(function(part){return part.trim();}).filter(Boolean);
    return Promise.all(parts.map(function(part){
      var direct=parseResearchTargets(part);if(direct.length)return Promise.resolve(direct[0]);
      return researchRequest('/api/v1/stocks/search?q='+encodeURIComponent(part)+'&limit=5').then(function(payload){
        var items=payload&&Array.isArray(payload.items)?payload.items:[];
        var exact=items.find(function(item){return String(item.name||'').trim()===part;});
        var chosen=exact||(items.length===1?items[0]:null);if(!chosen)return null;
        return {symbol:String(chosen.internalSymbol||chosen.symbol||'').toUpperCase().replace(/\.SH$/,'.SS'),name:chosen.name||part};
      }).catch(function(){return null;});
    })).then(function(items){
      return items.filter(function(item){return item&&item.symbol;}).filter(function(item,index,list){return list.findIndex(function(other){return other.symbol===item.symbol;})===index;});
    });
  }
  function setDimState(dim,status,record){
    var card=document.querySelector('.dimension[data-dim="'+dim+'"]');if(!card)return;
    card.classList.remove('is-running','is-done','is-failed','is-disabled');
    var label='●　未启动',button='启动分析';
    if(status==='running'){card.classList.add('is-running');label='●　分析中';button='分析中…';}
    else if(status==='completed'){card.classList.add('is-done');label='●　已完成';button='查看结果';}
    else if(status==='failed'){card.classList.add('is-failed');label='●　失败可重试';button='重新分析';}
    else if(status==='disabled'){card.classList.add('is-disabled');label='请先指定股票';button='不可用';}
    var statusEl=card.querySelector('.dim-status'),btn=card.querySelector('.dim-start');
    if(statusEl)statusEl.textContent=label;
    if(btn){btn.textContent=button;btn.disabled=status==='running'||status==='disabled';}
    card.dataset.hasResult=record&&record.result?'true':'false';
  }
  function renderStructuredSection(result){
    result=result||{};var chunks=[];
    if(result.headline)chunks.push('<div class="research-result-headline">'+escapeHTML(result.headline)+'</div>');
    function list(title,items,mapper){
      items=Array.isArray(items)?items:[];if(!items.length)return;
      chunks.push('<section class="research-result-section"><h4>'+title+'</h4><ul>'+items.map(function(item){return '<li>'+mapper(item)+'</li>';}).join('')+'</ul></section>');
    }
    list('事实依据',result.facts,function(item){if(typeof item==='string')return escapeHTML(item);return '<b>'+escapeHTML(item.statement||'')+'</b>'+(item.basis?'<small>'+escapeHTML(item.basis)+'</small>':'')+(item.as_of?'<small>'+escapeHTML(item.as_of)+'</small>':'');});
    list('主要推断',result.interpretations,function(item){return escapeHTML(item);});
    list('反方证据',result.counterevidence,function(item){return escapeHTML(item);});
    list('证据缺口',result.gaps,function(item){return escapeHTML(item);});
    if(result.boundary)chunks.push('<section class="research-result-section boundary"><h4>结论边界</h4><p>'+escapeHTML(result.boundary)+'</p></section>');
    return chunks.join('')||'<p class="muted">暂无结构化结果。</p>';
  }
  function renderResearchAnswer(run){
    var copy=$('#assistantCopy');if(!copy)return;
    if(run.status==='running'){copy.innerHTML='<div class="research-loading"><span></span><p>AI 正在读取证据快照并生成主回答…</p></div>';return;}
    if(run.status==='failed'){copy.innerHTML='<div class="research-error"><b>研究生成失败</b><p>'+escapeHTML(run.error||'请稍后重试')+'</p><button class="btn small" type="button" id="retryMainResearch">重新生成</button></div>';var retry=$('#retryMainResearch');if(retry)retry.addEventListener('click',retryMainResearch);return;}
    var answer=run.detail_status==='completed'&&run.detailed_answer?run.detailed_answer:(run.main_answer||'（无回答内容）');
    var notices=Object.keys(DIM_META).filter(function(key){return run.dimensions&&run.dimensions[key]&&run.dimensions[key].status==='completed';}).map(function(key){return '<button type="button" class="research-notice" data-open-dim="'+key+'">'+escapeHTML(DIM_META[key].name)+'已完成 · 查看</button>';}).join('');
    copy.innerHTML='<div class="research-answer">'+escapeHTML(answer)+'</div>'+
      (notices?'<div class="research-notices">'+notices+'</div>':'')+
      '<div class="research-meta">结果已保存到当前研究会话与 run；刷新或重进会话仍可查看。结论仅供参考，不构成投资建议。</div>';
    copy.querySelectorAll('[data-open-dim]').forEach(function(button){button.addEventListener('click',function(){openDimModal(button.dataset.openDim);});});
  }
  function refreshDimensionAvailability(){
    var targets=parseResearchTargets($('#researchTarget')?$('#researchTarget').value:'');
    var run=researchState.run,multi=targets.length>1||(run&&run.multi_target);
    Object.keys(DIM_META).forEach(function(key){
      var record=run&&run.dimensions?run.dimensions[key]:null;
      var status=record&&record.status;
      if(!run||run.status==='running')status=targets.length===1?'idle':'disabled';
      if(!targets.length)status='disabled';
      if(multi)status='disabled';
      setDimState(key,status||'idle',record);
    });
    var hint=$('#dimensionHint'),parallelHint=$('#parallelHint'),pa=$('#startParallelAnalysis');
    if(!targets.length){if(hint)hint.textContent='请先指定股票';if(parallelHint)parallelHint.textContent='请先填写带证券代码的研究标的。';}
    else if(multi){if(hint)hint.textContent='多标的仅支持主对话综合';if(parallelHint)parallelHint.textContent='多标的研究会在主对话统一比较，右侧五维不单独运行。';}
    else{if(hint)hint.textContent='五维先生成结构化小节；详细回答会读齐五维后再统一写作。';if(parallelHint)parallelHint.textContent='一次并行生成五维结构化小节，再基于同一快照完成一次综合写作。';}
    if(pa){
      var detailStatus=run&&run.detail_status;
      pa.textContent=detailStatus==='running'?'详细回答生成中…':(detailStatus==='completed'?'重新生成详细回答':(detailStatus==='failed'?'详细回答失败，重试':'生成详细回答'));
      pa.disabled=!run||run.status!=='completed'||multi||targets.length!==1||detailStatus==='running';
    }
  }
  function applyResearchRun(run,restoreForm){
    if(!run)return;
    researchState.run=run;researchState.runId=run.run_id;researchState.conversationId=run.conversation_id;
    if(restoreForm){
      var target=$('#researchTarget'),question=$('#researchQuestion');
      if(target&&run.targets)target.value=run.targets.map(function(item){return (item.name&&item.name!==item.symbol?item.name+' ':'')+item.symbol;}).join('；');
      if(question)question.value=run.question||'';
    }
    var meta=$('#researchAssistantMeta');if(meta)meta.textContent=(run.skill&&run.skill.active?'老李视角 · ':'')+(run.status==='running'?'分析中':(run.status==='failed'?'失败可重试':'已完成'));
    var evidenceMeta=$('#researchEvidenceMeta');if(evidenceMeta){var web=run.web_search||{},webText=web.status==='completed'?(' · 联网来源 '+Number(web.source_count||0)+' 条'):(web.status==='partial'?(' · 联网来源 '+Number(web.source_count||0)+' 条（部分失败）'):(web.status==='not_configured'?' · 联网待配置':(web.status==='failed'?' · 联网失败':' ')));evidenceMeta.textContent=(run.snapshot_captured_at?'证据快照 '+String(run.snapshot_captured_at).replace('T',' ').slice(0,16):'证据快照已保存')+webText;}
    renderResearchAnswer(run);refreshDimensionAvailability();
    var active=run.status==='running'||run.detail_status==='running'||Object.keys(run.dimensions||{}).some(function(key){return run.dimensions[key].status==='running';});
    if(active)startResearchPolling();else stopResearchPolling();
  }
  function loadResearchRun(restoreForm){
    if(!researchState.runId)return Promise.resolve();
    return researchRequest('/me/ai-research/runs/'+encodeURIComponent(researchState.runId)).then(function(run){applyResearchRun(run,!!restoreForm);return run;});
  }
  function pollResearchRun(){
    loadResearchRun(false).catch(function(){stopResearchPolling();});
  }
  function startResearchPolling(){
    if(researchState.pollTimer)return;
    researchState.pollTimer=setInterval(pollResearchRun,1400);
  }
  function stopResearchPolling(){if(researchState.pollTimer){clearInterval(researchState.pollTimer);researchState.pollTimer=null;}}
  function setResearchBusy(busy){
    researchState.busy=busy;var sr=$('#startResearch'),sf=$('#researchSend'),rf=$('#researchFollowup');
    if(sr)sr.disabled=busy;if(sf)sf.disabled=busy;if(rf)rf.disabled=busy;
  }
  function runMainResearch(question){
    if(researchState.busy)return;
    var q=String(question||'').trim();if(!q){toast('请先填写研究问题');return;}
    var rawTarget=$('#researchTarget')?$('#researchTarget').value:'';
    if(!String(rawTarget||'').trim()){toast('请先指定股票');refreshDimensionAvailability();return;}
    setResearchBusy(true);
    var copy=$('#assistantCopy');if(copy)copy.innerHTML='<div class="research-loading"><span></span><p>正在识别股票并建立证据快照…</p></div>';
    resolveResearchTargets(rawTarget).then(function(targets){
      if(!targets.length)throw new Error('没有识别到有效股票，请补充股票代码');
      var targetInput=$('#researchTarget');if(targetInput)targetInput.value=targets.map(function(item){return (item.name?item.name+' ':'')+item.symbol;}).join('；');
      return ensureResearchSession().then(function(){return targets;});
    }).then(function(targets){
      var body={question:q,targets:targets};if(researchState.conversationId)body.conversation_id=researchState.conversationId;
      return researchRequest('/me/ai-research/runs',{method:'POST',headers:{'Idempotency-Key':researchIdempotencyKey()},body:JSON.stringify(body)});
    }).then(function(run){applyResearchRun(run,false);toast('研究任务已启动');})
      .catch(function(error){if(copy)copy.innerHTML='<div class="research-error"><b>无法启动研究</b><p>'+escapeHTML(error.message)+'</p></div>';toast(error.message);})
      .then(function(){setResearchBusy(false);refreshDimensionAvailability();});
  }
  function retryMainResearch(){
    if(!researchState.runId)return;
    researchRequest('/me/ai-research/runs/'+encodeURIComponent(researchState.runId)+'/retry',{method:'POST'}).then(function(run){applyResearchRun(run,false);toast('已重新生成');}).catch(function(error){toast(error.message);});
  }
  function openDimModal(dim){
    var meta=DIM_META[dim]||{name:dim};var record=researchState.run&&researchState.run.dimensions?researchState.run.dimensions[dim]:null;
    $('#researchModalTitle').textContent=meta.name;
    var body=$('#researchModalBody');
    if(record&&record.status==='completed')body.innerHTML=renderStructuredSection(record.result);
    else if(record&&record.status==='running')body.innerHTML='<div class="research-loading"><span></span><p>正在分析中，请稍候…</p></div>';
    else if(record&&record.status==='failed')body.innerHTML='<div class="research-error"><b>分析失败</b><p>'+escapeHTML(record.error||'请重试')+'</p></div>';
    else body.innerHTML='<p class="muted">尚未启动该维度分析。</p>';
    $('#researchModal').classList.add('show');
  }
  function handleDimClick(dim){
    var run=researchState.run,record=run&&run.dimensions?run.dimensions[dim]:null;
    if(!run){toast('请先开始研究');return;}
    if(record&&record.status==='completed'){openDimModal(dim);return;}
    if(record&&record.status==='running'){openDimModal(dim);return;}
    researchRequest('/me/ai-research/runs/'+encodeURIComponent(run.run_id)+'/dimensions/'+encodeURIComponent(dim),{method:'POST'}).then(function(next){applyResearchRun(next,false);toast((DIM_META[dim]||{}).name+'已启动');}).catch(function(error){toast(error.message);});
  }
  function runParallel(){
    var run=researchState.run;if(!run){toast('请先开始研究');return;}
    researchRequest('/me/ai-research/runs/'+encodeURIComponent(run.run_id)+'/detail',{method:'POST'}).then(function(next){applyResearchRun(next,false);toast('五维分析与综合写作已启动');}).catch(function(error){toast(error.message);});
  }
  (function initResearch(){
    renderEvidenceDimensions();
    var dimensionList=$('#dimensionList');if(dimensionList)dimensionList.addEventListener('click',function(event){var button=event.target.closest('.dim-start');if(button)handleDimClick(button.getAttribute('data-dim'));});
    $$('.chips .chip').forEach(function(button){button.addEventListener('click',function(){var box=$('#researchQuestion');if(box){box.value=button.textContent+'，请给出数据依据和结论边界。';toast('问题已填入研究框');}});});
    var sr=$('#startResearch');if(sr)sr.addEventListener('click',function(){runMainResearch($('#researchQuestion')?$('#researchQuestion').value:'');});
    var pa=$('#startParallelAnalysis');if(pa)pa.addEventListener('click',runParallel);
    var rf=$('#researchFollowup'),send=$('#researchSend');
    function sendFollow(){if(!rf)return;var value=rf.value.trim();if(!value){toast('请输入追问内容');return;}rf.value='';runMainResearch(value);}
    if(send)send.addEventListener('click',sendFollow);
    if(rf)rf.addEventListener('keydown',function(event){if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendFollow();}});
    var target=$('#researchTarget');if(target)target.addEventListener('input',refreshDimensionAvailability);
    if(!document.getElementById('researchModal')){
      var modal=document.createElement('div');modal.className='research-modal';modal.id='researchModal';
      modal.innerHTML='<div class="research-modal-card"><div class="research-modal-head"><h3 id="researchModalTitle" style="margin:0">维度分析</h3><button class="research-modal-close" id="researchModalClose" type="button" aria-label="关闭">×</button></div><div class="research-modal-body" id="researchModalBody"></div></div>';
      document.body.appendChild(modal);modal.addEventListener('click',function(event){if(event.target===modal)modal.classList.remove('show');});$('#researchModalClose').addEventListener('click',function(){modal.classList.remove('show');});
    }
    ensureResearchSession().then(function(){return researchRequest('/me/ai-research/runs/current');}).then(function(payload){if(payload&&payload.item)applyResearchRun(payload.item,true);else refreshDimensionAvailability();}).catch(function(){refreshDimensionAvailability();});
  })();

  }
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
    dashboard:'/api/v1/dashboard/today',
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
    fetchDashboard:function(){
      if(!todayConfig.baseURL)return Promise.resolve({indices:todayDemo.indices,marketOverview:todayDemo.marketOverview,industryRotation:todayDemo.industryRotation,riseFallDistribution:todayDemo.riseFallDistribution,hotThemes:todayDemo.hotThemes,tradingActivity:todayDemo.tradingActivity,sectorFundFlow:todayDemo.sectorFundFlow});
      return todayRequest(todayConfig.endpoints.dashboard);
    },
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
    baseURL:window.location.origin,symbol:'300750.SZ',headers:{},credentials:'same-origin',allowedProtocols:['http:','https:'],endpoints:{}
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
  function sourceStyle(source){
    source=String(source||'');
    if(source.indexOf('巨潮')>-1)return {label:'巨潮',className:'cninfo'};
    if(source.indexOf('同花顺')>-1)return {label:'同花',className:'ths'};
    if(source.indexOf('财联社')>-1)return {label:'财联',className:'cls'};
    if(source.indexOf('雪球')>-1)return {label:'雪球',className:'xueqiu'};
    if(source.indexOf('理杏仁')>-1)return {label:'理杏',className:'lixinger'};
    if(source.indexOf('新浪')>-1)return {label:'新浪',className:'sina'};
    if(source.indexOf('证券时报')>-1)return {label:'证券',className:'stcn'};
    return {label:'东财',className:'eastmoney'};
  }
  function insightPillClass(type){type=String(type||'');if(type.indexOf('政策')>-1)return 'purple';if(type.indexOf('行业')>-1)return 'green';if(type.indexOf('公司')>-1)return 'orange';return 'blue'}
  function renderStockNews(payload){
    var list=$('#stockNewsList'),items=unwrapList(payload);if(!list)return;
    if(!items.length){list.innerHTML='<div class="empty-state">暂时没有可用的关键词检索入口</div>';return}
    list.innerHTML=items.map(function(item){var source=sourceStyle(item.source),target=trustedStockLink(item.appUrl)||'#';if(target==='#')target=trustedStockLink(item.url);return '<a class="news-item" href="'+escapeHTML(target)+'" target="_blank" rel="noopener noreferrer" data-news-id="'+escapeHTML(item.id)+'"><span class="source-mark '+source.className+'">'+source.label+'</span><span class="news-copy"><b class="news-title">'+escapeHTML(item.title)+'</b><span class="news-meta"><span>'+escapeHTML(item.source)+'</span><span>'+escapeHTML(item.category||'个股资讯')+'</span><time>'+escapeHTML(item.publishedAt||'--')+'</time></span></span><span class="external-arrow">↗</span></a>'}).join('');
  }
  function renderStockInsights(payload){
    var list=$('#stockInsightList'),status=$('#stockInsightStatus'),items=unwrapList(payload).slice(0,5);if(!list)return;
    if(status)status.textContent=payload&&payload.status==='completed'?'已更新 · 三天有效':payload&&payload.status==='not_configured'?'等待Tavily密钥':'三天一更';
    if(!items.length){var warning=payload&&payload.warning?payload.warning:'暂时没有可展示的行业精选';list.innerHTML='<div class="empty-state">'+escapeHTML(warning)+'</div>';return}
    list.innerHTML=items.map(function(item){var top=item.isTop||item.priority==='high',target=trustedStockLink(item.url),tag=target==='#'?'article':'a',linkAttrs=target==='#'?'':' href="'+escapeHTML(target)+'" target="_blank" rel="noopener noreferrer"';return '<'+tag+' class="insight-item'+(top?' priority':'')+'"'+linkAttrs+' data-insight-id="'+escapeHTML(item.id)+'"><div class="insight-top"><span class="pill '+insightPillClass(item.type)+'">'+escapeHTML(item.type||'行业关注')+'</span><span class="admin-badge">AI筛选</span></div><h4 class="insight-title">'+escapeHTML(item.title)+'</h4><p class="insight-summary">'+escapeHTML(item.summary)+'</p><div class="insight-foot"><span>'+escapeHTML(item.source||'联网来源')+'</span><time>'+escapeHTML(item.publishedAt||'近期')+'</time></div></'+tag+'>'}).join('');
  }
  window.QSUpdateStockIntelligence=function(payload){payload=payload||{};if(payload.news)renderStockNews(payload.news);if(payload.curatedInsights)renderStockInsights(payload.curatedInsights);return payload};
  window.QSReloadStockIntelligence=function(options){
    options=Object.assign({symbol:stockIntelConfig.symbol},options||{});
    var insightList=$('#stockInsightList'),insightStatus=$('#stockInsightStatus');if(insightList)insightList.innerHTML='<div class="empty-state">正在联网读取行业信息并筛选…</div>';if(insightStatus)insightStatus.textContent='读取中';
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
        if(canvas&&Array.isArray(item.trend)&&item.trend.length>1){canvas.setAttribute('data-points',item.trend.join(','));canvas.setAttribute('data-color',change>=0?CHART_UP_RED:CHART_DOWN_GREEN);line(canvas,item.trend,change>=0?CHART_UP_RED:CHART_DOWN_GREEN,true)}
      });
    },
    marketOverview:function(data){
      var card=$('#marketOverviewCard');if(!card||!data)return;var sides=card.querySelectorAll('.overview-wrap>div'),total=Number(data.total)||0,risingRate=Number(data.risingRate)||0,flatRate=Number(data.flatRate)||0,flatEnd=Math.min(100,risingRate+flatRate),donut=card.querySelector('.donut'),meta=$('#marketOverviewMeta');
      if(sides[0]){sides[0].querySelector('strong').textContent=numberText(data.rising,0);sides[0].querySelector('small').textContent=numberText(risingRate,2)+'%'}
      card.querySelector('.donut-center strong').textContent=numberText(total,0);
      if(sides[2]){sides[2].querySelector('strong').textContent=numberText(data.falling,0);sides[2].querySelector('small').textContent=numberText(data.fallingRate,2)+'%'}
      donut.style.background='conic-gradient('+CHART_UP_RED+' 0 '+risingRate+'%,'+CHART_FLAT_GRAY+' '+risingRate+'% '+flatEnd+'%,'+CHART_DOWN_GREEN+' '+flatEnd+'% 100%)';
      if(meta){var limitText=data.limitDataStatus==='date_mismatch'?'涨跌停数据仅到 '+(data.limitDataAsOf||'--')+'，未与本快照合并':data.limitDataStatus==='aligned'?'涨停 '+numberText(data.limitUp,0)+' / 跌停 '+numberText(data.limitDown,0):'涨跌停数据待补齐';meta.textContent='市场快照 '+(data.marketDate||'--')+'：平盘 '+numberText(data.flat,0)+' 只（'+numberText(data.flatRate,2)+'%） · '+limitText}
    },
    industryRotation:function(items){
      var list=$('#industryRotationList');if(!list)return;var rows=unwrapList(items);
      if(!rows.length){list.innerHTML='<p class="today-card-loading">行业轮动数据暂不可用</p>';return}
      list.innerHTML=rows.map(function(item,index){
        var change=Number(item.changePct),rawFive=item.fiveDayChangePct,five=rawFive===null||rawFive===undefined?NaN:Number(rawFive),trend=Array.isArray(item.trend)?item.trend.map(Number).filter(Number.isFinite):[],trendDates=Array.isArray(item.trendMarketDates)?item.trendMarketDates:[],available=item.trendStatus==='available'&&trend.length>=3&&trendDates.length===trend.length;
        var trendCell=available?'<canvas class="sparkline mini-line" data-color="'+(change>=0?CHART_UP_RED:CHART_DOWN_GREEN)+'" data-points="'+trend.join(',')+'" title="'+escapeHTML(trendDates[0]+' 至 '+trendDates[trendDates.length-1])+'"></canvas>':'<span class="mini-line-unavailable">历史走势补齐中</span>';
        var fiveCell=Number.isFinite(five)?'<span class="'+trendClass(five)+'">'+signedText(five,'%',2)+'</span>':'<span class="muted">—</span>';
        return '<div class="rank-row"><i class="rank-no">'+escapeHTML(item.rank||index+1)+'</i><b>'+escapeHTML(item.name)+'</b><span class="'+trendClass(change)+'">'+signedText(change,'%',2)+'</span>'+trendCell+fiveCell+'<span>'+numberText(item.turnover,2)+'</span></div>';
      }).join('');list.querySelectorAll('canvas').forEach(function(canvas){line(canvas,canvas.getAttribute('data-points').split(','),canvas.getAttribute('data-color'),false)});
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
      if(period)period.textContent=(data.period||'近7日')+' · 单位：亿元';
      if(!points.length){bar.innerHTML='<p class="today-card-loading">成交额历史暂不可用</p>';return}
      bar.innerHTML=points.map(function(item,index){var height=Math.max(12,(Number(item.value)||0)/max*88),marketDate=item.marketDate||item.date||'';return '<div class="bar-column '+(index===points.length-1?'latest':'')+'" title="'+escapeHTML(marketDate+' 成交额 '+numberText(item.value,2)+' 亿元')+'"><b class="bar-value">'+numberText(item.value,0)+'</b><span class="bar-plot"><i class="bar-fill" style="height:'+height+'%"></i></span><small class="bar-date">'+escapeHTML(item.date)+'</small></div>'}).join('');
      var label=data.activity_label||'成交额数据不足',relative=Number(data.relative_to_average_pct);
      summary.innerHTML='<span><small>'+(data.latest_is_intraday?'盘中累计':'最新成交额')+'</small><b class="blue">'+numberText(data.latest,0)+' 亿</b></span><span><small>近7日完整均值</small><b>'+numberText(data.average,0)+' 亿</b></span><span><small>'+escapeHTML(label)+'</small><b class="'+(Number.isFinite(relative)?trendClass(relative):'muted')+'">'+signedText(relative,'%',2)+'</b></span>';
    },
    sectorFundFlow:function(items){
      var list=$('#sectorFundFlowList');if(!list)return;var packet=items||{},rows=unwrapList(packet),max=Math.max.apply(null,rows.map(function(item){return Math.abs(Number(item.value)||0)}).concat([1])),label=packet.metric_label||'主力净流入估算（亿元）';list.innerHTML='<p class="muted">'+escapeHTML(label)+'，不是全市场资金净流入；仅代表当前数据源覆盖板块。</p>'+rows.map(function(item){var value=Number(item.value)||0,positive=value>=0;return '<div class="flow-row"><span>'+escapeHTML(item.name)+'</span><div class="flowbar '+(positive?'positive':'negative')+'"><span class="flow-axis"></span><i style="width:'+Math.max(2,Math.abs(value)/max*48)+'%"></i></div><b class="'+trendClass(value)+'">'+signedText(value,'',2)+'</b></div>'}).join('');
    }
  };
  var todayLoaders={
    indices:function(){return Promise.all(todayDemo.indices.map(function(item){return window.QSTodayAPI.fetchIndex({code:item.code})})).then(function(data){todayRenderers.indices(data);return data})},
    marketOverview:function(){return Promise.resolve(window.QSTodayAPI.fetchMarketOverview()).then(function(data){todayRenderers.marketOverview(data);return data})},
    industryRotation:function(){return Promise.resolve(window.QSTodayAPI.fetchIndustryRotation()).then(function(data){todayRenderers.industryRotation(data);return data})},
    riseFallDistribution:function(){return Promise.resolve(window.QSTodayAPI.fetchRiseFallDistribution()).then(function(data){todayRenderers.riseFallDistribution(data);return data})},
    hotThemes:function(){return Promise.resolve(window.QSTodayAPI.fetchHotThemes()).then(function(data){todayRenderers.hotThemes(data);return data})},
    tradingActivity:function(){return Promise.resolve(window.QSTodayAPI.fetchTradingActivity()).then(function(data){todayRenderers.tradingActivity(data);return data})},
    sectorFundFlow:function(){return Promise.resolve(window.QSTodayAPI.fetchSectorFundFlow()).then(function(data){todayRenderers.sectorFundFlow(data);return data})}
  };
  function todayModuleNeedsRefresh(key,value){
    if(key==='indices')return unwrapList(value).length<4;
    if(key==='marketOverview')return !value||Number(value.total)<=0||!value.marketDate;
    if(key==='industryRotation'){var industries=unwrapList(value);return !industries.length||industries.some(function(item){return item.trendStatus!=='available'||!Array.isArray(item.trend)||item.trend.length<3})}
    if(key==='riseFallDistribution')return !value||!unwrapList(value.bins).length||!value.marketDate;
    if(key==='hotThemes')return !unwrapList(value).length;
    if(key==='tradingActivity')return !value||unwrapList(value.points).length<3;
    if(key==='sectorFundFlow')return !value||!unwrapList(value).length;
    return false;
  }
  function todayAlignmentRecoveryKeys(payload){
    var mismatches=unwrapList(payload&&payload.dateAlignment&&payload.dateAlignment.mismatchedModules),mapping={limits:'marketOverview',marketOverview:'marketOverview',riseFallDistribution:'riseFallDistribution',industryRotation:'industryRotation',hotThemes:'hotThemes',tradingActivity:'tradingActivity',sectorFundFlow:'sectorFundFlow',indices:'indices'},keys=[];
    mismatches.forEach(function(module){var key=mapping[module];if(key&&keys.indexOf(key)===-1)keys.push(key)});
    return keys;
  }
  function todayModuleMarketDate(key,value){
    if(key==='marketOverview'||key==='riseFallDistribution')return value&&value.marketDate||'';
    if(key==='tradingActivity'){var activity=unwrapList(value&&value.points);return activity.length?activity[activity.length-1].marketDate||'':''}
    if(key==='industryRotation'||key==='hotThemes'){var rows=unwrapList(value);return rows.length?rows[0].marketDate||String(rows[0].marketTimestamp||'').slice(0,10):''}
    if(key==='sectorFundFlow')return value&&value.marketDate||String(value&&value.marketTimestamp||'').slice(0,10);
    if(key==='indices'){var indices=unwrapList(value);return indices.length?indices[0].marketDate||String(indices[0].marketTimestamp||'').slice(0,10):''}
    return '';
  }
  function todayUpdateTime(value){if(!value)return '处理时间待确认';var date=new Date(value);if(Number.isNaN(date.getTime()))return '处理时间待确认';return date.toLocaleString('zh-CN',{hour12:false,month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})}
  function todayModuleLabel(key){return {indices:'指数',marketOverview:'市场总览',limits:'涨跌停',industryRotation:'行业轮动',riseFallDistribution:'涨跌结构',hotThemes:'热门方向',tradingActivity:'成交活跃度',sectorFundFlow:'板块资金'}[key]||key}
  function renderTodayDataStatus(payload,pendingKeys){
    var status=$('#todayDataStatus');if(!status)return;payload=payload||{};pendingKeys=Array.isArray(pendingKeys)?pendingKeys:[];
    var backendAlignment=payload.dateAlignment||{},moduleDates={},keys=Object.keys(todayLoaders);
    keys.forEach(function(key){var marketDate=todayModuleMarketDate(key,payload[key]);if(marketDate)moduleDates[key]=marketDate});
    if(payload.marketOverview&&payload.marketOverview.limitDataAsOf)moduleDates.limits=payload.marketOverview.limitDataAsOf;
    var anchor=payload.asOfMarketDate||(payload.marketOverview&&payload.marketOverview.marketDate)||todayModuleMarketDate('tradingActivity',payload.tradingActivity);
    var mismatches=anchor?Object.keys(moduleDates).filter(function(key){return moduleDates[key]!==anchor}):[];
    if(!mismatches.length&&backendAlignment.status==='mixed')mismatches=unwrapList(backendAlignment.mismatchedModules).filter(function(key){return moduleDates[key]&&moduleDates[key]!==anchor});
    if(pendingKeys.length){status.textContent=(anchor?'数据截止 '+anchor+' · ':'')+'正在补齐：'+pendingKeys.map(todayModuleLabel).join('、');return}
    if(mismatches.length){status.textContent='数据日期未完全对齐 · 待补齐：'+mismatches.map(todayModuleLabel).join('、');return}
    status.textContent=(anchor?'数据截止 '+anchor+'（最近交易日）':'市场日期待确认')+' · 页面更新 '+todayUpdateTime(payload.generatedAt);
  }
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
    return Promise.resolve(window.QSTodayAPI.fetchDashboard()).then(function(payload){
      window.QSUpdateTodayDashboard(payload);
      var recoveryKeys=Object.keys(todayLoaders).filter(function(key){return todayModuleNeedsRefresh(key,payload[key])});
      todayAlignmentRecoveryKeys(payload).forEach(function(key){if(recoveryKeys.indexOf(key)===-1)recoveryKeys.push(key)});
      renderTodayDataStatus(payload,recoveryKeys);
      if(!recoveryKeys.length)return payload;
      return Promise.allSettled(recoveryKeys.map(function(key){return todayLoaders[key]()})).then(function(results){
        results.forEach(function(result,index){if(result.status==='fulfilled')payload[recoveryKeys[index]]=result.value});
        var remaining=recoveryKeys.filter(function(key){return todayModuleNeedsRefresh(key,payload[key])});
        renderTodayDataStatus(payload,remaining);
        return payload;
      });
    }).catch(function(error){
      console.warn(error);
      return Promise.allSettled(Object.keys(todayLoaders).map(function(key){return todayLoaders[key]()})).then(function(results){
        var success=results.filter(function(item){return item.status==='fulfilled'}).length;
        if(status)status.textContent='聚合接口已降级 · 已更新 '+success+'/'+results.length+' 个数据模块';
        return results;
      });
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
  var stockPageRequested=false;
  var stockState={symbol:'300750.SZ',name:'宁德时代',market:'A股',searchItems:[],activeSearchIndex:-1,searchSequence:0,loadSequence:0,loading:false};
  var stockWatchState={symbol:null,inWatchlist:false,loading:false,mode:'idle'};
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
  function stockDataStateLabel(value){
    return {available:'可用',partial:'部分可用',unavailable:'暂无数据',warming:'准备中'}[value]||'状态待确认';
  }
  function stockMetric(name,value,suffix){
    $$('[data-stock-metric="'+name+'"]').forEach(function(node){var number=value===null||value===undefined||value===''?NaN:Number(value);node.textContent=Number.isFinite(number)?numberText(number,2)+(suffix||''):'--'});
  }
  function renderStockCard(data){
    var identity=data.identity||{},quote=data.quote||{},metrics=data.metrics||{},change=Number(quote.changePct),changeValue=Number(quote.change),price=Number(quote.price),priceNode=document.querySelector('[data-stock-field="price"]');
    stockState.symbol=data.symbol||stockState.symbol;stockState.name=identity.name||stockState.symbol;stockState.market=identity.market||'A股';
    setStockField('name',stockState.name);setStockField('symbol',stockState.symbol);setStockField('market',identity.market||'A股');setStockField('industry',identity.industry||'行业待更新');setStockField('intelSymbol',stockState.name+' '+stockState.symbol);
    if(priceNode){
      priceNode.className='quote '+(Number.isFinite(change)?trendClass(change):'');
      priceNode.innerHTML=(Number.isFinite(price)?numberText(price,2):'--')+' <small>'+(Number.isFinite(changeValue)?signedText(changeValue,'',2):'--')+'　'+(Number.isFinite(change)?signedText(change,'%',2):'--')+'</small>';
    }
    setStockField('quoteMeta','最新行情　'+stockTime(quote.marketTimestamp)+'　数据来源：'+(quote.source||'行情数据服务'));
    setStockField('open',numberText(quote.open,2));setStockField('previousClose',numberText(quote.previousClose,2));setStockField('turnoverRatePct',quote.turnoverRatePct===null||quote.turnoverRatePct===undefined?'--':numberText(quote.turnoverRatePct,2)+'%');
    setStockField('high',numberText(quote.high,2));setStockField('low',numberText(quote.low,2));setStockField('heroPeTtm',numberText(metrics.peTtm,2));setStockField('volumeShares',stockVolume(quote.volumeShares));setStockField('amountCny',stockMoney(quote.amountCny));setStockField('totalMarketCapCny',stockMoney(quote.totalMarketCapCny));
    stockMetric('peTtm',metrics.peTtm,'');stockMetric('pbLf',metrics.pbLf,'');stockMetric('roeWeightedReport',metrics.roeWeightedReport,'%');stockMetric('revenueYoy',metrics.revenueYoy,'%');stockMetric('parentNetProfitYoy',metrics.parentNetProfitYoy,'%');
    setStockField('reportName',metrics.reportName||metrics.reportDate||'最新财报');
    setStockField('valuationSource','估值：'+(metrics.valuationSource||'暂不可用')+' · '+stockTime(metrics.valuationTimestamp));
    setStockField('financialSource','财务：'+(metrics.financialSource||'暂不可用'));
    setStockField('reportBasis','报告期：'+(metrics.reportName||metrics.reportDate||'--')+(metrics.periodBasis==='year_to_date_cumulative'?' · 年初至报告期累计':''));
    var dataStatus=data.dataStatus||{},officialSearch=data.officialSearch||{},status=$('#stockDataStatus');if(status){status.classList.remove('stock-error');var query=encodeURIComponent(officialSearch.cninfoQuery||stockState.name),quoteState=stockDataStateLabel(dataStatus.quote||'unavailable'),financialState=stockDataStateLabel(dataStatus.financials||'unavailable'),refreshState=data.refresh&&data.refresh.status!=='idle'?' · 数据更新中':'';status.innerHTML=escapeHTML(stockState.name+' · 行情'+quoteState+' · 财务'+financialState+refreshState)+' · <a href="https://www.cninfo.com.cn/new/fulltextSearch?notautosubmit=&keyWord='+query+'" target="_blank" rel="noopener noreferrer">巨潮资讯检索</a> · <a href="https://so.eastmoney.com/web/s?keyword='+query+'" target="_blank" rel="noopener noreferrer">研报检索</a>'}
    var priceChartNode=$('#priceChart'),volumeChartNode=$('#volumeChart');if(priceChartNode)priceChartNode.setAttribute('aria-label',stockState.name+'K线图');if(volumeChartNode)volumeChartNode.setAttribute('aria-label',stockState.name+'成交量图');
    stockIntelConfig.symbol=stockState.symbol;
  }
  function renderStockWatchButton(){
    var button=$('#stockWatchButton');if(!button)return;
    button.classList.toggle('active',stockWatchState.inWatchlist);
    button.disabled=stockWatchState.loading;
    button.textContent=stockWatchState.loading?(stockWatchState.mode==='checking'?'检查关注状态…':'正在保存…'):(stockWatchState.inWatchlist?'✓ 已关注 · 查看':'＋ 关注');
    button.title=stockWatchState.inWatchlist?'已保存到“我的关注”，点击查看':'保存到“我的关注”';
  }
  function syncStockWatchButton(symbol){
    stockWatchState.symbol=symbol;stockWatchState.loading=true;stockWatchState.mode='checking';renderStockWatchButton();
    return ensureWatchlistSession().then(function(){return watchRequest('/api/v1/me/watchlist')}).then(function(payload){
      if(stockWatchState.symbol!==symbol)return;
      var items=unwrapList(payload);stockWatchState.inWatchlist=items.some(function(item){return comparableWatchSymbol(item.symbol)===comparableWatchSymbol(symbol)});
    }).catch(function(error){
      if(stockWatchState.symbol===symbol){stockWatchState.inWatchlist=false;toast('关注状态读取失败：'+error.message)}
    }).finally(function(){if(stockWatchState.symbol===symbol){stockWatchState.loading=false;stockWatchState.mode='idle';renderStockWatchButton()}});
  }
  function saveCurrentStockToWatchlist(){
    if(stockWatchState.inWatchlist){showPage('watch');return}
    var symbol=stockState.symbol;stockWatchState.symbol=symbol;stockWatchState.loading=true;stockWatchState.mode='saving';renderStockWatchButton();
    ensureWatchlistSession().then(function(){
      return watchRequest('/api/v1/me/watchlist',{method:'POST',body:JSON.stringify({symbol:symbol,name:stockState.name||null,priority:'normal',reason:'从个股评分库加入关注，待补充明确关注理由',catalyst_condition:null,invalidation_condition:null,tracking_frequency:'weekly',tracking_status:'active'})});
    }).then(function(saved){
      if(stockWatchState.symbol!==symbol)return;
      stockWatchState.inWatchlist=true;
      var existing=watchState.items.find(function(item){return comparableWatchSymbol(item.symbol)===comparableWatchSymbol(symbol)});
      if(existing)Object.assign(existing,saved);else watchState.items.push(saved);
      toast('已加入“我的关注”');
    }).catch(function(error){toast('关注失败：'+error.message)}).finally(function(){
      if(stockWatchState.symbol===symbol){stockWatchState.loading=false;stockWatchState.mode='idle';renderStockWatchButton()}
    });
  }
  function industryNumber(value,digits){
    var number=Number(value);return Number.isFinite(number)?numberText(number,digits===undefined?2:digits):'--';
  }
  function industryFactorBand(score){
    var value=Number(score);
    if(!Number.isFinite(value))return '数据不足';
    if(value>=80)return '行业领先';
    if(value>=65)return '相对较强';
    if(value>=35)return '行业中游';
    if(value>=20)return '相对较弱';
    return '行业靠后';
  }
  function industryFactorDescription(key){
    return {
      growth:'收入与利润增长相对同行的位置',
      valuation:'PE、PB 等估值指标相对同行的位置',
      profitability:'ROE、ROIC 和利润表现相对同行的位置',
      stability:'偿债能力、负债结构和盈利波动相关指标',
      efficiency:'资产周转、现金回收和经营投入效率'
    }[key]||'基于当前公式计算的同行相对位置';
  }
  function clampChartLabelY(value,min,max){
    return Math.max(min,Math.min(max,value));
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
    var left=8,right=8,top=25,bottom=h-40,plotHeight=Math.max(50,bottom-top),groupWidth=(w-left-right)/series.length,colors=[CHART_PRIMARY_BLUE,'#72a7f5',CHART_COMPARE_GREEN];
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
          c.fillStyle='#526680';var label=numberText(value,Math.abs(value)>=100?0:1);var labelY=clampChartLabelY(value>=0?barTop-8:barTop+barHeight+9,9,h-30);c.fillText(label,x+barWidth/2,labelY);
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
  }
  function renderIndustryComparison(data){
    var factors=unwrapList(data.factors),industry=data.industry||{},coverage=data.coverage||{},radarData=data.radar||{},card=$('#industryFactorCard'),body=$('#industryFactorBody'),status=$('#industryFactorStatus');
    if(card)card.classList.remove('industry-factor-loading');if(body)body.setAttribute('aria-busy','false');
    if(status){status.className='pill '+(data.status==='available'?'green':'');status.textContent=data.status==='available'?'真实数据已更新':data.status==='warming'?'后台准备中':'部分数据可用'}
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
      return '<article class="industry-factor-score '+industryFactorStateClass(factor)+'"><div class="industry-factor-score-head"><span>'+escapeHTML(factor.label||factor.key)+'</span><b>'+escapeHTML(available?industryFactorBand(factor.score):'数据不足')+'</b></div><strong>'+(available?industryNumber(factor.score,1):'--')+' <small>/ 100</small></strong><p class="industry-factor-coverage">'+escapeHTML(factor.state||'数据不足')+' · 数据覆盖 '+industryNumber(factor.coveragePct,0)+'%</p><p class="industry-factor-description">'+escapeHTML(industryFactorDescription(factor.key))+'</p></article>';
    }).join('')||'<div class="industry-factor-empty">暂无可展示的维度数据</div>';
    var warnings=unwrapList(data.warnings),note=$('#industryFactorNote');
    if(note)note.textContent='分数表示公司在同一申万二级行业内的相对位置，50分约为行业中位。'+(warnings.length?' '+warnings[0]:'');
  }
  function renderIndustryComparisonError(error){
    var card=$('#industryFactorCard'),body=$('#industryFactorBody'),status=$('#industryFactorStatus'),meta=$('#industryFactorMeta'),cards=$('#industryFactorCards'),compareStatus=$('#valuationCompareStatus'),compareMeta=$('#valuationCompareMeta');
    if(card)card.classList.remove('industry-factor-loading');if(body)body.setAttribute('aria-busy','false');
    if(status){status.className='pill';status.textContent='暂不可用'}if(meta)meta.textContent='五维行业对比暂不可用：'+error.message;
    if(cards)cards.innerHTML='<div class="industry-factor-empty">没有使用模拟分数，请稍后刷新真实数据</div>';
    topMetricComparisonState.series=[];if(compareStatus){compareStatus.className='pill';compareStatus.textContent='暂不可用'}if(compareMeta)compareMeta.textContent='估值对比暂不可用：'+error.message;drawTopMetricComparison();
  }
  function loadIndustryComparison(symbol,options){
    options=options||{};
    return stockRequest(stockEndpoint(stockConfig.endpoints.industryComparison,symbol),{refresh:options.refresh===true}).then(function(data){
      if(options.loadSequence&&options.loadSequence!==stockState.loadSequence)return null;
      renderIndustryComparison(data);
      if(data.status==='warming'&&(options.retryCount||0)<30){
        var retryCount=(options.retryCount||0)+1,delay=Math.min(4000,1200+retryCount*250);
        var status=$('#industryFactorStatus');if(status)status.textContent='后台准备中 · 自动补齐';
        window.setTimeout(function(){
          if((!options.loadSequence||options.loadSequence===stockState.loadSequence)&&stockState.symbol===symbol){
            loadIndustryComparison(symbol,{loadSequence:options.loadSequence,retryCount:retryCount}).catch(function(){});
          }
        },delay);
      }
      return data;
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
    var loadSequence=++stockState.loadSequence,nextSymbol=symbol||stockState.symbol;stockState.loading=true;stockState.symbol=nextSymbol;if(klineState.symbol!==nextSymbol){klineState.visibleBars=null;klineState.panOffset=0}klineState.symbol=nextSymbol;var hero=$('#stockHero'),status=$('#stockDataStatus');if(hero)hero.classList.add('stock-loading');setIndustryLoading();if(status){status.classList.remove('stock-error');status.textContent='正在并行加载 '+stockState.symbol+' 的行情、K线与行业对比…'}
    var scoreTask=stockRequest(stockEndpoint(stockConfig.endpoints.scoreCard,stockState.symbol),{refresh:options.refresh===true}).then(function(data){
      if(loadSequence!==stockState.loadSequence)return null;
      renderStockCard(data);syncStockWatchButton(stockState.symbol);if($('#page-score').classList.contains('active'))updateStockURL();window.QSReloadStockIntelligence({symbol:stockState.symbol});return data;
    });
    var klineTask=loadKline(klineState.period||'1d',{force:options.refresh===true});
    var industryTask=loadIndustryComparison(stockState.symbol,{refresh:options.refresh===true,loadSequence:loadSequence});
    return Promise.allSettled([scoreTask,klineTask,industryTask]).then(function(results){
      if(results[0].status==='rejected')throw results[0].reason;
      return results;
    }).catch(function(error){
      if(loadSequence!==stockState.loadSequence)return null;
      if(status){status.classList.add('stock-error');status.textContent='个股数据暂不可用：'+error.message}throw error;
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
    if(!item)return;var input=$('#searchInput');input.value=(item.name||'')+' '+item.symbol;hideStockSearch();stockPageRequested=true;stockState.symbol=item.symbol;showPage('score');loadStock(item.symbol,{force:true}).catch(function(){});
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
  $('#stockWatchButton').addEventListener('click',saveCurrentStockToWatchlist);
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
  var klineState={symbol:klineConfig.symbol,period:'1d',data:[],loading:false,meta:{},requestSequence:0,visibleBars:null,panOffset:0,crosshair:null,statusText:''};
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
  function defaultVisibleBars(){return Math.min(58,klineState.data.length||58)}
  function visibleKlineRows(){
    var count=klineState.visibleBars===null?defaultVisibleBars():Math.max(12,Math.min(klineState.visibleBars,klineState.data.length));
    var end=Math.max(0,klineState.data.length-(klineState.panOffset||0)),start=Math.max(0,end-count);
    return klineState.data.slice(start,end);
  }
  function renderKlineStatus(){
    var node=$('#klineStatus');if(!node)return;
    var count=klineState.data.length?visibleKlineRows().length:0;
    node.textContent=klineState.statusText+(count?' · 显示 '+count+' 根':'')+((klineState.panOffset||0)>0?' · 历史视图（双击复位）':'');
  }
  function zoomKline(direction){
    if(!klineState.data.length)return;
    var current=visibleKlineRows().length,next=direction==='reset'?defaultVisibleBars():Math.round(current*(direction==='in'?.72:1.38));
    klineState.visibleBars=Math.max(12,Math.min(klineState.data.length,next));
    klineState.panOffset=direction==='reset'?0:Math.max(0,Math.min(klineState.panOffset||0,klineState.data.length-klineState.visibleBars));
    renderKlineStatus();priceChart();volumeChart();
  }
  function priceChart(){
    var cv=$('#priceChart');if(!cv||!cv.offsetParent||!klineState.data.length)return;var s=setup(cv),c=s.c,w=s.w,h=s.h,p={l:48,r:12,t:12,b:25},rows=visibleKlineRows(),allRows=klineState.data,maOffset=allRows.length-(klineState.panOffset||0)-rows.length,plotW=w-p.l-p.r,plotH=h-p.t-p.b,high=Math.max.apply(null,rows.map(function(x){return x.high})),low=Math.min.apply(null,rows.map(function(x){return x.low})),margin=(high-low)*.08||1;
    high+=margin;low-=margin;var range=high-low,mapY=function(v){return p.t+(high-v)/range*plotH},step=plotW/rows.length,bodyW=Math.max(2,Math.min(10,step*.62));
    c.font='10px Microsoft YaHei';c.textAlign='right';c.textBaseline='middle';
    for(var level=0;level<5;level++){var y=p.t+level*plotH/4,value=high-level*range/4;c.strokeStyle='#e7edf6';c.lineWidth=1;c.beginPath();c.moveTo(p.l,y);c.lineTo(w-p.r,y);c.stroke();c.fillStyle='#8290a6';c.fillText(value.toFixed(2),p.l-5,y)}
    rows.forEach(function(row,i){var x=p.l+step*(i+.5),color=row.close>=row.open?CHART_UP_RED:CHART_DOWN_GREEN,top=mapY(Math.max(row.open,row.close)),bottom=mapY(Math.min(row.open,row.close));c.strokeStyle=color;c.fillStyle=color;c.beginPath();c.moveTo(x,mapY(row.high));c.lineTo(x,mapY(row.low));c.stroke();c.fillRect(x-bodyW/2,top,bodyW,Math.max(2,bottom-top))});
    [[5,CHART_UP_RED],[10,CHART_PRIMARY_BLUE],[20,'#795add']].forEach(function(def){var values=movingAverage(allRows,def[0]).slice(maOffset),started=false;c.beginPath();values.forEach(function(v,i){if(v===null)return;var x=p.l+step*(i+.5),y=mapY(v);if(started)c.lineTo(x,y);else{c.moveTo(x,y);started=true}});c.strokeStyle=def[1];c.lineWidth=1.4;c.stroke()});
    c.textAlign='center';c.textBaseline='top';c.fillStyle='#8290a6';var ticks=Math.min(5,rows.length);for(var t=0;t<ticks;t++){var idx=Math.round(t*(rows.length-1)/(ticks-1||1)),x=p.l+step*(idx+.5);c.fillText(formatKlineTime(rows[idx].time,klineState.period),x,h-p.b+7)}
  }
  function volumeChart(){
    var cv=$('#volumeChart');if(!cv||!cv.offsetParent||!klineState.data.length)return;var s=setup(cv),c=s.c,w=s.w,h=s.h,p={l:48,r:12,t:7,b:5},rows=visibleKlineRows(),plotW=w-p.l-p.r,step=plotW/rows.length,max=Math.max.apply(null,rows.map(function(x){return x.volume}))||1,bodyW=Math.max(2,Math.min(10,step*.62));
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
    var requestSequence=++klineState.requestSequence,periodChanged=klineState.period!==period;klineState.period=period;klineState.loading=true;if(periodChanged){klineState.visibleBars=null;klineState.panOffset=0}
    $$('.chart-tabs [data-period]').forEach(function(button){var active=button.getAttribute('data-period')===period;button.classList.toggle('active',active);button.setAttribute('aria-selected',String(active))});
    var cacheKey=klineState.symbol+'|'+period+'|'+klineConfig.adjust;
    if(!options.force){
      var cached=klineCache.get(cacheKey);
      if(cached&&(Date.now()-cached.at)<60000){
        klineState.data=cached.rows;klineState.meta=cached.meta||{};klineState.loading=false;updateMALabels(cached.rows);
        var cachedMeta=cached.meta||{};
        klineState.statusText=(periodNames[period]||period)+' · '+(cachedMeta.adjustment||'真实行情')+' · '+(cachedMeta.source||'行情数据服务')+' · 本地秒开';
        renderKlineStatus();priceChart();volumeChart();return Promise.resolve(cached.rows);
      }
    }
    klineState.statusText=(periodNames[period]||period)+' · 正在加载…';renderKlineStatus();
    return Promise.resolve(window.QSMarketAPI.fetchKline({symbol:klineState.symbol,period:period,limit:period==='1Y'?12:period==='1M'?48:period==='1m'?120:80,adjust:klineConfig.adjust,refresh:options.force===true})).then(function(rows){
      if(requestSequence!==klineState.requestSequence)return [];
      rows=normalizeKlines(rows);if(!rows.length)throw new Error('暂无K线数据');klineState.data=rows;klineState.loading=false;updateMALabels(rows);var meta=klineState.meta||{};klineCache.set(cacheKey,{at:Date.now(),rows:rows,meta:meta});klineState.statusText=(periodNames[period]||period)+' · '+(meta.adjustment||'真实行情')+' · '+(meta.source||'行情数据服务');renderKlineStatus();priceChart();volumeChart();return rows;
    }).catch(function(error){
      if(requestSequence!==klineState.requestSequence)return [];
      klineState.data=[];klineState.loading=false;clearKlineCharts();klineState.statusText=(periodNames[period]||period)+' · 真实行情暂不可用';renderKlineStatus();console.warn(error);throw error;
    });
  }
  window.QSReloadKline=function(options){
    options=options||{};if(options.symbol)klineState.symbol=options.symbol;
    return loadKline(options.period||klineState.period);
  };
  function toggleKlineExpand(force){
    var card=$('#klineCard'),backdrop=$('#klineBackdrop'),button=$('#klineExpand');if(!card||!backdrop||!button)return;
    var expanded=typeof force==='boolean'?force:!card.classList.contains('expanded');card.classList.toggle('expanded',expanded);backdrop.classList.toggle('show',expanded);backdrop.setAttribute('aria-hidden',String(!expanded));document.body.classList.toggle('kline-open',expanded);button.setAttribute('aria-expanded',String(expanded));button.setAttribute('aria-label',expanded?'还原K线图':'放大K线图');button.title=expanded?'还原K线图':'放大K线图';button.innerHTML=(expanded?'×':'⛶')+'<span class="kline-expand-label">'+(expanded?'还原':'放大')+'</span>';setTimeout(function(){renderKlineStatus();priceChart();volumeChart()},40);
  }
  $$('.chart-tabs [data-period]').forEach(function(button){button.addEventListener('click',function(){loadKline(button.getAttribute('data-period'))})});
  $$('[data-kline-zoom]').forEach(function(button){button.addEventListener('click',function(){zoomKline(button.getAttribute('data-kline-zoom'))})});
  $('#priceChart').addEventListener('wheel',function(event){if(!klineState.data.length)return;event.preventDefault();zoomKline(event.deltaY<0?'in':'out')},{passive:false});
  $('#priceChart').addEventListener('dblclick',function(){zoomKline('reset')});
  var klineDrag=null,klineDragRaf=0;
  function klineStepPx(){var rows=visibleKlineRows();if(!rows.length)return 8;var cv=$('#priceChart'),w=cv?cv.clientWidth:600;return Math.max(2,(w-60)/rows.length)}
  $('#priceChart').addEventListener('mousedown',function(event){
    if(!klineState.data.length)return;event.preventDefault();
    klineDrag={x:event.clientX,pan:klineState.panOffset||0,moved:false};
  });
  window.addEventListener('mousemove',function(event){
    if(!klineDrag)return;
    var dx=event.clientX-klineDrag.x;if(Math.abs(dx)<3&&!klineDrag.moved)return;
    klineDrag.moved=true;klineState.crosshair=null;
    if(klineDragRaf)return;
    klineDragRaf=requestAnimationFrame(function(){
      klineDragRaf=0;if(!klineDrag)return;
      var maxOffset=Math.max(0,klineState.data.length-visibleKlineRows().length);
      klineState.panOffset=Math.max(0,Math.min(maxOffset,klineDrag.pan+Math.round((event.clientX-klineDrag.x)/klineStepPx())));
      renderKlineStatus();priceChart();volumeChart();
    });
  });
  window.addEventListener('mouseup',function(){if(klineDrag&&klineDrag.moved)priceChart();klineDrag=null});
  function chartCtx(cv){var r=window.devicePixelRatio||1,c=cv.getContext('2d');c.setTransform(r,0,0,r,0,0);return {c:c,w:cv.clientWidth,h:cv.clientHeight}}
  function redrawKlineWithCrosshair(){priceChart();volumeChart();drawKlineCrosshair()}
  function drawKlineCrosshair(){
    var st=klineState.crosshair;if(!st||!klineState.data.length)return;
    var rows=visibleKlineRows();if(!rows.length)return;
    var i=Math.max(0,Math.min(rows.length-1,st.index)),row=rows[i];
    var pcv=$('#priceChart');if(!pcv||!pcv.offsetParent)return;
    var s=chartCtx(pcv),c=s.c,w=s.w,h=s.h,p={l:48,r:12,t:12,b:25},plotW=w-p.l-p.r,plotH=h-p.t-p.b,step=plotW/rows.length,x=p.l+step*(i+.5);
    var high=Math.max.apply(null,rows.map(function(r2){return r2.high})),low=Math.min.apply(null,rows.map(function(r2){return r2.low})),margin=(high-low)*.08||1;high+=margin;low-=margin;var range=high-low;
    c.setLineDash([4,3]);c.strokeStyle='#8b99ad';c.lineWidth=1;
    c.beginPath();c.moveTo(x,p.t);c.lineTo(x,h-p.b);c.stroke();
    var my=Math.max(p.t,Math.min(h-p.b,st.y||p.t)),priceAtY=high-(my-p.t)/plotH*range;
    c.beginPath();c.moveTo(p.l,my);c.lineTo(w-p.r,my);c.stroke();c.setLineDash([]);
    c.font='10px Microsoft YaHei';c.textAlign='right';c.textBaseline='middle';
    var priceText=priceAtY.toFixed(2),ptw=c.measureText(priceText).width;
    c.fillStyle='#526680';c.fillRect(w-p.r-ptw-8,my-8,ptw+8,16);c.fillStyle='#fff';c.fillText(priceText,w-p.r-4,my);
    var allRows=klineState.data,startIdx=allRows.length-(klineState.panOffset||0)-rows.length,prev=allRows[startIdx+i-1],prevClose=prev?prev.close:row.open,chg=prevClose?(row.close-prevClose)/prevClose*100:0,up=chg>=0;
    var lines=[String(row.time).slice(0,10),'开 '+row.open.toFixed(2)+'　高 '+row.high.toFixed(2),'低 '+row.low.toFixed(2)+'　收 '+row.close.toFixed(2),'涨跌 '+(up?'+':'')+chg.toFixed(2)+'%','量 '+numberText(row.volume/1000000,2)+' 万手'];
    var bw=Math.max.apply(null,lines.map(function(t){return c.measureText(t).width}))+16,bx=p.l+8,by=p.t+8,bh=lines.length*15+10;
    c.fillStyle='rgba(255,255,255,.94)';c.fillRect(bx,by,bw,bh);c.strokeStyle='#d5e0ef';c.strokeRect(bx+.5,by+.5,bw,bh);
    c.textAlign='left';lines.forEach(function(t,li){c.fillStyle=li===3?(up?CHART_UP_RED:CHART_DOWN_GREEN):'#243957';c.fillText(t,bx+8,by+12+li*15)});
    var vcv=$('#volumeChart');
    if(vcv&&vcv.offsetParent){var vs=chartCtx(vcv),vc=vs.c;vc.strokeStyle='#8b99ad';vc.setLineDash([4,3]);vc.lineWidth=1;vc.beginPath();vc.moveTo(x,0);vc.lineTo(x,vs.h);vc.stroke();vc.setLineDash([])}
  }
  var klineCrossRaf=0;
  $('#priceChart').addEventListener('mousemove',function(event){
    if(klineDrag||!klineState.data.length)return;
    var rect=this.getBoundingClientRect(),x=event.clientX-rect.left,y=event.clientY-rect.top,rows=visibleKlineRows();if(!rows.length)return;
    var step=(rect.width-48-12)/rows.length,index=Math.max(0,Math.min(rows.length-1,Math.round((x-48)/step-.5)));
    klineState.crosshair={index:index,y:y};
    if(klineCrossRaf)return;
    klineCrossRaf=requestAnimationFrame(function(){klineCrossRaf=0;redrawKlineWithCrosshair()});
  });
  $('#priceChart').addEventListener('mouseleave',function(){
    if(!klineState.crosshair)return;klineState.crosshair=null;priceChart();volumeChart();
  });
  $('#klineExpand').addEventListener('click',function(){toggleKlineExpand()});
  $('#klineBackdrop').addEventListener('click',function(){toggleKlineExpand(false)});
  document.addEventListener('keydown',function(event){if(event.key==='Escape')toggleKlineExpand(false)});
  function drawAll(){
    $$('.sparkline').forEach(function(cv){line(cv,cv.getAttribute('data-points').split(','),cv.getAttribute('data-color')||CHART_PRIMARY_BLUE,cv.getAttribute('data-fill'))});
    $$('.radar').forEach(radar);drawTopMetricComparison();priceChart();volumeChart()
  }
  window.addEventListener('resize',function(){clearTimeout(window._drawTimer);window._drawTimer=setTimeout(drawAll,90)});
  if(window.ResizeObserver){
    var chartResizeObserver=new ResizeObserver(function(entries){
      if(entries.some(function(entry){return entry.target.id==='topMetricComparisonChart'}))drawTopMetricComparison();
      if(entries.some(function(entry){return entry.target.id==='klineCard'})){priceChart();volumeChart()}
    });
    var comparisonCanvas=$('#topMetricComparisonChart'),klineCardNode=$('#klineCard');if(comparisonCanvas)chartResizeObserver.observe(comparisonCanvas);if(klineCardNode)chartResizeObserver.observe(klineCardNode);
  }
  var PROFILE_PAGES={watch:true,research:true,review:true};
  var PROFILE_STATUS_LABELS={pending:'排队中',queued:'排队中',leased:'执行中',running:'执行中',retry_wait:'等待重试',completed:'已完成',succeeded:'已完成',failed:'失败',cancelled:'已取消',expired:'已过期'};
  function profileCount(value){var count=Number(value);return Number.isFinite(count)&&count>=0?Math.floor(count):0}
  function profileTime(value){if(!value)return '更新时间待确认';var date=new Date(value);if(Number.isNaN(date.getTime()))return escapeHTML(String(value));return date.toLocaleString('zh-CN',{hour12:false,month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})}
  function profilePageFromHref(href){var page=String(href||'').replace(/^#/,'');return PROFILE_PAGES[page]?page:''}
  function bindProfilePageActions(root){if(!root)return;root.querySelectorAll('[data-profile-page]').forEach(function(button){button.addEventListener('click',function(){var page=button.getAttribute('data-profile-page');if(PROFILE_PAGES[page])showPage(page)})})}
  function profileEmpty(title,description,page,actionLabel){var action=PROFILE_PAGES[page]?'<button class="btn profile-empty-action" type="button" data-profile-page="'+page+'">'+escapeHTML(actionLabel)+'</button>':'';return '<div class="profile-empty"><span class="profile-empty-icon" aria-hidden="true">○</span><strong>'+escapeHTML(title)+'</strong><p>'+escapeHTML(description)+'</p>'+action+'</div>'}
  function renderProfileSummary(summary){
    var target=$('#profileSummaryCards');if(!target)return;summary=summary||{};
    var cards=[{icon:'✓',label:'待处理',count:profileCount(summary.pending_count),meta:'需要你关注的研究任务',tone:'attention'},{icon:'☆',label:'我的关注',count:profileCount(summary.watchlist_count),meta:'已记录关注理由的证券',tone:'watch'},{icon:'▤',label:'研究资产',count:profileCount(summary.research_total),meta:'其中 '+profileCount(summary.research_running)+' 项正在执行',tone:'research'},{icon:'◫',label:'持仓与交易',count:profileCount(summary.position_count),meta:'当前持仓 · '+profileCount(summary.trade_count)+' 笔交易记录',tone:'position'}];
    target.innerHTML=cards.map(function(card){return '<article class="card profile-summary-card profile-summary-'+card.tone+'"><span class="profile-summary-icon" aria-hidden="true">'+card.icon+'</span><div><span class="profile-summary-label">'+escapeHTML(card.label)+'</span><strong>'+card.count+'</strong><p>'+escapeHTML(card.meta)+'</p></div></article>'}).join('');
  }
  function renderProfileTodos(items){
    var target=$('#profileTodoList');if(!target)return;items=Array.isArray(items)?items.slice(0,5):[];
    if(!items.length){target.innerHTML=profileEmpty('当前没有紧急待办','可以从关注池选择一只股票继续研究。','watch','查看我的关注');bindProfilePageActions(target);return}
    target.innerHTML='<div class="profile-list">'+items.map(function(item){var page=profilePageFromHref(item.href)||'research';return '<button class="profile-list-item profile-todo-item" type="button" data-profile-page="'+page+'"><span class="profile-status-dot '+(item.kind==='research_failed'?'is-danger':'is-active')+'" aria-hidden="true"></span><span class="profile-list-copy"><strong>'+escapeHTML(item.title||'研究任务待处理')+'</strong><small>'+escapeHTML((item.name||item.symbol||'研究任务')+(item.question?' · '+item.question:''))+'</small></span><span class="profile-list-meta"><b>'+escapeHTML(item.status_label||PROFILE_STATUS_LABELS[item.status]||'待处理')+'</b><time>'+profileTime(item.updated_at)+'</time></span><span class="profile-list-arrow" aria-hidden="true">›</span></button>'}).join('')+'</div>';bindProfilePageActions(target);
  }
  function renderProfileResearch(items){
    var target=$('#profileRecentResearch');if(!target)return;items=Array.isArray(items)?items.slice(0,5):[];
    if(!items.length){target.innerHTML=profileEmpty('还没有研究记录','从一个明确问题开始，系统会保留研究过程和状态。','research','开始第一次研究');bindProfilePageActions(target);return}
    target.innerHTML='<div class="profile-list">'+items.map(function(item){var status=String(item.status||'pending'),label=PROFILE_STATUS_LABELS[status]||'状态待确认',page=profilePageFromHref(item.href)||'research';return '<button class="profile-list-item" type="button" data-profile-page="'+page+'"><span class="profile-research-mark" aria-hidden="true">研</span><span class="profile-list-copy"><strong>'+escapeHTML(item.name||item.symbol||'研究任务')+'</strong><small>'+escapeHTML(item.question||'研究问题待补充')+'</small></span><span class="profile-list-meta"><b class="profile-status profile-status-'+escapeHTML(status)+'">'+escapeHTML(label)+'</b><time>'+profileTime(item.updated_at)+'</time></span><span class="profile-list-arrow" aria-hidden="true">›</span></button>'}).join('')+'</div>';bindProfilePageActions(target);
  }
  function renderProfileWatchlist(items){
    var target=$('#profileRecentWatchlist');if(!target)return;items=Array.isArray(items)?items.slice(0,5):[];
    if(!items.length){target.innerHTML=profileEmpty('关注池还是空的','添加 A 股证券并记录关注理由，后续研究才有可验证的起点。','watch','添加关注');bindProfilePageActions(target);return}
    target.innerHTML='<div class="profile-list">'+items.map(function(item){var page=profilePageFromHref(item.href)||'watch';return '<button class="profile-list-item" type="button" data-profile-page="'+page+'"><span class="profile-watch-mark" aria-hidden="true">自</span><span class="profile-list-copy"><strong>'+escapeHTML((item.name||'未命名证券')+' · '+(item.symbol||'代码待确认'))+'</strong><small>'+escapeHTML(item.reason||'尚未记录关注理由')+'</small></span><span class="profile-list-meta"><b>'+escapeHTML(watchStatusLabels[item.status]||'关注中')+'</b><time>'+profileTime(item.updated_at)+'</time></span><span class="profile-list-arrow" aria-hidden="true">›</span></button>'}).join('')+'</div>';bindProfilePageActions(target);
  }
  function renderProfileLifecycle(items){
    var target=$('#profileLifecycle');if(!target)return;items=Array.isArray(items)?items:[];var fallback=[{key:'watch',label:'关注',count:0,href:'#watch'},{key:'research',label:'研究',count:0,href:'#research'},{key:'position',label:'持仓',count:0,href:'#review'},{key:'review',label:'复盘',count:0,href:'#review'}];if(!items.length)items=fallback;
    target.innerHTML='<ol class="profile-lifecycle">'+items.slice(0,4).map(function(item,index){var page=profilePageFromHref(item.href);return '<li><button type="button" data-profile-page="'+(page||'watch')+'"><span class="profile-lifecycle-index">'+(index+1)+'</span><span><b>'+escapeHTML(item.label||'待完成')+'</b><small>'+profileCount(item.count)+' 项记录</small></span><span aria-hidden="true">›</span></button></li>'}).join('')+'</ol>';bindProfilePageActions(target);
  }
  function renderProfileWorkbench(data){
    var workbench=data&&data.workbench;if(!workbench||typeof workbench!=='object')throw new Error('工作台数据结构不完整');
    renderProfileSummary(workbench.summary);renderProfileTodos(workbench.todos);renderProfileResearch(workbench.recent_research);renderProfileWatchlist(workbench.recent_watchlist);renderProfileLifecycle(workbench.lifecycle);
    var time=$('#profileDataTime');if(time)time.textContent='数据更新 '+profileTime(workbench.generated_at);
  }
  function renderProfileLoading(){var summary=$('#profileSummaryCards');if(summary)summary.innerHTML='<article class="card profile-summary-card is-loading"></article>'.repeat(4);[['#profileTodoList','正在整理待办事项'],['#profileRecentResearch','正在读取研究记录'],['#profileRecentWatchlist','正在读取关注记录'],['#profileLifecycle','正在统计研究资产']].forEach(function(item){var target=$(item[0]);if(target)target.innerHTML='<p class="profile-loading-text">'+item[1]+'</p>'});var time=$('#profileDataTime');if(time)time.textContent='正在更新'}
  function renderProfileError(error){var message=error&&error.message?error.message:'请稍后重试';var summary=$('#profileSummaryCards');if(summary)summary.innerHTML='<article class="card profile-error-card"><span aria-hidden="true">!</span><div><strong>研究工作台暂时无法读取</strong><p>'+escapeHTML(message)+'</p><button class="btn" id="profileRetry" type="button">重新加载</button></div></article>';['#profileTodoList','#profileRecentResearch','#profileRecentWatchlist','#profileLifecycle'].forEach(function(selector){var target=$(selector);if(target)target.innerHTML='<p class="profile-unavailable">数据暂不可用</p>'});var time=$('#profileDataTime');if(time)time.textContent='更新失败';var retry=$('#profileRetry');if(retry)retry.addEventListener('click',function(){loadProfileSummary().catch(function(){})})}
  function loadProfileSummary(){renderProfileLoading();return ensureWatchlistSession().then(function(){return watchRequest('/api/v1/me/profile-summary')}).then(function(data){renderProfileWorkbench(data);return data}).catch(function(error){renderProfileError(error);throw error})}
  var marketReviewLoading=null;
  function marketReviewTime(value){
    if(!value)return '时间待确认';var date=new Date(value);if(Number.isNaN(date.getTime()))return escapeHTML(String(value));
    return date.toLocaleString('zh-CN',{hour12:false,month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});
  }
  function renderMarketReviewConclusions(targetId,items,emptyText){
    var target=$(targetId);if(!target)return;items=Array.isArray(items)?items:[];
    if(!items.length){target.innerHTML='<p class="muted">'+escapeHTML(emptyText)+'</p>';return}
    target.innerHTML=items.map(function(item){
      var url=trustedStockLink(item.url),sectors=Array.isArray(item.affected_sectors)?item.affected_sectors:[];
      var title=url==='#'?'<span>'+escapeHTML(item.text||'未命名事件')+'</span>':'<a href="'+escapeHTML(url)+'" target="_blank" rel="noopener noreferrer">'+escapeHTML(item.text||'未命名事件')+'</a>';
      return '<article class="evidence-review-item">'+title+'<div class="evidence-review-meta"><span>'+escapeHTML(item.source||'来源待确认')+'</span><span>'+marketReviewTime(item.published_at)+'</span>'+sectors.map(function(sector){return '<span class="evidence-review-sector">'+escapeHTML(sector)+'</span>'}).join('')+'</div></article>';
    }).join('');
  }
  function renderMarketReview(data){
    var metrics=data.metrics||{},conclusions=data.conclusions||{},start=String(data.period_start||''),end=String(data.period_end||'');
    $('#marketReviewTitle').textContent='本周市场复盘（'+start.slice(5).replace('-','.')+' - '+end.slice(5).replace('-','.')+'）';
    $('#marketReviewStatus').textContent=(data.status==='formal'?'周五收盘正式周报':'盘中候选事件')+' · '+marketReviewTime(data.generated_at)+' · '+(data.generation_mode==='llm_evidence_clustering'?'模型仅执行证据聚类':'确定性证据摘录');
    var sourceStatus=data.source_status||{};
    $('#marketReviewSources').innerHTML=Object.keys(sourceStatus).map(function(name){var state=sourceStatus[name]||{},available=!!state.available;return '<span class="source-state '+(available?'available':'unavailable')+'" title="'+escapeHTML(available?'已获取 '+(state.items||0)+' 条':'当前不可用，不参与结论')+'">'+escapeHTML(name)+' · '+(available?(state.items||0)+'条':'未接通')+'</span>'}).join('');
    var indices=Array.isArray(metrics.indices)?metrics.indices:[];
    $('#marketReviewIndices').innerHTML=indices.length?indices.map(function(item,index){var change=item.changePct===null||item.changePct===undefined?NaN:Number(item.changePct),cls=Number.isFinite(change)?(change>=0?'up':'down'):'',points=Array.isArray(item.trend)?item.trend:[];if(points.length===1)points.push(points[0]);return '<div class="market-card"><b>'+escapeHTML(item.name||item.code||'指数')+'</b><strong class="'+cls+'">'+numberText(item.value,2)+'</strong><p class="'+cls+'">'+(Number.isFinite(change)?(change>=0?'+':'')+change.toFixed(2)+'%':'--')+'</p><canvas class="market-index-spark" id="marketReviewIndexSpark'+index+'" aria-label="'+escapeHTML(item.name||'指数')+'本周走势"></canvas><div class="market-index-meta"><span>周涨跌 '+(item.changePoints===null||item.changePoints===undefined?'--':numberText(item.changePoints,2)+'点')+'</span><span>'+escapeHTML(item.marketDate||'日期待确认')+'</span></div></div>'}).join(''):'<p class="muted">五大指数行情暂不可用</p>';
    indices.forEach(function(item,index){var canvas=$('#marketReviewIndexSpark'+index),points=Array.isArray(item.trend)?item.trend.slice():[];if(points.length===1)points.push(points[0]);if(canvas&&points.length)line(canvas,points,Number(item.changePct)>=0?CHART_UP_RED:CHART_DOWN_GREEN,false)});
    var sectors=Array.isArray(metrics.industry_rotation)?metrics.industry_rotation:[],leaders=sectors.filter(function(item){return Number(item.changePct)>0}).slice(0,5),laggards=sectors.filter(function(item){return Number(item.changePct)<0}).sort(function(a,b){return Number(a.changePct)-Number(b.changePct)}).slice(0,5);
    function sectorRows(items,empty){return items.length?items.map(function(item){var value=Number(item.changePct);return '<li><span>'+escapeHTML(item.name||'未知板块')+' <b class="'+(value>=0?'up':'down')+'" style="float:right">'+(value>=0?'+':'')+value.toFixed(2)+'%</b></span></li>'}).join(''):'<li class="muted"><span>'+empty+'</span></li>'}
    $('#marketReviewSectorLeaders').innerHTML=sectorRows(leaders,'暂无上涨板块证据');$('#marketReviewSectorLaggards').innerHTML=sectorRows(laggards,'暂无下跌板块证据');
    var breadth=metrics.market_overview||{};
    if(breadth.total){var riseRate=Number(breadth.risingRate)||0,flatRate=Number(breadth.flatRate)||0,fallStart=riseRate+flatRate;$('#marketReviewBreadth').innerHTML='<div class="market-structure-wrap"><div class="market-structure-donut" style="background:conic-gradient('+CHART_UP_RED+' 0 '+riseRate+'%,'+CHART_FLAT_GRAY+' '+riseRate+'% '+fallStart+'%,'+CHART_DOWN_GREEN+' '+fallStart+'% 100%)"></div><div class="market-structure-legend"><p><span class="up">● 上涨</span><b>'+numberText(breadth.rising,0)+'家 '+numberText(breadth.risingRate,2)+'%</b></p><p><span class="muted">● 平盘</span><b>'+numberText(breadth.flat,0)+'家 '+numberText(breadth.flatRate,2)+'%</b></p><p><span class="down">● 下跌</span><b>'+numberText(breadth.falling,0)+'家 '+numberText(breadth.fallingRate,2)+'%</b></p></div></div><p class="tiny">'+escapeHTML(breadth.marketDate||'日期待确认')+' · '+escapeHTML(breadth.source||'市场广度来源待确认')+'</p>'}else{$('#marketReviewBreadth').innerHTML='<p class="muted">全市场涨跌数据暂不可用</p>'}
    var funds=metrics.funds||{},styles=Array.isArray(metrics.styles)?metrics.styles:[];
    function fundRow(item){item=item||{};var hasValue=item.value!==null&&item.value!==undefined&&Number.isFinite(Number(item.value)),value=hasValue?Number(item.value):NaN,cls=hasValue?(value>=0?'up':'down'):'muted';return '<div class="market-fund-row" title="'+escapeHTML(item.source||item.reason||'来源待确认')+'"><span>'+escapeHTML(item.label||'资金项')+'</span><b class="'+cls+'">'+(hasValue?(value>=0?'+':'')+value.toFixed(2)+' '+escapeHTML(item.unit||''):'暂不可用')+'</b></div>'}
    function styleRow(item){var value=item&&item.changePct!==null&&item.changePct!==undefined?Number(item.changePct):NaN,cls=Number.isFinite(value)?(value>=0?'up':'down'):'muted';return '<div class="market-style-row"><span>'+escapeHTML(item.name||'风格指数')+'</span><b class="'+cls+'">'+(Number.isFinite(value)?(value>=0?'+':'')+value.toFixed(2)+'%':'暂不可用')+'</b></div>'}
    $('#marketReviewFunds').innerHTML='<div class="market-fund-list">'+fundRow(funds.main)+fundRow(funds.north)+fundRow(funds.financing)+fundRow(funds.etf)+'</div><b class="market-style-title">本周风格指数</b>'+styles.map(styleRow).join('')+'<p class="tiny">资金与风格均为 Tushare 可核验数据；缺失项不使用估算值。</p>';
    var scores=metrics.review_scores||{},radarNode=$('#marketReviewRadar'),radarValues=Array.isArray(scores.values)?scores.values:[0,0,0,0,0],radarLabels=Array.isArray(scores.labels)?scores.labels:['赚钱效应','资金面','情绪面','风险水平','趋势强度'];if(radarNode){radarNode.setAttribute('data-values',radarValues.join(','));radarNode.setAttribute('data-labels',radarLabels.join(','));radar(radarNode)}$('#marketReviewRadarMethod').textContent=scores.method||'当前尚无足够的 Tushare 行情计算复盘概述。';
    renderMarketReviewConclusions('#marketReviewCoreEvents',conclusions.core_events,'本周尚未取得可核验的核心事件');
    renderMarketReviewConclusions('#marketReviewHighlights',conclusions.highlights,'当前没有足够证据形成市场亮点');
    renderMarketReviewConclusions('#marketReviewRisks',conclusions.risks,'当前没有足够证据形成风险结论');
    renderMarketReviewConclusions('#marketReviewDirections',conclusions.watch_directions,'未来14天暂无已接入的官方日程');
  }
  function loadMarketReview(force){
    if(marketReviewLoading&&!force)return marketReviewLoading;
    var status=$('#marketReviewStatus'),button=$('#refreshMarketReview');if(status)status.textContent=force?'正在刷新官方信息、公告和行情…':'正在读取有来源的市场复盘…';if(button)button.disabled=true;
    marketReviewLoading=fetch('/api/v1/reviews/market'+(force?'?refresh=true':''),{credentials:'same-origin'}).then(function(response){return response.json().catch(function(){return {}}).then(function(body){if(!response.ok)throw new Error(body.detail||('请求失败：'+response.status));return body})}).then(function(data){renderMarketReview(data);return data}).catch(function(error){if(status)status.textContent='市场复盘暂不可用：'+error.message;throw error}).finally(function(){marketReviewLoading=null;if(button)button.disabled=false});
    return marketReviewLoading;
  }
  var refreshMarketReviewButton=$('#refreshMarketReview');if(refreshMarketReviewButton)refreshMarketReviewButton.addEventListener('click',function(){loadMarketReview(true).then(function(){toast('市场复盘候选事件已刷新')}).catch(function(error){toast(error.message)})});
  drawAll();
  var refreshTodayButton=$('#refreshTodayData');if(refreshTodayButton)refreshTodayButton.addEventListener('click',function(){window.QSReloadTodayDashboard()});
  window.setInterval(function(){if(document.visibilityState==='visible'&&$('#page-today').classList.contains('active'))todayLoaders.indices().catch(function(){})},30000);
  window.setInterval(function(){if(document.visibilityState==='visible'&&$('#page-today').classList.contains('active'))window.QSReloadTodayDashboard()},120000);
  window.setInterval(function(){if(document.visibilityState==='visible'&&$('#review-market').classList.contains('active'))loadMarketReview(false).catch(function(){})},300000);
  var initialStockSymbol='300750.SZ';try{initialStockSymbol=new URL(location.href).searchParams.get('symbol')||initialStockSymbol}catch(error){}
  stockState.symbol=initialStockSymbol;klineState.symbol=initialStockSymbol;
  var initialPage=location.hash.replace('#','');if(['today','score','research','watch','review','profile'].indexOf(initialPage)===-1)initialPage='today';
  showPage(initialPage);
})();
