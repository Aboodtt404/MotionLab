import { C } from "./theme";
import { Rail } from "./components/Rail";
import { Stage } from "./components/Stage";
import { RightPanel } from "./components/RightPanel";

export function App() {
  return (
    <div style={{ height: "100vh", display: "flex", background: C.bg, color: C.text, overflow: "hidden" }}>
      <Rail />
      <Stage />
      <RightPanel />
    </div>
  );
}
