"""Public aggregate report; never expose experimental answers or private files."""
import html
import json
from pathlib import Path

RELEASE_PATH = Path(__file__).with_name('evolution_release.json')

def release_info():
    return json.loads(RELEASE_PATH.read_text(encoding='utf-8'))

def fraction(hits, denominator):
    return f'{hits:,}/{denominator:,} ({100 * hits / denominator:.2f}%)' if denominator else '不适用（分母为 0）'

def report_html():
    data = release_info()
    prop, process = data['property_experiment'], data['process_experiment']
    labels = {'operation': '工艺操作', 'parameter': '工艺参数', 'order': '先后顺序', 'binding': '完整材料/样品绑定'}
    rows = ''.join(f'<tr><th>{labels[key]}</th><td>{fraction(item["hits"], item["denominator"])}</td></tr>'
                   for key, item in process['coverage'].items())
    denominator = prop['denominator']
    return f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>最新进化版本与实验结果</title>
<style>body{{font:16px/1.7 Arial,"Microsoft YaHei",sans-serif;color:#172333;background:#f3f6f8;margin:0;padding:24px}}
main{{max-width:960px;margin:auto}}section{{background:white;padding:24px;margin:20px 0;border-radius:12px;border:1px solid #dce4ea}}
h1{{font-size:28px}}h2{{font-size:21px}}table{{border-collapse:collapse;width:100%}}th,td{{text-align:left;padding:12px;border-bottom:1px solid #dce4ea}}
.notice{{border-left:4px solid #bf711d;background:#fff7eb;padding:16px}}.scroll{{overflow:auto}}a{{color:#0066cc}}code{{overflow-wrap:anywhere}}
@media(max-width:600px){{body{{padding:12px}}section{{padding:16px}}th,td{{padding:8px}}h1{{font-size:24px}}}}</style>
<main><a href="/">返回抽取工作台</a><h1>最新进化版本与实验结果</h1>
<p>运行版本：<code>{html.escape(data['runtime_version'])}</code></p>
<div class="notice">以下为历史实验汇总，不是当前网页批次的实时评分，也不保证新上传论文达到同样指标。旧批次没有被覆盖。</div>
<section><h2>网页接入了什么</h2><p>大流程仍为文档读取 → 材料识别 → 聚合物 → 样品与工艺 → 性质 → 表征 → 校验与结果发布。</p>
<ul><li>性质阶段：科学计数法、单位和倍率、明确区间、热转变及原始样品标签的证据约束修复。</li>
<li>样品与工艺：同时读取 Methods 与 Results 中的相关上下文，改善标签、组成及状态保留。</li>
<li>Preview 发布：恢复已有证据且满足条件的表格值，保留不确定项，不编造样品归属。</li></ul>
<p>未自动开启额外正文/表格模型补抽。新增的独立工艺图 r7 仍是实验分支，不冒充网页已完成全量工艺升级。</p>
<p>费用说明：模型配置和传输重试保持生产设置。Stage 3 上下文上限由 50,000 增至 60,000 字符，并允许一次输出校验修复，可能增加输入 token 和一次模型调用；确定性修复本身不调用模型。</p></section>
<section><h2>性质实验：101 篇、3,525 组直接值</h2><div class="scroll"><table><thead><tr><th>统一 v4 口径</th><th>E13（已进化起点）</th><th>E25</th></tr></thead><tbody>
<tr><th>全阶段 Recall</th><td>{fraction(prop['baseline_all_stage_hits'], denominator)}</td><td>{fraction(prop['all_stage_hits'], denominator)}</td></tr>
<tr><th>最终结果 Recall</th><td>{fraction(prop['baseline_final_hits'], denominator)}</td><td>{fraction(prop['final_hits'], denominator)}</td></tr>
</tbody></table></div><p>仅衡量已核验、正文或表格直接报告值的数值与单位匹配。不是完整样品、工艺关系的准确率。101 篇中 98 篇分母非零，其余 3 篇不算作 Recall 100%。</p>
<p>这些论文参与过优化，不是未见测试集。历史效果还包含实验中的补抽和来源修复，不能仅凭本次代码接入声称已经重现。</p></section>
<section><h2>独立工艺审核：26 篇</h2><table><thead><tr><th>维度</th><th>参考覆盖率</th></tr></thead><tbody>{rows}</tbody></table>
<p>生成断言的证据支持率：{fraction(process['support']['hits'], process['support']['denominator'])}。</p>
<p class="notice">完整绑定覆盖率为 91.11%，仍未达到 95%。这是模型辅助主审及交叉审核的结果，不宣称已完成独立专家金标验证，也不代表 101 篇的工艺准确率。</p></section>
<section><h2>追溯与数据边界</h2><p>本页只展示汇总。未公开原始 PDF、私有 PoLyInfo、模型原始响应或用户上传任务。</p>
<p><a href="/api/reports/evolution/data">下载汇总 JSON 与来源记录</a></p>
<p>代码导入清单：<code>docs/e25_runtime_import_manifest.json</code>；接入说明：<code>docs/e25_runtime_integration_20260920.md</code>。</p></section></main></html>'''
