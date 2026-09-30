"use client";

import { Alert, Button, Input, Progress, Typography, Upload } from "antd";
import { Activity, ArrowRight, BadgeCheck, Check, ClipboardList, FileText, FileUp, FileCheck2, Layers, ListChecks, LoaderCircle, Play, ShieldCheck, Sparkles, Timer, X } from "lucide-react";
import type { ExtractionJob, HealthState, JobStage } from "../../types";
import { formatBytes, stageCatalog, stageStatusLabel } from "../../utils/format";
import { useExtraction } from "../../store/extraction";
import "./style.css";
const { Title, Text, Paragraph } = Typography;
const { Dragger } = Upload;

function UploadPage({ file, job, health, apiChecked, uploading, dmxApiKey, mineruApiKey, onFile, onDmxApiKey, onMineruApiKey, onStart, onRefresh, onLoadSample, onOpenResults }: {
  file: File | null;
  job: ExtractionJob | null;
  health: HealthState | null;
  apiChecked: boolean;
  uploading: boolean;
  dmxApiKey: string;
  mineruApiKey: string;
  onFile: (file: File | null) => void;
  onDmxApiKey: (value: string) => void;
  onMineruApiKey: (value: string) => void;
  onStart: () => void;
  onRefresh: () => void;
  onLoadSample: () => void;
  onOpenResults: () => void;
}) {
  const displayedStages: JobStage[] = stageCatalog.map((stage) => job?.stages.find((item) => item.id === stage.id) || { id: stage.id, status: "pending", artifact: null });
  const keysReady = Boolean(dmxApiKey.trim() && mineruApiKey.trim());
  const secureSubmission = health?.key_submission_allowed !== false;
  const running = ["queued", "running"].includes(job?.status || "");
  const canStart = Boolean(file && health && secureSubmission && keysReady && !uploading && !running);
  const doneCount = displayedStages.filter((s) => s.status === "complete").length;

  return (
    <div className="upload-page">

      {apiChecked && !health && (
        <Alert className="upload-alert" type="warning" showIcon message="本地抽取服务尚未启动"
          description="运行项目根目录的 start_web_tool.ps1 后刷新状态。前端不会伪造抽取进度。"
          action={<Button size="small" onClick={onRefresh}>重新检测</Button>} />
      )}
      {health && !secureSubmission && (
        <Alert className="upload-alert" type="warning" showIcon message="当前地址仅供浏览，上传抽取暂未开放"
          description="API Key 必须通过 HTTPS 传输。请改用系统提供的 HTTPS 地址。" />
      )}

      <div className="upload-grid">
        {/* ——— 左：提交卡 — 单卡走完 选文件→填密钥→开始 ——— */}
        <section className="ucard input-card submit-card">
          <div className="ucard-head">
            <div><h3><span className="title-icon"><ClipboardList size={15} /></span>新建抽取任务</h3><p>PDF · 最大 50 MB · 密钥内存态不落盘</p></div>
            <span className="step-chip">01</span>
          </div>

          <ol className="submit-steps">
            <li className={`submit-step ${file ? "done" : "active"}`}>
              <span className="submit-num">{file ? <Check size={12} strokeWidth={3} /> : "1"}</span>
              <div className="submit-body">
                <div className="submit-label">选择 PDF 文件</div>
                <Dragger
                  accept="application/pdf,.pdf"
                  multiple={false}
                  showUploadList={false}
                  beforeUpload={(next) => { onFile(next); return Upload.LIST_IGNORE; }}
                  disabled={running}
                  className="pdf-drop"
                >
                  <div className="pdf-drop-inner">
                    <span className="pdf-drop-icon"><FileUp size={20} /></span>
                    <div className="pdf-drop-text"><strong>{file ? "重新选择 PDF" : "拖拽 PDF 到此处，或点击选择"}</strong><span>仅支持可读取文本的论文 PDF · 最大 50 MB</span></div>
                    <span className="pdf-browse">浏览文件</span>
                  </div>
                </Dragger>
                {file ? (
                  <div className="file-row">
                    <span className="file-badge"><FileText size={15} /></span>
                    <div className="file-meta"><strong title={file.name}>{file.name}</strong><span>{formatBytes(file.size)} · 待提交</span></div>
                    {running ? <Check size={16} className="ok" /> : <button className="file-remove" aria-label="移除文件" onClick={(e) => { e.stopPropagation(); onFile(null); }}><X size={14} /></button>}
                  </div>
                ) : (
                  <div className="file-empty">尚未选择文件 — 选择后显示真实文件名与大小。</div>
                )}
              </div>
            </li>

            <li className={`submit-step ${keysReady ? "done" : file ? "active" : ""}`}>
              <span className="submit-num">{keysReady ? <Check size={12} strokeWidth={3} /> : "2"}</span>
              <div className="submit-body">
                <div className="submit-label">填写本次任务凭据 <em>内存态 · 不落盘</em></div>
                <div className="cred-block flat">
                  <div className="cred-grid">
                    <label htmlFor="dmx-api-key">DMX API Key<Input.Password id="dmx-api-key" value={dmxApiKey} onChange={(e) => onDmxApiKey(e.target.value)} autoComplete="new-password" placeholder="sk-…" size="middle" /></label>
                    <label htmlFor="mineru-api-key">MinerU API Key<Input.Password id="mineru-api-key" value={mineruApiKey} onChange={(e) => onMineruApiKey(e.target.value)} autoComplete="new-password" placeholder="minerU-…" size="middle" /></label>
                  </div>
                  {!keysReady && <p className="cred-hint">输入两个密钥后方可提交，任务结束后内存清除。</p>}
                </div>
              </div>
            </li>

            <li className={`submit-step ${canStart || running ? "active" : ""}`}>
              <span className="submit-num">3</span>
              <div className="submit-body">
                <div className="submit-label">确认并提交</div>
                <div className="input-actions">
                  <Button type="primary" size="middle" loading={uploading} disabled={!canStart} icon={!uploading ? <Play size={14} /> : undefined} onClick={onStart} className="start-btn">开始抽取</Button>
                  <Button size="middle" onClick={onLoadSample}>加载已完成示例</Button>
                </div>
                {!canStart && <p className="gate-hint">{!file ? "先选择 PDF 文件。" : !health ? "等待抽取服务连接。" : !keysReady ? "还差 API 密钥未填写（就在上方）。" : running ? "任务运行中，请稍候。" : ""}</p>}
              </div>
            </li>
          </ol>

          <p className="secure-note"><ShieldCheck size={13} />文件写入独立任务目录；请使用个人密钥并在服务商控制台核对用量。</p>
        </section>

        {/* ——— 右：流水线卡 ——— */}
        <section className="ucard pipe-card">
          <div className="ucard-head">
            <div><h3><span className="title-icon"><Activity size={15} /></span>抽取流水线</h3><p>{job ? `${job.ref_no} · ${job.file_name}` : "提交后显示真实阶段状态"}</p></div>
            <span className="step-chip">02</span>
          </div>

          <div className="pipe-meter">
            <div className="pipe-meter-top"><Text type="secondary">{doneCount} / {stageCatalog.length} 阶段完成</Text><strong>{job?.progress || 0}%</strong></div>
            <Progress percent={job?.progress || 0} showInfo={false} strokeWidth={6} strokeLinecap="round"
              trailColor="#eef0f3" strokeColor={job?.status === "failed" ? "#e5484d" : "#171717"}
              status={job?.status === "failed" ? "exception" : undefined} />
          </div>

          <ol className="pipe-list">
            {stageCatalog.map((stage, index) => {
              const state = displayedStages[index];
              return (
                <li className={`pipe-item ${state.status}`} key={stage.id}>
                  <span className="pipe-dot">
                    {state.status === "complete" ? <Check size={12} strokeWidth={3} /> : state.status === "running" ? <LoaderCircle size={13} className="spin" /> : state.status === "failed" ? <X size={12} strokeWidth={3} /> : <i>{index + 1}</i>}
                  </span>
                  <div className="pipe-body">
                    <div className="pipe-name"><strong>{stage.name}</strong><code>{stage.en}</code><span className="pipe-status">{stageStatusLabel(state.status)}</span></div>
                    <p>{stage.detail}{state.artifact ? ` · ${state.artifact}` : ""}</p>
                  </div>
                </li>
              );
            })}
          </ol>

          <div className="pipe-foot">
            {job?.error && <Alert type="error" showIcon message="任务未完成" description={job.error} className="upload-alert" />}
            {job?.result_ready
              ? <Button type="primary" block icon={<ArrowRight size={14} />} onClick={onOpenResults} className="start-btn result-btn">查看抽取结果</Button>
              : <p className="pipe-idle">{job ? "流水线按 Stage 0–5 顺序推进，结果就绪后可跳转查看。" : "暂无运行中的任务 — 左侧上传并开始抽取。"}</p>}
          </div>
        </section>
      </div>

      {/* ——— 下方补充区：常见问题（左）/ 抽取产出（右），与上方双卡同列宽对齐 ——— */}
      <div className="upload-extra">
        <section className="ucard extra-card faq-card">
          <div className="ucard-head">
            <div><h3><span className="title-icon"><FileText size={15} /></span>常见问题</h3><p>抽取失败先看这里</p></div>
          </div>
          <details open><summary>支持哪些论文？</summary><p>英文聚合物 / 电介质 / 储能方向论文 PDF，优先选择出版商原版可复制文本文件。</p></details>
          <details><summary>密钥会被保存吗？</summary><p>不会。密钥只保存在浏览器内存中，随本次任务提交，刷新或关闭即清除。</p></details>
          <details><summary>中途可以关闭页面吗？</summary><p>不建议。流水线按 Stage 0–5 顺序推进，关闭后需重新提交任务。</p></details>
        </section>

        <section className="ucard extra-card output-card">
          <div className="ucard-head">
            <div><h3><span className="title-icon"><Sparkles size={15} /></span>本次抽取将得到什么</h3><p>结构化聚合结果 · 可直接进入审核</p></div>
          </div>
          <ul className="output-list">
            {[
              { icon: <Layers size={15} />, t: "聚合物档案", d: "名称 / 缩写 / SMILES / 分子量 / 分子式" },
              { icon: <FileCheck2 size={15} />, t: "样品卡片", d: "配比 / 加工条件 / 厚度 / 测试方法" },
              { icon: <ListChecks size={15} />, t: "性能数据点", d: "介电 / 击穿 / 能量密度 · 含数值与单位" },
              { icon: <BadgeCheck size={15} />, t: "溯源定位", d: "每条记录保留原文页码与表格编号" },
            ].map((item) => (
              <li key={item.t}>
                <span className="output-icon">{item.icon}</span>
                <div><strong>{item.t}</strong><span>{item.d}</span></div>
              </li>
            ))}
          </ul>
          <div className="extra-foot">
            <span className="extra-meta"><Timer size={12} />典型论文约 3–8 分钟</span>
          </div>
        </section>
      </div>
    </div>
  );
}

export default function UploadRoute() {
  const s = useExtraction();
  return (
    <UploadPage
      file={s.selectedFile} job={s.job} health={s.health} apiChecked={s.apiChecked}
      uploading={s.uploading} dmxApiKey={s.dmxApiKey} mineruApiKey={s.mineruApiKey}
      onFile={s.setSelectedFile} onDmxApiKey={s.setDmxApiKey} onMineruApiKey={s.setMineruApiKey}
      onStart={() => void s.startExtraction()} onRefresh={() => void s.checkHealth()}
      onLoadSample={s.loadSample} onOpenResults={s.openResults}
    />
  );
}
