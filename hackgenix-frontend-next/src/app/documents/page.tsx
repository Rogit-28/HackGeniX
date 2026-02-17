'use client';

// ============================================================
// Documents Management — Resumes, JDs, Match
// ============================================================

import { useState, useEffect, useRef, useCallback } from 'react';
import { ProtectedRoute } from '@/components/auth/ProtectedRoute';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Separator } from '@/components/ui/separator';
import { Progress } from '@/components/ui/progress';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import {
  listResumes,
  listJobDescriptions,
  getResume,
  uploadResumeStream,
  deleteResume,
  createJDStream,
  uploadJDStream,
  matchResumeToJD,
} from '@/lib/api';
import type {
  Resume,
  JobDescription,
  MatchResult,
  ParsedResume,
  ParsedJobDescription,
  Experience,
  Education,
  Project,
  Research,
} from '@/lib/types';
import {
  Upload,
  Trash2,
  FileText,
  Briefcase,
  RefreshCw,
  Loader2,
  ChevronDown,
  ChevronRight,
  User,
  Mail,
  Phone,
  MapPin,
  Github,
  Linkedin,
  GraduationCap,
  Award,
  BookOpen,
  Code,
  Target,
  Sparkles,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  ArrowRight,
  Globe,
  Building,
  DollarSign,
  Clock,
  Star,
  Zap,
  Shield,
  TrendingUp,
} from 'lucide-react';
import { toast } from 'sonner';

// ============================================================
// Parsed Resume Viewer
// ============================================================

