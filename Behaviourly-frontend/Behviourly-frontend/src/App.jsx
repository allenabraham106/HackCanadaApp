import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Auth0Provider } from "@auth0/auth0-react";
import SiteLayout from "./components/SiteLayout";
import InfoPage from "./pages/InfoPage";
import HomePage from "./pages/HomePage";
import CameraPage from "./pages/CameraPage";
import CameraSummaryPage from "./pages/CameraSummaryPage";
import ProfilePage from "./pages/ProfilePage";
import InterviewContextPage from "./pages/InterviewContextPage";
import "./App.css";
import Interview from './Interveiw'

function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<SiteLayout />}>
        <Route index element={<InfoPage />} />
        <Route path="home" element={<HomePage />} />
        <Route path="interview-context" element={<InterviewContextPage />} />
        <Route path="camera" element={<CameraPage />} />
        <Route path="camera/summary" element={<CameraSummaryPage />} />
        <Route path="profile" element={<ProfilePage />} />
        <Route path="interview" element={<Interview />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

const domain = import.meta.env.VITE_AUTH0_DOMAIN;
const clientId = import.meta.env.VITE_AUTH0_CLIENT_ID;

if (!domain || !clientId) {
  console.warn(
    "Auth0: set VITE_AUTH0_DOMAIN and VITE_AUTH0_CLIENT_ID in .env for login to work"
  );
}

function App() {
  return (
    <Auth0Provider
      domain={domain || "your-tenant.auth0.com"}
      clientId={clientId || "your-client-id"}
      authorizationParams={{
        redirect_uri: window.location.origin,
      }}
    >
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </Auth0Provider>
  );
}


export default App;
