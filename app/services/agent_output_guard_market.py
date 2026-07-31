from __future__ import annotations

import re
from typing import Any

from app.services.agent_output_guard_common import _NUMBER_RE, _number_value

_UNSUPPORTED_PEER_OPERATING_INFERENCE_PATTERNS = (
    (
        "固定同行经营比较不得输出公司排名或优劣评级",
        re.compile(
            r"(?:样本中|同行中|四家公司|三家同行|中兴(?:通讯)?|烽火通信|紫光股份|锐捷网络)"
            r"[^。；\n]{0,80}(?:最高|最低|居中|排名|优于|劣于|更好|更差|最好|最差|最大|最小)"
            r"|(?:最高|最低|居中|排名|优于|劣于|更好|更差|最好|最差|最大|最小)"
            r"[^。；\n]{0,80}(?:样本中|同行中|中兴(?:通讯)?|烽火通信|紫光股份|锐捷网络)"
        ),
    ),
    (
        "同行业务结构差异不能自动改写为经营指标差异的原因",
        re.compile(
            r"(?:营收增速|利润增速|毛利率|净利率|经营现金流|数值差异|指标差异)"
            r"[^。；\n]{0,60}(?:主要反映|主要来自|主要受|天然|拖低|推高)"
            r"[^。；\n]{0,50}(?:业务结构|主营构成|分销|核心盈利业务)"
            r"|(?:业务结构|主营构成|分销|核心盈利业务)"
            r"[^。；\n]{0,50}(?:拖累|压低|推高|导致|造成|影响)"
            r"[^。；\n]{0,40}(?:毛利率|净利率|利润增速|经营现金流)"
            r"|(?:包含|含有|含)[^。；\n]{0,30}(?:分销|低毛利业务)"
            r"[^。；\n]{0,50}(?:综合)?毛利率(?:较低|偏低)"
            r"|(?:综合)?毛利率[^。；\n]{0,50}(?:与|由于|因为|受)[^。；\n]{0,50}"
            r"(?:分销|业务结构|主营构成)"
        ),
    ),
    (
        "净利润同比方向不能解释经营现金流比值",
        re.compile(
            r"(?:净利润同比|净利润增速|负利润增速|利润负增长)"
            r"[^。；\n]{0,80}(?:放大|缩小|导致|使得|造成)"
            r"[^。；\n]{0,40}(?:现金流/净利润|经营现金流比值|比值负数)"
        ),
    ),
    (
        "主营构成不得自行加总或混入非分部字段",
        re.compile(
            r"(?:主营构成|业务构成|收入构成|分部构成)[^。；\n]{0,80}"
            r"(?:应收账款|销售方|三表中未披露)"
            r"|(?:应收账款|销售方|三表中未披露)[^。；\n]{0,80}"
            r"(?:主营构成|业务构成|收入构成|分部构成)"
            r"|(?:主营构成|业务构成|占比|合计)[^。；\n]{0,80}"
            r"(?:超过|高于|低于)\s*100"
        ),
    ),
    (
        "主营构成毛利率必须使用年报或中报口径",
        re.compile(r"分部毛利率[^。；\n]{0,30}三表(?:中)?未披露"),
    ),
    (
        "同行公告日期不能用单一日期概括",
        re.compile(r"财务数据均为[^。；\n]{0,80}[（(]\d{4}-\d{2}-\d{2}公告[）)]"),
    ),
    (
        "主营构成报告期必须与证据逐家公司一致",
        re.compile(
            r"(?:主营构成|业务构成)[^。；\n]{0,90}"
            r"(?:报告期不同|不是(?:同一|统一)报告期|来自不同(?:年报|中报|年报/中报))"
        ),
    ),
)


def _is_index_contribution_clause(text: str) -> bool:
    return "贡献" in text and any(
        term in text for term in ("指数", "权重", "百分点", "pp", "成分", "贡献排名")
    )


