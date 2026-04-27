import { Routes, Route } from "react-router-dom";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import Chat from "./pages/Chat";
import Failures from "./pages/Failures";
import Wiki from "./pages/Wiki";
import Settings from "./pages/Settings";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/chat" element={<Chat />} />
        <Route path="/failures" element={<Failures />} />
        <Route path="/wiki" element={<Wiki />} />
        <Route path="/settings" element={<Settings />} />
      </Route>
    </Routes>
  );
}
