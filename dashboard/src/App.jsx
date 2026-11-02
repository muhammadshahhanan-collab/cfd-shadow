import WindFlowViewer from "./components/WindFlowViewer";

export default function App() {
  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-brand">
          <p className="app-kicker">CFD Shadow</p>
          <h1>Campus wind</h1>
        </div>
        <p className="app-lede">
          Wind + direct-sun tree/building shadows (time scrub) · LandsD massing · LAZ crowns.
          Drag to orbit · scroll to zoom · scrub HKT time for shade.
        </p>
      </header>
      <main className="app-main">
        <WindFlowViewer />
      </main>
    </div>
  );
}
