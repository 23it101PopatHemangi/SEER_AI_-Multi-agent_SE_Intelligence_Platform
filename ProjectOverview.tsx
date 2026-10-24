import React, { useEffect, useState } from 'react';
import { useParams, useNavigate, Link, useLocation } from 'react-router-dom';
import { useOktaAuth } from '@okta/okta-react';
import { projectService, Project } from '../services/projectService';
import { repositoryService, Repository } from '../services/repositoryService';
import { jiraService, JiraConnection, JiraProjectOption } from '../services/jiraService';
import { SelectJiraProjectModal } from './SelectJiraProjectModal';
import {
  Cpu,
  Github,
  Trello,
  GitBranch,
  ShieldAlert,
  Brain,
  Calendar,
  Info,
  ArrowRight,
  AlertCircle,
  RefreshCw,
} from 'lucide-react';
import { LoadingSpinner } from './LoadingSpinner';

export const ProjectOverview: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const { authState, oktaAuth } = useOktaAuth();

  const [project, setProject] = useState<Project | null>(null);
  const [repositories, setRepositories] = useState<Repository[]>([]);
  const [loading, setLoading] = useState(true);

  // Authenticated user email from Okta
  const [userEmail, setUserEmail] = useState<string>('');

  // Jira connection states
  const [jiraState, setJiraState] = useState<'idle' | 'connecting' | 'connected' | 'error'>('idle');
  const [jiraConnection, setJiraConnection] = useState<JiraConnection | null>(null);
  const [availableJiraProjects, setAvailableJiraProjects] = useState<JiraProjectOption[]>([]);
  const [jiraError, setJiraError] = useState<string | null>(null);
  const [isJiraModalOpen, setIsJiraModalOpen] = useState<boolean>(false);
  const [connectingMsg, setConnectingMsg] = useState<string>('Connecting to Jira...');
  const [disconnectingJira, setDisconnectingJira] = useState<boolean>(false);

  // Retrieve authenticated Okta user claims
  useEffect(() => {
    let active = true;
    if (authState?.isAuthenticated) {
      oktaAuth.getUser().then((user) => {
        if (active && user.email) {
          setUserEmail(user.email);
        }
      }).catch(err => console.error('Error fetching Okta user info:', err));
    }
    return () => {
      active = false;
    };
  }, [authState, oktaAuth]);

  // Load Jira connection status for the project
  const loadJiraStatus = async (email?: string) => {
    if (!projectId) return;
    try {
      const status = await jiraService.getConnectionStatus(projectId, email);
      if (status.connected && status.connection) {
        setJiraConnection(status.connection);
        setJiraState('connected');
      } else {
        setJiraConnection(null);
        setJiraState('idle');
      }
      if (status.available_projects) {
        setAvailableJiraProjects(status.available_projects);
      }
      return status;
    } catch (err: any) {
      console.error('Failed to load Jira status:', err);
      // Keep idle if not connected
      setJiraState('idle');
    }
  };

  // Handle start Jira connection flow
  const handleConnectJira = async () => {
    if (!projectId) return;
    setJiraError(null);
    setJiraState('connecting');
    setConnectingMsg('Checking Jira connection...');

    try {
      const status = await jiraService.getConnectionStatus(projectId, userEmail);
      if (status.authenticated && status.available_projects && status.available_projects.length > 0) {
        // User already has authenticated Atlassian account -> open project selection directly
        setAvailableJiraProjects(status.available_projects);
        setJiraState(status.connected ? 'connected' : 'idle');
        setIsJiraModalOpen(true);
        return;
      }

      setConnectingMsg('Redirecting to Atlassian authorization...');
      const authUrl = await jiraService.getAuthUrl(userEmail || 'user@seer.ai', projectId);
      window.location.href = authUrl;
    } catch (err: any) {
      console.error('Jira connect error:', err);
      setJiraState('error');
      setJiraError(err.message || 'Failed to initiate Jira connection. Verify server configuration.');
    }
  };

  // Handle Jira disconnect
  const handleDisconnectJira = async () => {
    if (!projectId) return;
    setDisconnectingJira(true);
    try {
      await jiraService.disconnectProject(projectId);
      setJiraConnection(null);
      setJiraState('idle');
      setJiraError(null);
    } catch (err: any) {
      console.error('Failed to disconnect Jira:', err);
      setJiraState('error');
      setJiraError('Failed to disconnect Jira project.');
    } finally {
      setDisconnectingJira(false);
    }
  };

  const loadData = async () => {
    if (!projectId) return;
    try {
      // 1. Fetch project meta
      const proj = await projectService.getProjectById(projectId);
      if (proj) {
        setProject(proj);
      } else {
        navigate('/projects');
        return;
      }
      
      // 2. Fetch actual repositories connected (Single Source of Truth)
      const repos = await repositoryService.getRepositories(projectId);
      setRepositories(repos);

    } catch (err) {
      console.error('Failed to load project overview data:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (projectId) {
      loadData();
      loadJiraStatus(userEmail);
    }
  }, [projectId, userEmail]);

  // Handle OAuth callback redirect URL parameters
  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const jiraAuth = params.get('jira_auth');
    const jiraErr = params.get('jira_error');

    if (jiraAuth === 'success') {
      window.history.replaceState({}, document.title, window.location.pathname);
      loadJiraStatus(userEmail).then(() => {
        setIsJiraModalOpen(true);
      });
    } else if (jiraErr) {
      window.history.replaceState({}, document.title, window.location.pathname);
      setJiraState('error');
      setJiraError(decodeURIComponent(jiraErr));
    }
  }, [location.search, projectId, userEmail]);

  // Formats dates to local timezone (India/IST, UTC+5:30) and formats: "19 Aug 2026, 12:30 AM"
  const formatProjectDate = (isoString?: string) => {
    if (!isoString) return 'N/A';
    try {
      const cleanIsoString = isoString.endsWith('Z') || isoString.includes('+')
        ? isoString 
        : `${isoString}Z`;
      const date = new Date(cleanIsoString);
      if (isNaN(date.getTime())) return 'N/A';
      
      const formatter = new Intl.DateTimeFormat('en-US', {
        timeZone: 'Asia/Kolkata',
        day: 'numeric',
        month: 'short',
        year: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
        hour12: true
      });
      
      const parts = formatter.formatToParts(date);
      const day = parts.find(p => p.type === 'day')?.value;
      const month = parts.find(p => p.type === 'month')?.value;
      const year = parts.find(p => p.type === 'year')?.value;
      const hour = parts.find(p => p.type === 'hour')?.value;
      const minute = parts.find(p => p.type === 'minute')?.value;
      const dayPeriod = parts.find(p => p.type === 'dayPeriod')?.value || '';
      
      return `${day} ${month} ${year}, ${hour}:${minute} ${dayPeriod.toUpperCase()}`;
    } catch (e) {
      return 'N/A';
    }
  };

  if (loading) {
    return <LoadingSpinner />;
  }

  if (!project) {
    return null;
  }

  // Deduce architecture telemetry availability (if at least one connected repo is analyzed)
  const analyzedRepos = repositories.filter(r => r.analysis_status === 'Analyzed');
  const isArchitectureAvailable = analyzedRepos.length > 0;
  
  // Collect all unique frameworks detected
  const uniqueTechs: string[] = [];
  if (isArchitectureAvailable) {
    // If language fields exist, list them
    repositories.forEach(r => {
      if (r.primary_language && !uniqueTechs.includes(r.primary_language)) {
        uniqueTechs.push(r.primary_language);
      }
    });
  }

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      {/* 1. Project Info Header Card */}
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800/80 rounded-xl p-6 md:p-8 shadow-sm space-y-4 transition">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-extrabold text-slate-900 dark:text-white">{project.name}</h1>
            <p className="text-slate-500 dark:text-slate-400 text-sm mt-1 max-w-2xl">
              {project.description || 'No description provided for this workspace.'}
            </p>
          </div>

          <div className="flex items-center space-x-3 shrink-0">
            <span className="text-xs font-semibold text-slate-400 dark:text-slate-500 uppercase tracking-widest">
              Status:
            </span>
            <span className="text-xs font-bold bg-emerald-50 dark:bg-emerald-950/20 text-emerald-600 dark:text-emerald-400 border border-emerald-100 dark:border-emerald-900/30 px-2.5 py-1 rounded-full">
              {project.status}
            </span>
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-4 border-t border-slate-100 dark:border-slate-800/60 text-xs text-slate-500 dark:text-slate-400">
          <div className="flex items-center space-x-2">
            <Calendar className="w-4 h-4 text-slate-400" />
            <span><strong className="font-semibold text-slate-700 dark:text-slate-300">Created:</strong> {formatProjectDate(project.createdAt)}</span>
          </div>
          <div className="flex items-center space-x-2">
            <Calendar className="w-4 h-4 text-slate-400" />
            <span><strong className="font-semibold text-slate-700 dark:text-slate-300">Last Updated:</strong> {formatProjectDate(project.updatedAt)}</span>
          </div>
        </div>
      </div>

      {/* 2. Grid of Connected Features */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        
        {/* Repositories Section */}
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800/80 rounded-xl p-6 shadow-sm flex flex-col justify-between min-h-[200px] transition">
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-2.5">
                <div className="p-1.5 bg-slate-100 dark:bg-slate-850 text-slate-500 dark:text-slate-400 rounded-lg">
                  <Github className="w-4 h-4" />
                </div>
                <h3 className="font-bold text-sm text-slate-800 dark:text-slate-200">Repositories</h3>
              </div>
              <span className="text-xs bg-slate-150 dark:bg-slate-800 text-slate-600 dark:text-slate-400 px-2 py-0.5 rounded-full font-bold">
                {repositories.length} connected
              </span>
            </div>

            {repositories.length > 0 ? (
              <div className="space-y-3.5 max-h-[160px] overflow-y-auto pr-1">
                {repositories.map((repo) => (
                  <div key={repo.id} className="flex items-center justify-between border-b border-slate-100 dark:border-slate-800/60 pb-2 text-xs last:border-b-0 last:pb-0">
                    <Link
                      to={`/projects/${projectId}/repositories/${repo.id}`}
                      className="font-bold text-slate-700 dark:text-slate-350 hover:text-primary-650 dark:hover:text-primary-400 truncate max-w-[150px] sm:max-w-[200px] hover:underline"
                    >
                      {repo.name}
                    </Link>
                    <div className="flex items-center space-x-2 text-slate-400 dark:text-slate-500 font-medium">
                      <span>{repo.primary_language || 'None'}</span>
                      <span>&bull;</span>
                      <span className={`px-1.5 py-0.25 text-[9px] font-bold rounded ${
                        repo.analysis_status === 'Analyzed'
                          ? 'bg-emerald-50 dark:bg-emerald-950/20 text-emerald-600 dark:text-emerald-400'
                          : 'bg-slate-100 dark:bg-slate-800 text-slate-550 dark:text-slate-400'
                      }`}>
                        {repo.analysis_status === 'Analyzed' ? 'Analyzed' : 'Unanalyzed'}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-slate-500 dark:text-slate-400 leading-relaxed">
                No repositories connected yet.
              </p>
            )}
          </div>
          
          <div className="pt-4 border-t border-slate-100 dark:border-slate-800/60 mt-4">
            <Link
              to={`/projects/${projectId}/repositories`}
              className="inline-flex items-center space-x-2 bg-primary-600 hover:bg-primary-500 text-white text-xs font-semibold px-4.5 py-2.5 rounded-lg shadow-sm transition"
            >
              <span>Connect Repository</span>
              <ArrowRight className="w-3.5 h-3.5" />
            </Link>
          </div>
        </div>

        {/* Jira / Backlog Section */}
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800/80 rounded-xl p-6 shadow-sm flex flex-col justify-between min-h-[200px] transition">
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-2.5">
                <div className="p-1.5 bg-blue-50 dark:bg-blue-950/30 text-blue-600 dark:text-blue-400 rounded-lg">
                  <Trello className="w-4 h-4" />
                </div>
                <h3 className="font-bold text-sm text-slate-800 dark:text-slate-200">Jira / Backlog</h3>
              </div>

              {jiraState === 'connected' && (
                <span className="text-xs bg-emerald-50 dark:bg-emerald-950/20 text-emerald-600 dark:text-emerald-400 border border-emerald-100 dark:border-emerald-900/30 px-2 py-0.5 rounded-full font-bold">
                  Connected
                </span>
              )}
            </div>

            {/* State: Connected */}
            {jiraState === 'connected' && jiraConnection && (
              <div className="space-y-2.5">
                <div className="flex items-center justify-between border-b border-slate-100 dark:border-slate-800/60 pb-2 text-xs">
                  <div className="flex items-center space-x-2 truncate">
                    <span className="font-bold text-slate-800 dark:text-slate-200 truncate">
                      {jiraConnection.jira_project_name}
                    </span>
                    <span className="px-1.5 py-0.5 text-[10px] font-mono font-semibold bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 rounded shrink-0">
                      {jiraConnection.jira_project_key}
                    </span>
                  </div>
                  {jiraConnection.site_url && (
                    <a
                      href={jiraConnection.site_url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-[10px] font-semibold text-primary-600 dark:text-primary-400 hover:underline shrink-0"
                    >
                      Open Jira &rarr;
                    </a>
                  )}
                </div>
                <p className="text-xs text-slate-500 dark:text-slate-400 leading-relaxed">
                  Jira project is connected. Issue tracking and backlog sync are linked to this workspace.
                </p>
              </div>
            )}

            {/* State: Connecting */}
            {jiraState === 'connecting' && (
              <div className="py-6 flex flex-col items-center justify-center space-y-3">
                <div className="w-6 h-6 border-2 border-primary-500 border-t-transparent rounded-full animate-spin"></div>
                <p className="text-xs font-medium text-slate-600 dark:text-slate-400 animate-pulse">
                  {connectingMsg}
                </p>
              </div>
            )}

            {/* State: Error */}
            {jiraState === 'error' && (
              <div className="space-y-3">
                <div className="flex items-start space-x-2 p-3 text-xs text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/20 border border-red-200 dark:border-red-800/50 rounded-lg">
                  <AlertCircle className="w-4 h-4 shrink-0 text-red-500 mt-0.5" />
                  <span className="leading-snug">{jiraError || 'Failed to connect to Jira.'}</span>
                </div>
              </div>
            )}

            {/* State: Idle / Connect Jira */}
            {jiraState === 'idle' && (
              <p className="text-xs text-slate-500 dark:text-slate-400 leading-relaxed">
                No Jira project connected yet. Connect your Jira workspace to integrate project tracking.
              </p>
            )}
          </div>
          
          <div className="pt-4 border-t border-slate-100 dark:border-slate-800/60 mt-4">
            {jiraState === 'connected' ? (
              <div className="flex items-center justify-between">
                <button
                  type="button"
                  onClick={() => setIsJiraModalOpen(true)}
                  className="text-xs font-semibold text-primary-600 dark:text-primary-400 hover:underline"
                >
                  Change Project
                </button>
                <button
                  type="button"
                  onClick={handleDisconnectJira}
                  disabled={disconnectingJira}
                  className="text-xs font-bold text-red-600 hover:text-red-500 transition disabled:opacity-50"
                >
                  {disconnectingJira ? 'Disconnecting...' : 'Disconnect'}
                </button>
              </div>
            ) : jiraState === 'error' ? (
              <button
                type="button"
                onClick={handleConnectJira}
                className="inline-flex items-center space-x-2 bg-primary-600 hover:bg-primary-500 text-white text-xs font-semibold px-4.5 py-2.5 rounded-lg shadow-sm transition"
              >
                <RefreshCw className="w-3.5 h-3.5" />
                <span>Retry Connection</span>
              </button>
            ) : (
              <button
                type="button"
                onClick={handleConnectJira}
                disabled={jiraState === 'connecting'}
                className="inline-flex items-center space-x-2 bg-primary-600 hover:bg-primary-500 text-white text-xs font-semibold px-4.5 py-2.5 rounded-lg shadow-sm transition disabled:opacity-50"
              >
                <Trello className="w-3.5 h-3.5" />
                <span>Connect Jira</span>
                <ArrowRight className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        </div>

        {/* Architecture Section */}
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800/80 rounded-xl p-6 shadow-sm flex flex-col justify-between min-h-[200px] transition">
          <div className="space-y-4">
            <div className="flex items-center space-x-2.5">
              <div className="p-1.5 bg-slate-100 dark:bg-slate-850 text-slate-500 dark:text-slate-400 rounded-lg">
                <GitBranch className="w-4 h-4" />
              </div>
              <h3 className="font-bold text-sm text-slate-800 dark:text-slate-200">Architecture</h3>
            </div>
            
            {isArchitectureAvailable ? (
              <div className="space-y-2">
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  Architecture model mapping is active based on code telemetry.
                </p>
                {uniqueTechs.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {uniqueTechs.map(t => (
                      <span key={t} className="px-2 py-0.5 text-[9px] font-bold bg-primary-50 dark:bg-primary-950/20 text-primary-650 dark:text-primary-400 rounded border border-primary-100 dark:border-primary-900/30">
                        {t}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <p className="text-xs text-slate-500 dark:text-slate-400 leading-relaxed">
                Architecture insights will appear after repository analysis.
              </p>
            )}
          </div>

          <div className="flex items-center justify-between border-t border-slate-100 dark:border-slate-800/60 mt-4 pt-3.5">
            <div className="flex items-center space-x-2 text-[10px] text-slate-400 dark:text-slate-500 font-semibold">
              <Info className="w-3.5 h-3.5 text-primary-500/50" />
              <span>
                {isArchitectureAvailable ? 'Telemetry loaded successfully' : 'Awaiting code telemetry sync'}
              </span>
            </div>
            <Link
              to={`/projects/${projectId}/architecture`}
              className="text-[10px] font-bold text-primary-600 dark:text-primary-400 hover:underline"
            >
              View Maps &rarr;
            </Link>
          </div>
        </div>

        {/* Risk Analysis Section */}
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800/80 rounded-xl p-6 shadow-sm flex flex-col justify-between min-h-[200px] transition">
          <div className="space-y-4">
            <div className="flex items-center space-x-2.5">
              <div className="p-1.5 bg-slate-100 dark:bg-slate-850 text-slate-500 dark:text-slate-400 rounded-lg">
                <ShieldAlert className="w-4 h-4" />
              </div>
              <h3 className="font-bold text-sm text-slate-800 dark:text-slate-200">Risk Analysis</h3>
            </div>
            
            {repositories.length > 0 ? (
              <p className="text-xs text-slate-500 dark:text-slate-400 leading-relaxed">
                Risk scanning is active using commit velocity, branch patterns, and repository metrics.
              </p>
            ) : (
              <p className="text-xs text-slate-500 dark:text-slate-400 leading-relaxed">
                Risk analysis will be available after project analysis. Connect repositories to initiate risk maps.
              </p>
            )}
          </div>

          <div className="flex items-center justify-between border-t border-slate-100 dark:border-slate-800/60 mt-4 pt-3.5">
            <div className="flex items-center space-x-2 text-[10px] text-slate-400 dark:text-slate-500 font-semibold">
              <Info className="w-3.5 h-3.5 text-primary-500/50" />
              <span>
                {repositories.length > 0 ? 'Risk scoring available' : 'Awaiting repository data'}
              </span>
            </div>
            <Link
              to={`/projects/${projectId}/risk`}
              className="text-[10px] font-bold text-primary-600 dark:text-primary-400 hover:underline"
            >
              View Risk Scorecard &rarr;
            </Link>
          </div>
        </div>

        {/* AI Insights Section */}
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800/80 rounded-xl p-6 shadow-sm flex flex-col justify-between min-h-[200px] md:col-span-2 transition">
          <div className="space-y-4">
            <div className="flex items-center space-x-2.5">
              <div className="p-1.5 bg-slate-100 dark:bg-slate-850 text-slate-500 dark:text-slate-400 rounded-lg">
                <Brain className="w-4 h-4" />
              </div>
              <h3 className="font-bold text-sm text-slate-800 dark:text-slate-200">AI Insights</h3>
            </div>
            <p className="text-xs text-slate-500 dark:text-slate-400 leading-relaxed">
              AI insights will appear after project data is connected. Once code telemetry is synced, models extract insights here.
            </p>
          </div>

          <div className="flex items-center justify-between border-t border-slate-100 dark:border-slate-800/60 mt-4 pt-3.5">
            <div className="flex items-center space-x-2 text-[10px] text-slate-400 dark:text-slate-500 font-semibold">
              <Info className="w-3.5 h-3.5 text-primary-500/50" />
              <span>Awaiting data sync</span>
            </div>
            <Link
              to={`/projects/${projectId}/ai-insights`}
              className="text-[10px] font-bold text-primary-600 dark:text-primary-400 hover:underline"
            >
              View Insights &rarr;
            </Link>
          </div>
        </div>

      </div>

      {/* Jira Project Selection Modal */}
      {projectId && (
        <SelectJiraProjectModal
          isOpen={isJiraModalOpen}
          projectId={projectId}
          userEmail={userEmail}
          initialProjects={availableJiraProjects}
          onClose={() => setIsJiraModalOpen(false)}
          onConnected={async () => {
            await loadJiraStatus(userEmail);
          }}
        />
      )}
    </div>
  );
};
export default ProjectOverview;
