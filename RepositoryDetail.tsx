import React, { useEffect, useState, useRef } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useOktaAuth } from '@okta/okta-react';
import {
  Github,
  ArrowLeft,
  File,
  Folder,
  AlertCircle,
  GitPullRequest,
  CheckCircle,
  Layers,
  Code2,
  Boxes,
  Zap,
  RotateCw,
  Server,
  BookOpen,
  Users,
  Search,
  ExternalLink,
  Activity,
  Package,
  ChevronDown,
  ChevronUp,
  Share2,
  ArrowUpRight,
  ArrowDownLeft,
} from 'lucide-react';

import {
  repositoryService,
  RepositoryDetail as IRepoDetail,
  KeyComponentDetail,
  ApiSurfaceDetail,
  CodePatternDetail,
  IntegrationPointDetail,
  DependencyDetail,
  CommitInfo,
} from '../services/repositoryService';
import { jiraService, JiraProjectOption, JiraRepositoryConnectionStatus } from '../services/jiraService';

type Tab = 'overview' | 'structure' | 'architecture' | 'commits' | 'issues' | 'pull-requests' | 'dependencies';

type AnalysisState = 'Queued' | 'Fetching' | 'Analyzing' | 'Completed' | 'Failed';

const ANALYSIS_STAGES = [
  { state: 'Queued' as AnalysisState, label: 'Queued for Analysis' },
  { state: 'Fetching' as AnalysisState, label: 'Fetching GitHub contents...' },
  { state: 'Analyzing' as AnalysisState, label: 'Extracting engineering intelligence...' },
  { state: 'Completed' as AnalysisState, label: 'Analysis Completed' },
];