_STREAM_DEFERRED_COMPLETENESS_INFERENCES = frozenset(
    {
        "用户询问全市场广度时回答必须给出涨跌家数和固定分类",
        "用户明确询问何时需要重新判断时回答必须说明对应情况",
        "用户明确询问不能确认的部分时回答必须保留证据边界",
    }
)
_STREAM_DEFERRED_COMPLETENESS_CONFLICTS = frozenset(
    {
        "用户明确询问成交额时必须引用可用的全市场成交额",
        "全市场成交额时间必须引用市场快照日期",
        "用户明确询问涨跌幅分布时必须引用可用的分布统计",
        "用户明确询问成分贡献时必须给出标的估算贡献和口径边界",
        "用户明确询问行业成分涨跌家数时必须给出上涨下跌平盘家数",
    }
)
_NEGATIVE_SENTIMENT_LANGUAGE_RE = re.compile(
    r"(?:社区|股吧|零售)[^。；\n]{0,24}(?:转负|偏空|看空|负面|悲观)"
)
_POSITIVE_SENTIMENT_LANGUAGE_RE = re.compile(
    r"(?:社区|股吧|零售)[^。；\n]{0,24}(?:转正|偏多|看多|正面|乐观)"
)
_UNSUPPORTED_MARKET_INFERENCE_PATTERNS = (
    (
        "市场资讯标题不能证明已经被价格消化或产生市场反应",
        re.compile(
            r"(?:资讯|消息|报道|观点|唱多|配置价值|持股市值|事件)"
            r"[^。；\n]{0,120}(?:已在市场上产生反应|已产生市场反应|"
            r"已被市场消化|已经被市场消化|已部分被市场消化|"
            r"已经计价|已计价|市场已经反应|市场已反应)"
        ),
    ),
    (
        "有限资讯覆盖不能证明当前不存在新的宏观政策或外部事件",
        re.compile(
            r"(?:当前|目前)[^。；\n]{0,24}(?:没有|不存在|尚无)"
            r"[^。；\n]{0,60}(?:新的?)?(?:宏观数据|政策公告|外部事件|催化剂)"
        ),
    ),
    (
        "后续行情不能简化为是否出现新增催化剂",
        re.compile(
            r"(?:今天|今日|后续|接下来)[^。；\n]{0,40}(?:能否)?(?:延续|上涨|下跌|走强|走弱)"
            r"[^。；\n]{0,36}(?:取决于|关键在于)[^。；\n]{0,36}(?:新增|新的?)催化剂"
        ),
    ),
    (
        "不能仅用上证与深证的差异替代大小盘风格指数",
        re.compile(
            r"(?:上证|沪指|深证|深成)[^。；\n]{0,100}"
            r"(?:上证|沪指|深证|深成)[^。；\n]{0,100}"
            r"(?:大盘股|中小盘|中小市值|小市值|中盘成长股|大盘权重股|"
            r"成长类板块|成长风格|价值风格|弹性更大的品种|高弹性品种)"
        ),
    ),
    (
        "成交量或量比不能直接证明增量资金入场或资金流向",
        re.compile(
            r"(?:成交量|成交额|量比|放量)[^。；\n]{0,80}"
            r"(?:增量资金|资金入场|资金流入|资金集中|资金净流入|机构买入)"
        ),
    ),
    (
        "成交量或量比不能直接证明上涨参与面或市场覆盖范围",
        re.compile(
            r"(?:(?:成交量|成交额|量能|量比|放量|缩量)[^。；\n]{0,100}"
            r"(?:说明|表明|意味着|显示|证明|印证|反映)[^。；\n]{0,80}"
            r"(?:上涨|反弹|行情)?[^。；\n]{0,30}"
            r"(?:参与面|覆盖面|上涨范围|参与范围)[^。；\n]{0,20}"
            r"(?:较窄|有限|不广|不足|不宽)|"
            r"(?:参与面|覆盖面|上涨范围|参与范围)[^。；\n]{0,40}"
            r"(?:较窄|有限|不广|不足|不宽)[^。；\n]{0,100}"
            r"(?:因为|由于|缘于|源于)[^。；\n]{0,50}"
            r"(?:成交量|成交额|量能|量比|放量|缩量))"
        ),
    ),
    (
        "成交额按每笔成交金额计一次，不能解释为买卖双方双重计数",
        re.compile(
            r"(?:成交额|成交金额)[^。；\n]{0,180}"
            r"(?:(?:同一笔|每一笔)交易[^。；\n]{0,80}"
            r"(?:买卖双方|双方|两边)[^。；\n]{0,40}(?:同时)?计入|"
            r"(?:买卖双方|双方|两边)[^。；\n]{0,80}(?:重复计入|双重计数|翻倍)|"
            r"翻倍)"
        ),
    ),
    (
        "全市场涨跌家数不能直接证明少数权重或集中板块拉动",
        re.compile(
            r"(?:全市场|上涨家数|上涨比例|涨跌家数)[^。；\n]{0,180}"
            r"(?:说明|表明|因此|意味着)[^。；\n]{0,80}"
            r"(?:少数权重|权重股|集中板块)[^。；\n]{0,30}(?:带动|拉动)"
        ),
    ),
    (
        "缺少个股涨幅分布时不能声称多数股票涨幅温和",
        re.compile(
            r"多数(?:股票|个股)[^。；\n]{0,40}"
            r"(?:涨幅温和|小幅上涨|仅小幅上涨)"
        ),
    ),
    (
        "热门板块排序不能证明板块集中度较高",
        re.compile(
            r"(?:领涨板块|热门板块|板块排名)[^。；\n]{0,180}"
            r"(?:集中度较高|集中度高|高度集中|板块集中)"
        ),
    ),
    (
        "盘中反弹或价格修复不能直接证明承接买盘",
        re.compile(
            r"(?:盘中|反弹|回升|价格修复)[^。；\n]{0,160}"
            r"(?:承接买盘|买盘承接|买盘关注|资金承接)"
        ),
    ),
    (
        "价格跌幅或回撤不能直接改写为估值压缩",
        re.compile(r"(?:跌幅|回撤|下跌)[^。；\n]{0,160}(?:估值压缩|估值消化)"),
    ),
    (
        "缺少历史校准时不能用跌幅越深支持均值回归",
        re.compile(
            r"(?:跌幅|下跌|回撤)[^。；\n]{0,120}"
            r"(?:越深|更深|扩大)[^。；\n]{0,60}(?:均值回归|回归均值)"
        ),
    ),
    (
        "代表性指数平均收益不能写成日均收盘价",
        re.compile(r"(?:日均|平均)收盘价[^。；\n]{0,30}[-+]?\d+(?:\.\d+)?%"),
    ),
    (
        "没有确定性阈值时不能把成交量写成均线确认条件",
        re.compile(
            r"(?:MA20|MA60|20\s*日均线|60\s*日均线|均线)"
            r"[^。；\n]{0,140}(?:伴随|需要)[^。；\n]{0,30}"
            r"(?:成交量确认|量能确认)"
        ),
    ),
    (
        "代表性指数涨幅不能直接证明市场或风格贡献",
        re.compile(
            r"(?:上证|深证|沪深\s*300|创业板|中证\s*500|"
            r"深市|沪市|权重股)[^。；\n]{0,120}"
            r"(?:贡献突出|贡献更大|主要贡献|贡献了)"
        ),
    ),
    (
        "均线位置不能直接外推反弹或修复空间",
        re.compile(
            r"(?:MA20|MA60|均线)[^。；\n]{0,180}"
            r"(?:反弹空间|修复空间)[^。；\n]{0,20}(?:较大|很大|打开|存在)?"
        ),
    ),
    (
        "5日与20日均量比不能改写为今日成交量显著放大",
        re.compile(
            r"(?:5\s*日量比|5\s*/\s*20\s*日量比|量比)"
            r"[^。；\n]{0,160}(?:显示|说明|表明|契合|印证|支持)"
            r"[^。；\n]{0,120}"
            r"(?:今日|当天)[^。；\n]{0,16}(?:成交)?(?:显著)?放量"
        ),
    ),
    (
        "单期最大回撤不能声称正在继续扩大",
        re.compile(
            r"(?:最大回撤|max_drawdown)[^。；\n]{0,40}"
            r"(?:继续|持续)(?:扩大|加深)"
        ),
    ),
    (
        "单期最大回撤不能声称尚未进一步扩大或已经止跌",
        re.compile(
            r"(?:最大回撤|回撤幅度)[^。；\n]{0,140}"
            r"(?:(?:尚未|未|没有)[^。；\n]{0,24}(?:进一步扩大|继续扩大|止跌)|"
            r"仍未出现止跌|已经止跌|已止跌)"
        ),
    ),
    (
        "单日跌幅不能写成已经构建新的路径低位",
        re.compile(
            r"(?:当前跌幅|单日跌幅|当日跌幅|当前回撤)[^。；\n]{0,100}"
            r"(?:构建|形成|进入)[^。；\n]{0,30}"
            r"(?:新的?)?(?:60\s*日)?(?:路径低位|路径区间|新低)"
        ),
    ),
    (
        "缺少连续成交序列时不能声称持续放量或缩量",
        re.compile(r"(?:持续|连续)(?:放量|缩量)"),
    ),
    (
        "市场指标不能推断资金将主动降低风险敞口",
        re.compile(
            r"(?:资金|投资者|机构)[^。；\n]{0,50}"
            r"(?:将|会|可能|进一步)[^。；\n]{0,30}"
            r"(?:降低|减少|收缩)[^。；\n]{0,20}(?:风险敞口|仓位|持仓)"
        ),
    ),
    (
        "区间收益不能写成连续多个交易日每天同向变化",
        re.compile(r"连续\s*(?:5|20|60)\s*日[^。；\n]{0,20}(?:跌|涨)"),
    ),
    (
        "区间收益不能声称市场连续数周持续回落",
        re.compile(
            r"(?:(?:前)?(?:几|数|多)周[^。；\n]{0,16}"
            r"(?:持续|连续)?(?:回落|下跌|走弱|偏弱)|"
            r"(?:持续|连续)(?:数周|几周|多周)[^。；\n]{0,16}"
            r"(?:回落|下跌|走弱|偏弱))"
        ),
    ),
    (
        "区间收益不能声称此前一段行情连续下跌",
        re.compile(
            r"(?:此前|之前|先前)[^。；\n]{0,20}"
            r"(?:一段|一轮)?[^。；\n]{0,12}"
            r"(?:持续|连续)(?:回落|下跌|走弱)"
        ),
    ),
    (
        "5日和20日累计收益不能直接改写成周线或月线",
        re.compile(r"(?:5|20)\s*日[^。；\n]{0,120}(?:周线|月线)"),
    ),
    (
        "没有历史序列时不能声称这是第一次反弹或需要二次验证",
        re.compile(r"(?:第一次|首次)[^。；\n]{0,30}(?:反弹|回升|修复|大涨)|二次验证"),
    ),
    (
        "区间收益不能直接证明指数处于低价或低位区间",
        re.compile(
            r"(?:5|20|60)\s*日[^。；\n]{0,30}"
            r"(?:累计)?(?:收益|涨跌|上涨|下跌|涨幅|跌幅)"
            r"[^。；\n]{0,70}"
            r"(?:低价区间|低位区间|低位区域)"
        ),
    ),
    (
        "没有历史趋势状态时不能声称状态已经发生切换",
        re.compile(
            r"(?:趋势|状态)[^。；\n]{0,40}(?:从[^。；\n]{0,20})?"
            r"(?:切换|转变|转为|变为)[^。；\n]{0,30}(?:偏弱|下行|向下)"
        ),
    ),
    (
        "年化波动率不能直接证明多次日内大幅摆动",
        re.compile(
            r"(?:年化波动|波动率)[^。；\n]{0,100}"
            r"(?:说明|意味着|表明)[^。；\n]{0,80}"
            r"(?:多次|频繁)[^。；\n]{0,30}(?:日内摆动|日内波动)"
        ),
    ),
    (
        "最大回撤不能直接写成尚未超出既有波动区间",
        re.compile(
            r"(?:最大回撤|回撤幅度)[^。；\n]{0,100}"
            r"(?:尚未|没有|未)[^。；\n]{0,20}(?:超出|超过)"
            r"[^。；\n]{0,30}(?:波动区间|波动范围)"
        ),
    ),
    (
        "最大回撤不能直接定义为正常或合理波动范围",
        re.compile(
            r"(?:最大回撤|回撤幅度|60\s*日回撤)[^。；\n]{0,120}"
            r"(?:属于|处于|落在|仍在|尚处于)[^。；\n]{0,40}"
            r"(?:(?:正常|合理|既有|常规)[^。；\n]{0,24}"
            r"(?:波动范围|波动区间|波动)|(?:近\s*60\s*日路径的)?波动容忍度)"
        ),
    ),
    (
        "单日涨跌不能直接定义为近期正常波动范围",
        re.compile(
            r"(?:单日(?:涨跌|变化)|跌幅|涨幅)[^。；\n]{0,100}"
            r"(?:在|处于|属于)[^。；\n]{0,30}"
            r"(?:近期|正常|既有|常规)[^。；\n]{0,24}(?:波动范围|波动区间)"
        ),
    ),
    (
        "单日跌幅不能单独证明非恐慌或窄幅回调",
        re.compile(
            r"(?:跌幅|下跌)[^。；\n]{0,140}"
            r"(?:(?:不是|并非|不构成)[^。；\n]{0,30}"
            r"(?:大阴线|恐慌性下跌|恐慌性抛售)|"
            r"(?:更像|属于)[^。；\n]{0,24}(?:窄幅回调|正常回调))"
        ),
    ),
    (
        "缺少分位或阈值时不能评价年化波动率高低",
        re.compile(
            r"(?:年化波动率|年化波动|波动率)[^。；\n]{0,100}"
            r"(?:尚可|可控|温和|不高|偏低|较低)"
        ),
    ),
    (
        "单一波动率或跌幅不能证明没有恐慌扩散",
        re.compile(
            r"(?:年化波动率|波动率|跌幅)[^。；\n]{0,160}"
            r"(?:没有|未出现|不支持)[^。；\n]{0,30}"
            r"(?:恐慌扩散|恐慌性抛售)"
        ),
    ),
    (
        "缺少分位或阈值时不能把最大回撤定义为极端或不极端",
        re.compile(
            r"(?:最大回撤|最大调整幅度|回撤幅度)[^。；\n]{0,120}"
            r"(?:并不|不算|不是|未达到|尚未达到)[^。；\n]{0,24}"
            r"(?:极端|异常|严重)"
        ),
    ),
    (
        "最大回撤不能与单期ATR按天数累积比较",
        re.compile(
            r"(?:最大回撤|回撤幅度|60\s*日回撤)[^。；\n]{0,180}"
            r"(?:小于|低于|不及)[^。；\n]{0,80}"
            r"(?:ATR|平均真实波幅)[^。；\n]{0,100}"
            r"(?:累积|累计|天数|乘以|×)"
        ),
    ),
    (
        "缺少历史校准时不能声称事件驱动下跌通常伴随放量",
        re.compile(
            r"(?:地缘事件|突发事件|事件驱动)[^。；\n]{0,100}"
            r"(?:通常|往往|一般)[^。；\n]{0,40}(?:放量|成交量)"
        ),
    ),
    (
        "缺少分位或阈值时不能把波动率划分为高低区间",
        re.compile(
            r"(?:波动率|年化波动)[^。；\n]{0,150}"
            r"(?:处于|属于|仍处于)[^。；\n]{0,30}"
            r"(?:中等|偏低|偏高|低波动|高波动|正常)[^。；\n]{0,24}"
            r"(?:区间|水平|状态)?"
        ),
    ),
    (
        "三大指数表述不能同时覆盖第四个代表性指数",
        re.compile(r"三大指数[^。；\n]{0,220}(?:罗素\s*2000|四个代表性指数)"),
    ),
    (
        "证据包没有给出观察窗口时不能发明连续数日确认条件",
        re.compile(r"(?:未来|后续|接下来|连续)\s*(?:几|数|若干|多)\s*日"),
    ),
    (
        "5日累计收益不能改写为趋势已延续超过一周",
        re.compile(
            r"5\s*日[^。；\n]{0,100}(?:累计)?收益[^。；\n]{0,140}"
            r"(?:延续|持续)[^。；\n]{0,30}(?:超过|超出)?一周"
        ),
    ),
    (
        "均线压制不能直接外推为更持续的承压格局",
        re.compile(
            r"(?:MA20|20\s*日均线)[^。；\n]{0,100}"
            r"(?:持续压制|无法快速收复)[^。；\n]{0,100}"
            r"(?:累积|演变|转化|变成)[^。；\n]{0,40}(?:承压|下行|弱势)"
        ),
    ),
    (
        "单期ATR不能声称波动持续处于高位",
        re.compile(
            r"(?:ATR|平均真实波幅)[^。；\n]{0,60}"
            r"(?:持续|连续)[^。；\n]{0,20}(?:较高|高位|放大)"
        ),
    ),
    (
        "当日低点不能证明价格风险尚未释放",
        re.compile(
            r"(?:当日低点|今日低点|盘中低点)[^。；\n]{0,100}"
            r"(?:风险|压力)[^。；\n]{0,20}(?:未释放|尚未释放|没有释放)"
        ),
    ),
    (
        "证据包没有历史回溯时不能声称历史上通常如此",
        re.compile(
            r"(?:历史回溯|历史经验|历史上)[^。；\n]{0,80}"
            r"(?:往往|通常|一般|经常|常常|容易|更容易|最容易|大多)"
        ),
    ),
    (
        "缺少校准证据时不能声称后续情景的概率或高频规律",
        re.compile(
            r"(?:未来|后续|接下来|下一交易日|几个交易日|这种组合|如果|一旦)"
            r"[^。；\n]{0,120}(?:大概率|概率上升|概率提高|更可能|最容易)"
        ),
    ),
    (
        "证据包没有给出观察窗口时不能发明未来交易日数量",
        re.compile(
            r"(?:未来|后续|接下来)\s*(?:"
            r"\d+\s*(?:[-—–~～至到]\s*\d+\s*)?个|几个|数个|若干)交易日"
        ),
    ),
    (
        "证据包没有给出阈值时不能发明量能或回撤验证门槛",
        re.compile(
            r"(?:"
            r"(?:至少|维持|扩大至|跌至|升至)[^。；\n]{0,24}"
            r"[-+]?\d+(?:\.\d+)?(?:\s*[-—–~～至到]\s*"
            r"[-+]?\d+(?:\.\d+)?)?\s*(?:倍|%)"
            r"|达到[^。；\n]{0,24}[-+]?\d+(?:\.\d+)?"
            r"(?:\s*[-—–~～至到]\s*[-+]?\d+(?:\.\d+)?)?\s*(?:倍|%)"
            r"[^。；\n]{0,16}(?:才|方|后|时|则|即|视为|确认|有效)"
            r")"
        ),
    ),
    (
        "A股日线的09:30日期锚点不能写成收盘或数据截止时间",
        re.compile(r"09[:：]30[^。；\n]{0,30}(?:收盘|截止|截至)"),
    ),
    (
        "没有用户确认或规则证据时不能发明典型投资者回撤承受区间",
        re.compile(
            r"(?:很多|多数|普通|一般)人[^。；\n]{0,60}"
            r"(?:承受|容忍|风险承受)[^。；\n]{0,30}\d"
        ),
    ),
    (
        "盘中低点本身不能证明抛压或卖压尚未释放",
        re.compile(
            r"(?:最低|低点|触及)[^。；\n]{0,60}(?:说明|表明)"
            r"[^。；\n]{0,40}(?:抛压|卖压)[^。；\n]{0,20}(?:释放|消化)"
        ),
    ),
    (
        "单一媒体标题不能证明系统性风险信号",
        re.compile(
            r"(?:报道|资讯|标题)[^。；\n]{0,100}(?:说明|表明)"
            r"[^。；\n]{0,40}(?:系统性|风险警示信号)"
        ),
    ),
    (
        "最大回撤不能直接改写为当前处于低位区间",
        re.compile(
            r"(?:最大回撤|回撤幅度)[^。；\n]{0,140}"
            r"(?:处于|位于)[^。；\n]{0,30}(?:低位区间|低点附近)"
        ),
    ),
    (
        "最大回撤不能直接改写为累计损失",
        re.compile(
            r"(?:最大回撤|回撤幅度|这段回撤|上述回撤)"
            r"[^。；\n]{0,160}(?:累计损失|累计亏损)"
        ),
    ),
    (
        "区间收益或回撤不能证明后续上涨空间有限",
        re.compile(
            r"(?:区间收益|累计收益|最大回撤|回撤)[^。；\n]{0,120}"
            r"(?:说明|表明|意味着|因此|——)[^。；\n]{0,60}"
            r"(?:上涨|反弹)?空间有限"
        ),
    ),
)
_UNSUPPORTED_SHAREHOLDER_INFERENCE_PATTERNS = (
    (
        "股东户数下降不能直接写成机构或主力吸筹",
        re.compile(
            r"(?:股东户数|股东人数)[^。；\n]{0,100}(?:下降|减少)"
            r"[^。；\n]{0,100}(?<!不能)(?<!无法)(?<!不代表)"
            r"(?:说明|表明|意味着|证明|显示)[^。；\n]{0,24}"
            r"(?:机构吸筹|主力吸筹|资金吸筹|明确利好)"
        ),
    ),
    (
        "股东户数上升不能直接预测股价下跌",
        re.compile(
            r"(?:股东户数|股东人数)[^。；\n]{0,100}(?:上升|增加)"
            r"[^。；\n]{0,100}(?:必然|一定|因此|意味着)[^。；\n]{0,24}(?:下跌|走弱)"
        ),
    ),
    (
        "香港中央结算代理人有限公司不能自动等同北向资金",
        re.compile(
            r"香港中央结算代理人有限公司[^。；\n]{0,80}"
            r"(?:就是|等同|代表|说明)[^。；\n]{0,24}北向资金"
        ),
    ),
    (
        "香港中央结算有限公司不能在缺少身份口径时直接标注为北向通道",
        re.compile(
            r"香港中央结算有限公司(?:\*\*)?\s*[（(](?:对应\s*)?[^）)\n]{0,30}"
            r"(?:北向|A\s*股通道|陆股通|沪股通|深股通)[^）)\n]{0,20}[）)]"
        ),
    ),
    (
        "十大股东报告期存量不能写成实时持仓或当日资金流",
        re.compile(
            r"(?:十大股东|前十大股东)[^。；\n]{0,100}"
            r"(?<!不是)(?<!并非)(?:实时持仓|当前实时持仓|当日资金流|今日资金流)"
        ),
    ),
    (
        "十大股东名单变化不能直接归因为ETF主动或被动调仓",
        re.compile(
            r"(?:ETF|指数基金)[^。；\n]{0,320}"
            r"(?<!不能)(?<!无法)(?<!不代表)"
            r"(?:被动减仓|主动建仓|主动增配|指数再平衡|被动调仓|"
            r"显著调仓|调仓行为)"
        ),
    ),
    (
        "股东名单本身不能补写控股国资国家队等身份标签",
        re.compile(
            r"(?:\*\*)?(?:控股股东|实际控制人|国资股东|国家队)"
            r"(?:\*\*)?\s*[：:]"
        ),
    ),
    (
        "香港中央结算持股不能直接证明外资配置意愿",
        re.compile(
            r"香港中央结算有限公司[^。；\n]{0,180}"
            r"(?:判断|说明|表明|反映)[^。；\n]{0,30}外资配置意愿"
        ),
    ),
    (
        "缺少披露日历证据时不能补写下一份报告的预计截止时间",
        re.compile(
            r"(?:半年报|中报|季报|十大股东更新)[^。；\n]{0,80}"
            r"(?:通常|预计|大约)[^。；\n]{0,30}(?:月底前|月末前|披露)"
        ),
    ),
    (
        "缺少固定披露频率证据时不能补写下一次股东户数的预计天数",
        re.compile(
            r"(?:下一期|下次)股东户数[^。；\n]{0,50}"
            r"(?:约|预计|大约)\s*\d+(?:\s*[—–~～至到]\s*\d+)?\s*天"
        ),
    ),
)
_SHAREHOLDER_BOUNDARY_RE = re.compile(
    r"(?:不能|无法|不应|不可|不得|不宜|尚不能|未能|不代表|并不代表|并非|不是)"
    r"(?:直接|自动)?(?:将|把)?"
)
_SHAREHOLDER_POSITIVE_REVERSAL_RE = re.compile(
    r"(?:但|却|而(?:是)?)[^。；\n]{0,36}"
    r"(?:说明|表明|意味着|证明|显示|就是|等同|代表|判断|反映|"
    r"实时持仓|当日资金流|今日资金流|机构吸筹|主力吸筹|"
    r"被动调仓|主动建仓|外资配置意愿)"
)


