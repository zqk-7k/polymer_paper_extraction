"use client";

import { Alert, Button, Input, Progress, Typography, Upload } from "antd";
import { ArrowRight, Check, FileText, FileUp, LoaderCircle, Play, ShieldCheck, X } from "lucide-react";
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
      {/* ——— Hero：克制编辑风，与其他页一致，只讲标题+状态 ——— */}
      <header className="upload-hero">
        <div className="upload-hero-main">
          <span className="upload-eyebrow">论文抽取 · 单篇 PDF</span>
          <Title level={2}>上传一篇高分子论文</Title>
          <Paragraph>按 ① 选文件 → ② 填密钥 → ③ 开始抽取的顺序，一张卡内完成提交，右侧实时显示流水线进度。</Paragraph>
        </div>
        <div className="upload-hero-side">
          <span className={`svc-dot ${health ? "on" : ""}`}><i />{health ? "服务在线" : apiChecked ? "服务未连接" : "检测中…"}</span>
          {job && (
            <span className={`svc-dot job-dot ${job.status === "complete" ? "ok" : job.status === "failed" ? "bad" : "run"}`}><i />{job.status === "complete" ? `已完成 ${job.progress}%` : job.status === "failed" ? "任务失败" : `运行中 ${job.progress || 0}%`}</span>
          )}
        </div>
      </header>

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
            <div><h3>新建抽取任务</h3><p>PDF · 最大 50 MB · 密钥内存态不落盘</p></div>
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
            <div><h3>抽取流水线</h3><p>{job ? `${job.ref_no} · ${job.file_name}` : "提交后显示真实阶段状态"}</p></div>
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