export const RepositoryDetail: React.FC = () => {
  const { authState, oktaAuth } = useOktaAuth();
  const { projectId, repositoryId } = useParams<{ projectId: string; repositoryId: string }>();

  const [detail, setDetail] = useState<IRepoDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<Tab>('overview');

  // Analysis State Flow
  const [analysisState, setAnalysisState] = useState<AnalysisState>('Queued');
  const [isReanalyzing, setIsReanalyzing] = useState<boolean>(false);
  const [loading, setLoading] = useState<boolean>(true);
  const stageTimeoutRef = useRef<any>(null);

  // Commits Lazy Loading / Expansion / Pagination States
  const [loadedCommits, setLoadedCommits] = useState<CommitInfo[]>([]);
  const [displayedCommits, setDisplayedCommits] = useState<CommitInfo[]>([]);
  const [commitPage, setCommitPage] = useState<number>(1);
  const [isAllMode, setIsAllMode] = useState<boolean>(false);
  const [isLoadingCommits, setIsLoadingCommits] = useState<boolean>(false);
  const [totalCommitsCount, setTotalCommitsCount] = useState<number>(0);
  const [prPage, setPrPage] = useState<number>(1);
  const [userEmail, setUserEmail] = useState('');
  const [jiraMapping, setJiraMapping] = useState<JiraRepositoryConnectionStatus | null>(null);
  const [jiraProjects, setJiraProjects] = useState<JiraProjectOption[]>([]);
  const [selectedJiraKey, setSelectedJiraKey] = useState('');
  const [savingJiraMapping, setSavingJiraMapping] = useState(false);

  // Initialize and Sync detail
  useEffect(() => {
    if (detail) {
      const initialCommits = detail.commits || [];
      setLoadedCommits(initialCommits);
      setDisplayedCommits(initialCommits.slice(0, 10));
      setCommitPage(1);
      setIsAllMode(false);
      
      // Calculate/adjust total commit count safely:
      const realTotal = Math.max(detail.total_commits || 0, initialCommits.length);
      setTotalCommitsCount(realTotal);
    }
  }, [detail]);

  // Load page-specific commits in Paginated Mode
  useEffect(() => {
    const fetchPageCommits = async () => {
      if (isAllMode || !projectId || !repositoryId || !detail) return;
      if (commitPage === 1 && loadedCommits.length > 0) {
        setDisplayedCommits(loadedCommits.slice(0, 10));
        return;
      }
      setIsLoadingCommits(true);
      try {
        let email = '';
        if (authState?.isAuthenticated) {
          const user = await oktaAuth.getUser();
          email = user.email || '';
        }
        const pageCommits = await repositoryService.getCommits(projectId, repositoryId, commitPage, 10, email);
        setDisplayedCommits(pageCommits);

        // Always preserve the maximum authoritative commit count from detail
        const backendTotal = detail.total_commits || 0;
        setTotalCommitsCount((prev) => Math.max(prev, backendTotal, (commitPage - 1) * 10 + pageCommits.length));
      } catch (err) {
        console.error("Error fetching page commits:", err);
      } finally {
        setIsLoadingCommits(false);
      }
    };
    fetchPageCommits();
  }, [commitPage, isAllMode, projectId, repositoryId, detail]);

  const handleLoadMoreCommits = async () => {
    if (!projectId || !repositoryId || isLoadingCommits) return;
    setIsLoadingCommits(true);
    try {
      let email = '';
      if (authState?.isAuthenticated) {
        const user = await oktaAuth.getUser();
        email = user.email || '';
      }
      const nextPage = Math.floor(loadedCommits.length / 10) + 1;
      const newCommits = await repositoryService.getCommits(projectId, repositoryId, nextPage, 10, email);
      if (newCommits.length > 0) {
        setLoadedCommits((prev) => [...prev, ...newCommits]);
        
        const backendTotal = detail?.total_commits || 0;
        setTotalCommitsCount((prev) => Math.max(prev, backendTotal, (nextPage - 1) * 10 + newCommits.length));
      }
    } catch (err) {
      console.error("Failed to load more commits", err);
    } finally {
      setIsLoadingCommits(false);
    }
  };

  // Filtering states
  const [issueFilter, setIssueFilter] = useState<'all' | 'open' | 'closed'>('all');
  const [prFilter, setPrFilter] = useState<'all' | 'open' | 'closed' | 'merged'>('all');
  const [structureSearch, setStructureSearch] = useState<string>('');
  const [depSearch, setDepSearch] = useState<string>('');

  // Accordion Section States for Collapsible Engineering Intelligence Cards
  const [expandedCards, setExpandedCards] = useState<Record<string, boolean>>({
    components: true,
    apiSurface: true,
    codePatterns: true,
    integrations: true,
    dependencies: true,
    architecture: true,
  });

  const toggleCard = (cardKey: string) => {
    setExpandedCards((prev) => ({ ...prev, [cardKey]: !prev[cardKey] }));
  };

  const executeProgressiveLoad = async (fetchPromise: Promise<IRepoDetail>) => {
    setLoading(true);
    setError(null);
    setAnalysisState('Queued');

    stageTimeoutRef.current = setTimeout(() => {
      setAnalysisState('Fetching');
      stageTimeoutRef.current = setTimeout(() => {
        setAnalysisState('Analyzing');
      }, 600);
    }, 400);

    try {
      const data = await fetchPromise;
      if (stageTimeoutRef.current) clearTimeout(stageTimeoutRef.current);
      setDetail(data);
      setAnalysisState('Completed');
      setLoading(false);
    } catch (err: any) {
      console.error(err);
      if (stageTimeoutRef.current) clearTimeout(stageTimeoutRef.current);
      setAnalysisState('Failed');
      setError(err.message || 'Failed to retrieve repository analysis.');
      setLoading(false);
    }
  };

  const loadRepository = async () => {
    if (!projectId || !repositoryId) return;
    let email = '';
    if (authState?.isAuthenticated) {
      const user = await oktaAuth.getUser();
      email = user.email || '';
    }
    setUserEmail(email);
    executeProgressiveLoad(repositoryService.getRepositoryDetail(projectId, repositoryId, email));
  };

  const loadJiraMapping = async (email: string) => {
    if (!projectId || !repositoryId) return;
    try {
      const [mapping, status] = await Promise.all([
        jiraService.getRepositoryConnection(projectId, repositoryId),
        jiraService.getConnectionStatus(projectId, email),
      ]);
      setJiraMapping(mapping);
      setJiraProjects(status.available_projects || []);
      setSelectedJiraKey(mapping.connection?.jira_project_key || '');
    } catch (err: any) {
      setError(err.message || 'Failed to load Jira repository mapping.');
    }
  };

  const saveJiraMapping = async () => {
    if (!projectId || !repositoryId || !selectedJiraKey) return;
    const selected = jiraProjects.find((project) => project.key === selectedJiraKey);
    if (!selected) return;
    setSavingJiraMapping(true);
    try {
      await jiraService.connectRepository(projectId, repositoryId, {
        jira_project_key: selected.key,
        jira_project_name: selected.name,
        jira_project_id: selected.id,
      }, userEmail);
      await loadJiraMapping(userEmail);
    } catch (err: any) {
      setError(err.message || 'Failed to save Jira repository mapping.');
    } finally {
      setSavingJiraMapping(false);
    }
  };

  const handleReanalyze = async () => {
    if (!projectId || !repositoryId || isReanalyzing) return;
    setIsReanalyzing(true);
    let email = '';
    if (authState?.isAuthenticated) {
      const user = await oktaAuth.getUser();
      email = user.email || '';
    }
    await executeProgressiveLoad(repositoryService.reanalyzeRepository(projectId, repositoryId, email));
    setIsReanalyzing(false);
  };

  useEffect(() => {
    if (authState) {
      loadRepository();
    }
    return () => {
      if (stageTimeoutRef.current) clearTimeout(stageTimeoutRef.current);
    };
  }, [projectId, repositoryId, authState]);

  useEffect(() => {
    if (projectId && repositoryId && authState?.isAuthenticated) {
      oktaAuth.getUser().then((user) => loadJiraMapping(user.email || '')).catch(() => undefined);
    }
  }, [projectId, repositoryId, authState]);

  const formatDate = (isoString: string) => {
    try {
      const date = new Date(isoString);
      return date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
    } catch (e) {
      return 'N/A';
    }
  };

  const getRelativeTime = (isoString: string) => {
    try {
      const diffMs = Date.now() - new Date(isoString).getTime();
      const diffMins = Math.floor(diffMs / 60000);
      const diffHours = Math.floor(diffMins / 60);
      const diffDays = Math.floor(diffHours / 24);

      if (diffMins < 1) return 'just now';
      if (diffMins < 60) return `${diffMins}m ago`;
      if (diffHours < 24) return `${diffHours}h ago`;
      if (diffDays === 1) return 'yesterday';
      return `${diffDays} days ago`;
    } catch (e) {
      return 'some time ago';
    }
  };

  // Render Progressive Loading State with Stepper
  if (loading) {
    return (
      <div className="p-8 max-w-4xl mx-auto flex flex-col items-center justify-center min-h-[500px] space-y-8">
        <div className="w-full max-w-lg bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-6 shadow-sm space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-bold text-slate-800 dark:text-slate-200 uppercase tracking-widest flex items-center space-x-2">
              <Activity className="w-4 h-4 text-primary-500 animate-pulse" />
              <span>Engineering Intelligence Progress</span>
            </h3>
            <span className="text-xs font-semibold px-2.5 py-0.5 rounded-full bg-primary-50 dark:bg-primary-950/40 text-primary-600 dark:text-primary-400 border border-primary-200 dark:border-primary-800">
              {analysisState}
            </span>
          </div>

          <div className="grid grid-cols-4 gap-2 pt-2">
            {ANALYSIS_STAGES.map((s, idx) => {
              const stagesOrder: AnalysisState[] = ['Queued', 'Fetching', 'Analyzing', 'Completed'];
              const currentIdx = stagesOrder.indexOf(analysisState);
              const isPast = idx <= currentIdx;
              const isCurrent = idx === currentIdx;

              return (
                <div key={s.state} className="space-y-2">
                  <div
                    className={`h-1.5 rounded-full transition-all duration-300 ${isPast ? 'bg-primary-600 dark:bg-primary-500' : 'bg-slate-200 dark:bg-slate-800'
                      }`}
                  />
                  <span
                    className={`text-[10px] block text-center font-medium ${isCurrent
                      ? 'text-primary-600 dark:text-primary-400 font-bold'
                      : isPast
                        ? 'text-slate-600 dark:text-slate-300'
                        : 'text-slate-400 dark:text-slate-600'
                      }`}
                  >
                    {s.state}
                  </span>
                </div>
              );
            })}
          </div>

          <div className="text-center pt-4 text-xs text-slate-500 dark:text-slate-400 flex items-center justify-center space-x-2">
            <div className="w-3.5 h-3.5 border-2 border-primary-500 border-t-transparent rounded-full animate-spin" />
            <span>
              {analysisState === 'Queued' && 'Queuing repository analysis pipeline...'}
              {analysisState === 'Fetching' && 'Fetching accessible contents and git activity from GitHub API...'}
              {analysisState === 'Analyzing' && 'Parsing frameworks, tech stack, APIs, patterns, and architecture...'}
              {analysisState === 'Completed' && 'Finalizing repository details...'}
            </span>
          </div>
        </div>

        <div className="w-full space-y-6 animate-pulse">
          <div className="h-28 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800/80 rounded-xl p-6 space-y-4">
            <div className="h-5 bg-slate-200 dark:bg-slate-800 rounded w-1/4" />
            <div className="grid grid-cols-2 gap-4">
              <div className="h-4 bg-slate-150 dark:bg-slate-850 rounded w-3/4" />
              <div className="h-4 bg-slate-150 dark:bg-slate-850 rounded w-1/2" />
            </div>
          </div>
        </div>
      </div>
    );
  }

  // Render Error state
  if (error || !detail) {
    return (
      <div className="p-8 max-w-xl mx-auto text-center space-y-4">
        <div className="inline-flex items-center justify-center p-3 bg-red-50 dark:bg-red-950/20 text-red-500 rounded-xl border border-red-200 dark:border-red-800/40">
          <AlertCircle className="w-8 h-8" />
        </div>
        <h2 className="text-xl font-bold text-slate-900 dark:text-white">Failed to load repository</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400">{error || 'An unexpected error occurred.'}</p>
        <div className="flex items-center justify-center space-x-4 pt-2">
          <Link
            to={`/projects/${projectId}/repositories`}
            className="inline-flex items-center space-x-2 text-sm font-semibold text-primary-600 dark:text-primary-400 hover:underline"
          >
            <ArrowLeft className="w-4 h-4" />
            <span>Back to Repositories</span>
          </Link>
          <button
            onClick={handleReanalyze}
            className="inline-flex items-center space-x-2 text-sm font-semibold bg-primary-600 text-white px-4 py-2 rounded-lg hover:bg-primary-700 transition"
          >
            <RotateCw className="w-4 h-4" />
            <span>Try Re-analyzing</span>
          </button>
        </div>
      </div>
    );
  }

  const {
    metadata,
    languages,
    file_structure,
    commits,
    total_commits = 0,
    branches = [],
    contributors = [],
    issues,
    issues_summary,
    pull_requests,
    pull_requests_summary,
    analysis,
  } = detail;

  // Detailed Structured Engineering Telemetry Objects
  const keyCompDetails: KeyComponentDetail[] = analysis?.key_components_details || [];
  const apiSurfaceDetails: ApiSurfaceDetail[] = analysis?.api_surface_details || [];
  const codePatternDetails: CodePatternDetail[] = analysis?.code_patterns_details || [];
  const integrationDetails: IntegrationPointDetail[] = analysis?.integration_points_details || [];
  const dependencyDetails: DependencyDetail[] = analysis?.dependencies_details || [];

  // Filter Issues
  const filteredIssues = issues.filter((issue) => {
    if (issueFilter === 'all') return true;
    return issue.state.toLowerCase() === issueFilter;
  });

  // Filter PRs
  const filteredPRs = pull_requests.filter((pr) => {
    if (prFilter === 'all') return true;
    if (prFilter === 'merged') return pr.is_merged;
    if (prFilter === 'closed') return pr.state.toLowerCase() === 'closed' && !pr.is_merged;
    return pr.state.toLowerCase() === prFilter;
  });

  // Filter Structure
  const filteredStructure = file_structure.filter((node) =>
    node.path.toLowerCase().includes(structureSearch.toLowerCase())
  );

  // Filter Dependencies
  const dependenciesList = analysis?.dependencies || [];
  const filteredDeps = dependencyDetails.filter((dep) =>
    dep.package.toLowerCase().includes(depSearch.toLowerCase())
  );

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      {/* Back link & Header */}
      <div className="space-y-4">
        <Link
          to={`/projects/${projectId}/repositories`}
          className="inline-flex items-center space-x-2 text-xs font-semibold text-slate-500 hover:text-slate-900 dark:hover:text-white transition"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          <span>Back to Repositories</span>
        </Link>

        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="flex items-center space-x-3">
            <div className="p-3 bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 rounded-xl">
              <Github className="w-6 h-6" />
            </div>
            <div>
              <div className="flex items-center space-x-2">
                <h1 className="text-2xl font-extrabold text-slate-900 dark:text-white">{metadata.name}</h1>
                <span className="text-[10px] font-bold uppercase tracking-wider bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400 px-2 py-0.5 rounded border border-slate-200 dark:border-slate-700">
                  Public
                </span>
                <span className="inline-flex items-center space-x-1 text-[10px] font-semibold bg-emerald-50 dark:bg-emerald-950/40 text-emerald-600 dark:text-emerald-400 px-2 py-0.5 rounded border border-emerald-200 dark:border-emerald-800">
                  <CheckCircle className="w-3 h-3" />
                  <span>{detail.analysis_status || 'Completed'}</span>
                </span>
              </div>
              <p className="text-xs text-slate-400 dark:text-slate-500 mt-0.5">
                Owner: {metadata.owner} &bull; Default Branch: {metadata.default_branch}
              </p>
            </div>
          </div>

          {/* Action buttons */}
          <div className="flex items-center space-x-3">
            <button
              onClick={handleReanalyze}
              disabled={isReanalyzing}
              className="flex items-center space-x-2 text-xs font-semibold bg-primary-600 hover:bg-primary-700 text-white px-4 py-2.5 rounded-lg shadow-sm transition disabled:opacity-50"
            >
              <RotateCw className={`w-3.5 h-3.5 ${isReanalyzing ? 'animate-spin' : ''}`} />
              <span>{isReanalyzing ? 'Re-analyzing...' : 'Re-analyze Repository'}</span>
            </button>

            <a
              href={metadata.github_url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center space-x-2 text-xs font-semibold bg-white dark:bg-slate-900 hover:bg-slate-50 dark:hover:bg-slate-800/80 border border-slate-200 dark:border-slate-800 text-slate-700 dark:text-slate-300 px-4 py-2.5 rounded-lg shadow-sm transition"
            >
              <Github className="w-4 h-4" />
              <span>Open on GitHub</span>
              <ExternalLink className="w-3 h-3 text-slate-400" />
            </a>
          </div>
        </div>
      </div>

      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-5 shadow-sm">
        <div className="flex items-center justify-between gap-3 mb-3">
          <div>
            <h3 className="text-sm font-bold text-slate-900 dark:text-white">Jira project mapping</h3>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">Choose where stories from this repository are created.</p>
          </div>
          <span className="text-xs font-semibold text-slate-500 dark:text-slate-400">{jiraMapping?.connection ? 'Repository mapping' : jiraMapping?.uses_project_fallback ? 'Project fallback' : 'Not mapped'}</span>
        </div>
        <div className="flex flex-col md:flex-row gap-3">
          <select
            value={selectedJiraKey}
            onChange={(event) => setSelectedJiraKey(event.target.value)}
            className="flex-1 px-3 py-2 text-sm rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-950"
          >
            <option value="">Select Jira project</option>
            {jiraProjects.map((project) => <option key={project.id || project.key} value={project.key}>{project.name} ({project.key})</option>)}
          </select>
          <button
            type="button"
            onClick={saveJiraMapping}
            disabled={!selectedJiraKey || savingJiraMapping}
            className="px-4 py-2 text-sm font-semibold rounded-lg bg-primary-600 text-white disabled:opacity-50"
          >
            {savingJiraMapping ? 'Saving...' : 'Save mapping'}
          </button>
        </div>
        {jiraMapping?.effective_connection && !jiraMapping.connection && (
          <p className="text-xs text-amber-600 mt-2">Currently using the project-level Jira project {jiraMapping.effective_connection.jira_project_key}. Save a mapping above to override it for this repository.</p>
        )}
      </div>

      {/* Mandatory Tabs Navigation */}
      <div className="border-b border-slate-200 dark:border-slate-800 flex overflow-x-auto space-x-6">
        {[
          { key: 'overview', label: 'Overview' },
          { key: 'structure', label: 'Structure' },
          { key: 'architecture', label: 'Architecture' },
          { key: 'commits', label: 'Commits' },
          { key: 'issues', label: 'Issues' },
          { key: 'pull-requests', label: 'Pull Requests' },
          { key: 'dependencies', label: 'Dependencies' },
        ].map((tabItem) => (
          <button
            key={tabItem.key}
            onClick={() => setActiveTab(tabItem.key as Tab)}
            className={`pb-4 text-sm font-semibold border-b-2 transition duration-150 whitespace-nowrap px-1 ${activeTab === tabItem.key
              ? 'border-primary-500 text-primary-600 dark:text-primary-400 font-bold'
              : 'border-transparent text-slate-500 hover:text-slate-900 dark:hover:text-slate-300'
              }`}
          >
            {tabItem.label}
          </button>
        ))}
      </div>

      {/* Tab Panels */}
      <div className="space-y-6">
        {/* T1. OVERVIEW TAB */}
        {activeTab === 'overview' && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-2 space-y-6">
              {/* Purpose & Description */}
              <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-6 shadow-sm space-y-4">
                <h3 className="text-sm font-bold text-slate-800 dark:text-slate-200 uppercase tracking-widest border-b border-slate-100 dark:border-slate-800 pb-2 flex items-center space-x-2">
                  <BookOpen className="w-4 h-4 text-primary-500" />
                  <span>Repository Overview & Purpose</span>
                </h3>

                <p className="text-sm text-slate-700 dark:text-slate-300 leading-relaxed font-normal">
                  {analysis?.overview || metadata.description || 'No overview summary detected in repository README.'}
                </p>

                {analysis?.readme_insights?.sections && analysis.readme_insights.sections.length > 0 && (
                  <div className="pt-2 border-t border-slate-100 dark:border-slate-800/80 space-y-2">
                    <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider block">
                      Documentation Key Sections
                    </span>
                    <div className="flex flex-wrap gap-2">
                      {analysis.readme_insights.sections.map((sec, idx) => (
                        <span
                          key={idx}
                          className="px-2.5 py-1 rounded-md text-xs font-medium bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-700"
                        >
                          # {sec}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {/* SECTION 1: KEY COMPONENTS (Collapsible Card) */}
              <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl shadow-sm overflow-hidden">
                <button
                  onClick={() => toggleCard('components')}
                  className="w-full p-6 text-left flex items-center justify-between bg-slate-50/50 dark:bg-slate-800/40 hover:bg-slate-100/50 dark:hover:bg-slate-800/60 transition"
                >
                  <div className="flex items-center space-x-3">
                    <Boxes className="w-5 h-5 text-primary-500" />
                    <div>
                      <h3 className="text-sm font-bold text-slate-900 dark:text-white uppercase tracking-wider">
                        KEY COMPONENTS ({keyCompDetails.length})
                      </h3>
                      <p className="text-xs text-slate-400">Essential files, module roles, and relationships</p>
                    </div>
                  </div>
                  {expandedCards.components ? (
                    <ChevronUp className="w-4 h-4 text-slate-400" />
                  ) : (
                    <ChevronDown className="w-4 h-4 text-slate-400" />
                  )}
                </button>

                {expandedCards.components && (
                  <div className="p-6 pt-2 space-y-3 border-t border-slate-100 dark:border-slate-800">
                    {keyCompDetails.length > 0 ? (
                      keyCompDetails.map((comp, idx) => (
                        <div
                          key={idx}
                          className="p-4 bg-slate-50 dark:bg-slate-800/50 rounded-xl border border-slate-200 dark:border-slate-800 space-y-2"
                        >
                          <div className="flex items-start justify-between gap-4">
                            <div>
                              <span className="text-xs font-bold text-slate-900 dark:text-white font-mono">
                                {comp.name}
                              </span>
                              <span className="ml-2 text-[10px] font-semibold bg-primary-50 dark:bg-primary-950/40 text-primary-600 dark:text-primary-400 px-2 py-0.5 rounded border border-primary-200 dark:border-primary-800">
                                {comp.role}
                              </span>
                            </div>
                            <span className="text-[11px] font-mono text-slate-400 truncate max-w-xs">
                              {comp.path}
                            </span>
                          </div>
                          <p className="text-xs text-slate-600 dark:text-slate-300">{comp.purpose}</p>
                          {comp.relationships.length > 0 && (
                            <div className="flex items-center space-x-2 text-[11px] text-slate-400">
                              <Share2 className="w-3 h-3 text-slate-400 shrink-0" />
                              <span>Relationships: {comp.relationships.join(', ')}</span>
                            </div>
                          )}
                        </div>
                      ))
                    ) : (
                      <p className="text-xs text-slate-400 italic">Not detected</p>
                    )}
                  </div>
                )}
              </div>

              {/* SECTION 2: API SURFACE (Collapsible Card) */}
              <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl shadow-sm overflow-hidden">
                <button
                  onClick={() => toggleCard('apiSurface')}
                  className="w-full p-6 text-left flex items-center justify-between bg-slate-50/50 dark:bg-slate-800/40 hover:bg-slate-100/50 dark:hover:bg-slate-800/60 transition"
                >
                  <div className="flex items-center space-x-3">
                    <Server className="w-5 h-5 text-primary-500" />
                    <div>
                      <h3 className="text-sm font-bold text-slate-900 dark:text-white uppercase tracking-wider">
                        API SURFACE ({apiSurfaceDetails.length})
                      </h3>
                      <p className="text-xs text-slate-400">Endpoints, HTTP verbs, parameters, and handler sources</p>
                    </div>
                  </div>
                  {expandedCards.apiSurface ? (
                    <ChevronUp className="w-4 h-4 text-slate-400" />
                  ) : (
                    <ChevronDown className="w-4 h-4 text-slate-400" />
                  )}
                </button>

                {expandedCards.apiSurface && (
                  <div className="p-6 pt-2 space-y-3 border-t border-slate-100 dark:border-slate-800">
                    {apiSurfaceDetails.length > 0 ? (
                      apiSurfaceDetails.map((api, idx) => (
                        <div
                          key={idx}
                          className="p-4 bg-slate-50 dark:bg-slate-800/50 rounded-xl border border-slate-200 dark:border-slate-800 space-y-2"
                        >
                          <div className="flex items-center space-x-3">
                            <span
                              className={`text-[10px] font-extrabold px-2 py-0.5 rounded border uppercase ${api.method === 'GET'
                                ? 'bg-blue-50 text-blue-600 border-blue-200 dark:bg-blue-950/40 dark:text-blue-400 dark:border-blue-800'
                                : api.method === 'POST'
                                  ? 'bg-emerald-50 text-emerald-600 border-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-400 dark:border-emerald-800'
                                  : 'bg-purple-50 text-purple-600 border-purple-200 dark:bg-purple-950/40 dark:text-purple-400 dark:border-purple-800'
                                }`}
                            >
                              {api.method}
                            </span>
                            <span className="font-mono text-xs font-bold text-slate-900 dark:text-slate-100">
                              {api.endpoint}
                            </span>
                          </div>
                          <p className="text-xs text-slate-600 dark:text-slate-300">{api.description}</p>
                          <div className="flex items-center justify-between text-[11px] text-slate-400 font-mono pt-1 border-t border-slate-200/50 dark:border-slate-700/50">
                            <span>Source: {api.source_file}</span>
                            {api.parameters.length > 0 && (
                              <span>Params: {api.parameters.join(', ')}</span>
                            )}
                          </div>
                        </div>
                      ))
                    ) : (
                      <p className="text-xs text-slate-400 italic">Not detected</p>
                    )}
                  </div>
                )}
              </div>

              {/* SECTION 3: CODE PATTERNS (Collapsible Card) */}
              <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl shadow-sm overflow-hidden">
                <button
                  onClick={() => toggleCard('codePatterns')}
                  className="w-full p-6 text-left flex items-center justify-between bg-slate-50/50 dark:bg-slate-800/40 hover:bg-slate-100/50 dark:hover:bg-slate-800/60 transition"
                >
                  <div className="flex items-center space-x-3">
                    <Code2 className="w-5 h-5 text-primary-500" />
                    <div>
                      <h3 className="text-sm font-bold text-slate-900 dark:text-white uppercase tracking-wider">
                        CODE PATTERNS ({codePatternDetails.length})
                      </h3>
                      <p className="text-xs text-slate-400">Architectural approaches, state management, and error handling</p>
                    </div>
                  </div>
                  {expandedCards.codePatterns ? (
                    <ChevronUp className="w-4 h-4 text-slate-400" />
                  ) : (
                    <ChevronDown className="w-4 h-4 text-slate-400" />
                  )}
                </button>

                {expandedCards.codePatterns && (
                  <div className="p-6 pt-2 space-y-3 border-t border-slate-100 dark:border-slate-800">
                    {codePatternDetails.length > 0 ? (
                      codePatternDetails.map((pat, idx) => (
                        <div
                          key={idx}
                          className="p-4 bg-slate-50 dark:bg-slate-800/50 rounded-xl border border-slate-200 dark:border-slate-800 space-y-2"
                        >
                          <div className="flex items-center justify-between">
                            <span className="text-xs font-bold text-slate-900 dark:text-white">
                              {pat.pattern_name}
                            </span>
                            <span className="text-[10px] font-semibold bg-amber-50 dark:bg-amber-950/40 text-amber-600 dark:text-amber-400 px-2 py-0.5 rounded border border-amber-200 dark:border-amber-800">
                              {pat.category}
                            </span>
                          </div>
                          <p className="text-xs text-slate-600 dark:text-slate-300">{pat.description}</p>
                          <div className="text-[11px] text-slate-500 dark:text-slate-400 bg-white dark:bg-slate-900 p-2.5 rounded-lg border border-slate-200 dark:border-slate-800 font-mono">
                            <span className="font-semibold text-primary-500">Approach: </span>
                            {pat.reusable_approach}
                          </div>
                        </div>
                      ))
                    ) : (
                      <p className="text-xs text-slate-400 italic">Not detected</p>
                    )}
                  </div>
                )}
              </div>

              {/* SECTION 4: INTEGRATION POINTS (Collapsible Card) */}
              <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl shadow-sm overflow-hidden">
                <button
                  onClick={() => toggleCard('integrations')}
                  className="w-full p-6 text-left flex items-center justify-between bg-slate-50/50 dark:bg-slate-800/40 hover:bg-slate-100/50 dark:hover:bg-slate-800/60 transition"
                >
                  <div className="flex items-center space-x-3">
                    <Zap className="w-5 h-5 text-primary-500" />
                    <div>
                      <h3 className="text-sm font-bold text-slate-900 dark:text-white uppercase tracking-wider">
                        INTEGRATION POINTS ({integrationDetails.length})
                      </h3>
                      <p className="text-xs text-slate-400">Connections with external databases, cloud services, and CI/CD</p>
                    </div>
                  </div>
                  {expandedCards.integrations ? (
                    <ChevronUp className="w-4 h-4 text-slate-400" />
                  ) : (
                    <ChevronDown className="w-4 h-4 text-slate-400" />
                  )}
                </button>

                {expandedCards.integrations && (
                  <div className="p-6 pt-2 space-y-3 border-t border-slate-100 dark:border-slate-800">
                    {integrationDetails.length > 0 ? (
                      integrationDetails.map((integ, idx) => (
                        <div
                          key={idx}
                          className="p-4 bg-slate-50 dark:bg-slate-800/50 rounded-xl border border-slate-200 dark:border-slate-800 space-y-2"
                        >
                          <div className="flex items-center justify-between">
                            <span className="text-xs font-bold text-slate-900 dark:text-white">
                              {integ.service_name}
                            </span>
                            <span className="flex items-center space-x-1 text-[10px] font-semibold bg-emerald-50 dark:bg-emerald-950/40 text-emerald-600 dark:text-emerald-400 px-2 py-0.5 rounded border border-emerald-200 dark:border-emerald-800">
                              {integ.direction === 'Outbound' ? (
                                <ArrowUpRight className="w-3 h-3" />
                              ) : (
                                <ArrowDownLeft className="w-3 h-3" />
                              )}
                              <span>{integ.direction} &bull; {integ.integration_type}</span>
                            </span>
                          </div>
                          <p className="text-xs text-slate-600 dark:text-slate-300">{integ.purpose}</p>
                          <span className="text-[11px] font-mono text-slate-400 block">
                            Configuration file: {integ.file_config}
                          </span>
                        </div>
                      ))
                    ) : (
                      <p className="text-xs text-slate-400 italic">Not detected</p>
                    )}
                  </div>
                )}
              </div>
            </div>

            {/* Right Sidebar */}
            <div className="space-y-6">
              {/* Language Breakdown */}
              <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-6 shadow-sm space-y-4">
                <h3 className="text-sm font-bold text-slate-800 dark:text-slate-200 uppercase tracking-widest border-b border-slate-100 dark:border-slate-800 pb-2">
                  Language Breakdown
                </h3>

                <div className="space-y-3">
                  {Object.keys(languages).length > 0 ? (
                    Object.entries(languages).map(([lang, pct]) => (
                      <div key={lang} className="space-y-1">
                        <div className="flex justify-between text-xs font-semibold text-slate-700 dark:text-slate-300">
                          <span>{lang}</span>
                          <span>{pct}%</span>
                        </div>
                        <div className="w-full bg-slate-100 dark:bg-slate-800 h-2 rounded-full overflow-hidden">
                          <div
                            className="bg-primary-500 h-full rounded-full"
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                      </div>
                    ))
                  ) : (
                    <p className="text-xs text-slate-400">No language data available.</p>
                  )}
                </div>
              </div>

              {/* Git Activity & Contributors */}
              <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-6 shadow-sm space-y-4">
                <h3 className="text-sm font-bold text-slate-800 dark:text-slate-200 uppercase tracking-widest border-b border-slate-100 dark:border-slate-800 pb-2 flex items-center space-x-2">
                  <Users className="w-4 h-4 text-primary-500" />
                  <span>Git Stats & Contributors</span>
                </h3>

                <div className="grid grid-cols-2 gap-4 text-center">
                  <div className="p-3 bg-slate-50 dark:bg-slate-800/50 rounded-lg border border-slate-100 dark:border-slate-800">
                    <span className="text-xs text-slate-400 block">Branches</span>
                    <span className="text-lg font-bold text-slate-800 dark:text-slate-200">
                      {branches.length || 1}
                    </span>
                  </div>
                  <div className="p-3 bg-slate-50 dark:bg-slate-800/50 rounded-lg border border-slate-100 dark:border-slate-800">
                    <span className="text-xs text-slate-400 block">Commits</span>
                    <span className="text-lg font-bold text-slate-800 dark:text-slate-200">
                      {totalCommitsCount.toLocaleString()}
                    </span>
                  </div>
                </div>

                {contributors.length > 0 && (
                  <div className="pt-2 space-y-2">
                    <span className="text-xs font-bold text-slate-500 uppercase tracking-wider block">
                      Top Contributors
                    </span>
                    <div className="space-y-2">
                      {contributors.slice(0, 5).map((c) => (
                        <div key={c.login} className="flex items-center justify-between text-xs">
                          <div className="flex items-center space-x-2">
                            {c.avatar_url ? (
                              <img src={c.avatar_url} alt={c.login} className="w-5 h-5 rounded-full" />
                            ) : (
                              <Users className="w-4 h-4 text-slate-400" />
                            )}
                            <span className="font-semibold text-slate-700 dark:text-slate-300">{c.login}</span>
                          </div>
                          <span className="text-slate-400 text-[11px] font-medium">{c.contributions} commits</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* T2. STRUCTURE TAB */}
        {activeTab === 'structure' && (
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-6 shadow-sm space-y-6">
            <div className="flex flex-col sm:flex-row justify-between sm:items-center gap-4 border-b border-slate-100 dark:border-slate-800 pb-4">
              <div>
                <h3 className="text-sm font-bold text-slate-800 dark:text-slate-200 uppercase tracking-widest">
                  Project File Structure
                </h3>
                <p className="text-xs text-slate-400">Total items: {file_structure.length}</p>
              </div>

              <div className="relative w-full sm:w-64">
                <Search className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
                <input
                  type="text"
                  placeholder="Filter files..."
                  value={structureSearch}
                  onChange={(e) => setStructureSearch(e.target.value)}
                  className="w-full pl-9 pr-3 py-1.5 text-xs bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-1 focus:ring-primary-500"
                />
              </div>
            </div>

            <div className="divide-y divide-slate-100 dark:divide-slate-800/60 max-h-[600px] overflow-y-auto font-mono text-xs">
              {filteredStructure.map((node) => (
                <div
                  key={node.path}
                  className="py-2 px-2 hover:bg-slate-50 dark:hover:bg-slate-800/40 rounded flex items-center space-x-2.5 transition"
                >
                  {node.type === 'tree' ? (
                    <Folder className="w-4 h-4 text-amber-500 shrink-0" />
                  ) : (
                    <File className="w-4 h-4 text-slate-400 shrink-0" />
                  )}
                  <span className="text-slate-800 dark:text-slate-200 truncate">{node.path}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* T3. ARCHITECTURE TAB */}
        {activeTab === 'architecture' && (
          <div className="space-y-6">
            <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-6 shadow-sm space-y-4">
              <h3 className="text-sm font-bold text-slate-800 dark:text-slate-200 uppercase tracking-widest border-b border-slate-100 dark:border-slate-800 pb-2 flex items-center space-x-2">
                <Layers className="w-4 h-4 text-primary-500" />
                <span>ARCHITECTURE OVERVIEW</span>
              </h3>

              <div className="text-sm text-slate-700 dark:text-slate-300 leading-relaxed font-mono bg-slate-50 dark:bg-slate-800/50 p-5 rounded-lg border border-slate-200 dark:border-slate-800 whitespace-pre-line">
                {analysis?.architecture_overview ? (
                  analysis.architecture_overview
                ) : (
                  <p className="font-sans text-slate-400 text-xs">Not detected</p>
                )}
              </div>
            </div>

            {/* Architecture Details Inspector Grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-6 shadow-sm space-y-4">
                <h4 className="text-xs font-bold text-slate-800 dark:text-slate-200 uppercase tracking-widest">
                  Key System Components ({keyCompDetails.length})
                </h4>
                <div className="space-y-2">
                  {keyCompDetails.map((c, i) => (
                    <div key={i} className="p-3 bg-slate-50 dark:bg-slate-800/50 rounded-lg text-xs font-mono space-y-1">
                      <span className="font-bold text-primary-600 dark:text-primary-400">{c.name}</span>
                      <p className="text-slate-500 font-sans">{c.purpose}</p>
                    </div>
                  ))}
                </div>
              </div>

              <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-6 shadow-sm space-y-4">
                <h4 className="text-xs font-bold text-slate-800 dark:text-slate-200 uppercase tracking-widest">
                  API Surface Endpoints ({apiSurfaceDetails.length})
                </h4>
                <div className="space-y-2">
                  {apiSurfaceDetails.map((a, i) => (
                    <div key={i} className="p-3 bg-slate-50 dark:bg-slate-800/50 rounded-lg text-xs font-mono flex items-center justify-between">
                      <span className="font-bold text-emerald-600 dark:text-emerald-400">{a.method} {a.endpoint}</span>
                      <span className="text-slate-400 text-[10px] font-sans">{a.source_file}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* T4. COMMITS TAB */}
        {activeTab === 'commits' && (
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-6 shadow-sm space-y-6">
            <div className="flex flex-col sm:flex-row justify-between sm:items-center gap-4 border-b border-slate-100 dark:border-slate-800 pb-4">
              <div>
                <h3 className="text-sm font-bold text-slate-800 dark:text-slate-200 uppercase tracking-widest">
                  Commit History
                </h3>
                <p className="text-xs text-slate-400 font-semibold">
                  {totalCommitsCount.toLocaleString()} Commits
                </p>
              </div>
              
              {/* Optional Toggle to Switch between Pagination and Show All Mode */}
              <div className="flex items-center space-x-1.5 bg-slate-100 dark:bg-slate-800 p-0.5 rounded-lg text-xs">
                <button
                  onClick={() => setIsAllMode(false)}
                  className={`px-3 py-1.5 rounded-md font-semibold transition ${!isAllMode
                    ? 'bg-white dark:bg-slate-950 text-primary-600 dark:text-primary-400 shadow-sm'
                    : 'text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'
                  }`}
                >
                  Paginated View
                </button>
                <button
                  onClick={() => setIsAllMode(true)}
                  className={`px-3 py-1.5 rounded-md font-semibold transition ${isAllMode
                    ? 'bg-white dark:bg-slate-950 text-primary-600 dark:text-primary-400 shadow-sm'
                    : 'text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'
                  }`}
                >
                  Show All (Lazy Load)
                </button>
              </div>
            </div>

            <div className="divide-y divide-slate-100 dark:divide-slate-800/60">
              {isLoadingCommits ? (
                <div className="py-8 text-center text-sm text-slate-400 flex items-center justify-center space-x-2">
                  <div className="w-4 h-4 border-2 border-primary-500 border-t-transparent rounded-full animate-spin" />
                  <span>Loading commits...</span>
                </div>
              ) : (isAllMode ? loadedCommits : displayedCommits).length > 0 ? (
                (isAllMode ? loadedCommits : displayedCommits).map((commit) => (
                  <div key={commit.sha} className="py-4 first:pt-0 last:pb-0 space-y-1.5">
                    <div className="flex items-start justify-between gap-4">
                      <p className="text-sm font-semibold text-slate-900 dark:text-slate-100">{commit.message}</p>
                      <span className="text-xs font-mono bg-slate-100 dark:bg-slate-800 px-2 py-0.5 rounded text-slate-500">
                        {commit.sha.substring(0, 7)}
                      </span>
                    </div>
                    <div className="flex items-center space-x-2 text-xs text-slate-400">
                      <span>{commit.author || 'Contributor'}</span>
                      <span>&bull;</span>
                      <span>{getRelativeTime(commit.date)}</span>
                    </div>
                  </div>
                ))
              ) : (
                <div className="py-8 text-center text-sm text-slate-400 italic">
                  No commits found
                </div>
              )}
            </div>

            {/* Commits controls */}
            <div className="flex items-center justify-center pt-4 border-t border-slate-100 dark:border-slate-800/60">
              {!isAllMode ? (
                /* Paginated View Controls (Previous / Page X of Y / Next) */
                <div className="flex items-center space-x-4">
                  <button
                    disabled={commitPage === 1 || isLoadingCommits}
                    onClick={() => setCommitPage((p) => Math.max(1, p - 1))}
                    className="px-3 py-1.5 text-xs font-bold bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-350 rounded-lg transition disabled:opacity-50"
                  >
                    Previous
                  </button>
                  <span className="text-xs text-slate-500 dark:text-slate-400">
                    Page {commitPage} of {Math.max(1, Math.ceil(totalCommitsCount / 10))}
                  </span>
                  <button
                    disabled={commitPage * 10 >= totalCommitsCount || (isAllMode ? loadedCommits : displayedCommits).length < 10 || isLoadingCommits}
                    onClick={() => setCommitPage((p) => p + 1)}
                    className="px-3 py-1.5 text-xs font-bold bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-350 rounded-lg transition disabled:opacity-50"
                  >
                    Next
                  </button>
                </div>
              ) : (
                /* Show All (Lazy Loading) Controls */
                loadedCommits.length < totalCommitsCount && (
                  <button
                    onClick={handleLoadMoreCommits}
                    disabled={isLoadingCommits}
                    className="px-4 py-2 text-xs font-bold bg-primary-600 hover:bg-primary-700 text-white rounded-lg transition disabled:opacity-50 flex items-center space-x-2"
                  >
                    {isLoadingCommits ? (
                      <>
                        <div className="w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin" />
                        <span>Loading...</span>
                      </>
                    ) : (
                      <span>Show more</span>
                    )}
                  </button>
                )
              )}
            </div>
          </div>
        )}

        {/* T5. ISSUES TAB */}
        {activeTab === 'issues' && (
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-6 shadow-sm space-y-6">
            <div className="flex flex-col sm:flex-row justify-between sm:items-center gap-4 border-b border-slate-100 dark:border-slate-800 pb-4">
              <div>
                <h3 className="text-sm font-bold text-slate-800 dark:text-slate-200 uppercase tracking-widest">
                  Repository Issues
                </h3>
                {issues_summary && (
                  <p className="text-xs text-slate-400">
                    Total: {issues_summary.total} &bull; Open: {issues_summary.open} &bull; Closed:{' '}
                    {issues_summary.closed}
                  </p>
                )}
              </div>

              <div className="flex items-center space-x-1.5 bg-slate-100 dark:bg-slate-800 p-0.5 rounded-lg text-xs">
                {(['all', 'open', 'closed'] as const).map((filter) => (
                  <button
                    key={filter}
                    onClick={() => setIssueFilter(filter)}
                    className={`px-3 py-1 rounded-md capitalize font-semibold transition ${issueFilter === filter
                      ? 'bg-white dark:bg-slate-950 text-primary-600 dark:text-primary-400 shadow-sm'
                      : 'text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'
                      }`}
                  >
                    {filter}
                  </button>
                ))}
              </div>
            </div>

            {filteredIssues.length > 0 ? (
              <div className="divide-y divide-slate-100 dark:divide-slate-800/60">
                {filteredIssues.map((issue) => (
                  <div key={issue.number} className="py-4.5 first:pt-0 last:pb-0 flex items-start space-x-3.5 text-sm">
                    <div className="shrink-0 mt-0.5">
                      {issue.state === 'open' ? (
                        <AlertCircle className="w-4 h-4 text-emerald-500" />
                      ) : (
                        <CheckCircle className="w-4 h-4 text-purple-500" />
                      )}
                    </div>
                    <div className="space-y-1.5 min-w-0 flex-1">
                      <div className="flex items-start justify-between gap-4">
                        <h4 className="font-semibold text-slate-900 dark:text-slate-100">{issue.title}</h4>
                        <span className="text-xs text-slate-400 shrink-0 font-medium">#{issue.number}</span>
                      </div>
                      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-slate-400">
                        <span>by {issue.author}</span>
                        <span>&bull;</span>
                        <span>opened {formatDate(issue.created_at)}</span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-slate-400 text-center py-12">No issues match the selected filter.</p>
            )}
          </div>
        )}

        {/* T6. PULL REQUESTS TAB */}
        {activeTab === 'pull-requests' && (() => {
          const PR_PER_PAGE = 10;
          const totalFilteredPRs = filteredPRs.length;
          const totalPRPages = Math.max(1, Math.ceil(totalFilteredPRs / PR_PER_PAGE));
          const paginatedPRs = filteredPRs.slice((prPage - 1) * PR_PER_PAGE, prPage * PR_PER_PAGE);

          return (
            <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-6 shadow-sm space-y-6">
              <div className="flex flex-col sm:flex-row justify-between sm:items-center gap-4 border-b border-slate-100 dark:border-slate-800 pb-4">
                <div>
                  <h3 className="text-sm font-bold text-slate-800 dark:text-slate-200 uppercase tracking-widest">
                    Pull Requests
                  </h3>
                  {pull_requests_summary && (
                    <p className="text-xs text-slate-400">
                      Total: {pull_requests_summary.total} &bull; Open: {pull_requests_summary.open} &bull; Closed:{' '}
                      {pull_requests_summary.closed} &bull; Merged: {pull_requests_summary.merged}
                    </p>
                  )}
                </div>

                <div className="flex items-center space-x-1.5 bg-slate-100 dark:bg-slate-800 p-0.5 rounded-lg text-xs">
                  {(['all', 'open', 'closed', 'merged'] as const).map((filter) => {
                    const getFilterCount = () => {
                      if (!pull_requests_summary) return 0;
                      if (filter === 'all') return pull_requests_summary.total;
                      if (filter === 'open') return pull_requests_summary.open;
                      if (filter === 'closed') return pull_requests_summary.closed;
                      if (filter === 'merged') return pull_requests_summary.merged;
                      return 0;
                    };
                    return (
                      <button
                        key={filter}
                        onClick={() => {
                          setPrFilter(filter);
                          setPrPage(1);
                        }}
                        className={`px-3 py-1 rounded-md capitalize font-semibold transition ${
                          prFilter === filter
                            ? 'bg-white dark:bg-slate-950 text-primary-600 dark:text-primary-400 shadow-sm'
                            : 'text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'
                        }`}
                      >
                        {filter} ({getFilterCount()})
                      </button>
                    );
                  })}
                </div>
              </div>

              {paginatedPRs.length > 0 ? (
                <div className="divide-y divide-slate-100 dark:divide-slate-800/60">
                  {paginatedPRs.map((pr) => (
                    <div key={pr.number} className="py-4.5 first:pt-0 last:pb-0 flex items-start space-x-3.5 text-sm">
                      <div className="shrink-0 mt-0.5">
                        <GitPullRequest
                          className={`w-4 h-4 ${pr.is_merged ? 'text-purple-500' : pr.state === 'open' ? 'text-emerald-500' : 'text-red-500'
                            }`}
                        />
                      </div>
                      <div className="space-y-1.5 min-w-0 flex-1">
                        <div className="flex items-start justify-between gap-4">
                          <h4 className="font-semibold text-slate-900 dark:text-slate-100">{pr.title}</h4>
                          <span className="text-xs text-slate-400 shrink-0 font-medium">#{pr.number}</span>
                        </div>
                        <div className="flex items-center space-x-2 text-xs text-slate-400">
                          <span>by {pr.author}</span>
                          <span>&bull;</span>
                          <span>opened {formatDate(pr.created_at)}</span>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-xs text-slate-400 text-center py-12">No pull requests match the selected filter.</p>
              )}

              {/* PR Pagination Bar */}
              {totalFilteredPRs > 0 && (
                <div className="flex items-center justify-between pt-4 border-t border-slate-100 dark:border-slate-800 text-xs text-slate-500">
                  <div>
                    Showing {Math.min((prPage - 1) * PR_PER_PAGE + 1, totalFilteredPRs)} to{' '}
                    {Math.min(prPage * PR_PER_PAGE, totalFilteredPRs)} of {totalFilteredPRs} PRs
                  </div>
                  <div className="flex items-center space-x-2">
                    <button
                      disabled={prPage === 1}
                      onClick={() => setPrPage((p) => Math.max(1, p - 1))}
                      className="px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-200 disabled:opacity-40 disabled:cursor-not-allowed hover:bg-slate-50 dark:hover:bg-slate-700 transition"
                    >
                      Previous
                    </button>
                    <span className="font-semibold px-2">
                      Page {prPage} of {totalPRPages}
                    </span>
                    <button
                      disabled={prPage >= totalPRPages}
                      onClick={() => setPrPage((p) => Math.min(totalPRPages, p + 1))}
                      className="px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-200 disabled:opacity-40 disabled:cursor-not-allowed hover:bg-slate-50 dark:hover:bg-slate-700 transition"
                    >
                      Next
                    </button>
                  </div>
                </div>
              )}
            </div>
          );
        })()}

        {/* T7. DEPENDENCIES TAB (SECTION 5: DEPENDENCIES Collapsible Card View) */}
        {activeTab === 'dependencies' && (
          <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl p-6 shadow-sm space-y-6">
            <div className="flex flex-col sm:flex-row justify-between sm:items-center gap-4 border-b border-slate-100 dark:border-slate-800 pb-4">
              <div>
                <h3 className="text-sm font-bold text-slate-800 dark:text-slate-200 uppercase tracking-widest">
                  DEPENDENCIES ({dependencyDetails.length || dependenciesList.length})
                </h3>
                <p className="text-xs text-slate-400">Software packages, versions, and ecosystem roles</p>
              </div>

              <div className="relative w-full sm:w-64">
                <Search className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
                <input
                  type="text"
                  placeholder="Search package..."
                  value={depSearch}
                  onChange={(e) => setDepSearch(e.target.value)}
                  className="w-full pl-9 pr-3 py-1.5 text-xs bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-1 focus:ring-primary-500"
                />
              </div>
            </div>

            {filteredDeps.length > 0 ? (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {filteredDeps.map((dep, idx) => (
                  <div
                    key={idx}
                    className="p-4 bg-slate-50 dark:bg-slate-800/50 rounded-xl border border-slate-200 dark:border-slate-800 space-y-2"
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center space-x-2 font-mono text-xs font-bold text-slate-900 dark:text-slate-100">
                        <Package className="w-4 h-4 text-primary-500 shrink-0" />
                        <span>{dep.package}</span>
                      </div>
                      <span className="text-[10px] font-semibold bg-slate-200 dark:bg-slate-700 text-slate-700 dark:text-slate-300 px-2 py-0.5 rounded">
                        {dep.ecosystem}
                      </span>
                    </div>
                    <p className="text-xs text-slate-600 dark:text-slate-300">{dep.purpose}</p>
                    <div className="flex items-center justify-between text-[11px] text-slate-400 pt-1 border-t border-slate-200/50 dark:border-slate-700/50 font-mono">
                      <span>Version: {dep.version}</span>
                      <span>{dep.relationships}</span>
                    </div>
                  </div>
                ))}
              </div>
            ) : dependenciesList.length > 0 ? (
              <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3">
                {dependenciesList.map((dep, idx) => (
                  <div
                    key={idx}
                    className="p-3 bg-slate-50 dark:bg-slate-800/50 rounded-lg border border-slate-200 dark:border-slate-800 flex items-center justify-between text-xs font-mono"
                  >
                    <div className="flex items-center space-x-2 truncate">
                      <Package className="w-3.5 h-3.5 text-primary-500 shrink-0" />
                      <span className="text-slate-800 dark:text-slate-200 truncate">{dep}</span>
                    </div>
                    <span className="text-[10px] text-slate-400 font-sans">Direct</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-slate-400 text-center py-12 italic">Not detected</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
export default RepositoryDetail;