def _has_unsupported_shareholder_inference(text: str, pattern: re.Pattern[str]) -> bool:
    """Treat explicit evidence boundaries as boundaries, not forbidden claims."""

    for clause in re.split(r"[。；\n]", text):
        for match in pattern.finditer(clause):
            matched_text = match.group(0)
            boundary_matches = list(_SHAREHOLDER_BOUNDARY_RE.finditer(matched_text))
            if not boundary_matches:
                return True
            boundary = boundary_matches[-1]
            if _SHAREHOLDER_POSITIVE_REVERSAL_RE.search(matched_text[boundary.end() :]):
                return True
            if _SHAREHOLDER_POSITIVE_REVERSAL_RE.search(clause[match.end() :]):
                return True
    return False


_SHAREHOLDER_STREAK_CLAIM_RE = re.compile(
    r"连续\s*(\d+)\s*(?:次|期|轮)[^。；\n]{0,32}(下降|减少|上升|增加)"
)
_AVAILABLE_DISTRIBUTION_MISSING_RE = re.compile(
    r"(?:缺少|没有|未提供)[^。；\n]{0,20}(?:个股)?涨跌?幅分布|"
    r"(?:个股)?涨跌?幅分布[^。；\n]{0,80}"
    r"(?:缺少|没有|未提供|缺失|不可用)[^。；\n]{0,24}"
    r"(?:分档(?:分布)?数据|明细|数据)?|"
    r"(?:个股)?涨跌?幅[^。；\n]{0,100}"
    r"(?:缺少|没有|未提供|缺失|不可用)[^。；\n]{0,24}"
    r"(?:±?\s*3%[^。；\n]{0,12})?分档(?:分布)?数据"
)
_AVAILABLE_TURNOVER_MISSING_RE = re.compile(
    r"(?:缺少|没有|未提供)[^。；\n]{0,20}(?:全市场)?成交额|"
    r"(?:全市场)?成交额[^。；\n]{0,12}(?:缺失|不可用)"
)
_AVAILABLE_MARKET_DRIVERS_MISSING_RE = re.compile(
    r"(?:当前|本次)?(?:证据|证据包)[^。；\n]{0,16}"
    r"(?:缺少|没有|未提供|尚无)[^。；\n]{0,80}"
    r"(?:市场资讯|消息面(?:驱动)?资讯|事件线索|驱动线索)"
)


