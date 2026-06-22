import { C, mono } from "../theme";
import { useStudio } from "../store";
import { Icon, ICONS } from "./ui";
import { ResultCard } from "./ResultCard";
import { Settings } from "./Settings";

export function RightPanel() {
  const { genStatus, retry } = useStudio();
  return (
    <div style={{ width: 344, flex: "0 0 344px", borderLeft: `1px solid ${C.border}`, background: C.panel, overflowY: "auto", padding: "18px 16px", display: "flex", flexDirection: "column", gap: 16 }}>
      {genStatus === "done" && <ResultCard />}
      {retry && genStatus === "running" && (
        <div style={{ background: "rgba(251,191,36,.08)", border: "1px solid rgba(251,191,36,.4)", borderRadius: 12, padding: "11px 12px", display: "flex", gap: 10, alignItems: "flex-start" }}>
          <span style={{ color: C.warn, flex: "0 0 15px", marginTop: 1 }}><Icon d={ICONS.retry} size={15} sw={1.8} /></span>
          <div style={{ fontSize: 11, lineHeight: 1.55, color: C.warn, fontFamily: mono }}>{retry}</div>
        </div>
      )}
      <Settings />
    </div>
  );
}
