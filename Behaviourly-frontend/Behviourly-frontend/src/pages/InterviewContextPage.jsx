import { useLocation, useNavigate } from "react-router-dom";
import "./InterviewContextPage.css";

const PLACEHOLDER_CONTEXT = {
  // TODO: Replace with real data source once backend wiring is in place.
  companyName: "{{company_name}}",
  roleTitle: "{{role_title}}",
  jobDescription: "{{job_description}}",
  companySummary:
    "{{company_summary}}",
  companyValues: ["{{company_value_1}}", "{{company_value_2}}", "{{company_value_3}}"],
  roleResponsibilities: [
    "{{responsibility_1}}",
    "{{responsibility_2}}",
    "{{responsibility_3}}",
  ],
  skillsEmphasized: [
    "{{skill_1}}",
    "{{skill_2}}",
    "{{skill_3}}",
    "{{skill_4}}",
  ],
  tailoredTips: ["{{tip_1}}", "{{tip_2}}", "{{tip_3}}"],
  likelyInterviewFocus: ["{{focus_1}}", "{{focus_2}}", "{{focus_3}}"],
};

function SectionList({ title, items }) {
  return (
    <section className="interview-context-section">
      <h3>{title}</h3>
      <ul>
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </section>
  );
}

export default function InterviewContextPage() {
  const navigate = useNavigate();
  const { state } = useLocation();

  const companyName = state?.company || PLACEHOLDER_CONTEXT.companyName;
  const roleTitle = state?.role || PLACEHOLDER_CONTEXT.roleTitle;

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
          <h2>{companyName}</h2>
        </div>
        <div>
          <span className="interview-context-overline">Position</span>
          <h2>{roleTitle}</h2>
        </div>
      </section>

      <section className="interview-context-card">
        <h3>Job Description</h3>
        <p>{PLACEHOLDER_CONTEXT.jobDescription}</p>
      </section>

      <section className="interview-context-card">
        <h3>Company Summary</h3>
        <p>{PLACEHOLDER_CONTEXT.companySummary}</p>
      </section>

      <div className="interview-context-grid">
        <SectionList title="Company Values" items={PLACEHOLDER_CONTEXT.companyValues} />
        <SectionList
          title="Role Responsibilities"
          items={PLACEHOLDER_CONTEXT.roleResponsibilities}
        />
        <SectionList title="Skills Emphasized" items={PLACEHOLDER_CONTEXT.skillsEmphasized} />
        <SectionList title="Tailored Tips" items={PLACEHOLDER_CONTEXT.tailoredTips} />
        <SectionList
          title="Likely Interview Focus"
          items={PLACEHOLDER_CONTEXT.likelyInterviewFocus}
        />
      </div>

      <div className="interview-context-actions">
        <button type="button" onClick={() => navigate("/home")}>Back to dashboard</button>
        <button
          type="button"
          className="interview-context-primary"
          onClick={() => navigate("/camera", { state: { company: companyName, role: roleTitle } })}
        >
          Start Practice Interview
        </button>
      </div>
    </div>
  );
}
