import { useUser } from "../UserContext";
import "./ProfilePage.css";

export default function ProfilePage() {
  const { user, loading } = useUser();

  if (loading) {
    return (
      <div className="profile-page">
        <div className="profile-card">
          <p>Loading...</p>
        </div>
      </div>
    );
  }

  if (!user) {
    return (
      <div className="profile-page">
        <div className="profile-card">
          <p className="profile-guest">You're not signed in.</p>
          <button className="profile-logout" onClick={() => window.location.href = "http://localhost:8000/login"}>
            Sign in
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="profile-page">
      <div className="profile-card">
        <div className="profile-avatar">
          {user.picture ? (
            <img src={user.picture} alt="" />
          ) : (
            <span>{user.name?.charAt(0) || "?"}</span>
          )}
        </div>
        <h1 className="profile-name">{user.name || "User"}</h1>
        {user.email && (
          <p className="profile-email">{user.email}</p>
        )}
        <button className="profile-logout" onClick={() => window.location.href = "http://localhost:8000/logout"}>
          Sign out
        </button>
      </div>
    </div>
  );
}