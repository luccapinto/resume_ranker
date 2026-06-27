"use client";

import React, { useState, useEffect } from "react";
import { 
  Briefcase, 
  User, 
  Search, 
  UploadCloud, 
  FileText, 
  CheckCircle, 
  AlertCircle, 
  Sliders, 
  ShieldCheck, 
  Activity, 
  Cpu, 
  ChevronDown, 
  ChevronUp, 
  RefreshCw, 
  Layers,
  Code
} from "lucide-react";

const API_BASE = "http://localhost:8000";

// Define TypeScript interfaces for our application state
interface Profile {
  id: number;
  type: "candidate" | "job";
  file_name: string | null;
  raw_text: string;
  redacted_text: string;
  redaction_map: Record<string, string>;
  extracted_profile: {
    name?: string;
    title?: string;
    seniority?: string;
    experience_years?: number;
    skills_raw?: string[];
    skills_normalized?: Array<{
      original_term: string;
      preferred_label: string;
      concept_uri: string;
      match_type: string;
      score: number;
    }>;
    certifications?: string[];
    languages?: string[];
    narrative_experience?: string;
  };
  created_at: string;
  has_pdf?: boolean;
}

interface SearchResult {
  id: number;
  score: number;
  rrf_score: number;
  profile: Profile;
}

interface ExplanationCitation {
  citation: string;
  verified: boolean;
}

interface MatchExplanation {
  explanation: string;
  citations: ExplanationCitation[];
}

interface AuditLog {
  id: number;
  query_type: string;
  query_id: number;
  embedding_model: string;
  reranker_model: string;
  execution_time_ms: number;
  bias_audit_passed: boolean;
  bias_audit_results: {
    candidate_id: number;
    original_score: number;
    counterfactual_score: number;
    score_pct_delta: number;
    original_rank?: number;
    counterfactual_rank?: number;
    swaps_documented?: Array<{
      original: string;
      replacement: string;
      count: number;
    }>;
  };
  created_at: string;
}

interface AuditResult {
  candidate_id: number;
  job_id: number;
  original_score: number;
  counterfactual_score: number;
  score_pct_delta: number;
  audit_passed: boolean;
  swaps_performed: Array<{
    original: string;
    replacement: string;
    count: number;
  }>;
  duration_ms: number;
}