def _has_available_index_return_missing_claim(
    text: str, indices: list[dict[str, Any]]
) -> bool:
    aliases_by_symbol = {
        "^GSPC": ("标普500", "标普"),
        "^IXIC": ("纳斯达克综合", "纳斯达克", "纳指"),
        "^DJI": ("道琼斯工业指数", "道琼斯", "道指"),
        "^RUT": ("罗素2000", "罗素"),
        "000001.SS": ("上证综指", "上证", "沪指"),
        "399001.SZ": ("深证成指", "深证", "深成指"),
        "399006.SZ": ("创业板指", "创业板"),
        "000300.SS": ("沪深300",),
        "000905.SS": ("中证500",),
    }
    missing_terms = ("缺少", "没有", "未提供", "未直接提供", "缺失", "不可用")
    metric_pattern = re.compile(
        r"(?:return_)?(1|5|20|60)(?:d_pct|\s*日(?:累计)?收益)(?:字段|数据)?"
    )
    for clause in re.split(r"[。；\n]", text):
        if not any(term in clause for term in missing_terms):
            continue
        normalized = re.sub(r"\s+", "", clause)
        for period_match in metric_pattern.finditer(clause):
            window = clause[max(0, period_match.start() - 18) : period_match.end() + 18]
            if not any(term in window for term in missing_terms):
                continue
            metric_key = f"return_{period_match.group(1)}d_pct"
            named_items = []
            for item in indices:
                aliases = aliases_by_symbol.get(
                    str(item.get("symbol") or ""),
                    (str(item.get("name") or ""),),
                )
                if any(alias and alias in normalized for alias in aliases):
                    named_items.append(item)
            candidates = named_items or indices
            available = [
                item
                for item in candidates
                if isinstance((item.get("metrics") or {}).get(metric_key), (int, float))
            ]
            if named_items and available:
                return True
            if not named_items and candidates and len(available) == len(candidates):
                return True
    return False


