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
          Wind on PolyU + Block Z · dark-brown LandsD buildings · measured LAZ crowns.
          Drag to orbit · scroll to zoom.
        </p>
      </header>
      <main className="app-main">
        <WindFlowViewer />
      </main>
    </div>
  );
}