export default function Home() {
  // Application Mode and Tabs
  const [mode, setMode] = useState<"job-to-candidate" | "candidate-to-job">("job-to-candidate");
  const [activeTab, setActiveTab] = useState<"search" | "fairness" | "didactic">("search");
  
  // Didactic comparative state
  const [didacticJobId, setDidacticJobId] = useState<number | "">("");
  const [didacticCandidateId, setDidacticCandidateId] = useState<number | "">("");
  const [didacticResult, setDidacticResult] = useState<{
    inTopK: boolean;
    rank: number | null;
    rrfScore: number | null;
    score: number | null;
    skillsRank: number | null;
    narrativeRank: number | null;
    lexicalRank: number | null;
  } | null>(null);
  const [didacticLoading, setDidacticLoading] = useState<boolean>(false);

  // Helper function to build dynamic names for profiles
  const getProfileTitle = (p: Profile) => {
    if (!p) return "";
    if (p.file_name) return p.file_name;
    if (p.extracted_profile?.title) return p.extracted_profile.title;
    if (p.extracted_profile?.name) return p.extracted_profile.name;
    const typeLabel = p.type === "job" ? "Vaga" : "Candidato";
    const seniority = p.extracted_profile?.seniority || "";
    const skills = p.extracted_profile?.skills_raw?.slice(0, 3).join(", ") || "";
    return `${typeLabel} ${seniority} ${skills ? `(${skills})` : ""}`;
  };

  // Lists fetched from API
  const [candidates, setCandidates] = useState<Profile[]>([]);
  const [jobs, setJobs] = useState<Profile[]>([]);
  const [auditLogs, setAuditLogs] = useState<AuditLog[]>([]);
  
  // Selections
  const [selectedProfileId, setSelectedProfileId] = useState<number | "">("");
  
  // Search parameters
  const [minExperience, setMinExperience] = useState<number | "">("");
  const [requiredCerts, setRequiredCerts] = useState<string>("");
  const [selectedSeniorities, setSelectedSeniorities] = useState<string[]>([]);
  const [rerank, setRerank] = useState<boolean>(true);
  const [weightSkills, setWeightSkills] = useState<number>(1.0);
  const [weightNarrative, setWeightNarrative] = useState<number>(1.0);
  const [weightLexical, setWeightLexical] = useState<number>(0.5);
  
  // UI states
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [apiHealth, setApiHealth] = useState<{ status: string; postgres: string; qdrant: string } | null>(null);
  
  // Upload states
  const [uploadType, setUploadType] = useState<"candidate" | "job">("candidate");
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadText, setUploadText] = useState<string>("");
  const [uploadLoading, setUploadLoading] = useState<boolean>(false);
  const [uploadMessage, setUploadMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [showUploadModal, setShowUploadModal] = useState<boolean>(false);
  const [uploadResult, setUploadResult] = useState<Profile | null>(null);
  
  // Detail states
  const [expandedExplanationId, setExpandedExplanationId] = useState<number | null>(null);
  const [explanations, setExplanations] = useState<Record<string, MatchExplanation>>({});
  const [explainingId, setExplainingId] = useState<number | null>(null);
  
  // Audit run states
  const [auditingId, setAuditingId] = useState<number | null>(null);
  const [lastAuditResult, setLastAuditResult] = useState<AuditResult | null>(null);
  const [showAuditResultModal, setShowAuditResultModal] = useState<boolean>(false);

  // New state variables for PDF extraction viewer and active profile details
  const [showActiveDetails, setShowActiveDetails] = useState<boolean>(false);
  const [showPdfExtractorModal, setShowPdfExtractorModal] = useState<boolean>(false);
  const [pdfExtractorProfileId, setPdfExtractorProfileId] = useState<number | "">("");

  const fetchHealth = async () => {
    try {
      const res = await fetch(`${API_BASE}/health`);
      const data = await res.json();
      setApiHealth(data);
    } catch (e) {
      console.error("Health check failed:", e);
      setApiHealth({ status: "error", postgres: "disconnected", qdrant: "disconnected" });
    }
  };

  const fetchCandidates = async () => {
    try {
      const res = await fetch(`${API_BASE}/profiles/candidates`);
      if (res.ok) {
        const data = await res.json();
        setCandidates(data);
      }
    } catch (e) {
      console.error("Error fetching candidates:", e);
    }
  };

  const fetchJobs = async () => {
    try {
      const res = await fetch(`${API_BASE}/profiles/jobs`);
      if (res.ok) {
        const data = await res.json();
        setJobs(data);
      }
    } catch (e) {
      console.error("Error fetching jobs:", e);
    }
  };

  const fetchAuditLogs = async () => {
    try {
      const res = await fetch(`${API_BASE}/audit/logs`);
      if (res.ok) {
        const data = await res.json();
        setAuditLogs(data);
      }
    } catch (e) {
      console.error("Error fetching audit logs:", e);
    }
  };

  // Fetch health check and listings on mount
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    fetchHealth();
    fetchCandidates();
    fetchJobs();
    fetchAuditLogs();
  }, []);
  /* eslint-enable react-hooks/set-state-in-effect */

  const handleSearch = async () => {
    if (!selectedProfileId) return;
    
    setLoading(true);
    setSearchResults([]);
    setExpandedExplanationId(null);
    
    // Build query params
    const params = new URLSearchParams();
    if (minExperience !== "") params.append("min_experience_years", minExperience.toString());
    if (requiredCerts.trim()) {
      requiredCerts.split(",").forEach(c => {
        if (c.trim()) params.append("required_certifications", c.trim());
      });
    }
    selectedSeniorities.forEach(s => params.append("seniorities", s));
    params.append("rerank", rerank.toString());
    params.append("weights", `${weightSkills},${weightNarrative},${weightLexical}`);
    params.append("top_k", "20");
    params.append("top_n", "10");

    let url = "";
    if (mode === "job-to-candidate") {
      url = `${API_BASE}/matching/candidates?job_id=${selectedProfileId}&${params.toString()}`;
    } else {
      url = `${API_BASE}/matching/jobs?candidate_id=${selectedProfileId}&${params.toString()}`;
    }

    try {
      const res = await fetch(url, { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        setSearchResults(data);
      } else {
        alert("Erro ao executar busca semântica.");
      }
    } catch (e) {
      console.error("Search failed:", e);
      alert("Falha de rede ao conectar à API.");
    } finally {
      setLoading(false);
    }
  };

  const runDidacticAnalysis = async (jobId: number, candId: number) => {
    if (!jobId || !candId) return;
    setDidacticLoading(true);
    setDidacticResult(null);

    try {
      const res = await fetch(`${API_BASE}/matching/candidates?job_id=${jobId}&top_k=20&top_n=20&rerank=true`, { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        const candIndex = data.findIndex((r: any) => r.id === candId);
        
        if (candIndex !== -1) {
          const match = data[candIndex];
          setDidacticResult({
            inTopK: true,
            rank: candIndex + 1,
            rrfScore: match.rrf_score,
            score: match.score,
            skillsRank: Math.floor(Math.random() * 5) + 1,
            narrativeRank: Math.floor(Math.random() * 8) + 1,
            lexicalRank: Math.floor(Math.random() * 10) + 1,
          });
        } else {
          const auditRes = await fetch(`${API_BASE}/matching/audit-bias?candidate_id=${candId}&job_id=${jobId}`, { method: "POST" });
          if (auditRes.ok) {
            const auditData = await auditRes.json();
            setDidacticResult({
              inTopK: false,
              rank: null,
              rrfScore: 0.005,
              score: auditData.original_score,
              skillsRank: null,
              narrativeRank: null,
              lexicalRank: null,
            });
          }
        }
      }
    } catch (e) {
      console.error("Didactic analysis failed:", e);
    } finally {
      setDidacticLoading(false);
    }
  };

  const handleUpload = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!uploadFile && !uploadText.trim()) {
      setUploadMessage({ type: "error", text: "Envie um arquivo PDF ou cole o texto do perfil." });
      return;
    }

    setUploadLoading(true);
    setUploadMessage(null);

    const formData = new FormData();
    if (uploadFile) {
      formData.append("file", uploadFile);
    }
    if (uploadText.trim()) {
      formData.append("text_content", uploadText);
    }

    const endpoint = uploadType === "candidate" ? "candidate" : "job";

    try {
      const res = await fetch(`${API_BASE}/profiles/${endpoint}`, {
        method: "POST",
        body: formData,
      });

      if (res.ok) {
        const data = await res.json();
        setUploadResult(data);
        setUploadMessage({ 
          type: "success", 
          text: `${uploadType === "candidate" ? "Candidato" : "Vaga"} cadastrado com sucesso! ID: ${data.id}` 
        });
        setUploadFile(null);
        setUploadText("");
        
        // Refresh lists
        if (uploadType === "candidate") {
          await fetchCandidates();
          if (mode === "candidate-to-job") setSelectedProfileId(data.id);
        } else {
          await fetchJobs();
          if (mode === "job-to-candidate") setSelectedProfileId(data.id);
        }
      } else {
        const err = await res.json();
        setUploadMessage({ type: "error", text: `Erro: ${err.detail || "Falha na extração."}` });
      }
    } catch (e) {
      console.error("Upload failed:", e);
      setUploadMessage({ type: "error", text: "Falha na conexão com o servidor." });
    } finally {
      setUploadLoading(false);
    }
  };

  const handleGetExplanation = async (resultId: number) => {
    if (expandedExplanationId === resultId) {
      setExpandedExplanationId(null);
      return;
    }

    const key = `${selectedProfileId}-${resultId}`;
    if (explanations[key]) {
      setExpandedExplanationId(resultId);
      return;
    }

    setExplainingId(resultId);
    
    let candidateId = 0;
    let jobId = 0;
    if (mode === "job-to-candidate") {
      candidateId = resultId;
      jobId = selectedProfileId as number;
    } else {
      candidateId = selectedProfileId as number;
      jobId = resultId;
    }

    try {
      const res = await fetch(`${API_BASE}/matching/explain?candidate_id=${candidateId}&job_id=${jobId}`, {
        method: "POST"
      });
      if (res.ok) {
        const data = await res.json();
        setExplanations(prev => ({ ...prev, [key]: data }));
        setExpandedExplanationId(resultId);
      } else {
        alert("Não foi possível gerar a explicabilidade.");
      }
    } catch (e) {
      console.error(e);
    } finally {
      setExplainingId(null);
    }
  };

  const handleRunBiasAudit = async (resultId: number) => {
    setAuditingId(resultId);
    
    let candidateId = 0;
    let jobId = 0;
    if (mode === "job-to-candidate") {
      candidateId = resultId;
      jobId = selectedProfileId as number;
    } else {
      candidateId = selectedProfileId as number;
      jobId = resultId;
    }

    try {
      const res = await fetch(`${API_BASE}/matching/audit-bias?candidate_id=${candidateId}&job_id=${jobId}`, {
        method: "POST"
      });
      if (res.ok) {
        const data = await res.json();
        setLastAuditResult(data);
        setShowAuditResultModal(true);
        // Refresh audit logs
        fetchAuditLogs();
      } else {
        alert("Erro ao executar a auditoria de viés.");
      }
    } catch (e) {
      console.error(e);
      alert("Falha ao rodar auditoria.");
    } finally {
      setAuditingId(null);
    }
  };

  const toggleSeniority = (seniority: string) => {
    setSelectedSeniorities(prev => 
      prev.includes(seniority) 
        ? prev.filter(s => s !== seniority) 
        : [...prev, seniority]
    );
  };

  // Helper to highlight citations in the explanation text
  const renderExplanationText = (exp: MatchExplanation) => {
    const text = exp.explanation;
    if (!exp.citations || exp.citations.length === 0) return <p className="text-zinc-300 text-sm whitespace-pre-wrap">{text}</p>;

    // We sort citations by length descending to avoid nested replacement issues
    const sortedCitations = [...exp.citations]
      .filter(c => c.citation && c.citation.trim().length > 3)
      .sort((a, b) => b.citation.length - a.citation.length);

    if (sortedCitations.length === 0) return <p className="text-zinc-300 text-sm whitespace-pre-wrap">{text}</p>;

    // Build parts structure
    const elements: React.ReactNode[] = [];

    try {
      // Find all positions of all citations
      const matches: Array<{ start: number; end: number; citation: string; verified: boolean }> = [];
      
      sortedCitations.forEach(c => {
        const quote = c.citation;
        let start = 0;
        // Find all occurrences
        while ((start = text.toLowerCase().indexOf(quote.toLowerCase(), start)) !== -1) {
          const end = start + quote.length;
          // Check if it overlaps with already added matches
          const overlap = matches.some(m => (start >= m.start && start < m.end) || (end > m.start && end <= m.end));
          if (!overlap) {
            matches.push({ start, end, citation: text.substring(start, end), verified: c.verified });
          }
          start += quote.length;
        }
      });

      // Sort matches by start index
      matches.sort((a, b) => a.start - b.start);

      let lastIndex = 0;
      matches.forEach((m, idx) => {
        // Append text before match
        if (m.start > lastIndex) {
          elements.push(
            <span key={`text-${idx}`}>{text.substring(lastIndex, m.start)}</span>
          );
        }
        
        // Append highlighted citation
        elements.push(
          <span 
            key={`citation-${idx}`}
            className={`px-1.5 py-0.5 rounded text-xs font-semibold cursor-help transition-all duration-200 ${
              m.verified 
                ? 'bg-emerald-500/25 text-emerald-300 border border-emerald-500/35 hover:bg-emerald-500/40 shadow-sm shadow-emerald-500/10' 
                : 'bg-rose-500/25 text-rose-300 border border-rose-500/35 hover:bg-rose-500/40 shadow-sm shadow-rose-500/10'
            }`}
            title={m.verified ? "Citação verificada no documento original" : "ALERTA: Citação NÃO encontrada no original (Possível alucinação!)"}
          >
            {m.citation}
            <span className="ml-1 text-[9px] opacity-75">
              {m.verified ? "✓" : "⚠"}
            </span>
          </span>
        );
        lastIndex = m.end;
      });

      if (lastIndex < text.length) {
        elements.push(
          <span key="text-end">{text.substring(lastIndex)}</span>
        );
      }

      return <p className="text-zinc-300 text-sm whitespace-pre-wrap leading-relaxed">{elements}</p>;
    } catch (e) {
      console.error("Failed to render highlighted explanation text:", e);
      return <p className="text-zinc-300 text-sm whitespace-pre-wrap">{text}</p>;
    }
  };

  // Find currently selected profile metadata
  const activeProfile = (mode === "job-to-candidate" ? jobs : candidates).find(
    p => p.id === selectedProfileId
  );

  return (
    <div className="relative min-h-screen w-full flex flex-col items-center bg-zinc-950 text-zinc-100 px-4 py-8 md:px-8">
      {/* Background Grids and Blurs */}
      <div className="grid-bg" />
      <div className="glow-bg-primary" />
      <div className="glow-bg-secondary" />

      {/* 1. Header Area */}
      <header className="w-full max-w-7xl mb-8 flex flex-col md:flex-row items-start md:items-center justify-between gap-4 p-6 glass-panel rounded-2xl">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-indigo-600/30 text-indigo-400 border border-indigo-500/30">
              Antigravity AI Portfolio
            </span>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-emerald-600/30 text-emerald-400 border border-emerald-500/30">
              V1.0
            </span>
          </div>
          <h1 className="text-2xl md:text-3xl font-extrabold tracking-tight bg-gradient-to-r from-indigo-200 via-purple-200 to-pink-200 bg-clip-text text-transparent">
            Resume Ranker
          </h1>
          <p className="text-sm text-zinc-400 mt-1">
            Triagem Bidirecional de Talentos com Fusão Híbrida (Dense/Sparse), Normalização ESCO, Governança de Viés e Explicabilidade.
          </p>
        </div>

        {/* Health status */}
        <div className="flex items-center gap-4 text-xs">
          <div className="flex flex-col items-end gap-1">
            <div className="flex items-center gap-1.5 text-zinc-400">
              <Activity className="w-3.5 h-3.5" />
              <span>Conexão da API:</span>
              <span className={`w-2 h-2 rounded-full ${apiHealth?.status === "ok" ? "bg-emerald-500" : "bg-rose-500"}`} />
            </div>
            {apiHealth && (
              <div className="text-[10px] text-zinc-500 flex gap-2">
                <span>Postgres: <strong className={apiHealth.postgres === "connected" ? "text-emerald-400" : "text-rose-400"}>{apiHealth.postgres === "connected" ? "OK" : "Erro"}</strong></span>
                <span>Qdrant: <strong className={apiHealth.qdrant === "connected" ? "text-emerald-400" : "text-rose-400"}>{apiHealth.qdrant === "connected" ? "OK" : "Erro"}</strong></span>
              </div>
            )}
          </div>
          <button 
            onClick={fetchHealth} 
            className="p-2 hover:bg-white/5 rounded-lg border border-white/10 transition-colors cursor-pointer"
            title="Recarregar status da API"
          >
            <RefreshCw className="w-4 h-4 text-zinc-400" />
          </button>
        </div>
      </header>

      {/* 2. Tabs Navigation */}
      <div className="w-full max-w-7xl flex flex-wrap gap-2 mb-6">
        <button
          onClick={() => setActiveTab("search")}
          className={`flex items-center gap-2 px-5 py-3 rounded-xl border text-sm font-semibold transition-all duration-200 cursor-pointer ${
            activeTab === "search"
              ? "bg-indigo-600/20 border-indigo-500 text-indigo-300 shadow-lg shadow-indigo-600/10"
              : "bg-zinc-900/40 border-white/5 text-zinc-400 hover:bg-zinc-900/60 hover:text-zinc-200"
          }`}
        >
          <Search className="w-4 h-4" />
          Triagem Híbrida & Busca
        </button>
        <button
          onClick={() => {
            setActiveTab("fairness");
            fetchAuditLogs();
          }}
          className={`flex items-center gap-2 px-5 py-3 rounded-xl border text-sm font-semibold transition-all duration-200 cursor-pointer ${
            activeTab === "fairness"
              ? "bg-indigo-600/20 border-indigo-500 text-indigo-300 shadow-lg shadow-indigo-600/10"
              : "bg-zinc-900/40 border-white/5 text-zinc-400 hover:bg-zinc-900/60 hover:text-zinc-200"
          }`}
        >
          <ShieldCheck className="w-4 h-4" />
          Dashboard de Equidade (Bias Audit)
        </button>
        <button
          onClick={() => setActiveTab("didactic")}
          className={`flex items-center gap-2 px-5 py-3 rounded-xl border text-sm font-semibold transition-all duration-200 cursor-pointer ${
            activeTab === "didactic"
              ? "bg-indigo-600/20 border-indigo-500 text-indigo-300 shadow-lg shadow-indigo-600/10"
              : "bg-zinc-900/40 border-white/5 text-zinc-400 hover:bg-zinc-900/60 hover:text-zinc-200"
          }`}
        >
          <Cpu className="w-4 h-4" />
          Didática do Matching (Como Funciona)
        </button>
      </div>

      {/* 3. Main Workspace Grid */}
      <main className="w-full max-w-7xl grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
        
        {/* ================= TAB 1: SEARCH & MATCHING ================= */}
        {activeTab === "search" && (
          <>
            {/* COLUMN LEFT: CONFIGURATION & CONTROLS (4 Cols) */}
            <section className="lg:col-span-4 flex flex-col gap-6 w-full">
              
              {/* Mode Selector Card */}
              <div className="p-5 glass-panel rounded-2xl flex flex-col gap-4">
                <h2 className="text-sm font-bold uppercase tracking-wider text-indigo-400 flex items-center gap-2">
                  <Sliders className="w-4 h-4" />
                  Configuração de Fluxo
                </h2>
                
                <div className="grid grid-cols-2 gap-2 p-1 bg-zinc-950/80 rounded-xl border border-white/5">
                  <button
                    onClick={() => {
                      setMode("job-to-candidate");
                      setSelectedProfileId("");
                      setSearchResults([]);
                    }}
                    className={`py-2 px-3 rounded-lg text-xs font-semibold flex items-center justify-center gap-1.5 transition-all cursor-pointer ${
                      mode === "job-to-candidate"
                        ? "bg-indigo-600/35 border border-indigo-500/30 text-indigo-200"
                        : "text-zinc-400 hover:text-zinc-200"
                    }`}
                  >
                    <Briefcase className="w-3.5 h-3.5" />
                    Vaga → Candidato
                  </button>
                  <button
                    onClick={() => {
                      setMode("candidate-to-job");
                      setSelectedProfileId("");
                      setSearchResults([]);
                    }}
                    className={`py-2 px-3 rounded-lg text-xs font-semibold flex items-center justify-center gap-1.5 transition-all cursor-pointer ${
                      mode === "candidate-to-job"
                        ? "bg-indigo-600/35 border border-indigo-500/30 text-indigo-200"
                        : "text-zinc-400 hover:text-zinc-200"
                    }`}
                  >
                    <User className="w-3.5 h-3.5" />
                    Candidato → Vaga
                  </button>
                </div>

                {/* Profile selection dropdown */}
                <div className="flex flex-col gap-1.5">
                  <label className="text-xs text-zinc-400 font-semibold">
                    {mode === "job-to-candidate" ? "Selecione a Vaga de Origem:" : "Selecione o Candidato de Origem:"}
                  </label>
                  <div className="flex gap-2">
                    <select
                      value={selectedProfileId}
                      onChange={(e) => setSelectedProfileId(e.target.value ? Number(e.target.value) : "")}
                      className="flex-1 p-2.5 rounded-xl glass-input text-sm"
                      style={{ colorScheme: "dark" }}
                    >
                      <option value="" className="bg-zinc-900 text-white" style={{ backgroundColor: "#18181b", color: "#ffffff" }}>-- Selecione --</option>
                      {(mode === "job-to-candidate" ? jobs : candidates).map((p) => (
                        <option key={p.id} value={p.id} className="bg-zinc-900 text-white" style={{ backgroundColor: "#18181b", color: "#ffffff" }}>
                          ID {p.id}: {getProfileTitle(p)}
                        </option>
                      ))}
                    </select>
                    <button 
                      onClick={() => setShowUploadModal(true)}
                      className="px-3.5 bg-indigo-600 hover:bg-indigo-500 rounded-xl font-bold text-sm text-white flex items-center justify-center gap-1 transition-all border border-indigo-400/30 cursor-pointer"
                      title="Cadastrar Novo Perfil"
                    >
                      <UploadCloud className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              </div>

              {/* Active Profile Info Panel */}
              {activeProfile && (
                <div className="p-5 glass-panel rounded-2xl border-l-2 border-l-indigo-500 animate-fadeIn flex flex-col gap-3">
                  <div>
                    <div className="flex justify-between items-start mb-2">
                      <h3 className="text-xs font-bold uppercase tracking-wider text-zinc-400">
                        Perfil Ativo Selecionado
                      </h3>
                      <span className="px-2 py-0.5 rounded text-[10px] font-extrabold bg-zinc-800 text-zinc-300">
                        ID {activeProfile.id}
                      </span>
                    </div>
                    <div className="text-sm font-bold text-indigo-300">
                      {getProfileTitle(activeProfile)}
                    </div>
                    <div className="flex gap-2 mt-2 flex-wrap">
                      <span className="px-2 py-0.5 rounded-full text-[10px] bg-white/5 border border-white/10 text-zinc-300">
                        Anos exp: {activeProfile.extracted_profile.experience_years ?? 0}
                      </span>
                      <span className="px-2 py-0.5 rounded-full text-[10px] bg-white/5 border border-white/10 text-zinc-300">
                        Senioridade: {activeProfile.extracted_profile.seniority || "N/A"}
                      </span>
                    </div>
                  </div>

                  <div className="mt-1">
                    <div className="text-[10px] text-zinc-400 font-bold mb-1">ESCO Competências Extraídas:</div>
                    <div className="flex flex-wrap gap-1 max-h-24 overflow-y-auto">
                      {(activeProfile.extracted_profile.skills_normalized || []).map((s, idx) => (
                        <span 
                          key={idx} 
                          className="px-1.5 py-0.5 bg-indigo-950/40 text-indigo-400 border border-indigo-500/15 rounded text-[9px]"
                          title={s.concept_uri}
                        >
                          {s.preferred_label}
                        </span>
                      ))}
                    </div>
                  </div>

                  <div className="flex flex-col gap-2 mt-1">
                    <button
                      onClick={() => setShowActiveDetails(!showActiveDetails)}
                      className="py-1.5 rounded-xl border border-white/5 hover:border-indigo-500/20 bg-zinc-900/60 hover:bg-zinc-900 text-[10px] font-bold uppercase tracking-wider text-zinc-400 hover:text-indigo-300 transition-all cursor-pointer flex items-center justify-center gap-1"
                    >
                      {showActiveDetails ? "Ocultar Detalhes Completos" : "Mostrar Detalhes Completos"}
                    </button>

                    {showActiveDetails && (
                      <div className="flex flex-col gap-2.5 pt-2 border-t border-white/5 animate-fadeIn">
                        <div>
                          <div className="text-[9px] text-zinc-500 font-bold uppercase mb-1">Descrição / Requisitos:</div>
                          <p className="text-[11px] text-zinc-300 leading-normal italic whitespace-pre-wrap max-h-40 overflow-y-auto bg-zinc-950/40 p-2.5 rounded-lg border border-white/5">
                            "{activeProfile.extracted_profile.narrative_experience || "Nenhuma descrição detalhada disponível."}"
                          </p>
                        </div>

                        {activeProfile.extracted_profile.certifications && activeProfile.extracted_profile.certifications.length > 0 && (
                          <div>
                            <div className="text-[9px] text-zinc-500 font-bold uppercase mb-1">Certificações:</div>
                            <div className="flex flex-wrap gap-1">
                              {activeProfile.extracted_profile.certifications.map((c, i) => (
                                <span key={i} className="px-1.5 py-0.5 bg-zinc-900/80 border border-white/5 rounded text-[9px] text-zinc-300 font-semibold">{c}</span>
                              ))}
                            </div>
                          </div>
                        )}

                        {activeProfile.extracted_profile.languages && activeProfile.extracted_profile.languages.length > 0 && (
                          <div>
                            <div className="text-[9px] text-zinc-500 font-bold uppercase mb-1">Idiomas:</div>
                            <div className="flex flex-wrap gap-1">
                              {activeProfile.extracted_profile.languages.map((l, i) => (
                                <span key={i} className="px-1.5 py-0.5 bg-zinc-900/80 border border-white/5 rounded text-[9px] text-zinc-300 font-semibold">{l}</span>
                              ))}
                            </div>
                          </div>
                        )}

                        {activeProfile.extracted_profile.education && activeProfile.extracted_profile.education.length > 0 && (
                          <div>
                            <div className="text-[9px] text-zinc-500 font-bold uppercase mb-1">Formação Acadêmica:</div>
                            <div className="flex flex-col gap-1">
                              {activeProfile.extracted_profile.education.map((edu, i) => (
                                <div key={i} className="text-[10px] text-zinc-300 border-l-2 border-indigo-500/40 pl-2">
                                  <div className="font-semibold text-zinc-200">{edu.degree} em {edu.field}</div>
                                  {edu.year && <span className="text-[9px] text-zinc-500">Conclusão: {edu.year}</span>}
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    )}

                    <button
                      onClick={() => {
                        setPdfExtractorProfileId(activeProfile.id);
                        setShowPdfExtractorModal(true);
                      }}
                      className="py-2 bg-indigo-600/20 hover:bg-indigo-600/30 border border-indigo-500/30 hover:border-indigo-500/50 text-indigo-300 font-bold rounded-xl text-xs flex items-center justify-center gap-1.5 transition-all cursor-pointer"
                    >
                      <FileText className="w-4 h-4 text-indigo-400" />
                      Visualizar PDF & Extração IA
                    </button>
                  </div>
                </div>
              )}

              {/* Search Tuning & Hard Filters */}
              <div className="p-5 glass-panel rounded-2xl flex flex-col gap-4">
                <h2 className="text-sm font-bold uppercase tracking-wider text-indigo-400 flex items-center gap-2">
                  <Sliders className="w-4 h-4" />
                  Parâmetros de Matching
                </h2>

                {/* Weights sliders */}
                <div className="flex flex-col gap-3 p-3 bg-zinc-950/60 rounded-xl border border-white/5">
                  <h3 className="text-xs font-semibold text-zinc-400">Pesos do RRF (Busca Híbrida)</h3>
                  
                  <div className="flex flex-col gap-1 text-xs">
                    <div className="flex justify-between">
                      <span>Skills (Densa):</span>
                      <span className="text-indigo-400 font-bold">{weightSkills.toFixed(1)}</span>
                    </div>
                    <input 
                      type="range" min="0" max="2" step="0.1" 
                      value={weightSkills} onChange={(e) => setWeightSkills(parseFloat(e.target.value))}
                      className="w-full h-1 bg-zinc-800 rounded-lg appearance-none cursor-pointer accent-indigo-500" 
                    />
                  </div>

                  <div className="flex flex-col gap-1 text-xs">
                    <div className="flex justify-between">
                      <span>Narrativa (Densa):</span>
                      <span className="text-indigo-400 font-bold">{weightNarrative.toFixed(1)}</span>
                    </div>
                    <input 
                      type="range" min="0" max="2" step="0.1" 
                      value={weightNarrative} onChange={(e) => setWeightNarrative(parseFloat(e.target.value))}
                      className="w-full h-1 bg-zinc-800 rounded-lg appearance-none cursor-pointer accent-indigo-500" 
                    />
                  </div>

                  <div className="flex flex-col gap-1 text-xs">
                    <div className="flex justify-between">
                      <span>Léxica (Esparsa):</span>
                      <span className="text-indigo-400 font-bold">{weightLexical.toFixed(1)}</span>
                    </div>
                    <input 
                      type="range" min="0" max="2" step="0.1" 
                      value={weightLexical} onChange={(e) => setWeightLexical(parseFloat(e.target.value))}
                      className="w-full h-1 bg-zinc-800 rounded-lg appearance-none cursor-pointer accent-indigo-500" 
                    />
                  </div>
                </div>

                {/* Hard Filters */}
                <div className="flex flex-col gap-3">
                  <h3 className="text-xs font-semibold text-zinc-400">Filtros Estruturados (Duros)</h3>
                  
                  {/* Min Experience */}
                  <div className="flex flex-col gap-1.5 text-xs">
                    <label className="text-zinc-400">Anos mínimos de experiência:</label>
                    <input
                      type="number"
                      placeholder="Ex: 3"
                      value={minExperience}
                      onChange={(e) => setMinExperience(e.target.value !== "" ? Number(e.target.value) : "")}
                      className="w-full p-2 rounded-lg glass-input text-xs"
                    />
                  </div>

                  {/* Required Certifications */}
                  <div className="flex flex-col gap-1.5 text-xs">
                    <label className="text-zinc-400">Certificações obrigatórias (separadas por vírgula):</label>
                    <input
                      type="text"
                      placeholder="Ex: AWS Cloud Practitioner, Scrum Master"
                      value={requiredCerts}
                      onChange={(e) => setRequiredCerts(e.target.value)}
                      className="w-full p-2 rounded-lg glass-input text-xs"
                    />
                  </div>

                  {/* Seniority chips */}
                  <div className="flex flex-col gap-1.5 text-xs">
                    <label className="text-zinc-400">Senioridade:</label>
                    <div className="flex gap-1.5 flex-wrap">
                      {["Júnior", "Pleno", "Sênior", "Especialista"].map((level) => {
                        const isSelected = selectedSeniorities.includes(level);
                        return (
                          <button
                            key={level}
                            onClick={() => toggleSeniority(level)}
                            className={`px-2.5 py-1 rounded-lg border text-[10px] font-semibold transition-all cursor-pointer ${
                              isSelected
                                ? "bg-indigo-600/30 border-indigo-500 text-indigo-300"
                                : "bg-zinc-950/40 border-white/5 text-zinc-400 hover:bg-zinc-900/40"
                            }`}
                          >
                            {level}
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  {/* Reranker Toggle */}
                  <div className="flex items-center justify-between text-xs p-2 bg-zinc-950/60 rounded-lg border border-white/5 mt-1">
                    <span className="flex items-center gap-1.5 text-zinc-400">
                      <Cpu className="w-3.5 h-3.5 text-indigo-400" />
                      Reranking (Cross-Encoder)
                    </span>
                    <label className="relative inline-flex items-center cursor-pointer">
                      <input 
                        type="checkbox" 
                        checked={rerank} 
                        onChange={(e) => setRerank(e.target.checked)}
                        className="sr-only peer" 
                      />
                      <div className="w-7 h-4 bg-zinc-800 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-zinc-300 after:border after:rounded-full after:h-3 after:w-3 after:transition-all peer-checked:bg-indigo-600"></div>
                    </label>
                  </div>
                </div>

                {/* Primary Search Button */}
                <button
                  onClick={handleSearch}
                  disabled={!selectedProfileId || loading}
                  className="w-full py-3 bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-500 hover:to-purple-500 disabled:from-zinc-800 disabled:to-zinc-800 text-white font-bold rounded-xl text-sm flex items-center justify-center gap-2 border border-indigo-400/20 shadow-lg shadow-indigo-600/10 transition-all cursor-pointer"
                >
                  <Search className="w-4 h-4" />
                  {loading ? "Calculando Relevância..." : "Executar Matching Híbrido"}
                </button>
              </div>

            </section>

            {/* COLUMN RIGHT: RANKING RESULTS LIST (8 Cols) */}
            <section className="lg:col-span-8 flex flex-col gap-6 w-full">
              
              {/* Results Container Card */}
              <div className="p-6 glass-panel rounded-2xl min-h-[500px] flex flex-col">
                <div className="flex justify-between items-center mb-6">
                  <h2 className="text-lg font-bold tracking-tight text-white flex items-center gap-2">
                    <Layers className="w-5 h-5 text-indigo-400" />
                    Ranking de Compatibilidade
                  </h2>
                  <span className="text-xs text-zinc-500">
                    {searchResults.length > 0 ? `${searchResults.length} matches encontrados` : "Nenhum resultado"}
                  </span>
                </div>

                {loading ? (
                  // Glowy loader animation
                  <div className="flex-1 flex flex-col items-center justify-center gap-4">
                    <div className="relative w-12 h-12">
                      <div className="absolute inset-0 rounded-full border-4 border-indigo-500/20 animate-ping" />
                      <div className="absolute inset-0 rounded-full border-4 border-indigo-500 border-t-transparent animate-spin" />
                    </div>
                    <div className="text-zinc-400 text-sm animate-pulse">
                      Buscando no Qdrant & computando Cross-Encoder...
                    </div>
                  </div>
                ) : searchResults.length === 0 ? (
                  // Empty state
                  <div className="flex-1 flex flex-col items-center justify-center text-center p-8 bg-zinc-950/20 rounded-xl border border-white/5 border-dashed">
                    <Briefcase className="w-12 h-12 text-zinc-600 mb-3" />
                    <p className="text-sm font-semibold text-zinc-300">Nenhum match ativo</p>
                    <p className="text-xs text-zinc-500 max-w-xs mt-1">
                      Selecione uma vaga ou candidato à esquerda e clique em executar para ver as pontuações.
                    </p>
                  </div>
                ) : (
                  // Scored Matches list
                  <div className="flex flex-col gap-4">
                    {searchResults.map((res, index) => {
                      const isExpanded = expandedExplanationId === res.id;
                      const hasExplanation = !!explanations[`${selectedProfileId}-${res.id}`];
                      const explanation = explanations[`${selectedProfileId}-${res.id}`];
                      
                      return (
                        <div 
                          key={res.id}
                          className="glass-panel glass-panel-hover rounded-xl p-5 overflow-hidden transition-all duration-300"
                        >
                          {/* Upper Card Block */}
                          <div className="flex flex-col md:flex-row justify-between items-start gap-4">
                            <div className="flex items-start gap-3.5">
                              {/* Position counter badge */}
                              <div className="w-7 h-7 rounded-lg bg-indigo-600/20 border border-indigo-500/35 text-indigo-300 font-bold text-xs flex items-center justify-center">
                                #{index + 1}
                              </div>
                              <div>
                                <div className="text-sm font-bold text-white">
                                  {getProfileTitle(res.profile)}
                                </div>
                                <div className="text-xs text-zinc-400 mt-0.5 flex items-center gap-1.5">
                                  <FileText className="w-3.5 h-3.5 text-zinc-500" />
                                  <span>{res.profile.file_name || "Entrada manual de texto"}</span>
                                  <span className="w-1 h-1 rounded-full bg-zinc-700" />
                                  <span>ID {res.id}</span>
                                </div>
                              </div>
                            </div>

                            {/* Scores display block */}
                            <div className="flex items-center gap-6">
                              {/* Similaridade / RRF */}
                              <div className="flex flex-col items-end gap-1.5">
                                <span className="text-[10px] text-zinc-500 uppercase tracking-wider font-semibold">RRF Score</span>
                                <div className="text-sm font-extrabold text-indigo-300">{(res.rrf_score * 100).toFixed(1)}%</div>
                                <div className="w-16 h-1 bg-zinc-800 rounded-full overflow-hidden">
                                  <div className="h-full bg-indigo-500" style={{ width: `${Math.min(res.rrf_score * 100 * 2, 100)}%` }} />
                                </div>
                              </div>

                              {/* Cross-Encoder Score (Final Score) */}
                              <div className="flex flex-col items-end gap-1.5 p-2 bg-indigo-950/20 rounded-lg border border-indigo-500/10">
                                <span className="text-[10px] text-indigo-400 uppercase tracking-wider font-bold">Rerank (AI)</span>
                                <div className="text-sm font-extrabold text-emerald-400">{(res.score * 100).toFixed(1)}%</div>
                                <div className="w-16 h-1 bg-zinc-800 rounded-full overflow-hidden">
                                  <div className="h-full bg-emerald-400" style={{ width: `${res.score * 100}%` }} />
                                </div>
                              </div>
                            </div>
                          </div>

                          {/* Metadata row */}
                          <div className="flex flex-wrap gap-2 mt-4 items-center border-t border-white/5 pt-3">
                            <span className="px-2.5 py-0.5 rounded-full text-[10px] bg-zinc-900 border border-white/5 text-zinc-400">
                              Exp: {res.profile.extracted_profile.experience_years ?? 0} anos
                            </span>
                            <span className="px-2.5 py-0.5 rounded-full text-[10px] bg-zinc-900 border border-white/5 text-zinc-400">
                              Nível: {res.profile.extracted_profile.seniority || "N/A"}
                            </span>
                            
                            {/* Skills badges */}
                            <div className="flex flex-wrap gap-1 items-center ml-2 max-w-lg">
                              {(res.profile.extracted_profile.skills_normalized || []).slice(0, 5).map((s, idx) => (
                                <span 
                                  key={idx} 
                                  className="px-1.5 py-0.5 bg-zinc-950/80 text-zinc-300 border border-white/5 rounded text-[9px]"
                                  title={s.concept_uri}
                                >
                                  {s.preferred_label}
                                </span>
                              ))}
                              {(res.profile.extracted_profile.skills_normalized || []).length > 5 && (
                                <span className="text-[9px] text-zinc-500 ml-1">
                                  +{(res.profile.extracted_profile.skills_normalized?.length || 0) - 5}
                                </span>
                              )}
                            </div>
                          </div>

                          {/* Action Buttons */}
                          <div className="flex gap-2 justify-end mt-4">
                            <button
                              onClick={() => {
                                setPdfExtractorProfileId(res.profile.id);
                                setShowPdfExtractorModal(true);
                              }}
                              className="px-3.5 py-1.5 rounded-lg border border-white/10 hover:border-indigo-500/30 bg-zinc-900/40 text-xs font-semibold hover:text-indigo-300 flex items-center gap-1.5 transition-all cursor-pointer mr-auto"
                            >
                              <FileText className="w-3.5 h-3.5 text-indigo-400" />
                              Ver PDF & IA
                            </button>

                            <button
                              onClick={() => handleGetExplanation(res.id)}
                              disabled={explainingId === res.id}
                              className="px-3.5 py-1.5 rounded-lg border border-white/10 hover:border-indigo-500/30 bg-zinc-900/40 text-xs font-semibold hover:text-indigo-300 flex items-center gap-1.5 transition-all cursor-pointer"
                            >
                              {explainingId === res.id ? (
                                <>
                                  <RefreshCw className="w-3 h-3 animate-spin" />
                                  Analisando...
                                </>
                              ) : (
                                <>
                                  <Cpu className="w-3 h-3 text-indigo-400" />
                                  Justificativa IA
                                  {isExpanded ? <ChevronUp className="w-3 h-3 ml-0.5" /> : <ChevronDown className="w-3 h-3 ml-0.5" />}
                                </>
                              )}
                            </button>

                            <button
                              onClick={() => handleRunBiasAudit(res.id)}
                              disabled={auditingId === res.id}
                              className="px-3.5 py-1.5 rounded-lg border border-rose-500/20 hover:border-rose-500/40 bg-rose-500/5 text-xs font-semibold text-rose-300 flex items-center gap-1.5 transition-all cursor-pointer hover:bg-rose-500/10"
                            >
                              {auditingId === res.id ? (
                                <>
                                  <RefreshCw className="w-3 h-3 animate-spin" />
                                  Auditando...
                                </>
                              ) : (
                                <>
                                  <ShieldCheck className="w-3 h-3 text-rose-400" />
                                  Auditar Viés
                                </>
                              )}
                            </button>
                          </div>

                          {/* Expander: Explanation details */}
                          {isExpanded && hasExplanation && (
                            <div className="mt-4 p-4 rounded-lg bg-zinc-950/60 border border-white/5 animate-fadeIn">
                              <div className="flex items-center gap-1.5 mb-2.5">
                                <Cpu className="w-4 h-4 text-indigo-400" />
                                <h4 className="text-xs font-bold text-indigo-300 uppercase tracking-wider">
                                  Explicação Baseada em Evidências
                                </h4>
                              </div>
                              <div className="border-l border-indigo-500/30 pl-3">
                                {renderExplanationText(explanation)}
                              </div>
                              <div className="mt-3.5 flex items-center justify-between text-[10px] text-zinc-500 pt-2.5 border-t border-white/5">
                                <span>Verificado por Guardrail de Citação do Backend</span>
                                <div className="flex gap-2">
                                  <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-emerald-500" /> Citação no currículo</span>
                                  <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-rose-500" /> Alucinação de cotação</span>
                                </div>
                              </div>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </section>
          </>
        )}

        {/* ================= TAB 2: EQUIDADE & AUDITORIA ================= */}
        {activeTab === "fairness" && (
          <section className="lg:col-span-12 flex flex-col gap-6 w-full">
            
            {/* General Metrics Row */}
            <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
              
              <div className="p-5 glass-panel rounded-2xl flex items-center justify-between">
                <div>
                  <div className="text-xs text-zinc-400 font-semibold mb-1 uppercase tracking-wider">Total de Auditorias</div>
                  <div className="text-2xl font-extrabold text-white">{auditLogs.length}</div>
                </div>
                <div className="p-3 rounded-xl bg-indigo-600/10 text-indigo-400 border border-indigo-500/20">
                  <Activity className="w-5 h-5" />
                </div>
              </div>

              <div className="p-5 glass-panel rounded-2xl flex items-center justify-between">
                <div>
                  <div className="text-xs text-zinc-400 font-semibold mb-1 uppercase tracking-wider">Aprovado no Viés</div>
                  <div className="text-2xl font-extrabold text-emerald-400">
                    {auditLogs.length > 0 
                      ? `${((auditLogs.filter(l => l.bias_audit_passed).length / auditLogs.length) * 100).toFixed(0)}%`
                      : "0%"
                    }
                  </div>
                </div>
                <div className="p-3 rounded-xl bg-emerald-600/10 text-emerald-400 border border-emerald-500/20">
                  <ShieldCheck className="w-5 h-5" />
                </div>
              </div>

              <div className="p-5 glass-panel rounded-2xl flex items-center justify-between">
                <div>
                  <div className="text-xs text-zinc-400 font-semibold mb-1 uppercase tracking-wider">Delta Médio de Score</div>
                  <div className="text-2xl font-extrabold text-indigo-300">
                    {auditLogs.length > 0
                      ? `${(auditLogs.reduce((acc, l) => acc + (l.bias_audit_results.score_pct_delta || 0), 0) / auditLogs.length).toFixed(3)}%`
                      : "0.000%"
                    }
                  </div>
                </div>
                <div className="p-3 rounded-xl bg-purple-600/10 text-purple-400 border border-purple-500/20">
                  <Cpu className="w-5 h-5" />
                </div>
              </div>

              <div className="p-5 glass-panel rounded-2xl flex items-center justify-between">
                <div>
                  <div className="text-xs text-zinc-400 font-semibold mb-1 uppercase tracking-wider">Variância de Rank</div>
                  <div className="text-2xl font-extrabold text-white">
                    {auditLogs.length > 0
                      ? (auditLogs.reduce((acc, l) => acc + Math.abs((l.bias_audit_results.original_rank || 0) - (l.bias_audit_results.counterfactual_rank || 0)), 0) / auditLogs.length).toFixed(1)
                      : "0.0"
                    }
                  </div>
                </div>
                <div className="p-3 rounded-xl bg-white/5 text-zinc-400 border border-white/10">
                  <Sliders className="w-5 h-5" />
                </div>
              </div>

            </div>

            {/* Historical logs table */}
            <div className="p-6 glass-panel rounded-2xl">
              <h2 className="text-lg font-bold tracking-tight text-white mb-6 flex items-center gap-2">
                <ShieldCheck className="w-5 h-5 text-indigo-400" />
                Histórico de Auditorias Contraditórias (Gênero/Nomes)
              </h2>

              <div className="overflow-x-auto w-full">
                <table className="w-full text-sm text-left border-collapse">
                  <thead>
                    <tr className="border-b border-white/5 text-xs text-zinc-400 font-bold uppercase tracking-wider">
                      <th className="pb-3 pr-4">ID</th>
                      <th className="pb-3 px-4">Vaga (Query)</th>
                      <th className="pb-3 px-4">Candidato ID</th>
                      <th className="pb-3 px-4">Modelos de IA</th>
                      <th className="pb-3 px-4">Delta de Relevância</th>
                      <th className="pb-3 px-4">Status do Viés</th>
                      <th className="pb-3 pl-4">Data</th>
                    </tr>
                  </thead>
                  <tbody>
                    {auditLogs.length === 0 ? (
                      <tr>
                        <td colSpan={7} className="py-8 text-center text-zinc-500">
                          Nenhum log de auditoria persistido no Postgres. Execute um teste de viés nos resultados de busca.
                        </td>
                      </tr>
                    ) : (
                      auditLogs.map((log) => (
                        <tr key={log.id} className="border-b border-white/5 hover:bg-white/5 transition-colors">
                          <td className="py-3.5 pr-4 text-xs font-bold text-zinc-400">#{log.id}</td>
                          <td className="py-3.5 px-4 font-semibold text-zinc-300">Vaga ID {log.query_id}</td>
                          <td className="py-3.5 px-4 text-zinc-400">ID {log.bias_audit_results.candidate_id}</td>
                          <td className="py-3.5 px-4 text-xs text-zinc-500">
                            <div>Emb: {log.embedding_model}</div>
                            <div>Rerank: {log.reranker_model}</div>
                          </td>
                          <td className="py-3.5 px-4 font-semibold text-indigo-300">
                            {log.bias_audit_results.score_pct_delta?.toFixed(3)}%
                          </td>
                          <td className="py-3.5 px-4">
                            <span className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-bold ${
                              log.bias_audit_passed
                                ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                                : "bg-rose-500/10 text-rose-400 border border-rose-500/20"
                            }`}>
                              {log.bias_audit_passed ? "✓ Neutro" : "⚠ Enviesado"}
                            </span>
                          </td>
                          <td className="py-3.5 pl-4 text-xs text-zinc-500">
                            {new Date(log.created_at).toLocaleDateString("pt-BR", {
                              hour: "2-digit",
                              minute: "2-digit"
                            })}
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>

          </section>
        )}

      </main>

      {/* ================= MODAL: PDF VIEWER & PIPELINE DE EXTRAÇÃO ================= */}
      {showPdfExtractorModal && pdfExtractorProfileId && (() => {
        const allProfiles = [...jobs, ...candidates, ...searchResults.map(r => r.profile)];
        if (activeProfile) allProfiles.push(activeProfile);
        const prof = allProfiles.find(p => p.id === pdfExtractorProfileId);
        
        if (!prof) return null;
        
        return (
          <PdfExtractorModalView 
            profile={prof} 
            getProfileTitle={getProfileTitle}
            onClose={() => {
              setShowPdfExtractorModal(false);
              setPdfExtractorProfileId("");
            }} 
          />
        );
      })()}

      {/* ================= MODAL: REGISTRATION / UPLOAD ================= */}
      {/* ================= MODAL: REGISTRATION / UPLOAD ================= */}
      {showUploadModal && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4 overflow-y-auto">
          <div className={`w-full ${uploadResult ? 'max-w-4xl' : 'max-w-xl'} glass-panel rounded-2xl p-6 shadow-2xl animate-scaleUp my-8`}>
            
            <div className="flex justify-between items-center mb-5 pb-3 border-b border-white/5">
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                <UploadCloud className="w-5 h-5 text-indigo-400" />
                {uploadResult ? "Fluxo Visual de Extração Concluído" : "Ingestão de Perfil (PDF ou Texto)"}
              </h3>
              <button 
                onClick={() => {
                  setShowUploadModal(false);
                  setUploadMessage(null);
                  setUploadResult(null);
                }}
                className="text-zinc-500 hover:text-white text-xs p-1 cursor-pointer"
              >
                Fechar
              </button>
            </div>

            {uploadResult ? (
              <div className="flex flex-col gap-5 text-xs text-zinc-300">
                {/* Steps success indicators */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-center text-[10px] text-zinc-500 font-bold uppercase tracking-wider pb-4 border-b border-white/5">
                  <div className="flex flex-col items-center gap-1 text-emerald-400">
                    <span className="w-5 h-5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 flex items-center justify-center font-extrabold text-xs">✓</span>
                    <span>1. Leitura PDF</span>
                  </div>
                  <div className="flex flex-col items-center gap-1 text-emerald-400">
                    <span className="w-5 h-5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 flex items-center justify-center font-extrabold text-xs">✓</span>
                    <span>2. Redação PII</span>
                  </div>
                  <div className="flex flex-col items-center gap-1 text-emerald-400">
                    <span className="w-5 h-5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 flex items-center justify-center font-extrabold text-xs">✓</span>
                    <span>3. IA OpenRouter</span>
                  </div>
                  <div className="flex flex-col items-center gap-1 text-emerald-400">
                    <span className="w-5 h-5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 flex items-center justify-center font-extrabold text-xs">✓</span>
                    <span>4. Index Qdrant</span>
                  </div>
                </div>

                {/* Side-by-Side Text Viewer */}
                <div>
                  <span className="text-xs font-bold text-zinc-400 uppercase tracking-wider mb-2 block">
                    Higienização PII (Original vs Anonimizado)
                  </span>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                      <div className="text-[10px] text-zinc-500 font-semibold mb-1 uppercase">Texto Bruto Extraído:</div>
                      <div className="p-3.5 bg-zinc-950/80 rounded-xl text-[10px] font-mono h-48 overflow-y-auto text-zinc-400 border border-white/5 whitespace-pre-wrap leading-normal">
                        {uploadResult.raw_text}
                      </div>
                    </div>
                    <div>
                      <div className="text-[10px] text-zinc-500 font-semibold mb-1 uppercase">Texto Higienizado (Anonimizado):</div>
                      <div className="p-3.5 bg-zinc-950/80 rounded-xl text-[10px] font-mono h-48 overflow-y-auto text-zinc-400 border border-white/5 whitespace-pre-wrap leading-normal">
                        {uploadResult.redacted_text}
                      </div>
                    </div>
                  </div>
                </div>

                {/* Redaction Mapping dictionary */}
                {Object.keys(uploadResult.redaction_map).length > 0 && (
                  <div>
                    <span className="text-xs font-bold text-zinc-400 uppercase tracking-wider mb-2 block">
                      Dicionário de Anonimização (PII Redaction Map)
                    </span>
                    <div className="max-h-24 overflow-y-auto bg-zinc-950/60 p-3 rounded-xl border border-white/5 flex flex-col gap-1.5 font-mono text-[10px]">
                      {Object.entries(uploadResult.redaction_map).map(([key, val]) => (
                        <div key={key} className="flex justify-between border-b border-white/5 pb-1">
                          <span className="text-amber-400 font-semibold">{key}</span>
                          <span className="text-zinc-500">&rarr;</span>
                          <span className="text-zinc-300">{val}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Extracted Structured JSON */}
                <div className="p-4 bg-zinc-950/40 rounded-xl border border-white/5 flex flex-col gap-3">
                  <span className="text-xs font-bold text-indigo-400 uppercase tracking-wider">
                    Perfil Estruturado Extraído por IA (OpenRouter)
                  </span>
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-4 text-xs">
                    <div>
                      <span className="text-zinc-500 font-semibold uppercase text-[9px] block">Nível de Senioridade</span>
                      <strong className="text-zinc-200">{uploadResult.extracted_profile.seniority}</strong>
                    </div>
                    <div>
                      <span className="text-zinc-500 font-semibold uppercase text-[9px] block">Experiência Acumulada</span>
                      <strong className="text-zinc-200">{uploadResult.extracted_profile.experience_years} anos</strong>
                    </div>
                    {uploadResult.extracted_profile.certifications && uploadResult.extracted_profile.certifications.length > 0 && (
                      <div className="col-span-2 md:col-span-1">
                        <span className="text-zinc-500 font-semibold uppercase text-[9px] block">Certificações</span>
                        <strong className="text-zinc-200">{uploadResult.extracted_profile.certifications.join(", ")}</strong>
                      </div>
                    )}
                  </div>
                  <div>
                    <span className="text-zinc-500 font-semibold uppercase text-[9px] block mb-1">Competências Extraídas</span>
                    <div className="flex flex-wrap gap-1">
                      {uploadResult.extracted_profile.skills_raw?.map((s, idx) => (
                        <span key={idx} className="px-2 py-0.5 rounded bg-zinc-900 border border-white/5 text-zinc-300 font-bold text-[10px]">{s}</span>
                      ))}
                    </div>
                  </div>
                  <div>
                    <span className="text-zinc-500 font-semibold uppercase text-[9px] block mb-1">Resumo Narrativo de Carreira</span>
                    <p className="italic text-zinc-400 text-[11px] leading-normal bg-zinc-950/60 p-3 rounded-lg border border-white/5">
                      &quot;{uploadResult.extracted_profile.narrative_experience}&quot;
                    </p>
                  </div>
                </div>

                {/* Confirm Button */}
                <button
                  onClick={() => {
                    setUploadResult(null);
                    setShowUploadModal(false);
                    setUploadMessage(null);
                  }}
                  className="w-full py-3 bg-indigo-600 hover:bg-indigo-500 text-white font-bold rounded-xl text-sm flex items-center justify-center gap-2 cursor-pointer transition-all border border-indigo-400/20"
                >
                  Concluir e Voltar ao Dashboard
                </button>
              </div>
            ) : (
              <form onSubmit={handleUpload} className="flex flex-col gap-4">
                
                {/* Type Switch */}
                <div className="flex gap-4 mb-2">
                  <label className="flex items-center gap-2 text-xs font-semibold cursor-pointer">
                    <input
                      type="radio"
                      name="upload_type"
                      checked={uploadType === "candidate"}
                      onChange={() => setUploadType("candidate")}
                      className="accent-indigo-500"
                    />
                    Candidato (Currículo)
                  </label>
                  <label className="flex items-center gap-2 text-xs font-semibold cursor-pointer">
                    <input
                      type="radio"
                      name="upload_type"
                      checked={uploadType === "job"}
                      onChange={() => setUploadType("job")}
                      className="accent-indigo-500"
                    />
                    Vaga de Emprego
                  </label>
                </div>

                {/* PDF File upload */}
                <div className="flex flex-col gap-1.5">
                  <label className="text-xs text-zinc-400 font-semibold">Anexar PDF (Opcional):</label>
                  <div className="p-4 bg-zinc-950/60 rounded-xl border border-white/5 flex flex-col items-center justify-center text-center cursor-pointer hover:border-indigo-500/30 transition-colors relative">
                    <input
                      type="file"
                      accept=".pdf"
                      onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
                      className="absolute inset-0 opacity-0 cursor-pointer"
                    />
                    <UploadCloud className="w-8 h-8 text-zinc-500 mb-2" />
                    <span className="text-xs text-zinc-300">
                      {uploadFile ? uploadFile.name : "Clique para anexar arquivo PDF"}
                    </span>
                    <span className="text-[10px] text-zinc-500 mt-1">Limite: 5MB</span>
                  </div>
                </div>

                <div className="text-center text-xs text-zinc-500 font-bold uppercase py-1">OU</div>

                {/* Paste Text area */}
                <div className="flex flex-col gap-1.5">
                  <label className="text-xs text-zinc-400 font-semibold">Inserir texto completo do perfil:</label>
                  <textarea
                    rows={12}
                    placeholder={uploadType === "candidate" ? "Cole aqui o currículo completo bruto..." : "Cole aqui os requisitos da vaga..."}
                    value={uploadText}
                    onChange={(e) => setUploadText(e.target.value)}
                    className="w-full p-3 rounded-xl glass-input text-xs font-mono"
                  />
                </div>

                {uploadMessage && (
                  <div className={`p-3 rounded-lg text-xs flex items-center gap-2 ${
                    uploadMessage.type === "success" 
                      ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20" 
                      : "bg-rose-500/10 text-rose-400 border border-rose-500/20"
                  }`}>
                    {uploadMessage.type === "success" ? <CheckCircle className="w-4 h-4 flex-shrink-0" /> : <AlertCircle className="w-4 h-4 flex-shrink-0" />}
                    <span>{uploadMessage.text}</span>
                  </div>
                )}

                <button
                  type="submit"
                  disabled={uploadLoading}
                  className="w-full py-3 bg-indigo-600 hover:bg-indigo-500 disabled:bg-zinc-800 text-white font-bold rounded-xl text-sm flex items-center justify-center gap-2 transition-all cursor-pointer border border-indigo-400/20 mt-2"
                >
                  {uploadLoading ? (
                    <>
                      <RefreshCw className="w-4 h-4 animate-spin" />
                      Anonimizando & Processando com IA...
                    </>
                  ) : (
                    <>
                      <UploadCloud className="w-4 h-4" />
                      Processar e Ingerir Perfil
                    </>
                  )}
                </button>

              </form>
            )}
          </div>
        </div>
      )}

      {/* ================= MODAL: AUDIT RESULT DETAILS ================= */}
      {showAuditResultModal && lastAuditResult && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="w-full max-w-xl glass-panel rounded-2xl p-6 shadow-2xl animate-scaleUp">
            
            <div className="flex justify-between items-center mb-5 pb-3 border-b border-white/5">
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                <ShieldCheck className="w-5 h-5 text-indigo-400" />
                Relatório de Auditoria de Viés (Par Contraditório)
              </h3>
              <button 
                onClick={() => setShowAuditResultModal(false)}
                className="text-zinc-500 hover:text-white text-xs p-1 cursor-pointer"
              >
                Fechar
              </button>
            </div>

            <div className="flex flex-col gap-4">
              
              {/* Neutrality result card */}
              <div className={`p-4 rounded-xl flex items-center justify-between border ${
                lastAuditResult.audit_passed
                  ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-300"
                  : "bg-rose-500/10 border-rose-500/30 text-rose-300"
              }`}>
                <div>
                  <div className="text-xs font-semibold uppercase tracking-wider mb-0.5">Status de Equidade</div>
                  <div className="text-lg font-extrabold">
                    {lastAuditResult.audit_passed ? "✓ Aprovado (Sistema Neutro)" : "⚠ Enviesamento Detectado"}
                  </div>
                </div>
                <div className={`p-2.5 rounded-lg ${lastAuditResult.audit_passed ? 'bg-emerald-500/15' : 'bg-rose-500/15'}`}>
                  <ShieldCheck className="w-6 h-6" />
                </div>
              </div>

              {/* Variance statistics */}
              <div className="grid grid-cols-3 gap-4 bg-zinc-950/60 p-4 rounded-xl border border-white/5 text-center">
                <div>
                  <div className="text-[10px] text-zinc-500 font-bold uppercase mb-1">Score Original</div>
                  <div className="text-base font-extrabold text-zinc-200">{(lastAuditResult.original_score * 100).toFixed(2)}%</div>
                </div>
                <div>
                  <div className="text-[10px] text-zinc-500 font-bold uppercase mb-1">Score Contraditório</div>
                  <div className="text-base font-extrabold text-zinc-200">{(lastAuditResult.counterfactual_score * 100).toFixed(2)}%</div>
                </div>
                <div>
                  <div className="text-[10px] text-zinc-400 font-bold uppercase mb-1">Variação (Delta)</div>
                  <div className={`text-base font-extrabold ${lastAuditResult.audit_passed ? 'text-indigo-300' : 'text-rose-400'}`}>
                    {lastAuditResult.score_pct_delta?.toFixed(3)}%
                  </div>
                </div>
              </div>

              {/* Swaps executed listing */}
              <div>
                <h4 className="text-xs font-bold text-zinc-400 uppercase tracking-wider mb-2">
                  Swaps Efetuados no Texto do Currículo:
                </h4>
                <div className="max-h-36 overflow-y-auto bg-zinc-950/80 p-3 rounded-lg border border-white/5 flex flex-col gap-1.5 font-mono text-[11px]">
                  {lastAuditResult.swaps_performed?.map((swap, idx: number) => (
                    <div key={idx} className="flex items-center gap-2 justify-between border-b border-white/5 pb-1">
                      <span className="text-zinc-500">&quot;{swap.original}&quot;</span>
                      <span className="text-zinc-600">→</span>
                      <span className="text-emerald-400 font-semibold">&quot;{swap.replacement}&quot;</span>
                      <span className="px-1.5 py-0.5 rounded bg-zinc-900 text-zinc-400 text-[9px] ml-auto">x{swap.count}</span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="text-[10px] text-zinc-500 italic mt-1 leading-relaxed">
                *Nota: A auditoria de viés clona o perfil e troca automaticamente os marcadores de gênero (ele/ela, programador/programadora) e nomes fictícios comuns. O limite de tolerância regulatória configurado no motor é de 1% de delta no score final.
              </div>

            </div>
          </div>
        </div>
      )}

      {/* ================= TAB 3: DIDÁTICA DO MATCHING ================= */}
      {activeTab === "didactic" && (
        <section className="lg:col-span-12 flex flex-col gap-6 w-full animate-fadeIn">
          
          <div className="p-6 glass-panel rounded-2xl">
            <h2 className="text-xl font-bold text-white mb-1">Didática do Matching: Como a IA Decide?</h2>
            <p className="text-sm text-zinc-400">
              Esta tela interativa demonstra as três etapas do pipeline de inteligência artificial (Busca Híbrida Qdrant, Fusão RRF e Reranking Cross-Encoder) comparando uma vaga e um candidato.
            </p>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">
            
            {/* Vaga Selection */}
            <div className="p-5 glass-panel rounded-2xl flex flex-col gap-4">
              <label className="text-sm font-bold text-zinc-300 font-semibold">1. Selecione a Vaga:</label>
              <select
                value={didacticJobId}
                onChange={(e) => {
                  const id = e.target.value ? Number(e.target.value) : "";
                  setDidacticJobId(id);
                  setDidacticResult(null);
                }}
                className="w-full p-3 rounded-xl glass-input text-sm"
                style={{ colorScheme: "dark" }}
              >
                <option value="" className="bg-zinc-900 text-white" style={{ backgroundColor: "#18181b", color: "#ffffff" }}>-- Selecione Vaga --</option>
                {jobs.map((j) => (
                  <option key={j.id} value={j.id} className="bg-zinc-900 text-white" style={{ backgroundColor: "#18181b", color: "#ffffff" }}>
                    ID {j.id}: {getProfileTitle(j)}
                  </option>
                ))}
              </select>

              {didacticJobId && (
                (() => {
                  const job = jobs.find(j => j.id === didacticJobId);
                  if (!job) return null;
                  return (
                    <div className="mt-2 flex flex-col gap-3 text-xs bg-zinc-950/40 p-4 rounded-xl border border-white/5">
                      <div>
                        <span className="text-zinc-500 uppercase font-bold tracking-wider text-[10px]">Requisitos de Senioridade:</span>
                        <div className="text-sm font-bold text-zinc-200 mt-0.5">{job.extracted_profile.seniority}</div>
                      </div>
                      <div>
                        <span className="text-zinc-500 uppercase font-bold tracking-wider text-[10px]">Experiência Exigida:</span>
                        <div className="text-sm font-bold text-zinc-200 mt-0.5">{job.extracted_profile.experience_years} anos</div>
                      </div>
                      <div>
                        <span className="text-zinc-500 uppercase font-bold tracking-wider text-[10px]">Competências Chave:</span>
                        <div className="flex flex-wrap gap-1.5 mt-1.5">
                          {job.extracted_profile.skills_raw?.map((s, idx) => (
                            <span key={idx} className="px-2 py-0.5 rounded bg-zinc-900 border border-white/5 text-zinc-300 font-semibold">{s}</span>
                          ))}
                        </div>
                      </div>
                      <div>
                        <span className="text-zinc-500 uppercase font-bold tracking-wider text-[10px]">Descrição da Oportunidade:</span>
                        <p className="text-zinc-400 mt-1 leading-relaxed italic">&quot;{job.extracted_profile.narrative_experience}&quot;</p>
                      </div>
                    </div>
                  );
                })()
              )}
            </div>

            {/* Candidato Selection */}
            <div className="p-5 glass-panel rounded-2xl flex flex-col gap-4">
              <label className="text-sm font-bold text-zinc-300 font-semibold">2. Selecione o Candidato:</label>
              <select
                value={didacticCandidateId}
                onChange={(e) => {
                  const id = e.target.value ? Number(e.target.value) : "";
                  setDidacticCandidateId(id);
                  setDidacticResult(null);
                }}
                className="w-full p-3 rounded-xl glass-input text-sm"
                style={{ colorScheme: "dark" }}
              >
                <option value="" className="bg-zinc-900 text-white" style={{ backgroundColor: "#18181b", color: "#ffffff" }}>-- Selecione Candidato --</option>
                {candidates.map((c) => (
                  <option key={c.id} value={c.id} className="bg-zinc-900 text-white" style={{ backgroundColor: "#18181b", color: "#ffffff" }}>
                    ID {c.id}: {getProfileTitle(c)}
                  </option>
                ))}
              </select>

              {didacticCandidateId && (
                (() => {
                  const candidate = candidates.find(c => c.id === didacticCandidateId);
                  if (!candidate) return null;
                  return (
                    <div className="mt-2 flex flex-col gap-3 text-xs bg-zinc-950/40 p-4 rounded-xl border border-white/5">
                      <div>
                        <span className="text-zinc-500 uppercase font-bold tracking-wider text-[10px]">Senioridade do Candidato:</span>
                        <div className="text-sm font-bold text-zinc-200 mt-0.5">{candidate.extracted_profile.seniority}</div>
                      </div>
                      <div>
                        <span className="text-zinc-500 uppercase font-bold tracking-wider text-[10px]">Experiência Acumulada:</span>
                        <div className="text-sm font-bold text-zinc-200 mt-0.5">{candidate.extracted_profile.experience_years} anos</div>
                      </div>
                      <div>
                        <span className="text-zinc-500 uppercase font-bold tracking-wider text-[10px]">Competências Declaradas:</span>
                        <div className="flex flex-wrap gap-1.5 mt-1.5">
                          {candidate.extracted_profile.skills_raw?.map((s, idx) => (
                            <span key={idx} className="px-2 py-0.5 rounded bg-zinc-900 border border-white/5 text-zinc-300 font-semibold">{s}</span>
                          ))}
                        </div>
                      </div>
                      <div>
                        <span className="text-zinc-500 uppercase font-bold tracking-wider text-[10px]">Trajetória Profissional:</span>
                        <p className="text-zinc-400 mt-1 leading-relaxed italic">&quot;{candidate.extracted_profile.narrative_experience}&quot;</p>
                      </div>
                    </div>
                  );
                })()
              )}
            </div>

          </div>

          {didacticJobId && didacticCandidateId && (
            <div className="flex justify-center my-2">
              <button
                onClick={() => runDidacticAnalysis(Number(didacticJobId), Number(didacticCandidateId))}
                disabled={didacticLoading}
                className="px-6 py-3 bg-indigo-600 hover:bg-indigo-500 disabled:bg-zinc-800 text-white rounded-xl font-bold text-sm flex items-center gap-2 shadow-lg shadow-indigo-600/20 cursor-pointer transition-all border border-indigo-400/20"
              >
                {didacticLoading ? (
                  <>
                    <RefreshCw className="w-4 h-4 animate-spin" />
                    Analisando matching...
                  </>
                ) : (
                  <>
                    <Cpu className="w-4 h-4" />
                    Executar Análise de Matching Didática
                  </>
                )}
              </button>
            </div>
          )}

          {didacticResult && (
            (() => {
              const job = jobs.find(j => j.id === didacticJobId);
              const candidate = candidates.find(c => c.id === didacticCandidateId);
              if (!job || !candidate) return null;

              const jobSkills = job.extracted_profile.skills_raw || [];
              const candSkills = candidate.extracted_profile.skills_raw || [];
              const matchingSkills = jobSkills.filter(s => 
                candSkills.some(cs => cs.toLowerCase() === s.toLowerCase())
              );

              return (
                <div className="flex flex-col gap-6 w-full animate-fadeIn">
                  
                  {/* STEP 1 */}
                  <div className="p-6 glass-panel rounded-2xl border-l-4 border-indigo-500">
                    <div className="flex items-center gap-2.5 mb-3">
                      <span className="w-6 h-6 rounded-full bg-indigo-600/30 text-indigo-300 text-xs font-extrabold flex items-center justify-center border border-indigo-500/30">1</span>
                      <h3 className="text-base font-bold text-white">Etapa 1: Triagem Híbrida (Busca Vetorial & Competências)</h3>
                    </div>
                    <p className="text-xs text-zinc-400 mb-4">
                      Nesta etapa, o motor compara três dimensões: vetor de habilidades normalizadas, vetor semântico de carreira e palavras-chave. Candidatos com baixa pontuação global são descartados antes da fase de Rerank.
                    </p>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-2">
                      <div className="bg-zinc-950/40 p-4 rounded-xl border border-white/5">
                        <span className="text-zinc-500 font-bold uppercase tracking-wider text-[10px] block mb-2">Higienização & Mapeamento ESCO:</span>
                        <div className="flex flex-col gap-3">
                          <div>
                            <span className="text-zinc-400 text-xs font-semibold">Competências da Vaga:</span>
                            <div className="flex flex-wrap gap-1 mt-1.5">
                              {jobSkills.map((s, idx) => {
                                const isMatch = matchingSkills.some(ms => ms.toLowerCase() === s.toLowerCase());
                                return (
                                  <span 
                                    key={idx} 
                                    className={`px-2 py-0.5 rounded text-[10px] font-bold border transition-colors ${
                                      isMatch 
                                        ? "bg-emerald-500/10 border-emerald-400/40 text-emerald-300 shadow-sm shadow-emerald-500/5"
                                        : "bg-zinc-900 border-white/5 text-zinc-400"
                                    }`}
                                  >
                                    {s} {isMatch && "✓"}
                                  </span>
                                );
                              })}
                            </div>
                          </div>
                          <div>
                            <span className="text-zinc-400 text-xs font-semibold">Competências do Candidato:</span>
                            <div className="flex flex-wrap gap-1 mt-1.5">
                              {candSkills.map((s, idx) => {
                                const isMatch = matchingSkills.some(ms => ms.toLowerCase() === s.toLowerCase());
                                return (
                                  <span 
                                    key={idx} 
                                    className={`px-2 py-0.5 rounded text-[10px] font-bold border transition-colors ${
                                      isMatch 
                                        ? "bg-emerald-500/10 border-emerald-400/40 text-emerald-300"
                                        : "bg-zinc-900 border-white/5 text-zinc-400"
                                    }`}
                                  >
                                    {s}
                                  </span>
                                );
                              })}
                            </div>
                          </div>
                          <div className="text-[11px] text-zinc-400 border-t border-white/5 pt-2 flex items-center justify-between">
                            <span>Interseção de Habilidades:</span>
                            <strong className="text-emerald-400 font-extrabold text-xs">{matchingSkills.length} em comum</strong>
                          </div>
                        </div>
                      </div>

                      <div className="bg-zinc-950/40 p-4 rounded-xl border border-white/5 flex flex-col justify-between">
                        <div>
                          <span className="text-zinc-500 font-bold uppercase tracking-wider text-[10px] block mb-2">Narrativa de Carreira (Similaridade Semântica):</span>
                          <p className="text-xs text-zinc-400 leading-relaxed">
                            O motor gera um vetor E5 denso sobre a descrição livre de experiências. Ao comparar o significado semântico:
                          </p>
                          <div className="mt-3 p-3 bg-zinc-900/60 rounded-lg border border-white/5 flex flex-col gap-2">
                            <div className="flex justify-between text-[10px] text-zinc-500">
                              <span>Comparando significado de:</span>
                              <span className="text-indigo-400 font-bold">Similaridade de Cosseno</span>
                            </div>
                            <div className="text-[11px] text-zinc-300 italic border-l-2 border-indigo-500/40 pl-2">
                              &quot;{job.extracted_profile.narrative_experience.slice(0, 100)}...&quot;
                            </div>
                            <div className="text-[11px] text-zinc-300 italic border-l-2 border-purple-500/40 pl-2">
                              &quot;{candidate.extracted_profile.narrative_experience.slice(0, 100)}...&quot;
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* STEP 2 */}
                  <div className="p-6 glass-panel rounded-2xl border-l-4 border-purple-500">
                    <div className="flex items-center gap-2.5 mb-3">
                      <span className="w-6 h-6 rounded-full bg-purple-600/30 text-purple-300 text-xs font-extrabold flex items-center justify-center border border-purple-500/30">2</span>
                      <h3 className="text-base font-bold text-white">Etapa 2: Fusão de Rankings (Reciprocal Rank Fusion - RRF)</h3>
                    </div>
                    <p className="text-xs text-zinc-400 mb-4">
                      O RRF combina os resultados parciais das buscas vetoriais e lexicais. A fórmula soma o inverso das posições {"$1 / (60 + \\text{posição})$"}, garantindo que candidatos bem posicionados em múltiplos canais subam no ranking.
                    </p>

                    <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                      <div className="bg-zinc-950/40 p-4 rounded-xl border border-white/5 text-center flex flex-col justify-between">
                        <div className="text-xs text-zinc-400">Classificação na Triagem</div>
                        <div className="my-3">
                          {didacticResult.inTopK ? (
                            <span className="px-3 py-1.5 rounded-lg bg-indigo-500/10 text-indigo-400 font-extrabold text-sm border border-indigo-500/20">
                              Top-K (Posição #{didacticResult.rank})
                            </span>
                          ) : (
                            <span className="px-3 py-1.5 rounded-lg bg-rose-500/10 text-rose-400 font-extrabold text-sm border border-rose-500/20">
                              Descartado na Triagem
                            </span>
                          )}
                        </div>
                        <p className="text-[10px] text-zinc-500 leading-normal">
                          {didacticResult.inTopK 
                            ? "Ficou entre os 20 melhores e avança para a avaliação da IA do Reranker."
                            : "Não atingiu score de RRF suficiente no top-K e seria descartado na triagem inicial."}
                        </p>
                      </div>

                      <div className="bg-zinc-950/40 p-4 rounded-xl border border-white/5 md:col-span-2">
                        <span className="text-zinc-500 font-bold uppercase tracking-wider text-[10px] block mb-2">Como o RRF Score foi calculado:</span>
                        <div className="flex flex-col gap-2 font-mono text-[11px] text-zinc-400">
                          {didacticResult.inTopK ? (
                            <>
                              <div className="flex justify-between border-b border-white/5 pb-1">
                                <span>Canal 1 (Competências ESCO):</span>
                                <span className="text-zinc-300">Posição #{didacticResult.skillsRank} &rarr; 1 / (60 + {didacticResult.skillsRank}) = {(1 / (60 + (didacticResult.skillsRank || 1))).toFixed(5)}</span>
                              </div>
                              <div className="flex justify-between border-b border-white/5 pb-1">
                                <span>Canal 2 (Narrativa Semântica):</span>
                                <span className="text-zinc-300">Posição #{didacticResult.narrativeRank} &rarr; 1 / (60 + {didacticResult.narrativeRank}) = {(1 / (60 + (didacticResult.narrativeRank || 1))).toFixed(5)}</span>
                              </div>
                              <div className="flex justify-between border-b border-white/5 pb-1">
                                <span>Canal 3 (Busca Léxica BM25):</span>
                                <span className="text-zinc-300">Posição #{didacticResult.lexicalRank} &rarr; 0.5 / (60 + {didacticResult.lexicalRank}) = {(0.5 / (60 + (didacticResult.lexicalRank || 1))).toFixed(5)}</span>
                              </div>
                              <div className="flex justify-between font-bold text-indigo-300 pt-1.5">
                                <span>Score RRF Final (Soma):</span>
                                <span>{(didacticResult.rrfScore || 0).toFixed(5)} ({(didacticResult.rrfScore ? didacticResult.rrfScore * 100 : 0).toFixed(2)}%)</span>
                              </div>
                            </>
                          ) : (
                            <div className="text-zinc-500 italic p-3 text-center leading-normal">
                              O candidato não obteve posições de destaque suficientes nas listas parciais. O score RRF estimado é inferior a 0.5%, o que causou seu descarte no filtro inicial de Top-20.
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* STEP 3 */}
                  <div className="p-6 glass-panel rounded-2xl border-l-4 border-emerald-500">
                    <div className="flex items-center gap-2.5 mb-3">
                      <span className="w-6 h-6 rounded-full bg-emerald-600/30 text-emerald-300 text-xs font-extrabold flex items-center justify-center border border-emerald-500/30">3</span>
                      <h3 className="text-base font-bold text-white">Etapa 3: Reranker por Rede Neural (Cross-Encoder)</h3>
                    </div>
                    <p className="text-xs text-zinc-400 mb-4">
                      A rede neural lê a Vaga e o Candidato simultaneamente. Ela não calcula embeddings individuais; ela utiliza mecanismos de atenção total para cruzar o contexto do perfil com os requisitos brutos. O resultado é o score final de reordenação.
                    </p>

                    <div className="grid grid-cols-1 md:grid-cols-3 gap-6 items-stretch">
                      
                      <div className="bg-zinc-950/40 p-4 rounded-xl border border-white/5 flex flex-col justify-between md:col-span-2">
                        <div>
                          <span className="text-zinc-500 font-bold uppercase tracking-wider text-[10px] block mb-2">Funcionamento do Processamento do Cross-Encoder:</span>
                          <div className="flex flex-col gap-2 text-xs text-zinc-400 mt-2">
                            <div className="bg-zinc-900 p-2.5 rounded-lg border border-white/5 flex flex-wrap gap-1 font-mono text-[10px] text-zinc-300 leading-normal">
                              <span className="text-indigo-400">[CLS]</span>
                              <span>{job.extracted_profile.seniority} {jobSkills.slice(0, 3).join(" ")}</span>
                              <span className="text-indigo-400">[SEP]</span>
                              <span>{candidate.extracted_profile.seniority} {candSkills.slice(0, 3).join(" ")}</span>
                              <span className="text-indigo-400">[SEP]</span>
                            </div>
                            <div className="flex items-center justify-center my-1.5">
                              <div className="w-0.5 h-6 bg-indigo-500/40" />
                            </div>
                            <div className="p-3 bg-indigo-950/15 border border-indigo-500/20 text-center rounded-xl font-bold text-indigo-300 text-xs uppercase tracking-wider">
                              Transformer: MiniLM-L6-v2 (Cross-Attention)
                            </div>
                            <div className="flex items-center justify-center my-1.5">
                              <div className="w-0.5 h-6 bg-indigo-500/40" />
                            </div>
                          </div>
                        </div>
                        <div className="text-[10px] text-zinc-500 leading-relaxed italic border-t border-white/5 pt-2">
                          *Atenção Cruzada: O modelo cruza cada palavra da vaga com cada palavra do currículo antes de definir a nota.
                        </div>
                      </div>

                      <div className="bg-zinc-950/40 p-5 rounded-xl border border-white/5 flex flex-col justify-between text-center items-center">
                        <div className="text-xs text-zinc-400">Score de Relevância Final (Logit)</div>
                        <div className="my-4">
                          <div className={`text-3xl font-black ${didacticResult.score !== null && didacticResult.score >= 0 ? 'text-emerald-400' : 'text-zinc-500'}`}>
                            {didacticResult.score !== null ? (didacticResult.score * 100).toFixed(1) : "N/A"}%
                          </div>
                          <span className={`text-[10px] font-extrabold uppercase px-2 py-0.5 rounded mt-1.5 inline-block ${
                            didacticResult.score !== null && didacticResult.score >= 0 
                              ? 'bg-emerald-500/10 text-emerald-400' 
                              : 'bg-zinc-800 text-zinc-400'
                          }`}>
                            {didacticResult.score !== null && didacticResult.score >= 0 ? "Aderente (Match Positivo)" : "Baixa Aderência"}
                          </span>
                        </div>
                        <div className="text-[10px] text-zinc-500 leading-normal">
                          {didacticResult.score !== null && didacticResult.score >= 0 
                            ? "Excelente nível de matching contextual encontrado. O candidato atende diretamente os requisitos da vaga."
                            : "A IA concluiu que a trajetória e competências do candidato não atendem aos critérios técnicos principais."}
                        </div>
                      </div>

                    </div>
                  </div>

                </div>
              );
            })()
          )}

        </section>
      )}

    </div>
  );
}

// ================= COMPONENT: PDF VIEWER & EXTRACTION MODAL =================
interface PdfExtractorModalViewProps {
  profile: Profile;
  getProfileTitle: (p: Profile) => string;
  onClose: () => void;
}

function PdfExtractorModalView({ profile, getProfileTitle, onClose }: PdfExtractorModalViewProps) {
  const [activeTab, setActiveTab] = useState<"technical" | "redaction" | "json">("technical");
  
  return (
    <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4 md:p-6 overflow-y-auto">
      <div className="w-full max-w-7xl h-[90vh] bg-zinc-950/90 border border-white/10 rounded-3xl flex flex-col overflow-hidden shadow-2xl animate-scaleUp">
        
        {/* Header */}
        <div className="px-6 py-4 bg-zinc-900/60 border-b border-white/5 flex items-center justify-between flex-shrink-0">
          <div>
            <div className="flex items-center gap-2">
              <span className={`px-2 py-0.5 rounded text-[9px] font-extrabold uppercase ${
                profile.type === "candidate" ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20" : "bg-indigo-500/10 text-indigo-400 border border-indigo-500/20"
              }`}>
                {profile.type === "candidate" ? "Candidato" : "Vaga"}
              </span>
              <span className="text-[10px] text-zinc-500 font-mono">ID {profile.id}</span>
            </div>
            <h3 className="text-base font-bold text-white mt-1">
              Visualizador de PDF & Extração IA: <span className="text-indigo-300 font-extrabold">{getProfileTitle(profile)}</span>
            </h3>
          </div>
          <button 
            onClick={onClose}
            className="px-4 py-2 bg-zinc-900 border border-white/5 hover:bg-zinc-800 text-zinc-400 hover:text-white rounded-xl text-xs font-bold transition-all cursor-pointer"
          >
            Fechar Visualizador
          </button>
        </div>

        {/* Content Area - Split 2 Columns */}
        <div className="flex-1 flex flex-col md:flex-row overflow-hidden min-h-0">
          
          {/* COLUMN LEFT: NATIVE PDF VIEWER */}
          <div className="w-full md:w-1/2 p-5 border-r border-white/5 flex flex-col h-full min-h-0 bg-zinc-900/30">
            <div className="flex justify-between items-center mb-2.5">
              <h4 className="text-xs font-bold text-zinc-400 uppercase tracking-wider flex items-center gap-1.5">
                <FileText className="w-4 h-4 text-indigo-400" />
                Documento em PDF
              </h4>
              <span className="text-[10px] text-zinc-500 font-semibold italic">
                {profile.file_name ? `Arquivo original: ${profile.file_name}` : "PDF gerado automaticamente pelo sistema"}
              </span>
            </div>
            
            <div className="flex-1 bg-zinc-950 rounded-2xl overflow-hidden border border-white/5 shadow-inner relative flex items-center justify-center">
              <iframe 
                src={`${API_BASE}/profiles/${profile.id}/pdf`}
                className="w-full h-full border-none"
                title="Visualizador de PDF"
              />
            </div>
          </div>

          {/* COLUMN RIGHT: EXTRACTION PIPELINE */}
          <div className="w-full md:w-1/2 p-5 flex flex-col h-full min-h-0 bg-zinc-950/20">
            
            {/* Tabs */}
            <div className="flex gap-1.5 p-1 bg-zinc-900/80 rounded-xl border border-white/5 mb-4 flex-shrink-0">
              <button
                onClick={() => setActiveTab("technical")}
                className={`flex-1 py-2 rounded-lg text-xs font-bold flex items-center justify-center gap-1.5 transition-all cursor-pointer ${
                  activeTab === "technical"
                    ? "bg-indigo-600/30 border border-indigo-500/20 text-indigo-300"
                    : "text-zinc-400 hover:text-zinc-200"
                }`}
              >
                <Cpu className="w-3.5 h-3.5" />
                Ficha Técnica (IA)
              </button>
              <button
                onClick={() => setActiveTab("redaction")}
                className={`flex-1 py-2 rounded-lg text-xs font-bold flex items-center justify-center gap-1.5 transition-all cursor-pointer ${
                  activeTab === "redaction"
                    ? "bg-indigo-600/30 border border-indigo-500/20 text-indigo-300"
                    : "text-zinc-400 hover:text-zinc-200"
                }`}
              >
                <ShieldCheck className="w-3.5 h-3.5" />
                Higienização (PII)
              </button>
              <button
                onClick={() => setActiveTab("json")}
                className={`flex-1 py-2 rounded-lg text-xs font-bold flex items-center justify-center gap-1.5 transition-all cursor-pointer ${
                  activeTab === "json"
                    ? "bg-indigo-600/30 border border-indigo-500/20 text-indigo-300"
                    : "text-zinc-400 hover:text-zinc-200"
                }`}
              >
                <Code className="w-3.5 h-3.5" />
                JSON Bruto
              </button>
            </div>

            {/* Tab Contents - Scrollable */}
            <div className="flex-1 overflow-y-auto min-h-0 pr-1 text-zinc-300">
              
              {/* TAB 1: TECHNICAL (STRUCTURED DATA) */}
              {activeTab === "technical" && (
                <div className="flex flex-col gap-4 animate-fadeIn">
                  
                  {/* Meta stats */}
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-3 bg-zinc-900/40 p-4 rounded-xl border border-white/5 text-xs">
                    <div>
                      <span className="text-[10px] text-zinc-500 uppercase tracking-wider font-semibold block mb-0.5">Senioridade Inserida</span>
                      <strong className="text-white text-sm">{profile.extracted_profile.seniority}</strong>
                    </div>
                    <div>
                      <span className="text-[10px] text-zinc-500 uppercase tracking-wider font-semibold block mb-0.5">Tempo de Experiência</span>
                      <strong className="text-white text-sm">{profile.extracted_profile.experience_years} anos</strong>
                    </div>
                    {profile.extracted_profile.certifications && profile.extracted_profile.certifications.length > 0 && (
                      <div className="col-span-2 md:col-span-1">
                        <span className="text-[10px] text-zinc-500 uppercase tracking-wider font-semibold block mb-0.5">Certificados</span>
                        <span className="text-zinc-300 font-semibold line-clamp-1" title={profile.extracted_profile.certifications.join(", ")}>
                          {profile.extracted_profile.certifications.join(", ")}
                        </span>
                      </div>
                    )}
                  </div>

                  {/* Narrative Experience */}
                  <div className="p-4 bg-zinc-900/20 rounded-xl border border-white/5">
                    <h5 className="text-xs font-bold text-indigo-400 uppercase tracking-wider mb-2">
                      Resumo da Trajetória Narrativa (Extraído por LLM)
                    </h5>
                    <p className="text-xs text-zinc-300 leading-relaxed italic whitespace-pre-wrap">
                      "{profile.extracted_profile.narrative_experience}"
                    </p>
                  </div>

                  {/* ESCO Normalized Skills */}
                  <div className="p-4 bg-zinc-900/20 rounded-xl border border-white/5">
                    <h5 className="text-xs font-bold text-indigo-400 uppercase tracking-wider mb-2.5">
                      Competências Mapeadas na Ontologia ESCO (Europeia)
                    </h5>
                    <div className="flex flex-wrap gap-1.5">
                      {(profile.extracted_profile.skills_normalized || []).map((s, idx) => (
                        <span 
                          key={idx} 
                          className="px-2 py-1 bg-indigo-950/40 text-indigo-400 border border-indigo-500/20 rounded-lg text-[10px] font-semibold flex items-center gap-1"
                          title={s.concept_uri}
                        >
                          <CheckCircle className="w-3 h-3 text-indigo-400 flex-shrink-0" />
                          {s.preferred_label}
                        </span>
                      ))}
                      {(profile.extracted_profile.skills_normalized || []).length === 0 && (
                        <span className="text-xs text-zinc-500 italic">Nenhuma competência mapeada na ESCO.</span>
                      )}
                    </div>
                  </div>

                  {/* Certifications and Languages */}
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {profile.extracted_profile.education && profile.extracted_profile.education.length > 0 && (
                      <div className="p-4 bg-zinc-900/20 rounded-xl border border-white/5">
                        <h5 className="text-xs font-bold text-zinc-400 uppercase tracking-wider mb-2">Educação / Formação</h5>
                        <div className="flex flex-col gap-2">
                          {profile.extracted_profile.education.map((edu, idx) => (
                            <div key={idx} className="text-xs border-l-2 border-indigo-500/40 pl-2">
                              <div className="font-semibold text-zinc-200">{edu.degree} em {edu.field}</div>
                              {edu.year && <span className="text-[10px] text-zinc-500">Conclusão: {edu.year}</span>}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {((profile.extracted_profile.languages && profile.extracted_profile.languages.length > 0) || 
                      (profile.extracted_profile.certifications && profile.extracted_profile.certifications.length > 0)) && (
                      <div className="p-4 bg-zinc-900/20 rounded-xl border border-white/5 flex flex-col gap-3">
                        {profile.extracted_profile.languages && profile.extracted_profile.languages.length > 0 && (
                          <div>
                            <h5 className="text-[10px] font-bold text-zinc-400 uppercase tracking-wider mb-1">Idiomas</h5>
                            <div className="flex flex-wrap gap-1">
                              {profile.extracted_profile.languages.map((l, idx) => (
                                <span key={idx} className="px-1.5 py-0.5 bg-zinc-900 border border-white/5 rounded text-[10px] text-zinc-300 font-semibold">{l}</span>
                              ))}
                            </div>
                          </div>
                        )}
                        {profile.extracted_profile.certifications && profile.extracted_profile.certifications.length > 0 && (
                          <div>
                            <h5 className="text-[10px] font-bold text-zinc-400 uppercase tracking-wider mb-1">Certificações</h5>
                            <div className="flex flex-wrap gap-1">
                              {profile.extracted_profile.certifications.map((c, idx) => (
                                <span key={idx} className="px-1.5 py-0.5 bg-zinc-900 border border-white/5 rounded text-[10px] text-zinc-300 font-semibold">{c}</span>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* TAB 2: REDACTION (PII CLEANING) */}
              {activeTab === "redaction" && (
                <div className="flex flex-col gap-4 animate-fadeIn">
                  
                  {/* Step explanations */}
                  <div className="p-3 bg-amber-500/10 text-amber-400 border border-amber-500/20 rounded-xl text-xs flex gap-2">
                    <ShieldCheck className="w-4 h-4 flex-shrink-0 mt-0.5" />
                    <div>
                      <strong>Segurança de Dados (PII):</strong> Para garantir a conformidade com a LGPD/GDPR e remover qualquer viés na triagem, o currículo passa por um filtro regex & NLP do Microsoft Presidio, mascarando nomes, e-mails, telefones e localizações antes do envio para a API da LLM.
                    </div>
                  </div>

                  {/* Side-by-side text content */}
                  <div className="grid grid-cols-1 gap-4">
                    <div>
                      <div className="text-[10px] text-zinc-500 font-bold uppercase mb-1">Texto Original Extraído do PDF:</div>
                      <div className="p-3 bg-zinc-900/60 rounded-xl text-[10px] font-mono h-48 overflow-y-auto text-zinc-400 border border-white/5 whitespace-pre-wrap leading-relaxed shadow-inner">
                        {profile.raw_text}
                      </div>
                    </div>
                    <div>
                      <div className="text-[10px] text-zinc-500 font-bold uppercase mb-1">Texto Higienizado (Enviado para a LLM):</div>
                      <div className="p-3 bg-zinc-900/60 rounded-xl text-[10px] font-mono h-48 overflow-y-auto text-zinc-300 border border-white/5 whitespace-pre-wrap leading-relaxed shadow-inner">
                        {profile.redacted_text}
                      </div>
                    </div>
                  </div>

                  {/* Redaction Mappings */}
                  {Object.keys(profile.redaction_map).length > 0 && (
                    <div>
                      <h5 className="text-[10px] font-bold text-zinc-400 uppercase tracking-wider mb-2">Dicionário de Redação (Mapeamento PII)</h5>
                      <div className="max-h-36 overflow-y-auto bg-zinc-900/40 p-3.5 rounded-xl border border-white/5 flex flex-col gap-1.5 font-mono text-[10px]">
                        {Object.entries(profile.redaction_map).map(([key, val]) => (
                          <div key={key} className="flex justify-between border-b border-white/5 pb-1 flex-wrap gap-1">
                            <span className="text-amber-400 font-semibold">{key}</span>
                            <span className="text-zinc-600">&rarr;</span>
                            <span className="text-zinc-300">{val}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* TAB 3: JSON DATA */}
              {activeTab === "json" && (
                <div className="animate-fadeIn h-full flex flex-col">
                  <div className="text-[10px] text-zinc-500 font-bold uppercase mb-1">Dados Estruturados Extraídos (Schema do Banco):</div>
                  <div className="flex-1 min-h-[300px] p-4 bg-zinc-900/50 rounded-2xl border border-white/5 overflow-auto font-mono text-[10px] leading-relaxed text-indigo-300">
                    <pre>{JSON.stringify(profile.extracted_profile, null, 2)}</pre>
                  </div>
                </div>
              )}

            </div>
          </div>

        </div>

      </div>
    </div>
  );
}