def _market_cause_fact_required_but_missing(
    answer: str, evidence: dict[str, Any]
) -> bool:
    focus_key = str((evidence.get("question_focus") or {}).get("key") or "")
    if focus_key != "market_cause":
        return False
    target_date = str(
        (evidence.get("analysis_target") or {}).get("market_date") or ""
    ).strip()
    candidates = []
    for item in evidence.get("indices") or []:
        if item.get("status") == "unavailable":
            continue
        if target_date and item.get("same_date_as_analysis_target") is False:
            continue
        value = (item.get("metrics") or {}).get("return_1d_pct")
        if isinstance(value, (int, float)):
            candidates.append((str(item.get("name") or ""), float(value)))
    if not candidates:
        return False
    for clause in re.split(r"[。；\n]", answer):
        for name, expected in candidates:
            if not name or name not in clause:
                continue
            values = []
            for match in _NUMBER_RE.finditer(clause):
                parsed = _number_value(match.group(0))
                if parsed is None:
                    continue
                prefix = clause[max(0, match.start() - 8) : match.start()]
                if any(term in prefix for term in ("跌", "下跌", "下降", "回落")):
                    parsed = -abs(parsed)
                elif any(term in prefix for term in ("涨", "上涨", "上升", "走高")):
                    parsed = abs(parsed)
                values.append(parsed)
            if any(
                abs(value - expected) <= max(0.06, abs(expected) * 0.01)
                for value in values
            ):
                return False
    return True


def _market_breadth_claim_is_user_reference(clause: str) -> bool:
    if not any(
        term in clause
        for term in (
            "你说的",
            "你所说的",
            "你感觉的",
            "你提到的",
            "问题中的",
            "按你的描述",
            "用户所说",
            "这个普涨快照",
            "该普涨快照",
            "上述普涨快照",
            "前述普涨快照",
        )
    ):
        return False
    return "普涨" in clause


