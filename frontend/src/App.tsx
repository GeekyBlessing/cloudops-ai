/**
 * Top-level app shell: header + client-side routing between the incident
 * list and incident detail pages.
 */

import { BrowserRouter, Route, Routes } from "react-router-dom";
import { ApiKeyControl } from "./components/ApiKeyControl";
import { IncidentDetailPage } from "./pages/IncidentDetailPage";
import { IncidentListPage } from "./pages/IncidentListPage";

export default function App() {
  return (
    <BrowserRouter>
      <div className="app-shell">
        <header className="app-header">
          <div className="app-header__row">
            <div>
              <h1>CloudOps AI</h1>
              <p className="app-subtitle">Agentic incident response dashboard</p>
            </div>
            <ApiKeyControl />
          </div>
        </header>
        <main className="app-main">
          <Routes>
            <Route path="/" element={<IncidentListPage />} />
            <Route path="/incidents/:incidentId" element={<IncidentDetailPage />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
