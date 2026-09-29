import { FlaskConical } from "lucide-react";
import type { PolymerEntity } from "../types";
import { repeatUnitFor } from "../utils/format";

export function PolymerStructure({ entity, compact = false }: { entity: PolymerEntity; compact?: boolean }) {
  const repeatUnit = repeatUnitFor(entity);
  if (!repeatUnit.definition) {
    return <div className={`structure-placeholder ${compact ? "compact" : ""}`}><FlaskConical size={compact ? 18 : 24} /><div className="structure-copy"><strong>结构式待补充</strong><span>缺少可验证的重复单元连接信息</span></div></div>;
  }
  return <div className={`repeat-unit-structure ${compact ? "compact" : ""}`}><div className="repeat-bracket">[</div><div className="repeat-backbone">{repeatUnit.definition.backbone}</div><div className="repeat-bracket right">]<sub>n</sub></div>{repeatUnit.definition.note && <small>{repeatUnit.definition.note}</small>}</div>;
}