def _market_breadth_claim_is_negated(clause: str) -> bool:
    return (
        re.search(
            r"(?:并非|不是|不等于|未达到|没有达到|不能称为|不可称为|"
            r"不应称为|而非|非)\s*(?:全市场)?\s*普涨",
            clause,
        )
        is not None
        or re.search(
            r"普涨[^，。；\n]{0,12}(?:并不成立|不能确认|无法确认|尚待核验)",
            clause,
        )
        is not None
    )


def _market_breadth_claim_has_matching_evidence(
    clause: str,
    evidence: dict[str, Any] | None,
) -> bool:
    if not evidence:
        return False
    market_breadth = evidence.get("market_breadth") or {}
    breadth = market_breadth.get("breadth") or {}
    if (
        market_breadth.get("status") != "available"
        or str(breadth.get("state") or "") != "普涨"
    ):
        return False
    if market_breadth.get("same_date_as_analysis_target") is not False:
        return True

    market_date = str(market_breadth.get("market_date") or "")[:10]
    if not market_date:
        return False
    try:
        year, month, day = (int(part) for part in market_date.split("-"))
    except (TypeError, ValueError):
        return False
    exact_terms = (
        market_date,
        f"{year}年{month}月{day}日",
        f"{month}月{day}日",
    )
    if any(term in clause for term in exact_terms):
        return True

    explicit_dates = re.findall(r"(?:\d{4}年)?\d{1,2}月\d{1,2}日|\d{4}-\d{2}-\d{2}", clause)
    if explicit_dates:
        return False
    user_question = str(evidence.get("user_question") or "")
    relative_terms = ("今天", "今日", "当前", "盘中", "午间", "截至目前")
    if any(term in clause for term in relative_terms) and any(
        term in user_question for term in relative_terms
    ):
        return True
    return any(term in user_question for term in relative_terms) and any(
        term in user_question
        for term in ("昨天", "昨日", "上一交易日", "前一交易日", "前日")
    )


def _has_whole_market_breadth_overclaim(
    text: str,
    evidence: dict[str, Any] | None = None,
) -> bool:
    cautious_terms = (
        "不能确认",
        "无法确认",
        "尚不能确认",
        "不能断言",
        "不能声称",
        "是否普涨",
        "普涨仍待",
        "普涨尚待",
        "广度仍待",
        "广度尚待",
        "更接近结构性行情",
        "倾向结构性行情",
    )
    for clause in re.split(r"[。；\n]", text):
        if "普涨" not in clause:
            continue
        if any(term in clause for term in cautious_terms):
            continue
        if _market_breadth_claim_is_negated(clause):
            continue
        if _market_breadth_claim_is_user_reference(clause):
            continue
        if _market_breadth_claim_has_matching_evidence(clause, evidence):
            continue
        return True
    return False


def _has_unsupported_majority_stock_claim(text: str) -> bool:
    cautious_terms = (
        "不能确认",
        "无法确认",
        "尚不能确认",
        "仍待核验",
        "尚待核验",
        "尚未核验",
        "尚未由同日全市场",
        "没有同日全市场",
        "缺少同日全市场",
    )
    majority_claim = re.compile(
        r"(?:大多数|多数|大部分|超过半数|过半)"
        r"[^，。；\n]{0,12}(?:股票|个股)"
        r"[^，。；\n]{0,12}(?:上涨|下跌|收涨|收跌|飘红|飘绿)"
    )
    for clause in re.split(r"[。；\n]", text):
        if majority_claim.search(clause) is None:
            continue
        if any(term in clause for term in cautious_terms):
            continue
        return True
    return False


def _has_uncautious_breadth_label(text: str, label: str) -> bool:
    cautious_terms = (
        "不能确认",
        "无法确认",
        "尚不能确认",
        "未达到",
        "不等于",
        "并非",
        "而非",
        "不是",
        "是否",
        "不能称为",
        "不可称为",
        "不应称为",
        "固定分类方法",
        "固定分类标准",
        "固定分类规则",
        "分类规则",
        "普涨要求",
        "普跌要求",
    )
    for clause in re.split(r"[。；\n]", text):
        if label not in clause:
            continue
        if any(term in clause for term in cautious_terms):
            continue
        return True
    return False


def _has_uncautious_structural_market_claim(text: str) -> bool:
    cautious_terms = (
        "不能确认",
        "无法确认",
        "尚不能确认",
        "不能断言",
        "不能作为确定结论",
        "是否属于结构性行情",
        "是否为结构性行情",
    )
    for clause in re.split(r"[。；\n]", text):
        if "结构性行情" not in clause:
            continue
        if any(term in clause for term in cautious_terms):
            continue
        if re.search(
            r"(?:是|属于|已经|确认|明确为|归为|归类为)"
            r"[^，。；\n]{0,28}结构性行情",
            clause,
        ):
            return True
    return False


def _has_unproven_downtrend_claim(text: str) -> bool:
    cautious_terms = (
        "不等于",
        "不代表",
        "没有形成",
        "未形成",
        "尚未形成",
        "不能确认",
        "不能直接确认",
        "无法直接确认",
        "尚未确认",
        "不是",
        "并非",
        "而非",
    )
    for clause in re.split(r"[。；\n]", text):
        if not _MARKET_DOWNTREND_OVERCLAIM_RE.search(clause):
            continue
        if any(term in clause for term in cautious_terms):
            continue
        return True
    return False


def _has_wrong_index_return_extreme_claim(
    text: str, indices: list[dict[str, Any]]
) -> bool:
    available = [
        item
        for item in indices
        if isinstance((item.get("metrics") or {}).get("return_1d_pct"), (int, float))
    ]
    if len(available) < 2:
        return False
    aliases_by_symbol = {
        "^GSPC": ("标普500", "标普"),
        "^IXIC": ("纳斯达克综合", "纳斯达克", "纳指"),
        "^DJI": ("道琼斯工业指数", "道琼斯", "道指"),
        "^RUT": ("罗素2000", "罗素"),
        "000001.SS": ("上证综指", "上证", "沪指"),
        "399001.SZ": ("深证成指", "深证", "深成指"),
        "399006.SZ": ("创业板指", "创业板"),
        "000300.SS": ("沪深300",),
        "000905.SS": ("中证500",),
    }
    claims = (
        ("跌幅最大", min),
        ("领跌", min),
        ("涨幅最大", max),
        ("领涨", max),
    )
    for clause in re.split(r"[。；\n]", text):
        normalized_clause = re.sub(r"\s+", "", clause)
        comparison_items = available
        if "三大指数" in normalized_clause:
            major_symbols = {"^GSPC", "^IXIC", "^DJI"}
            scoped = [
                item
                for item in available
                if str(item.get("symbol") or "") in major_symbols
            ]
            if len(scoped) >= 2:
                comparison_items = scoped
        values = [
            float((item.get("metrics") or {})["return_1d_pct"])
            for item in comparison_items
        ]
        for term, reducer in claims:
            claim_position = normalized_clause.find(term)
            if claim_position < 0:
                continue
            prefix = normalized_clause[:claim_position]
            subjects = []
            for item in available:
                aliases = aliases_by_symbol.get(
                    str(item.get("symbol") or ""),
                    (str(item.get("name") or ""),),
                )
                position = max(
                    (prefix.rfind(alias) for alias in aliases if alias), default=-1
                )
                if position >= 0:
                    subjects.append((position, item))
            if not subjects:
                continue
            subject = max(subjects, key=lambda row: row[0])[1]
            if subject not in comparison_items:
                continue
            subject_value = float((subject.get("metrics") or {})["return_1d_pct"])
            expected = reducer(values)
            if abs(subject_value - expected) > 1e-6:
                return True
    return False


