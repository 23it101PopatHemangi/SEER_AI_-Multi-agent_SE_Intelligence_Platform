import React, { useEffect, useState } from 'react';
import {
  AlertCircle,
  AlertTriangle,
  ArrowRight,
  Calendar,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  Code2,
  Database,
  ExternalLink,
  FileText,
  Filter,
  GitBranch,
  Github,
  HelpCircle,
  Info,
  Layers,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  Terminal,
  Trello,
  Zap,
} from 'lucide-react';
import { useOktaAuth } from '@okta/okta-react';
import { Link, useParams } from 'react-router-dom';
import { jiraService, JiraProjectDestination } from '../services/jiraService';
import {
  riskService,
  RiskAnalysisResponse,
  RiskIndicator,
  RiskEvidenceItem,
  RiskAffectedIssue,
  ApiError,
} from '../services/riskService';
import { LoadingSpinner } from './LoadingSpinner';

// Jira Issue Priority Styling: Highest, High, Medium, Low, Lowest
const getJiraPriorityBadge = (priority?: string) => {
  const norm = (priority || '').toLowerCase().trim();
  switch (norm) {
    case 'highest':
      return {
        bg: 'bg-red-100 dark:bg-red-950/70',
        text: 'text-red-700 dark:text-red-300',
        border: 'border-red-300 dark:border-red-800',
        label: 'Highest',
      };
    case 'high':
      return {
        bg: 'bg-orange-100 dark:bg-orange-950/70',
        text: 'text-orange-700 dark:text-orange-300',
        border: 'border-orange-300 dark:border-orange-800',
        label: 'High',
      };
    case 'medium':
      return {
        bg: 'bg-amber-100 dark:bg-amber-950/70',
        text: 'text-amber-700 dark:text-amber-300',
        border: 'border-amber-300 dark:border-amber-800',
        label: 'Medium',
      };
    case 'low':
      return {
        bg: 'bg-emerald-100 dark:bg-emerald-950/70',
        text: 'text-emerald-700 dark:text-emerald-300',
        border: 'border-emerald-300 dark:border-emerald-800',
        label: 'Low',
      };
    case 'lowest':
      return {
        bg: 'bg-slate-100 dark:bg-slate-800',
        text: 'text-slate-600 dark:text-slate-400',
        border: 'border-slate-300 dark:border-slate-700',
        label: 'Lowest',
      };
    case 'unassigned':
    case 'none':
    case 'null':
    case 'priority not set':
    case 'not set':
    case '':
    default:
      return {
        bg: 'bg-slate-100 dark:bg-slate-800/80',
        text: 'text-slate-600 dark:text-slate-400',
        border: 'border-slate-300 dark:border-slate-700',
        label: norm && !['unassigned', 'none', 'null', 'priority not set', 'not set', ''].includes(norm)
          ? priority!
          : 'Priority not set',
      };
  }
};

// Calculated Risk Severity Styling: Critical, High, Medium, Low
const severityBadge: Record<string, { bg: string; text: string; border: string }> = {
  critical: {
    bg: 'bg-rose-50 dark:bg-rose-950/40',
    text: 'text-rose-700 dark:text-rose-300',
    border: 'border-rose-300 dark:border-rose-900/60',
  },
  high: {
    bg: 'bg-red-50 dark:bg-red-950/40',
    text: 'text-red-700 dark:text-red-300',
    border: 'border-red-200 dark:border-red-900/60',
  },
  medium: {
    bg: 'bg-amber-50 dark:bg-amber-950/40',
    text: 'text-amber-700 dark:text-amber-300',
    border: 'border-amber-200 dark:border-amber-900/60',
  },
  low: {
    bg: 'bg-blue-50 dark:bg-blue-950/40',
    text: 'text-blue-700 dark:text-blue-300',
    border: 'border-blue-200 dark:border-blue-900/60',
  },
};

