import { C } from "./theme";
import { Viewport } from "./components/Viewport";
import { TopBar } from "./components/TopBar";
import { ToolDock } from "./components/ToolDock";
import { Inspector } from "./components/Inspector";
import { CommandBar } from "./components/CommandBar";
import { GeneratingOverlay } from "./components/Overlays";
import { Library } from "./components/Library";

// "Command Deck" layout: the 3D viewport is full-bleed (the hero); everything else floats over it.
export function App() {
  return (
    <div style={{ position: "fixed", inset: 0, background: C.bg, color: C.text, overflow: "hidden", fontFamily: "Inter, sans-serif" }}>
      <Viewport />
      {/* cinematic vignette over the canvas */}
      <div style={{ position: "absolute", inset: 0, pointerEvents: "none", background: "radial-gradient(130% 90% at 50% 30%, transparent 55%, rgba(0,0,0,.55) 100%)" }} />

      <TopBar />
      <ToolDock />
      <Inspector />
      <CommandBar />
      <GeneratingOverlay />
      <Library />
    </div>
  );
}