def _has_unavailable_index_return_claim(
    text: str, indices: list[dict[str, Any]]
) -> bool:
    aliases_by_symbol = {
        "^GSPC": ("标普500", "标普"),
        "^IXIC": ("纳斯达克综合", "纳斯达克", "纳指"),
        "^DJI": ("道琼斯工业指数", "道琼斯", "道指"),
        "^RUT": ("罗素2000", "罗素"),
        "000001.SS": ("上证综指", "上证", "沪指"),
        "399001.SZ": ("深证成指", "深证", "深成指"),
        "399006.SZ": ("创业板指", "创业板"),
        "000300.SS": ("沪深300",),
        "000905.SS": ("中证500",),
    }
    for clause in re.split(r"[。；\n]", text):
        if not re.search(r"[-+]?\d+(?:\.\d+)?%", clause):
            continue
        if not any(
            term in clause for term in ("涨幅", "跌幅", "上涨", "下跌", "收涨", "收跌")
        ):
            continue
        metric_key = (
            "return_60d_pct"
            if "60日" in clause
            else "return_20d_pct"
            if "20日" in clause
            else "return_5d_pct"
            if "5日" in clause
            else "return_1d_pct"
        )
        unavailable = [
            item
            for item in indices
            if not isinstance((item.get("metrics") or {}).get(metric_key), (int, float))
        ]
        normalized = re.sub(r"\s+", "", clause)
        for item in unavailable:
            aliases = aliases_by_symbol.get(
                str(item.get("symbol") or ""),
                (str(item.get("name") or ""),),
            )
            if any(alias and alias in normalized for alias in aliases):
                return True
    return False


def _has_index_return_direction_conflict(
    text: str, indices: list[dict[str, Any]]
) -> bool:
    aliases_by_symbol = {
        "^GSPC": ("标普500", "标普"),
        "^IXIC": ("纳斯达克综合", "纳斯达克", "纳指"),
        "^DJI": ("道琼斯工业指数", "道琼斯", "道指"),
        "^RUT": ("罗素2000", "罗素"),
        "000001.SS": ("上证综指", "上证", "沪指"),
        "399001.SZ": ("深证成指", "深证", "深成指"),
        "399006.SZ": ("创业板指", "创业板"),
        "000300.SS": ("沪深300",),
        "000905.SS": ("中证500",),
    }
    grouped_direction = re.compile(
        r"((?:5|20|60)\s*日(?:\s*[、和及/]\s*(?:5|20|60)\s*日)+)"
        r"[^。；\n]{0,30}(?:累计)?收益[^。；\n]{0,20}"
        r"(?:均|都)?(?:为|是)?(正|负)"
    )
    for clause in re.split(r"[。；\n]", text):
        normalized = re.sub(r"\s+", "", clause)
        for match in grouped_direction.finditer(normalized):
            periods = {
                int(value) for value in re.findall(r"(5|20|60)日", match.group(1))
            }
            expected_positive = match.group(2) == "正"
            for item in indices:
                aliases = aliases_by_symbol.get(
                    str(item.get("symbol") or ""),
                    (str(item.get("name") or ""),),
                )
                if not any(alias and alias in normalized for alias in aliases):
                    continue
                metrics = item.get("metrics") or {}
                for period in periods:
                    value = metrics.get(f"return_{period}d_pct")
                    if not isinstance(value, (int, float)):
                        continue
                    if expected_positive != (float(value) > 0):
                        return True
    return False


def _has_index_trend_state_conflict(text: str, indices: list[dict[str, Any]]) -> bool:
    aliases_by_symbol = {
        "^GSPC": ("标普500", "标普"),
        "^IXIC": ("纳斯达克综合", "纳斯达克", "纳指"),
        "^DJI": ("道琼斯工业指数", "道琼斯", "道指"),
        "^RUT": ("罗素2000", "罗素"),
        "000001.SS": ("上证综指", "上证", "沪指"),
        "399001.SZ": ("深证成指", "深证", "深成指"),
        "399006.SZ": ("创业板指", "创业板"),
        "000300.SS": ("沪深300",),
        "000905.SS": ("中证500",),
    }
    claim_pattern = re.compile(
        r"(?:中期)?趋势状态(?:为|是|：|:)?\s*"
        r"[\"'“”]?((?:中期)?偏强|(?:中期)?偏弱|趋势分化|分化|下行)"
    )
    for clause in re.split(r"[。；\n]", text):
        normalized = re.sub(r"\s+", "", clause)
        claim = claim_pattern.search(normalized)
        if claim is None:
            continue
        claimed_state = claim.group(1)
        for item in indices:
            aliases = aliases_by_symbol.get(
                str(item.get("symbol") or ""),
                (str(item.get("name") or ""),),
            )
            if not any(alias and alias in normalized for alias in aliases):
                continue
            evidence_state = str((item.get("metrics") or {}).get("trend_state") or "")
            if not evidence_state:
                continue
            normalized_claim = (
                "中期偏强"
                if "偏强" in claimed_state
                else "中期偏弱"
                if "偏弱" in claimed_state
                else "趋势分化"
                if "分化" in claimed_state
                else "下行"
            )
            if normalized_claim not in evidence_state:
                return True
    return False


def _has_wrong_index_volatility_extreme_claim(
    text: str, indices: list[dict[str, Any]]
) -> bool:
    available = [
        item
        for item in indices
        if isinstance(
            (item.get("metrics") or {}).get("volatility_20d_annualized_pct"),
            (int, float),
        )
    ]
    if len(available) < 2:
        return False
    aliases_by_symbol = {
        "^GSPC": ("标普500", "标普"),
        "^IXIC": ("纳斯达克综合", "纳斯达克", "纳指"),
        "^DJI": ("道琼斯工业指数", "道琼斯", "道指"),
        "^RUT": ("罗素2000", "罗素"),
        "000001.SS": ("上证综指", "上证", "沪指"),
        "399001.SZ": ("深证成指", "深证", "深成指"),
    }
    values = [
        float((item.get("metrics") or {})["volatility_20d_annualized_pct"])
        for item in available
    ]
    for clause in re.split(r"[。；\n]", text):
        normalized_clause = re.sub(r"\s+", "", clause)
        for term, expected in (("最低", min(values)), ("最高", max(values))):
            claim_position = normalized_clause.find(term)
            if claim_position < 0 or "波动" not in normalized_clause[:claim_position]:
                continue
            prefix = normalized_clause[:claim_position]
            subjects = []
            for item in available:
                aliases = aliases_by_symbol.get(
                    str(item.get("symbol") or ""),
                    (str(item.get("name") or ""),),
                )
                position = max(
                    (prefix.rfind(alias) for alias in aliases if alias), default=-1
                )
                if position >= 0:
                    subjects.append((position, item))
            if not subjects:
                continue
            subject = max(subjects, key=lambda row: row[0])[1]
            subject_value = float(
                (subject.get("metrics") or {})["volatility_20d_annualized_pct"]
            )
            if abs(subject_value - expected) > 1e-6:
                return True
    return False


