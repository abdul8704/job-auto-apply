export interface Bullet { id: string; text: string }
export interface Link { label: string; url: string }
export interface Experience { id: string; company: string; title: string; location: string; start: string; end: string; bullets: Bullet[] }
export interface Project { id: string; name: string; description: string; tech: string[]; url: string; featured: boolean; bullets: Bullet[] }
export interface SkillGroup { category: string; items: string[] }
export interface Profile {
  contact: { name: string; email: string; phone: string; location: string; links: Link[] };
  summary: string;
  education: unknown[];
  experience: Experience[];
  projects: Project[];
  skills: SkillGroup[];
  certifications: string[];
  achievements: string[];
  answers?: Record<string, string>;
}
export interface User { id: string; email: string; is_admin: boolean }
export interface DocumentOut { id: string; filename: string; kind: string; status: string; error: string | null; parsed_profile: Profile | null }
export interface ImportedRepo { name: string; url: string; stars: number; languages: string[]; featured: boolean; project: Project }
export interface GitHubImport {
  id: string; username: string; status: string; error: string | null;
  result: { repos: ImportedRepo[]; languages: string[]; domains: string[]; warnings: string[] } | null;
}
export interface JobPosting {
  title: string; company: string; location: string; summary: string;
  responsibilities: string[]; required_skills: string[]; preferred_skills: string[]; keywords: string[];
}
export interface Job {
  id: string; url: string | null; status: string; title: string | null; company: string | null;
  company_domain: string | null; parsed: JobPosting | null; contacts_status: string;
  contacts_warnings: string[] | null; error: string | null; created_at: string;
}
export interface Contact { id: string; full_name: string; position: string; email: string | null; email_status: string; category: string; source: string }
export interface Kit {
  id: string; job_id: string; status: string; error: string | null; resume_id: string | null;
  has_cover_letter_pdf: boolean; warnings: string[] | null; cover_letter: string | null;
  honesty_report: { matched_keywords?: string[]; missing_keywords?: string[]; reverted?: { text: string; reason: string }[]; rejected_skills?: string[] } | null;
}
export interface Resume { id: string; status: string; pages: number | null; error: string | null }
export interface Message { subject: string; body: string; to_email: string | null; kind: string }