function ResumeViewer({ data }: { data: ParsedResume }) {
  return (
    <div className="space-y-4">
      {/* Contact */}
      {data.contact && (
        <div>
          <h4 className="text-sm font-semibold mb-2 flex items-center gap-1.5">
            <User className="h-3.5 w-3.5" /> Contact
          </h4>
          <div className="grid grid-cols-2 gap-2 text-sm">
            {data.contact.name && (
              <div className="flex items-center gap-1.5">
                <User className="h-3 w-3 text-muted-foreground" />
                {data.contact.name}
              </div>
            )}
            {data.contact.email && (
              <div className="flex items-center gap-1.5">
                <Mail className="h-3 w-3 text-muted-foreground" />
                {data.contact.email}
              </div>
            )}
            {data.contact.phone && (
              <div className="flex items-center gap-1.5">
                <Phone className="h-3 w-3 text-muted-foreground" />
                {data.contact.phone}
              </div>
            )}
            {data.contact.location && (
              <div className="flex items-center gap-1.5">
                <MapPin className="h-3 w-3 text-muted-foreground" />
                {data.contact.location}
              </div>
            )}
            {data.contact.github && (
              <div className="flex items-center gap-1.5">
                <Github className="h-3 w-3 text-muted-foreground" />
                <a href={data.contact.github} target="_blank" rel="noreferrer" className="text-primary hover:underline truncate">
                  {data.contact.github.replace(/^https?:\/\/(www\.)?/, '')}
                </a>
              </div>
            )}
            {data.contact.linkedin && (
              <div className="flex items-center gap-1.5">
                <Linkedin className="h-3 w-3 text-muted-foreground" />
                <a href={data.contact.linkedin} target="_blank" rel="noreferrer" className="text-primary hover:underline truncate">
                  {data.contact.linkedin.replace(/^https?:\/\/(www\.)?/, '')}
                </a>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Summary */}
      {data.summary && (
        <div>
          <h4 className="text-sm font-semibold mb-1">Summary</h4>
          <p className="text-sm text-muted-foreground">{data.summary}</p>
        </div>
      )}

      {/* Skills */}
      {data.skills && data.skills.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold mb-2 flex items-center gap-1.5">
            <Code className="h-3.5 w-3.5" /> Skills ({data.skills.length})
          </h4>
          <div className="flex flex-wrap gap-1.5">
            {data.skills.map((skill, i) => (
              <Badge key={i} variant="secondary" className="text-xs">
                {skill}
              </Badge>
            ))}
          </div>
        </div>
      )}

      {/* Experience */}
      {data.experience && data.experience.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold mb-2 flex items-center gap-1.5">
            <Briefcase className="h-3.5 w-3.5" /> Experience ({data.experience.length})
          </h4>
          <div className="space-y-3">
            {data.experience.map((exp: Experience, i: number) => (
              <div key={i} className="border rounded-md p-3 text-sm">
                <div className="flex justify-between items-start">
                  <div>
                    <p className="font-medium">{exp.title || 'Untitled Role'}</p>
                    <p className="text-muted-foreground">{exp.company}{exp.location ? ` \u2022 ${exp.location}` : ''}</p>
                  </div>
                  {(exp.start_date || exp.end_date) && (
                    <span className="text-xs text-muted-foreground whitespace-nowrap ml-2">
                      {exp.start_date || '?'} \u2013 {exp.end_date || 'Present'}
                    </span>
                  )}
                </div>
                {exp.description && <p className="text-muted-foreground mt-1">{exp.description}</p>}
                {exp.highlights && exp.highlights.length > 0 && (
                  <ul className="mt-1.5 space-y-0.5">
                    {exp.highlights.map((h, j) => (
                      <li key={j} className="flex items-start gap-1.5 text-xs">
                        <CheckCircle2 className="h-3 w-3 text-success mt-0.5 shrink-0" />
                        {h}
                      </li>
                    ))}
                  </ul>
                )}
                {exp.impact && exp.impact.length > 0 && (
                  <div className="mt-1.5">
                    <span className="text-xs font-medium text-success">Impact: </span>
                    {exp.impact.map((imp, j) => (
                      <span key={j} className="text-xs text-muted-foreground">{j > 0 ? ' \u2022 ' : ''}{imp}</span>
                    ))}
                  </div>
                )}
                {exp.skills && exp.skills.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-1.5">
                    {exp.skills.map((s, j) => (
                      <Badge key={j} variant="outline" className="text-[10px] px-1.5 py-0">
                        {s}
                      </Badge>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Education */}
      {data.education && data.education.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold mb-2 flex items-center gap-1.5">
            <GraduationCap className="h-3.5 w-3.5" /> Education ({data.education.length})
          </h4>
          <div className="space-y-2">
            {data.education.map((edu: Education, i: number) => (
              <div key={i} className="border rounded-md p-3 text-sm">
                <p className="font-medium">{edu.degree}{edu.field ? ` in ${edu.field}` : ''}</p>
                <p className="text-muted-foreground">{edu.institution}</p>
                <div className="flex gap-3 text-xs text-muted-foreground mt-0.5">
                  {(edu.start_date || edu.end_date) && (
                    <span>{edu.start_date || '?'} \u2013 {edu.end_date || 'Present'}</span>
                  )}
                  {edu.gpa != null && <span>GPA: {edu.gpa}</span>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Projects */}
      {data.projects && data.projects.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold mb-2 flex items-center gap-1.5">
            <Target className="h-3.5 w-3.5" /> Projects ({data.projects.length})
          </h4>
          <div className="space-y-2">
            {data.projects.map((proj: Project, i: number) => (
              <div key={i} className="border rounded-md p-3 text-sm">
                <div className="flex items-start justify-between">
                  <p className="font-medium">{proj.name || 'Untitled'}</p>
                  {proj.url && (
                    <a href={proj.url} target="_blank" rel="noreferrer" className="text-xs text-primary hover:underline">
                      link
                    </a>
                  )}
                </div>
                {proj.description && <p className="text-muted-foreground text-xs mt-0.5">{proj.description}</p>}
                {proj.tech_stack && proj.tech_stack.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-1.5">
                    {proj.tech_stack.map((t, j) => (
                      <Badge key={j} variant="secondary" className="text-[10px] px-1.5 py-0">{t}</Badge>
                    ))}
                  </div>
                )}
                {proj.highlights && proj.highlights.length > 0 && (
                  <ul className="mt-1.5 space-y-0.5">
                    {proj.highlights.map((h, j) => (
                      <li key={j} className="text-xs text-muted-foreground flex items-start gap-1">
                        <span className="text-success">\u2022</span> {h}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Research */}
      {data.research && data.research.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold mb-2 flex items-center gap-1.5">
            <BookOpen className="h-3.5 w-3.5" /> Research ({data.research.length})
          </h4>
          <div className="space-y-2">
            {data.research.map((r: Research, i: number) => (
              <div key={i} className="border rounded-md p-3 text-sm">
                <p className="font-medium">{r.title || 'Untitled'}</p>
                {r.venue && <p className="text-xs text-muted-foreground">{r.venue}</p>}
                {r.status && <Badge variant="outline" className="text-[10px] mt-1">{r.status}</Badge>}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Certifications */}
      {data.certifications && data.certifications.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold mb-2 flex items-center gap-1.5">
            <Award className="h-3.5 w-3.5" /> Certifications
          </h4>
          <ul className="space-y-0.5">
            {data.certifications.map((c, i) => (
              <li key={i} className="text-sm flex items-center gap-1.5">
                <Award className="h-3 w-3 text-warning" /> {c}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Soft Skills */}
      {data.soft_skills && data.soft_skills.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold mb-2">Soft Skills</h4>
          <div className="flex flex-wrap gap-1.5">
            {data.soft_skills.map((s, i) => (
              <Badge key={i} variant="outline" className="text-xs">{s}</Badge>
            ))}
          </div>
        </div>
      )}

      {/* Areas of Interest */}
      {data.areas_of_interest && data.areas_of_interest.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold mb-2">Areas of Interest</h4>
          <div className="flex flex-wrap gap-1.5">
            {data.areas_of_interest.map((a, i) => (
              <Badge key={i} variant="secondary" className="text-xs">{a}</Badge>
            ))}
          </div>
        </div>
      )}

      {/* Languages */}
      {data.languages && data.languages.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold mb-2 flex items-center gap-1.5">
            <Globe className="h-3.5 w-3.5" /> Languages
          </h4>
          <div className="flex flex-wrap gap-1.5">
            {data.languages.map((l, i) => (
              <Badge key={i} variant="outline" className="text-xs">{l}</Badge>
            ))}
          </div>
        </div>
      )}

      {/* Extra Sections */}
      {data.extra_sections && Object.keys(data.extra_sections).length > 0 && (
        <div>
          <h4 className="text-sm font-semibold mb-2">Additional Sections</h4>
          {Object.entries(data.extra_sections).map(([key, value]) => (
            <div key={key} className="mb-2">
              <p className="text-xs font-medium capitalize">{key.replace(/_/g, ' ')}</p>
              <p className="text-xs text-muted-foreground">{typeof value === 'string' ? value : JSON.stringify(value)}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ============================================================
// Parsed JD Viewer
// ============================================================

function JDViewer({ data }: { data: ParsedJobDescription }) {
  return (
    <div className="space-y-4">
      {/* Header Info */}
      <div className="grid grid-cols-2 gap-2 text-sm">
        {data.title && (
          <div className="flex items-center gap-1.5">
            <Briefcase className="h-3 w-3 text-muted-foreground" /> {data.title}
          </div>
        )}
        {data.company && (
          <div className="flex items-center gap-1.5">
            <Building className="h-3 w-3 text-muted-foreground" /> {data.company}
          </div>
        )}
        {data.location && (
          <div className="flex items-center gap-1.5">
            <MapPin className="h-3 w-3 text-muted-foreground" /> {data.location}
          </div>
        )}
        {data.employment_type && (
          <div className="flex items-center gap-1.5">
            <Clock className="h-3 w-3 text-muted-foreground" /> {data.employment_type}
          </div>
        )}
        {data.experience_level && (
          <div className="flex items-center gap-1.5">
            <TrendingUp className="h-3 w-3 text-muted-foreground" /> {data.experience_level}
          </div>
        )}
        {(data.experience_years_min != null || data.experience_years_max != null) && (
          <div className="flex items-center gap-1.5 text-muted-foreground">
            <Clock className="h-3 w-3" />
            {data.experience_years_min ?? 0}\u2013{data.experience_years_max ?? '?'} years
          </div>
        )}
        {(data.salary_min != null || data.salary_max != null) && (
          <div className="flex items-center gap-1.5">
            <DollarSign className="h-3 w-3 text-muted-foreground" />
            {data.salary_currency || '$'}{data.salary_min?.toLocaleString()}{data.salary_max ? `\u2013${data.salary_max.toLocaleString()}` : '+'}
          </div>
        )}
      </div>

      {/* Required Skills */}
      {data.required_skills && data.required_skills.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold mb-2">Required Skills</h4>
          <div className="flex flex-wrap gap-1.5">
            {data.required_skills.map((s, i) => (
              <Badge key={i} variant="default" className="text-xs">{s}</Badge>
            ))}
          </div>
        </div>
      )}

      {/* Preferred Skills */}
      {data.preferred_skills && data.preferred_skills.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold mb-2">Preferred Skills</h4>
          <div className="flex flex-wrap gap-1.5">
            {data.preferred_skills.map((s, i) => (
              <Badge key={i} variant="secondary" className="text-xs">{s}</Badge>
            ))}
          </div>
        </div>
      )}

      {/* Responsibilities */}
      {data.responsibilities && data.responsibilities.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold mb-2">Responsibilities</h4>
          <ul className="space-y-1">
            {data.responsibilities.map((r, i) => (
              <li key={i} className="text-sm flex items-start gap-1.5">
                <ArrowRight className="h-3 w-3 text-primary mt-0.5 shrink-0" /> {r}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Qualifications */}
      {data.qualifications && data.qualifications.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold mb-2">Qualifications</h4>
          <ul className="space-y-1">
            {data.qualifications.map((q, i) => (
              <li key={i} className="text-sm flex items-start gap-1.5">
                <CheckCircle2 className="h-3 w-3 text-success mt-0.5 shrink-0" /> {q}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Benefits */}
      {data.benefits && data.benefits.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold mb-2">Benefits</h4>
          <ul className="space-y-1">
            {data.benefits.map((b, i) => (
              <li key={i} className="text-sm flex items-start gap-1.5">
                <Star className="h-3 w-3 text-warning mt-0.5 shrink-0" /> {b}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// ============================================================
// Match Results Viewer
// ============================================================

function MatchResultsViewer({ result }: { result: MatchResult }) {
  const scoreColor = (score: number) =>
    score >= 70 ? 'text-success' : score >= 40 ? 'text-warning' : 'text-destructive';

  return (
    <div className="space-y-4">
      {/* Score Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="border rounded-lg p-3 text-center">
          <p className="text-xs text-muted-foreground">Overall</p>
          <p className={`text-2xl font-bold ${scoreColor(result.overall_score)}`}>
            {result.overall_score.toFixed(0)}
          </p>
        </div>
        <div className="border rounded-lg p-3 text-center">
          <p className="text-xs text-muted-foreground">Skill Match</p>
          <p className={`text-2xl font-bold ${scoreColor(result.skill_match_score)}`}>
            {result.skill_match_score.toFixed(0)}
          </p>
        </div>
        <div className="border rounded-lg p-3 text-center">
          <p className="text-xs text-muted-foreground">Experience</p>
          <p className={`text-2xl font-bold ${scoreColor(result.experience_match_score)}`}>
            {result.experience_match_score.toFixed(0)}
          </p>
        </div>
        <div className="border rounded-lg p-3 text-center">
          <p className="text-xs text-muted-foreground">Semantic</p>
          <p className={`text-2xl font-bold ${scoreColor(result.semantic_similarity_score)}`}>
            {result.semantic_similarity_score.toFixed(0)}
          </p>
        </div>
      </div>

      {/* LLM Score + Reasoning */}
      {result.llm_enabled && result.llm_fit_score != null && (
        <div className="border rounded-lg p-3">
          <div className="flex items-center justify-between mb-2">
            <h4 className="text-sm font-semibold flex items-center gap-1.5">
              <Sparkles className="h-3.5 w-3.5" /> LLM Fit Score
            </h4>
            <span className={`text-xl font-bold ${scoreColor(result.llm_fit_score)}`}>
              {result.llm_fit_score.toFixed(0)}
            </span>
          </div>
          {result.llm_reasoning && (
            <p className="text-sm text-muted-foreground">{result.llm_reasoning}</p>
          )}
        </div>
      )}

      {/* Experience Quality */}
      {result.experience_quality && (
        <div>
          <h4 className="text-sm font-semibold mb-1">Experience Quality</h4>
          <Badge variant="outline">{result.experience_quality}</Badge>
          {result.experience_quality_reasoning && (
            <p className="text-xs text-muted-foreground mt-1">{result.experience_quality_reasoning}</p>
          )}
        </div>
      )}

      {/* Matched / Missing Skills */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {result.matched_skills.length > 0 && (
          <div>
            <h4 className="text-sm font-semibold mb-2 flex items-center gap-1.5">
              <CheckCircle2 className="h-3.5 w-3.5 text-success" /> Matched Skills ({result.matched_skills.length})
            </h4>
            <div className="flex flex-wrap gap-1">
              {result.matched_skills.map((s, i) => (
                <Badge key={i} variant="secondary" className="text-xs bg-success/10 text-success border-success/30">{s}</Badge>
              ))}
            </div>
          </div>
        )}
        {result.missing_skills.length > 0 && (
          <div>
            <h4 className="text-sm font-semibold mb-2 flex items-center gap-1.5">
              <XCircle className="h-3.5 w-3.5 text-destructive" /> Missing Skills ({result.missing_skills.length})
            </h4>
            <div className="flex flex-wrap gap-1">
              {result.missing_skills.map((s, i) => (
                <Badge key={i} variant="secondary" className="text-xs bg-destructive/10 text-destructive border-destructive/30">{s}</Badge>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Transferable Skills */}
      {result.transferable_skills && result.transferable_skills.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold mb-2 flex items-center gap-1.5">
            <Zap className="h-3.5 w-3.5 text-info" /> Transferable Skills
          </h4>
          <div className="space-y-1">
            {result.transferable_skills.map((ts, i) => (
              <div key={i} className="text-sm">
                <span className="font-medium">{ts.skill_name}</span>
                <span className="text-muted-foreground"> \u2014 {ts.description}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Strengths */}
      {result.strengths && result.strengths.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold mb-2 flex items-center gap-1.5">
            <TrendingUp className="h-3.5 w-3.5 text-success" /> Strengths
          </h4>
          <ul className="space-y-0.5">
            {result.strengths.map((s, i) => (
              <li key={i} className="text-sm flex items-start gap-1.5">
                <CheckCircle2 className="h-3 w-3 text-success mt-0.5 shrink-0" /> {s}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Risk Flags */}
      {result.risk_flags && result.risk_flags.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold mb-2 flex items-center gap-1.5">
            <Shield className="h-3.5 w-3.5 text-warning" /> Risk Flags
          </h4>
          <ul className="space-y-0.5">
            {result.risk_flags.map((r, i) => (
              <li key={i} className="text-sm flex items-start gap-1.5">
                <AlertTriangle className="h-3 w-3 text-warning mt-0.5 shrink-0" /> {r}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Recommendations */}
      {result.recommendations.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold mb-2">Recommendations</h4>
          <ul className="space-y-0.5">
            {result.recommendations.map((r, i) => (
              <li key={i} className="text-sm flex items-start gap-1.5">
                <ArrowRight className="h-3 w-3 text-primary mt-0.5 shrink-0" /> {r}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// ============================================================
// Main Documents Content
// ============================================================

function DocumentsContent() {
  // --- State: Resumes ---
  const [resumes, setResumes] = useState<Resume[]>([]);
  const [resumesLoading, setResumesLoading] = useState(true);
  const [expandedResume, setExpandedResume] = useState<string | null>(null);
  const [resumeDetails, setResumeDetails] = useState<Record<string, Resume>>({});
  const [uploading, setUploading] = useState(false);
  const [uploadStream, setUploadStream] = useState('');
  const resumeFileRef = useRef<HTMLInputElement>(null);

  // --- State: JDs ---
  const [jds, setJds] = useState<JobDescription[]>([]);
  const [jdsLoading, setJdsLoading] = useState(true);
  const [expandedJD, setExpandedJD] = useState<string | null>(null);
  const [jdUploading, setJdUploading] = useState(false);
  const [jdUploadStream, setJdUploadStream] = useState('');
  const [jdMode, setJdMode] = useState<'upload' | 'paste'>('upload');
  const [jdTitle, setJdTitle] = useState('');
  const [jdCompany, setJdCompany] = useState('');
  const [jdText, setJdText] = useState('');
  const jdFileRef = useRef<HTMLInputElement>(null);

  // --- State: Match ---
  const [matchResumeId, setMatchResumeId] = useState('');
  const [matchJdId, setMatchJdId] = useState('');
  const [matching, setMatching] = useState(false);
  const [matchResult, setMatchResult] = useState<MatchResult | null>(null);
  const [matchStream, setMatchStream] = useState('');

  // --- Load Lists ---
  const loadResumes = useCallback(async () => {
    setResumesLoading(true);
    try {
      const data = await listResumes();
      setResumes(data);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to load resumes');
    } finally {
      setResumesLoading(false);
    }
  }, []);

  const loadJDs = useCallback(async () => {
    setJdsLoading(true);
    try {
      const data = await listJobDescriptions();
      setJds(data);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to load job descriptions');
    } finally {
      setJdsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadResumes();
    loadJDs();
  }, [loadResumes, loadJDs]);

  // --- Resume expand: fetch full details ---
  const toggleResumeExpand = async (id: string) => {
    if (expandedResume === id) {
      setExpandedResume(null);
      return;
    }
    setExpandedResume(id);
    if (!resumeDetails[id]) {
      try {
        const full = await getResume(id);
        setResumeDetails((prev) => ({ ...prev, [id]: full }));
      } catch (err) {
        toast.error(err instanceof Error ? err.message : 'Failed to load resume details');
      }
    }
  };

  // --- Upload Resume ---
  const handleResumeUpload = async () => {
    const file = resumeFileRef.current?.files?.[0];
    if (!file) return;
    setUploading(true);
    setUploadStream('');
    try {
      for await (const event of uploadResumeStream(file)) {
        setUploadStream((prev) => prev + event.data + '\n');
      }
      toast.success('Resume uploaded successfully');
      if (resumeFileRef.current) resumeFileRef.current.value = '';
      loadResumes();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Upload failed');
    } finally {
      setUploading(false);
    }
  };

  // --- Delete Resume ---
  const handleDeleteResume = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm('Delete this resume?')) return;
    try {
      await deleteResume(id);
      toast.success('Resume deleted');
      setResumes((prev) => prev.filter((r) => r.id !== id));
      if (expandedResume === id) setExpandedResume(null);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Delete failed');
    }
  };

  // --- Upload / Create JD ---
  const handleJDUpload = async () => {
    setJdUploading(true);
    setJdUploadStream('');
    try {
      if (jdMode === 'upload') {
        const file = jdFileRef.current?.files?.[0];
        if (!file) return;
        for await (const event of uploadJDStream(file)) {
          setJdUploadStream((prev) => prev + event.data + '\n');
        }
        if (jdFileRef.current) jdFileRef.current.value = '';
      } else {
        if (!jdText.trim()) {
          toast.error('Please enter job description text');
          return;
        }
        for await (const event of createJDStream(jdText, jdTitle || undefined, jdCompany || undefined)) {
          setJdUploadStream((prev) => prev + event.data + '\n');
        }
        setJdTitle('');
        setJdCompany('');
        setJdText('');
      }
      toast.success('Job description created successfully');
      loadJDs();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'JD creation failed');
    } finally {
      setJdUploading(false);
    }
  };

  // --- Match ---
  const handleMatch = async () => {
    if (!matchResumeId || !matchJdId) {
      toast.error('Select both a resume and a job description');
      return;
    }
    setMatching(true);
    setMatchResult(null);
    setMatchStream('');
    try {
      for await (const event of matchResumeToJD(matchResumeId, matchJdId)) {
        setMatchStream((prev) => prev + event.data + '\n');
        // Parse final result event
        if (event.event === 'result' || event.event === 'match_complete') {
          try {
            const parsed = JSON.parse(event.data);
            if (parsed.match_result) {
              setMatchResult(parsed.match_result);
            } else if (parsed.overall_score != null) {
              setMatchResult(parsed);
            }
          } catch {
            // not json, ignore
          }
        }
        // Also try parsing from data without event type
        if (!event.event) {
          try {
            const parsed = JSON.parse(event.data);
            if (parsed.match_result) {
              setMatchResult(parsed.match_result);
            }
          } catch {
            // not json, ignore
          }
        }
      }
      if (!matchResult) {
        // Try to extract from the full stream
        toast.success('Match complete');
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Match failed');
    } finally {
      setMatching(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Documents</h1>
          <p className="text-muted-foreground">
            Manage resumes, job descriptions, and run match analysis
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => { loadResumes(); loadJDs(); }} disabled={resumesLoading || jdsLoading}>
            <RefreshCw className={`mr-2 h-4 w-4 ${(resumesLoading || jdsLoading) ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
        </div>
      </div>

      {/* Two-Column Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* ======== LEFT: RESUMES ======== */}
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <FileText className="h-5 w-5" /> Resumes
              </CardTitle>
              <CardDescription>Upload and manage candidate resumes</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* Upload */}
              <div className="flex gap-2">
                <Input
                  ref={resumeFileRef}
                  type="file"
                  accept=".pdf,.docx,.doc,.txt"
                  disabled={uploading}
                  className="flex-1"
                />
                <Button onClick={handleResumeUpload} disabled={uploading}>
                  {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
                </Button>
              </div>
              {uploadStream && (
                <pre className="text-xs bg-muted p-2 rounded-md max-h-32 overflow-auto whitespace-pre-wrap">{uploadStream}</pre>
              )}

              <Separator />

              {/* List */}
              {resumesLoading ? (
                <div className="flex justify-center py-8">
                  <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                </div>
              ) : resumes.length === 0 ? (
                <p className="text-sm text-muted-foreground text-center py-4">No resumes uploaded yet</p>
              ) : (
                <div className="space-y-2">
                  {resumes.map((resume) => (
                    <div key={resume.id} className="border rounded-lg">
                      <div
                        className="flex items-center justify-between p-3 cursor-pointer hover:bg-muted/50 transition-colors"
                        onClick={() => toggleResumeExpand(resume.id)}
                      >
                        <div className="flex items-center gap-2 min-w-0">
                          {expandedResume === resume.id ? (
                            <ChevronDown className="h-4 w-4 shrink-0" />
                          ) : (
                            <ChevronRight className="h-4 w-4 shrink-0" />
                          )}
                          <div className="min-w-0">
                            <p className="text-sm font-medium truncate">{resume.filename}</p>
                            <p className="text-xs text-muted-foreground">
                              {resume.candidate_name || 'Unknown'} &middot;{' '}
                              <Badge variant={resume.status === 'parsed' ? 'secondary' : 'outline'} className="text-[10px] px-1 py-0">
                                {resume.status}
                              </Badge>
                            </p>
                          </div>
                        </div>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={(e) => handleDeleteResume(resume.id, e)}
                          className="text-destructive hover:text-destructive shrink-0"
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>

                      {expandedResume === resume.id && (
                        <div className="px-3 pb-3 border-t">
                          {resumeDetails[resume.id]?.parsed_data ? (
                            <div className="pt-3">
                              <ResumeViewer data={resumeDetails[resume.id].parsed_data!} />
                            </div>
                          ) : resumeDetails[resume.id] ? (
                            <p className="text-sm text-muted-foreground py-3">No parsed data available</p>
                          ) : (
                            <div className="flex justify-center py-4">
                              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* ======== RIGHT: JOB DESCRIPTIONS ======== */}
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Briefcase className="h-5 w-5" /> Job Descriptions
              </CardTitle>
              <CardDescription>Upload or create job descriptions</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* Mode Toggle */}
              <div className="flex gap-2">
                <Button
                  variant={jdMode === 'upload' ? 'default' : 'outline'}
                  size="sm"
                  onClick={() => setJdMode('upload')}
                >
                  Upload File
                </Button>
                <Button
                  variant={jdMode === 'paste' ? 'default' : 'outline'}
                  size="sm"
                  onClick={() => setJdMode('paste')}
                >
                  Paste Text
                </Button>
              </div>

              {jdMode === 'upload' ? (
                <div className="flex gap-2">
                  <Input
                    ref={jdFileRef}
                    type="file"
                    accept=".pdf,.docx,.doc,.txt"
                    disabled={jdUploading}
                    className="flex-1"
                  />
                  <Button onClick={handleJDUpload} disabled={jdUploading}>
                    {jdUploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
                  </Button>
                </div>
              ) : (
                <div className="space-y-3">
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <Label className="text-xs">Title</Label>
                      <Input
                        value={jdTitle}
                        onChange={(e) => setJdTitle(e.target.value)}
                        placeholder="Job title"
                        disabled={jdUploading}
                      />
                    </div>
                    <div>
                      <Label className="text-xs">Company</Label>
                      <Input
                        value={jdCompany}
                        onChange={(e) => setJdCompany(e.target.value)}
                        placeholder="Company name"
                        disabled={jdUploading}
                      />
                    </div>
                  </div>
                  <div>
                    <Label className="text-xs">Description</Label>
                    <Textarea
                      value={jdText}
                      onChange={(e) => setJdText(e.target.value)}
                      placeholder="Paste job description text..."
                      rows={6}
                      disabled={jdUploading}
                    />
                  </div>
                  <Button onClick={handleJDUpload} disabled={jdUploading} className="w-full">
                    {jdUploading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Upload className="mr-2 h-4 w-4" />}
                    Create JD
                  </Button>
                </div>
              )}

              {jdUploadStream && (
                <pre className="text-xs bg-muted p-2 rounded-md max-h-32 overflow-auto whitespace-pre-wrap">{jdUploadStream}</pre>
              )}

              <Separator />

              {/* List */}
              {jdsLoading ? (
                <div className="flex justify-center py-8">
                  <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                </div>
              ) : jds.length === 0 ? (
                <p className="text-sm text-muted-foreground text-center py-4">No job descriptions yet</p>
              ) : (
                <div className="space-y-2">
                  {jds.map((jd) => (
                    <div key={jd.id} className="border rounded-lg">
                      <div
                        className="flex items-center justify-between p-3 cursor-pointer hover:bg-muted/50 transition-colors"
                        onClick={() => setExpandedJD(expandedJD === jd.id ? null : jd.id)}
                      >
                        <div className="flex items-center gap-2 min-w-0">
                          {expandedJD === jd.id ? (
                            <ChevronDown className="h-4 w-4 shrink-0" />
                          ) : (
                            <ChevronRight className="h-4 w-4 shrink-0" />
                          )}
                          <div className="min-w-0">
                            <p className="text-sm font-medium truncate">{jd.title}</p>
                            <p className="text-xs text-muted-foreground">
                              {jd.company || 'No company'} &middot;{' '}
                              <Badge variant={jd.status === 'parsed' ? 'secondary' : 'outline'} className="text-[10px] px-1 py-0">
                                {jd.status}
                              </Badge>
                            </p>
                          </div>
                        </div>
                      </div>

                      {expandedJD === jd.id && (
                        <div className="px-3 pb-3 border-t">
                          {jd.parsed_data ? (
                            <div className="pt-3">
                              <JDViewer data={jd.parsed_data} />
                            </div>
                          ) : (
                            <p className="text-sm text-muted-foreground py-3">No parsed data available</p>
                          )}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>

      {/* ======== MATCH SECTION ======== */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Sparkles className="h-5 w-5" /> Resume-JD Match Analysis
          </CardTitle>
          <CardDescription>
            Compare a resume against a job description for fit analysis
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 items-end">
            <div>
              <Label className="text-sm">Resume</Label>
              <Select value={matchResumeId} onValueChange={setMatchResumeId}>
                <SelectTrigger>
                  <SelectValue placeholder="Select resume" />
                </SelectTrigger>
                <SelectContent>
                  {resumes.map((r) => (
                    <SelectItem key={r.id} value={r.id}>
                      {r.candidate_name || r.filename}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-sm">Job Description</Label>
              <Select value={matchJdId} onValueChange={setMatchJdId}>
                <SelectTrigger>
                  <SelectValue placeholder="Select JD" />
                </SelectTrigger>
                <SelectContent>
                  {jds.map((j) => (
                    <SelectItem key={j.id} value={j.id}>
                      {j.title}{j.company ? ` (${j.company})` : ''}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <Button onClick={handleMatch} disabled={matching || !matchResumeId || !matchJdId}>
              {matching ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Sparkles className="mr-2 h-4 w-4" />
              )}
              Run Match
            </Button>
          </div>

          {/* Stream Output */}
          {matchStream && !matchResult && (
            <pre className="text-xs bg-muted p-2 rounded-md max-h-32 overflow-auto whitespace-pre-wrap">{matchStream}</pre>
          )}

          {/* Match Results */}
          {matchResult && <MatchResultsViewer result={matchResult} />}
        </CardContent>
      </Card>
    </div>
  );
}

export default function DocumentsPage() {
  return (
    <ProtectedRoute requiredPermission="view_document">
      <DocumentsContent />
    </ProtectedRoute>
  );
}