const categoryLabels: Record<string, string> = {
  schedule: 'Schedule',
  delivery: 'Delivery Block',
  dependency: 'Timeline Dependency',
  priority: 'Priority',
  hygiene: 'Task Hygiene',
  planning: 'Sprint Planning',
  ownership: 'Ownership',
  github: 'GitHub Telemetry',
  ci_cd: 'CI / CD Pipeline',
  srs_coverage: 'SRS Requirements',
  architecture: 'Architecture & Security',
  synchronization: 'Jira Sync',
};

const getOriginIcon = (origin?: string) => {
  const norm = (origin || '').toLowerCase();
  if (norm.includes('jira')) return <Trello className="w-3.5 h-3.5 text-blue-500" />;
  if (norm.includes('git')) return <Github className="w-3.5 h-3.5 text-slate-700 dark:text-slate-300" />;
  if (norm.includes('srs')) return <FileText className="w-3.5 h-3.5 text-emerald-500" />;
  if (norm.includes('arch')) return <Code2 className="w-3.5 h-3.5 text-purple-500" />;
  return <Database className="w-3.5 h-3.5 text-slate-500" />;
};

export const RiskAnalysis: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>();
  const { authState, oktaAuth } = useOktaAuth();
  const [email, setEmail] = useState('');
  const [destinations, setDestinations] = useState<JiraProjectDestination[]>([]);
  const [selectedProjectKey, setSelectedProjectKey] = useState('');
  const [analysis, setAnalysis] = useState<RiskAnalysisResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [apiError, setApiError] = useState<{ message: string; status?: number } | null>(null);

  // Filters & State
  const [severityFilter, setSeverityFilter] = useState<'all' | 'high' | 'medium' | 'low'>('all');
  const [originFilter, setOriginFilter] = useState<string>('all');
  const [expandedTechDetails, setExpandedTechDetails] = useState<Record<string, boolean>>({});

  useEffect(() => {
    if (authState?.isAuthenticated) {
      oktaAuth.getUser().then((user) => setEmail(user.email || '')).catch(() => undefined);
    }
  }, [authState, oktaAuth]);

  useEffect(() => {
    if (!projectId) return;
    jiraService
      .getProjectDestinations(projectId)
      .then((items) => {
        setDestinations(items);
        setSelectedProjectKey((current) => current || items[0]?.key || '');
      })
      .catch((err) => setApiError({ message: err.message || 'Failed to load Jira destinations.' }));
  }, [projectId]);

  const loadAnalysis = (showSpinner = false) => {
    if (!projectId) return;
    if (showSpinner) setLoading(true);
    else setRefreshing(true);
    setApiError(null);

    riskService
      .getAnalysis(projectId, email, selectedProjectKey || undefined)
      .then(setAnalysis)
      .catch((err: any) => {
        setApiError({
          message: err.message || 'Failed to load risk analysis.',
          status: err.status,
        });
      })
      .finally(() => {
        setLoading(false);
        setRefreshing(false);
      });
  };

  useEffect(() => {
    if (projectId) loadAnalysis(true);
  }, [projectId, email, selectedProjectKey]);

  if (loading) return <LoadingSpinner />;

  // Unique origins for dynamic origin filter pill list
  const availableOrigins = Array.from(
    new Set((analysis?.indicators || []).map((i) => i.source_origin || 'Unknown'))
  );

  const filteredIndicators = (analysis?.indicators || []).filter((ind) => {
    if (severityFilter !== 'all' && ind.severity !== severityFilter) return false;
    if (originFilter !== 'all' && (ind.source_origin || 'Unknown') !== originFilter) return false;
    return true;
  });

  const highCount = (analysis?.indicators || []).filter((i) => i.severity === 'high' || i.severity === 'critical').length;
  const medCount = (analysis?.indicators || []).filter((i) => i.severity === 'medium').length;
  const lowCount = (analysis?.indicators || []).filter((i) => i.severity === 'low').length;

  const formattedLastUpdated = analysis?.last_updated
    ? new Intl.DateTimeFormat('en-US', {
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
        second: '2-digit',
      }).format(new Date(analysis.last_updated))
    : null;

  const toggleTechDetails = (id: string) => {
    setExpandedTechDetails((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  return (
    <div className="p-6 md:p-8 max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white flex items-center gap-2.5">
            <ShieldAlert className="w-7 h-7 text-primary-500" />
            <span>Risk Intelligence & Delivery Analysis</span>
          </h1>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
            Verified delivery risks with separate Jira priorities, calculated risk severities, and clickable issue traces.
          </p>
        </div>

        <div className="flex items-center gap-2.5 flex-wrap">
          <select
            value={selectedProjectKey}
            onChange={(event) => setSelectedProjectKey(event.target.value)}
            className="px-3 py-2 text-sm rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-primary-500"
          >
            <option value="">All project issues / default</option>
            {destinations.map((destination) => (
              <option key={destination.key} value={destination.key}>
                {destination.name} ({destination.key})
              </option>
            ))}
          </select>

          <button
            type="button"
            onClick={() => loadAnalysis(false)}
            disabled={refreshing}
            className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-semibold text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg border border-slate-200 dark:border-slate-700 transition"
            title="Refresh Analysis from Live Sources"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${refreshing ? 'animate-spin' : ''}`} />
            <span>{refreshing ? 'Refreshing...' : 'Refresh'}</span>
          </button>

          <Link
            to={`/projects/${projectId}/jira-timeline`}
            className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-semibold rounded-lg bg-primary-50 text-primary-700 dark:bg-primary-950/40 dark:text-primary-300 border border-primary-200 dark:border-primary-800 hover:bg-primary-100 transition"
          >
            <Calendar className="w-3.5 h-3.5" />
            <span>View Timeline</span>
          </Link>
        </div>
      </div>

      {/* Graceful API Failure & Error Notification */}
      {apiError && (
        <div className="p-4 rounded-xl border border-red-200 dark:border-red-900/60 bg-red-50 dark:bg-red-950/20 text-sm text-red-800 dark:text-red-200 flex flex-col sm:flex-row sm:items-center justify-between gap-3 shadow-sm">
          <div className="flex items-start gap-2.5">
            <AlertCircle className="w-5 h-5 shrink-0 text-red-600 dark:text-red-400 mt-0.5" />
            <div>
              <p className="font-bold">
                {apiError.status === 401 || apiError.status === 403
                  ? 'Authentication or Authorization Required'
                  : apiError.status === 404
                  ? 'Resource Not Found'
                  : apiError.status === 429
                  ? 'Rate Limit Exceeded'
                  : apiError.status === 0
                  ? 'Network Connection Failure'
                  : 'Unable to Load Live Risk Telemetry'}
              </p>
              <p className="text-xs text-red-700 dark:text-red-300 mt-0.5">{apiError.message}</p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => loadAnalysis(false)}
            className="shrink-0 px-3 py-1.5 text-xs font-semibold rounded-lg bg-red-100 hover:bg-red-200 dark:bg-red-900/50 dark:hover:bg-red-800 text-red-800 dark:text-red-200 border border-red-300 dark:border-red-700 transition"
          >
            Retry Connection
          </button>
        </div>
      )}

      {analysis && (
        <>
          {/* Top Metric Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3.5" role="list" aria-label="Risk metrics">
            {/* Overall Health Card */}
            <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 flex flex-col justify-between shadow-sm hover:shadow-md hover:border-slate-300 dark:hover:border-slate-700 transition-all duration-200 cursor-default">
              <div>
                <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Overall Project Health</span>
                <div className="flex items-center gap-2 mt-2">
                  {analysis.health === 'At risk' && <ShieldAlert className="w-5 h-5 text-red-500" />}
                  {analysis.health === 'Needs attention' && <AlertTriangle className="w-5 h-5 text-amber-500" />}
                  {analysis.health === 'No risks detected' && <ShieldCheck className="w-5 h-5 text-emerald-500" />}
                  <p className="text-lg font-bold text-slate-900 dark:text-white">{analysis.health}</p>
                </div>
              </div>
              <div className="mt-3 pt-2 border-t border-slate-100 dark:border-slate-800 text-[11px] text-slate-500 flex items-center justify-between">
                <span>{highCount > 0 ? `${highCount} critical indicator(s)` : `${analysis.indicators.length} total signal(s)`}</span>
                <span className="font-mono text-[10px] text-slate-400">Rule-based</span>
              </div>
            </div>

            {/* Jira Issues */}
            <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 flex flex-col justify-between shadow-sm hover:shadow-md hover:border-slate-300 dark:hover:border-slate-700 transition-all duration-200 cursor-default">
              <div>
                <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider flex items-center justify-between">
                  <span>Jira Issues</span>
                  <Trello className="w-3.5 h-3.5 text-blue-500" />
                </span>
                <p className="text-2xl font-bold text-slate-900 dark:text-white mt-1">{analysis.jira_issue_count}</p>
              </div>
              <div className="mt-3 pt-2 border-t border-slate-100 dark:border-slate-800 flex items-center justify-between text-xs text-slate-500">
                <span>{analysis.unfinished_issue_count} unfinished</span>
                <span>{analysis.jira_issue_count - analysis.unfinished_issue_count} completed</span>
              </div>
            </div>

            {/* Overdue & Blocked */}
            <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 flex flex-col justify-between shadow-sm hover:shadow-md hover:border-slate-300 dark:hover:border-slate-700 transition-all duration-200 cursor-default">
              <div>
                <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider flex items-center justify-between">
                  <span>Schedule Bottlenecks</span>
                  <Clock className="w-3.5 h-3.5 text-red-500" />
                </span>
                <div className="flex items-baseline gap-2 mt-1">
                  <p className="text-2xl font-bold text-red-600 dark:text-red-400">{analysis.overdue_issue_count}</p>
                  <span className="text-xs text-slate-500">overdue / {analysis.blocked_issue_count} blocked</span>
                </div>
              </div>
              <div className="mt-3 pt-2 border-t border-slate-100 dark:border-slate-800 text-[11px] text-slate-400">
                Verified due dates strictly before today
              </div>
            </div>

            {/* GitHub Telemetry */}
            <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 flex flex-col justify-between shadow-sm hover:shadow-md hover:border-slate-300 dark:hover:border-slate-700 transition-all duration-200 cursor-default">
              <div>
                <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider flex items-center justify-between">
                  <span>GitHub Telemetry</span>
                  <Github className="w-3.5 h-3.5 text-slate-700 dark:text-slate-300" />
                </span>
                <p className="text-2xl font-bold text-slate-900 dark:text-white mt-1">
                  {analysis.github_activity.recent_commits} <span className="text-sm font-normal text-slate-500">commits</span>
                </p>
              </div>
              <div className="mt-3 pt-2 border-t border-slate-100 dark:border-slate-800 flex items-center justify-between text-xs text-slate-500">
                <span>{analysis.github_activity.open_issues} open repo issues</span>
                <span>{analysis.github_activity.repositories} repo(s)</span>
              </div>
            </div>
          </div>

          {/* Assessment Basis Banner & Last-Updated */}
          <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 flex flex-col md:flex-row md:items-center justify-between gap-3 text-xs text-slate-600 dark:text-slate-300 shadow-sm">
            <div>
              <strong className="text-slate-800 dark:text-slate-200">Assessment Methodology & Telemetry Scope:</strong> {analysis.health_basis}
              <p className="mt-1 text-slate-400 dark:text-slate-500">{analysis.prediction_status}</p>
            </div>
            {formattedLastUpdated && (
              <div className="shrink-0 flex items-center gap-1.5 text-slate-500 dark:text-slate-400 font-mono text-[11px] bg-slate-50 dark:bg-slate-800/60 px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700">
                <Clock className="w-3 h-3 text-primary-500" />
                <span>Verified: {formattedLastUpdated}</span>
              </div>
            )}
          </div>

          {analysis.message && (
            <div className="p-4 rounded-xl border border-amber-200 bg-amber-50 text-xs text-amber-800 dark:border-amber-900/50 dark:bg-amber-950/20 dark:text-amber-200 flex items-center gap-2">
              <Info className="w-4 h-4 shrink-0" />
              <span>{analysis.message}</span>
            </div>
          )}

          {/* Filter Bar & Risk Indicators List */}
          <div className="space-y-4">
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <h2 className="text-base font-bold text-slate-900 dark:text-white">Detected Risk Indicators</h2>
                <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400">
                  {filteredIndicators.length} of {analysis.indicators.length}
                </span>
              </div>

              {/* Severity & Origin filter pills */}
              <div className="flex items-center gap-2 flex-wrap text-xs">
                {/* Severity Pills */}
                <div className="inline-flex rounded-lg border border-slate-200 dark:border-slate-700 p-0.5 bg-slate-50 dark:bg-slate-800/40">
                  <button
                    type="button"
                    onClick={() => setSeverityFilter('all')}
                    className={`px-2 py-1 rounded font-semibold transition ${
                      severityFilter === 'all'
                        ? 'bg-slate-900 text-white dark:bg-white dark:text-slate-900 shadow-sm'
                        : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
                    }`}
                  >
                    All ({analysis.indicators.length})
                  </button>
                  <button
                    type="button"
                    onClick={() => setSeverityFilter('high')}
                    className={`px-2 py-1 rounded font-semibold transition ${
                      severityFilter === 'high'
                        ? 'bg-red-600 text-white shadow-sm'
                        : 'text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/30'
                    }`}
                  >
                    High ({highCount})
                  </button>
                  <button
                    type="button"
                    onClick={() => setSeverityFilter('medium')}
                    className={`px-2 py-1 rounded font-semibold transition ${
                      severityFilter === 'medium'
                        ? 'bg-amber-600 text-white shadow-sm'
                        : 'text-amber-600 dark:text-amber-400 hover:bg-amber-50 dark:hover:bg-amber-950/30'
                    }`}
                  >
                    Med ({medCount})
                  </button>
                  <button
                    type="button"
                    onClick={() => setSeverityFilter('low')}
                    className={`px-2 py-1 rounded font-semibold transition ${
                      severityFilter === 'low'
                        ? 'bg-blue-600 text-white shadow-sm'
                        : 'text-blue-600 dark:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-950/30'
                    }`}
                  >
                    Low ({lowCount})
                  </button>
                </div>

                {/* Origin Filter Dropdown/Pills */}
                {availableOrigins.length > 1 && (
                  <select
                    value={originFilter}
                    onChange={(e) => setOriginFilter(e.target.value)}
                    className="px-2.5 py-1 text-xs font-semibold rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-700 dark:text-slate-300"
                  >
                    <option value="all">All Origins</option>
                    {availableOrigins.map((orig) => (
                      <option key={orig} value={orig}>
                        {orig}
                      </option>
                    ))}
                  </select>
                )}
              </div>
            </div>

            {filteredIndicators.length === 0 ? (
              <div className="border border-dashed border-slate-300 dark:border-slate-700 rounded-xl p-10 text-center text-sm text-slate-500">
                {analysis.indicators.length === 0
                  ? 'No delivery risks detected across current Jira and GitHub telemetry.'
                  : `No indicators match current filter criteria.`}
              </div>
            ) : (
              <div className="space-y-4">
                {filteredIndicators.map((indicator, index) => {
                  const style = severityBadge[indicator.severity.toLowerCase()] || severityBadge.low;
                  const indicatorId = `${indicator.category}-${index}`;
                  const isTechDetailsOpen = !!expandedTechDetails[indicatorId];

                  return (
                    <div
                      key={indicatorId}
                      className={`group rounded-xl border p-5 transition-all duration-200 shadow-sm hover:shadow-md ${style.bg} ${style.border}`}
                    >
                      {/* Indicator Header */}
                      <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-2">
                        <div className="space-y-1">
                          <div className="flex items-center gap-2 flex-wrap">
                            {/* Calculated Risk Severity Badge */}
                            <span
                              className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded border ${style.border} ${style.text}`}
                              title="Calculated Risk Severity based on delivery rules"
                            >
                              Risk Severity: {indicator.severity}
                            </span>

                            <span className="text-[11px] font-medium text-slate-500 dark:text-slate-400">
                              Category: <strong>{categoryLabels[indicator.category] || indicator.category}</strong>
                            </span>

                            <div className="inline-flex items-center gap-1 text-[11px] font-semibold px-2 py-0.5 rounded bg-white/80 dark:bg-slate-900/80 border border-slate-200/80 dark:border-slate-800 text-slate-700 dark:text-slate-300">
                              {getOriginIcon(indicator.source_origin)}
                              <span>{indicator.source_origin || 'Telemetry'}</span>
                            </div>
                          </div>
                          <h3 className="text-base font-bold text-slate-900 dark:text-white pt-1">
                            {indicator.title}
                          </h3>
                        </div>
                      </div>

                      {/* Explanation & Action */}
                      <div className="mt-3.5 grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
                        <div className="p-3 rounded-lg bg-white/70 dark:bg-slate-900/60 border border-slate-200/50 dark:border-slate-800/50 hover:border-slate-300 dark:hover:border-slate-700 transition-colors duration-150">
                          <span className="font-semibold text-slate-700 dark:text-slate-300 block mb-1">
                            Risk Explanation / Root Cause:
                          </span>
                          <p className="text-slate-600 dark:text-slate-400 leading-relaxed">{indicator.reason}</p>
                        </div>

                        <div className="p-3 rounded-lg bg-white/70 dark:bg-slate-900/60 border border-slate-200/50 dark:border-slate-800/50 hover:border-slate-300 dark:hover:border-slate-700 transition-colors duration-150">
                          <span className="font-semibold text-slate-700 dark:text-slate-300 flex items-center gap-1 mb-1">
                            <Zap className="w-3 h-3 text-amber-500" /> Actionable AI Recommendation:
                          </span>
                          <p className="text-slate-600 dark:text-slate-400 leading-relaxed">{indicator.suggested_action}</p>
                        </div>
                      </div>

                      {/* Affected Jira Issues with Real Priority Badges and Clickable Links */}
                      {((indicator.affected_issues && indicator.affected_issues.length > 0) ||
                        (indicator.affected_issue_keys && indicator.affected_issue_keys.length > 0)) && (
                        <div className="mt-3.5 flex items-center gap-2 flex-wrap">
                          <span className="text-[11px] font-semibold text-slate-700 dark:text-slate-300">
                            Affected Jira Issues:
                          </span>
                          {(indicator.affected_issues && indicator.affected_issues.length > 0
                            ? indicator.affected_issues
                            : (indicator.affected_issue_keys || []).map((k) => ({
                                key: k,
                                jira_url: analysis.jira_base_url
                                  ? `${analysis.jira_base_url.replace(/\/$/, '')}/browse/${k}`
                                  : undefined,
                              }))
                          ).map((issue: RiskAffectedIssue) => {
                            const pBadge = getJiraPriorityBadge(issue.priority);
                            const issueHref =
                              issue.jira_url ||
                              (analysis.jira_base_url
                                ? `${analysis.jira_base_url.replace(/\/$/, '')}/browse/${issue.key}`
                                : null);

                            return (
                              <div
                                key={issue.key}
                                className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-lg bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 shadow-sm hover:border-primary-300 dark:hover:border-primary-700 transition-colors duration-150"
                              >
                                {issueHref ? (
                                  <a
                                    href={issueHref}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="text-[11px] font-mono font-bold text-primary-600 dark:text-primary-400 hover:underline inline-flex items-center gap-1"
                                    title={`Open ${issue.key} in Jira (external tab)`}
                                  >
                                    <span>{issue.key}</span>
                                    <ExternalLink className="w-2.5 h-2.5 shrink-0" />
                                  </a>
                                ) : (
                                  <span
                                    className="text-[11px] font-mono font-bold text-slate-700 dark:text-slate-300"
                                    title="Link unavailable"
                                  >
                                    {issue.key}
                                  </span>
                                )}

                                {/* Real Jira Priority Badge */}
                                <span
                                  className={`text-[9px] font-bold px-1.5 py-0.2 rounded border ${pBadge.bg} ${pBadge.text} ${pBadge.border}`}
                                  title={pBadge.label === "Priority not set" ? "No priority set in Jira — not a risk signal" : `Jira Priority: ${pBadge.label}`}
                                >
                                  {pBadge.label}
                                </span>
                              </div>
                            );
                          })}
                        </div>
                      )}

                      {/* Supporting Evidence List with Direct Clickable External Links */}
                      {((indicator.evidence_items && indicator.evidence_items.length > 0) ||
                        (indicator.evidence && indicator.evidence.length > 0)) && (
                        <div className="mt-3 pt-3 border-t border-slate-200/60 dark:border-slate-800/60">
                          <span className="text-[11px] font-bold text-slate-700 dark:text-slate-300 block mb-1.5">
                            Verified Telemetry Evidence:
                          </span>
                          <ul className="space-y-1.5 text-xs text-slate-600 dark:text-slate-300 font-mono">
                            {indicator.evidence_items && indicator.evidence_items.length > 0
                              ? indicator.evidence_items.map((item, itemIdx) => (
                                  <li key={itemIdx} className="flex items-start gap-1.5">
                                    <span className="text-slate-400 select-none mt-0.5">•</span>
                                    {item.url ? (
                                      <a
                                        href={item.url}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="text-primary-600 dark:text-primary-400 hover:underline inline-flex items-center gap-1 break-all"
                                      >
                                        <span>{item.label}</span>
                                        <ExternalLink className="w-3 h-3 shrink-0" />
                                      </a>
                                    ) : (
                                      <span className="break-all">{item.label}</span>
                                    )}
                                  </li>
                                ))
                              : indicator.evidence.map((rawEvidence, itemIdx) => (
                                  <li key={itemIdx} className="flex items-start gap-1.5">
                                    <span className="text-slate-400 select-none">•</span>
                                    <span className="break-all">{rawEvidence}</span>
                                  </li>
                                ))}
                          </ul>
                        </div>
                      )}

                      {/* Collapsible Technical Details Section */}
                      {(indicator.source_api || indicator.calculation_logic) && (
                        <div className="mt-3 pt-2">
                          <button
                            type="button"
                            onClick={() => toggleTechDetails(indicatorId)}
                            className="inline-flex items-center gap-1 text-[11px] font-semibold text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-100 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 rounded"
                          >
                            {isTechDetailsOpen ? (
                              <ChevronDown className="w-3 h-3" />
                            ) : (
                              <ChevronRight className="w-3 h-3" />
                            )}
                            <span>Technical Details</span>
                          </button>

                          {isTechDetailsOpen && (
                            <div className="mt-2 p-2.5 rounded-lg bg-slate-900/5 dark:bg-slate-950/40 border border-slate-200/60 dark:border-slate-800/60 text-[11px] font-mono space-y-1 text-slate-600 dark:text-slate-400">
                              {indicator.source_api && (
                                <div className="flex items-start gap-1.5">
                                  <span className="font-semibold text-slate-700 dark:text-slate-300 select-none shrink-0">
                                    Source API:
                                  </span>
                                  <span className="text-primary-600 dark:text-primary-400 break-all">
                                    {indicator.source_api}
                                  </span>
                                </div>
                              )}
                              {indicator.calculation_logic && (
                                <div className="flex items-start gap-1.5">
                                  <span className="font-semibold text-slate-700 dark:text-slate-300 select-none shrink-0">
                                    Logic Rule:
                                  </span>
                                  <span className="text-slate-600 dark:text-slate-400 break-all">
                                    {indicator.calculation_logic}
                                  </span>
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
};

export default RiskAnalysis;