def _has_mismatched_major_index_count(text: str, indices: list[dict[str, Any]]) -> bool:
    available = [item for item in indices if item.get("status") != "unavailable"]
    if len(available) < 4 or "三大指数" not in text:
        return False
    for clause in re.split(r"[。；\n]", text):
        if "三大指数" not in clause:
            continue
        normalized = re.sub(r"\s+", "", clause)
        named_four = all(
            term in normalized for term in ("标普", "纳斯达克", "道琼斯", "罗素")
        )
        if "四个代表性指数" in normalized or named_four:
            return True
    return False


def _has_moving_average_status_conflict(
    text: str, indices: list[dict[str, Any]]
) -> bool:
    aliases_by_symbol = {
        "^GSPC": ("标普500", "标普"),
        "^IXIC": ("纳斯达克综合", "纳斯达克", "纳指"),
        "^DJI": ("道琼斯工业指数", "道琼斯", "道指"),
        "^RUT": ("罗素2000", "罗素"),
        "000001.SS": ("上证综指", "上证", "沪指"),
        "399001.SZ": ("深证成指", "深证", "深成指"),
    }
    for clause in re.split(r"[。；\n]", text):
        normalized_clause = re.sub(r"\s+", "", clause)
        for item in indices:
            metrics = item.get("metrics") or {}
            latest = metrics.get("latest_close")
            if not isinstance(latest, (int, float)):
                continue
            aliases = aliases_by_symbol.get(
                str(item.get("symbol") or ""),
                (str(item.get("name") or ""),),
            )
            if not any(alias and alias in normalized_clause for alias in aliases):
                continue
            below_ma20 = isinstance(metrics.get("ma20"), (int, float)) and float(
                latest
            ) < float(metrics["ma20"])
            below_ma60 = isinstance(metrics.get("ma60"), (int, float)) and float(
                latest
            ) < float(metrics["ma60"])
            above_ma20 = isinstance(metrics.get("ma20"), (int, float)) and float(
                latest
            ) > float(metrics["ma20"])
            above_ma60 = isinstance(metrics.get("ma60"), (int, float)) and float(
                latest
            ) > float(metrics["ma60"])
            if (below_ma20 or below_ma60) and re.search(
                r"两条均线[^。；\n]{0,18}(?:均)?(?:尚未|未被|没有)[^。；\n]{0,14}跌破",
                normalized_clause,
            ):
                return True
            if below_ma20 and re.search(
                r"(?:MA20|20日均线)[^。；\n]{0,24}(?:尚未|未被|没有)[^。；\n]{0,14}跌破",
                normalized_clause,
                re.IGNORECASE,
            ):
                return True
            if below_ma60 and re.search(
                r"(?:MA60|60日均线)[^。；\n]{0,24}(?:尚未|未被|没有)[^。；\n]{0,14}跌破",
                normalized_clause,
                re.IGNORECASE,
            ):
                return True
            if above_ma20 and re.search(
                r"(?:(?:已经|已|仍|目前)?(?:在)?(?:MA20|20日(?:均)?线)[^。；\n]{0,8}下方|"
                r"(?:已经|已|仍|目前)?(?:有效)?跌破(?:了)?(?:MA20|20日(?:均)?线))",
                normalized_clause,
                re.IGNORECASE,
            ):
                return True
            if above_ma60 and re.search(
                r"(?:(?:已经|已|仍|目前)?(?:在)?(?:MA60|60日(?:均)?线)[^。；\n]{0,8}下方|"
                r"(?:已经|已|仍|目前)?(?:有效)?跌破(?:了)?(?:MA60|60日(?:均)?线))",
                normalized_clause,
                re.IGNORECASE,
            ):
                return True
    return False


def _has_unproven_analyst_revision_claim(text: str) -> bool:
    cautious_terms = (
        "不能判断",
        "无法判断",
        "尚不能判断",
        "不能确认",
        "无法确认",
        "尚无历史",
        "没有历史",
        "尚未形成历史",
        "不能混用",
        "不能作为",
        "不构成",
        "并非",
        "不得说",
    )
    for clause in re.split(r"[。；\n]", text):
        if not re.search(r"(?:上修|下修|调高|调低)", clause):
            continue
        if "是否" in clause or clause.rstrip().endswith(("?", "？")):
            continue
        if any(term in clause for term in cautious_terms):
            continue
        return True
    return False


def _has_unsafe_rating_recommendation(
    text: str, *, analyst_evidence_available: bool
) -> bool:
    non_advice_terms = (
        "不构成交易建议",
        "不是交易建议",
        "不等于交易建议",
        "不能作为交易建议",
    )
    for clause in re.split(r"[。；\n]", text):
        if not re.search(r"(?:买入评级|卖出评级)", clause):
            continue
        if analyst_evidence_available and any(
            term in clause for term in ("样本", "券商", "机构", "研报")
        ):
            recommendation_language = any(
                term in clause for term in ("给予", "维持", "调整为")
            ) or (
                "建议" in clause
                and not any(term in clause for term in non_advice_terms)
            )
            if not recommendation_language:
                continue
        return True
    return False


_TOP10_HISTORICAL_COMPARISON_RE = re.compile(
    r"(?:前十名|十大股东)[^。；\n]{0,100}"
    r"(?:与|较)(?:之前|上期|前期|上一期|历史)[^。；\n]{0,40}"
    r"(?:持平|变化不大|基本稳定|上升|下降|增加|减少)"
)
_MARKET_DOWNTREND_OVERCLAIM_RE = re.compile(
    r"(?:趋势|格局)[^。；\n]{0,30}(?:依然|仍然|继续|持续)?"
    r"(?:向下|下行)|下跌趋势"
)
_REPRESENTATIVE_INDEX_COUNT_RE = re.compile(r"(\d+)\s*个代表性指数")
_APPROX_REPRESENTATIVE_INDEX_COUNT_RE = re.compile(
    r"(?:近百|上百|百余|数十|几十)(?:只|个)?代表性指数"
)
_SINGLE_INDEX_ADVANCE_RATIO_RE = re.compile(
    r"(?:上证综指|深证成指|标普500|纳斯达克|道琼斯|日经225|KOSPI)"
    r"\s*(?:的)?上涨比例"
)
_UNAVAILABLE_MA5_RE = re.compile(r"(?:MA\s*5|5\s*日均线)", re.IGNORECASE)
_UNSUPPORTED_WAVE_RE = re.compile(r"(?:A|B|C)\s*浪|浪型", re.IGNORECASE)
