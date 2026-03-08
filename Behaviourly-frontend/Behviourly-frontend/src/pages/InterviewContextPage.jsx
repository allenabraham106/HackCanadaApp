import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import "./InterviewContextPage.css";

const FALLBACK_REQUEST_INPUTS = {
  company: "Unknown Company",
  role: "Unknown Role",
};

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

function SectionList({ title, items = [] }) {
  return (
    <section className="interview-context-section">
      <h3>{title}</h3>
      <ul>
        {items.map((item, index) => (
          <li key={`${title}-${index}-${item}`}>{item}</li>
        ))}
      </ul>
    </section>
  );
}

export default function InterviewContextPage() {
  const navigate = useNavigate();
  const { state } = useLocation();

  const company = state?.company || FALLBACK_REQUEST_INPUTS.company;
  const role = state?.role || FALLBACK_REQUEST_INPUTS.role;

  const [briefing, setBriefing] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let isMounted = true;

    const fetchInterviewContext = async () => {
      setLoading(true);
      setError("");

      try {
        const response = await fetch(`${API_BASE_URL}/interview_context`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            company_name: company,
            role_title: role,
            job_description: null,
          }),
        });

        if (!response.ok) {
          throw new Error(`Failed to fetch interview context (${response.status})`);
        }

        const data = await response.json();

        if (isMounted) {
          setBriefing(data);
        }
      } catch (fetchError) {
        if (isMounted) {
          setError(fetchError.message || "Unable to load interview context.");
        }
      } finally {
        if (isMounted) {
          setLoading(false);
        }
      }
    };

    fetchInterviewContext();

    return () => {
      isMounted = false;
    };
  }, [company, role]);

  const generatedJobDescription =
    briefing?.job_description ||
    (briefing?.role?.responsibilities?.length
      ? `This ${briefing.role.title || role} role at ${briefing.company?.name || company} emphasizes: ${briefing.role.responsibilities.join(
          ", "
        )}.`
      : "Job description is being generated from your selected role.");

  return (
    <div className="interview-context-page">
      <header className="interview-context-hero">
        <p className="interview-context-label">Before you begin</p>
        <h1>Interview Briefing</h1>
        <p>
          Review the context below to align your responses with the role before you begin your mock interview.
        </p>
      </header>

      <section className="interview-context-card interview-context-overview">
        <div>
          <span className="interview-context-overline">Company</span>
          <h2>{briefing?.company?.name || company}</h2>
        </div>
        <div>
          <span className="interview-context-overline">Position</span>
          <h2>{briefing?.role?.title || role}</h2>
        </div>
      </section>

      {loading && (
        <section className="interview-context-card">
          <h3>Loading Briefing</h3>
          <p>Generating tailored interview context...</p>
        </section>
      )}

      {error && (
        <section className="interview-context-card">
          <h3>Unable to Load Briefing</h3>
          <p>{error}</p>
        </section>
      )}

      {!loading && !error && briefing && (
        <>
          <section className="interview-context-card">
            <h3>Job Description</h3>
            <p>{generatedJobDescription}</p>
          </section>

          <section className="interview-context-card">
            <h3>Company Summary</h3>
            <p>{briefing.company?.summary}</p>
          </section>

          <div className="interview-context-grid">
            <SectionList title="Company Values" items={briefing.company?.values} />
            <SectionList
              title="Role Responsibilities"
              items={briefing.role?.responsibilities}
            />
            <SectionList title="Skills Emphasized" items={briefing.skills_emphasized} />
            <SectionList title="Tailored Tips" items={briefing.tailored_tips} />
            <SectionList
              title="Likely Interview Focus"
              items={briefing.likely_interview_focus}
            />
          </div>

          <section className="interview-context-card">
            <h3>Confidence Note</h3>
            <p>{briefing.confidence_note}</p>
          </section>
        </>
      )}

      <div className="interview-context-actions">
        <button type="button" onClick={() => navigate("/home")}>
          Back to dashboard
        </button>
        <button
          type="button"
          className="interview-context-primary"
          onClick={() => navigate("/interview", { state: { company, role } })}
        >
          Start Practice Interview
        </button>
      </div>
    </div>
  );
}
