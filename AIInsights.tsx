import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle,
  ArrowRight,
  Bot,
  Brain,
  CheckCircle2,
  ExternalLink,
  FileSearch,
  Filter,
  GitFork,
  Github,
  MessageSquare,
  RefreshCw,
  Send,
  ShieldAlert,
  Sparkles,
  Trash2,
  Trello,
  User,
  Zap,
} from 'lucide-react';
import { useOktaAuth } from '@okta/okta-react';
import { useParams } from 'react-router-dom';
import {
  ReactFlow,
  Background,
  Controls,
  Edge,
  MiniMap,
  Node,
  Position,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import {
  insightsService,
  InsightResponse,
  JiraDependencyGraph,
} from '../services/insightsService';
import { LoadingSpinner } from './LoadingSpinner';
import { useTheme } from '../context/ThemeContext';

interface ChatMessage {
  id: string;
  sender: 'user' | 'assistant';
  timestamp: string;
  question?: string;
  data?: InsightResponse;
  error?: string;
}

const QUESTION_CATEGORIES = [
  {
    category: '⚡ Delivery Risks',
    questions: [
      'What are the biggest delivery risks and what should we do next?',
      'Which Jira issues are currently blocked or overdue?',
    ],
  },
  {
    category: '📋 Sprint & Backlog',
    questions: [
      'Which Jira issues should the team prioritize this week?',
      'Are any tasks stale or missing assignees?',
    ],
  },
  {
    category: '🏗️ Architecture & APIs',
    questions: [
      'How does the current architecture support the requested work?',
      'Are there unapproved security or authentication components?',
    ],
  },
  {
    category: '📄 Requirements & SRS',
    questions: [
      'Which requirements from the SRS are pending approval in Jira?',
      'How complete is the SRS requirement coverage?',
    ],
  },
];

const FOLLOW_UPS = [
  'Show the dependency chain behind that risk.',
  'Which source supports this finding?',
  'What should the engineering team do first?',
  'Are there any unaddressed security gaps?',
];

function formatInlineMarkdown(text: string): React.ReactNode {
  const tokens = text.split(/(\*\*[^*]+\*\*|\[[^\]]+\]\([^)]+\))/g);
  return tokens.map((token, i) => {
    if (token.startsWith('**') && token.endsWith('**')) {
      return (
        <strong key={i} className="font-semibold text-slate-900 dark:text-white">
          {token.slice(2, -2)}
        </strong>
      );
    }
    const linkMatch = token.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
    if (linkMatch) {
      return (
        <a
          key={i}
          href={linkMatch[2]}
          target="_blank"
          rel="noopener noreferrer"
          className="text-primary-600 dark:text-primary-400 hover:underline font-medium inline-flex items-center gap-0.5"
        >
          {linkMatch[1]}
          <ExternalLink className="w-2.5 h-2.5 shrink-0" />
        </a>
      );
    }
    return token;
  });
}

function renderFormattedAnswer(text: string) {
  const paragraphs = text.split('\n\n');
  return (
    <div className="space-y-2.5 text-sm text-slate-700 dark:text-slate-300 leading-relaxed">
      {paragraphs.map((para, pIdx) => {
        const lines = para.split('\n');
        const isList = lines.length > 1 && lines.every((l) => /^\s*[-*•]/.test(l));
        if (isList) {
          return (
            <ul key={pIdx} className="space-y-1.5 pl-4 list-disc list-outside text-slate-700 dark:text-slate-300">
              {lines.map((line, lIdx) => (
                <li key={lIdx} className="leading-snug">
                  {formatInlineMarkdown(line.replace(/^\s*[-*•]\s*/, ''))}
                </li>
              ))}
            </ul>
          );
        }
        return (
          <p key={pIdx} className="leading-relaxed">
            {formatInlineMarkdown(para)}
          </p>
        );
      })}
    </div>
  );
}

export const AIInsights: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>();
  const { oktaAuth } = useOktaAuth();
  const { theme } = useTheme();
  const isDark = theme === 'dark';

  const [activeTab, setActiveTab] = useState<'chat' | 'graph'>('chat');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputQuestion, setInputQuestion] = useState('');
  const [loading, setLoading] = useState(false);
  const [email, setEmail] = useState<string>();

  // Graph state
  const [graph, setGraph] = useState<JiraDependencyGraph | null>(null);
  const [graphLoading, setGraphLoading] = useState(false);
  const [graphError, setGraphError] = useState<string | null>(null);
  const [graphFilter, setGraphFilter] = useState<'all' | 'blocked' | 'risk'>('all');

  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    oktaAuth.getUser().then((user) => setEmail(user.email)).catch(() => undefined);
  }, [oktaAuth]);

  // Load dependency graph on mount or tab change
  const loadGraph = () => {
    if (!projectId) return;
    setGraphLoading(true);
    setGraphError(null);
    insightsService
      .getJiraDependencyGraph(projectId, email)
      .then((data) => {
        setGraph(data);
      })
      .catch((err) => {
        setGraphError(err.message || 'Unable to load Jira dependencies.');
      })
      .finally(() => setGraphLoading(false));
  };

  useEffect(() => {
    if (projectId) loadGraph();
  }, [projectId, email]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  const handleAsk = async (textToSend?: string) => {
    const q = (textToSend || inputQuestion).trim();
    if (!projectId || q.length < 3 || loading) return;

    setInputQuestion('');
    const userMsgId = `user-${Date.now()}`;
    const assistantMsgId = `assistant-${Date.now()}`;

    setMessages((prev) => [
      ...prev,
      {
        id: userMsgId,
        sender: 'user',
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        question: q,
      },
    ]);

    setLoading(true);

    try {
      const response = await insightsService.ask(projectId, q, email);
      setMessages((prev) => [
        ...prev,
        {
          id: assistantMsgId,
          sender: 'assistant',
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          data: response,
        },
      ]);
    } catch (err: any) {
      setMessages((prev) => [
        ...prev,
        {
          id: assistantMsgId,
          sender: 'assistant',
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          error: err.message || 'Unable to retrieve answer from project telemetry.',
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  // Build ReactFlow nodes & edges with dark mode visibility
  const graphNodes = useMemo<Node[]>(() => {
    if (!graph || !graph.nodes) return [];
    const visible = graph.nodes.filter((node) => {
      if (graphFilter === 'blocked') return node.blocked;
      if (graphFilter === 'risk') return node.risk;
      return true;
    });

    const cols = 4;
    return visible.map((node, index) => {
      const col = index % cols;
      const row = Math.floor(index / cols);
      const isBlocked = node.blocked;
      const isRisk = node.risk;

      const borderColor = isBlocked
        ? '#ef4444'
        : isRisk
        ? '#f59e0b'
        : isDark
        ? '#334155'
        : '#cbd5e1';

      const bgColor = isBlocked
        ? isDark
          ? 'rgba(69, 10, 10, 0.95)'
          : 'rgba(254, 242, 242, 0.98)'
        : isRisk
        ? isDark
          ? 'rgba(69, 26, 3, 0.95)'
          : 'rgba(255, 251, 235, 0.98)'
        : isDark
        ? 'rgba(15, 23, 42, 0.95)'
        : 'rgba(255, 255, 255, 0.98)';

      return {
        id: node.id,
        position: { x: col * 320, y: row * 160 },
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
        data: {
          label: (
            <div
              className="p-3.5 rounded-xl cursor-pointer hover:scale-[1.02] transition-transform text-left space-y-1.5"
              onClick={() => {
                if (node.url) window.open(node.url, '_blank', 'noopener,noreferrer');
              }}
            >
              <div className="flex items-center justify-between gap-1.5">
                <span className="font-mono font-bold text-xs text-primary-500 dark:text-primary-400">
                  {node.id}
                </span>
                {node.url && <ExternalLink className="w-3 h-3 text-slate-400 shrink-0" />}
              </div>
              <p className="text-xs font-medium text-slate-900 dark:text-slate-100 line-clamp-2 leading-snug">
                {node.title}
              </p>
              <div className="flex items-center gap-1.5 pt-1 text-[10px] flex-wrap">
                <span className="px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 font-semibold border border-slate-200 dark:border-slate-700">
                  {node.status}
                </span>
                <span className="px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 border border-slate-200 dark:border-slate-700">
                  {node.priority}
                </span>
                {isBlocked && (
                  <span className="px-1.5 py-0.5 rounded bg-red-100 dark:bg-red-950/80 text-red-700 dark:text-red-300 font-bold border border-red-200 dark:border-red-900">
                    Blocked
                  </span>
                )}
                {isRisk && !isBlocked && (
                  <span className="px-1.5 py-0.5 rounded bg-amber-100 dark:bg-amber-950/80 text-amber-700 dark:text-amber-300 font-bold border border-amber-200 dark:border-amber-900">
                    At Risk
                  </span>
                )}
              </div>
            </div>
          ),
        },
        style: {
          width: 290,
          borderRadius: '0.85rem',
          borderWidth: '1.5px',
          borderColor: borderColor,
          background: bgColor,
          color: isDark ? '#f8fafc' : '#0f172a',
          boxShadow: isDark
            ? '0 4px 6px -1px rgba(0, 0, 0, 0.5)'
            : '0 2px 4px rgba(0, 0, 0, 0.06)',
        },
      };
    });
  }, [graph, graphFilter, isDark]);

  const graphEdges = useMemo<Edge[]>(() => {
    if (!graph || !graph.edges) return [];
    const visibleIds = new Set(graphNodes.map((n) => n.id));

    return graph.edges
      .filter((edge) => visibleIds.has(edge.source) && visibleIds.has(edge.target))
      .map((edge) => {
        const isBlockEdge = (edge.relationship || '').toLowerCase().includes('block');
        return {
          id: edge.id,
          source: edge.source,
          target: edge.target,
          label: edge.relationship,
          animated: isBlockEdge,
          style: {
            stroke: isBlockEdge ? '#ef4444' : isDark ? '#94a3b8' : '#64748b',
            strokeWidth: isBlockEdge ? 2.5 : 1.75,
          },
          labelStyle: {
            fontSize: 10,
            fontWeight: 700,
            fill: isBlockEdge ? '#ef4444' : isDark ? '#e2e8f0' : '#334155',
          },
          labelBgStyle: {
            fill: isDark ? '#0f172a' : '#ffffff',
            fillOpacity: 0.95,
          },
          labelBgPadding: [4, 2] as [number, number],
          labelBgBorderRadius: 4,
        };
      });
  }, [graph, graphNodes, isDark]);

  return (
    <div className="p-4 md:p-6 max-w-7xl mx-auto space-y-5">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-extrabold text-slate-900 dark:text-white flex items-center gap-2.5">
            <div className="p-2 rounded-xl bg-primary-600 text-white shadow-sm">
              <Sparkles className="w-5 h-5" />
            </div>
            <span>Engineering Copilot & Insights</span>
          </h1>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            Project-aware conversational assistant grounded in real Jira tickets, GitHub commits, SRS requirements, and Risk Analysis.
          </p>
        </div>

        {/* Tab Toggle */}
        <div className="inline-flex rounded-xl border border-slate-200 dark:border-slate-800 p-1 bg-white dark:bg-slate-900 shadow-xs">
          <button
            type="button"
            onClick={() => setActiveTab('chat')}
            className={`inline-flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition ${
              activeTab === 'chat'
                ? 'bg-primary-600 text-white shadow-sm'
                : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
            }`}
          >
            <MessageSquare className="w-3.5 h-3.5" />
            <span>Copilot Chat</span>
            {messages.length > 0 && (
              <span className="px-1.5 py-0.2 rounded-full text-[10px] bg-white/20 text-white">
                {messages.length}
              </span>
            )}
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('graph')}
            className={`inline-flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition ${
              activeTab === 'graph'
                ? 'bg-primary-600 text-white shadow-sm'
                : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
            }`}
          >
            <GitFork className="w-3.5 h-3.5" />
            <span>Jira Dependency Graph</span>
            {graph?.nodes && (
              <span className="px-1.5 py-0.2 rounded-full text-[10px] bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400">
                {graph.nodes.length}
              </span>
            )}
          </button>
        </div>
      </div>

      {/* ========================================================================= */}
      {/* TAB 1: COPILOT CHAT                                                       */}
      {/* ========================================================================= */}
      {activeTab === 'chat' && (
        <div className="space-y-4">
          {/* Categorized Question Chips */}
          <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-xs space-y-2.5">
            <div className="flex items-center justify-between text-xs text-slate-500">
              <span className="font-semibold text-slate-700 dark:text-slate-300 flex items-center gap-1.5">
                <Bot className="w-4 h-4 text-primary-500" />
                <span>Suggested Questions Grounded in Project Data</span>
              </span>
              {messages.length > 0 && (
                <button
                  type="button"
                  onClick={() => setMessages([])}
                  className="inline-flex items-center gap-1 text-[11px] text-slate-400 hover:text-red-500 transition"
                  title="Clear conversation"
                >
                  <Trash2 className="w-3 h-3" />
                  <span>Clear Chat</span>
                </button>
              )}
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              {QUESTION_CATEGORIES.map((cat) => (
                <div key={cat.category} className="space-y-1">
                  <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400">
                    {cat.category}
                  </span>
                  <div className="flex flex-col gap-1">
                    {cat.questions.map((q) => (
                      <button
                        key={q}
                        type="button"
                        onClick={() => handleAsk(q)}
                        disabled={loading}
                        className="text-left px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-900/60 hover:bg-primary-50 dark:hover:bg-primary-950/30 hover:border-primary-300 dark:hover:border-primary-700 text-slate-700 dark:text-slate-300 text-xs transition line-clamp-1 disabled:opacity-50"
                      >
                        {q}
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Chat Messages Stream */}
          <div className="space-y-4 min-h-[300px]">
            {messages.length === 0 && (
              <div className="p-8 border border-dashed border-slate-200 dark:border-slate-800 rounded-2xl text-center space-y-4 bg-slate-50/50 dark:bg-slate-900/30">
                <div className="w-12 h-12 rounded-2xl bg-primary-100 dark:bg-primary-950/60 text-primary-600 dark:text-primary-400 flex items-center justify-center mx-auto shadow-xs">
                  <Sparkles className="w-6 h-6" />
                </div>
                <div className="space-y-1">
                  <h3 className="text-base font-bold text-slate-800 dark:text-slate-100">
                    SEER Engineering Copilot
                  </h3>
                  <p className="text-xs text-slate-500 dark:text-slate-400 max-w-md mx-auto">
                    Real-time telemetry grounded in Jira issues, GitHub repositories, and SRS requirements.
                  </p>
                </div>
                <div className="flex items-center justify-center gap-2 pt-1 flex-wrap">
                  <button
                    type="button"
                    onClick={() => handleAsk('Hi SEER AI')}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-primary-600 hover:bg-primary-700 text-white text-xs font-semibold shadow-xs transition"
                  >
                    <span>👋 Hi SEER AI</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => handleAsk('What are the biggest delivery risks and what should we do next?')}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-750 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700 text-xs font-medium transition"
                  >
                    <span>⚡ Check Delivery Risks</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => setActiveTab('graph')}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-emerald-200 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 text-xs font-medium hover:bg-emerald-100 dark:hover:bg-emerald-900/50 transition"
                  >
                    <GitFork className="w-3.5 h-3.5" />
                    <span>Open Dependency Graph</span>
                  </button>
                </div>
              </div>
            )}

            {messages.map((msg) => (
              <div
                key={msg.id}
                className={`flex gap-3 ${msg.sender === 'user' ? 'justify-end' : 'justify-start'}`}
              >
                {/* Assistant Avatar */}
                {msg.sender === 'assistant' && (
                  <div className="w-8 h-8 rounded-xl bg-primary-600 text-white flex items-center justify-center shrink-0 shadow-xs mt-1">
                    <Sparkles className="w-4 h-4" />
                  </div>
                )}

                {/* Message Body */}
                <div
                  className={`max-w-3xl rounded-2xl p-5 shadow-xs ${
                    msg.sender === 'user'
                      ? 'bg-primary-600 text-white rounded-tr-xs'
                      : 'bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-tl-xs space-y-4'
                  }`}
                >
                  {/* User Query */}
                  {msg.sender === 'user' && (
                    <div>
                      <p className="text-sm font-medium">{msg.question}</p>
                      <span className="text-[10px] opacity-70 block mt-1 text-right">
                        {msg.timestamp}
                      </span>
                    </div>
                  )}

                  {/* Assistant Response Card */}
                  {msg.sender === 'assistant' && msg.data && (
                    <>
                      {/* Header */}
                      <div className="flex items-center justify-between gap-2 pb-2 border-b border-slate-100 dark:border-slate-800">
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-bold text-slate-900 dark:text-white">
                            Copilot Analysis
                          </span>
                          <span
                            className={`text-[9px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full ${
                              msg.data.mode === 'gemini'
                                ? 'bg-purple-100 text-purple-700 dark:bg-purple-950/60 dark:text-purple-300'
                                : 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300'
                            }`}
                          >
                            {msg.data.mode === 'gemini' ? '● Gemini Engine' : '● Verified Telemetry Engine'}
                          </span>
                        </div>
                        <span className="text-[10px] text-slate-400">{msg.timestamp}</span>
                      </div>

                      {/* Main Narrative Answer */}
                      {renderFormattedAnswer(msg.data.answer)}

                      {/* Key Findings */}
                      {msg.data.findings && msg.data.findings.length > 0 && (
                        <div className="p-3.5 rounded-xl bg-slate-50 dark:bg-slate-800/40 border border-slate-200/70 dark:border-slate-800 space-y-2">
                          <span className="text-xs font-bold text-slate-800 dark:text-slate-200 flex items-center gap-1.5">
                            <ShieldAlert className="w-3.5 h-3.5 text-amber-500" />
                            <span>Verified Telemetry Findings</span>
                          </span>
                          <ul className="space-y-1.5 text-xs text-slate-600 dark:text-slate-400">
                            {msg.data.findings.map((finding, idx) => (
                              <li key={idx} className="flex items-start gap-1.5">
                                <span className="text-primary-500 font-bold select-none">•</span>
                                <span className="leading-snug">{formatInlineMarkdown(finding)}</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {/* Interactive Next Steps & Recommended Actions */}
                      {msg.data.actions && msg.data.actions.length > 0 && (
                        <div className="p-3.5 rounded-xl bg-gradient-to-br from-primary-50/70 to-blue-50/40 dark:from-primary-950/20 dark:to-slate-900 border border-primary-200/70 dark:border-primary-900/40 space-y-2.5">
                          <div className="flex items-center justify-between">
                            <span className="text-xs font-bold text-primary-900 dark:text-primary-200 flex items-center gap-1.5">
                              <Zap className="w-3.5 h-3.5 text-primary-500" />
                              <span>Interactive Next Steps & Actions</span>
                            </span>
                            <span className="text-[10px] text-slate-400 font-medium">Click any action to explore</span>
                          </div>
                          <div className="flex flex-col gap-1.5">
                            {msg.data.actions.map((act, idx) => {
                              const cleanAct = act.trim();
                              const askMatch = cleanAct.match(/^(?:Ask:?\s*|Prompt:?\s*)['"]?(.+?)['"]?$/i);
                              const isGraphAction =
                                cleanAct.toLowerCase().includes('dependency graph') ||
                                cleanAct.toLowerCase().includes('switch to the');

                              if (askMatch) {
                                const questionText = askMatch[1].trim();
                                return (
                                  <button
                                    key={idx}
                                    type="button"
                                    onClick={() => handleAsk(questionText)}
                                    disabled={loading}
                                    className="group flex items-center justify-between w-full text-left px-3 py-2 rounded-lg bg-white dark:bg-slate-900 border border-primary-200 dark:border-primary-900/60 hover:bg-primary-50 dark:hover:bg-primary-950/40 hover:border-primary-400 dark:hover:border-primary-600 transition shadow-2xs cursor-pointer disabled:opacity-50"
                                  >
                                    <span className="flex items-center gap-2 text-xs font-semibold text-primary-900 dark:text-primary-200">
                                      <MessageSquare className="w-3.5 h-3.5 text-primary-500 shrink-0 group-hover:scale-110 transition-transform" />
                                      <span className="line-clamp-1">{questionText}</span>
                                    </span>
                                    <span className="inline-flex items-center gap-1 text-[10px] uppercase font-bold text-primary-600 dark:text-primary-400 bg-primary-100/70 dark:bg-primary-900/50 px-2 py-0.5 rounded-full shrink-0 group-hover:translate-x-0.5 transition-transform">
                                      <span>Ask</span>
                                      <ArrowRight className="w-2.5 h-2.5" />
                                    </span>
                                  </button>
                                );
                              }

                              if (isGraphAction) {
                                return (
                                  <button
                                    key={idx}
                                    type="button"
                                    onClick={() => setActiveTab('graph')}
                                    className="group flex items-center justify-between w-full text-left px-3 py-2 rounded-lg bg-emerald-50/80 dark:bg-emerald-950/30 border border-emerald-200 dark:border-emerald-800 hover:bg-emerald-100/80 dark:hover:bg-emerald-900/50 hover:border-emerald-400 transition shadow-2xs cursor-pointer"
                                  >
                                    <span className="flex items-center gap-2 text-xs font-semibold text-emerald-900 dark:text-emerald-200">
                                      <GitFork className="w-3.5 h-3.5 text-emerald-600 dark:text-emerald-400 shrink-0 group-hover:rotate-45 transition-transform" />
                                      <span>View Interactive Jira Dependency Graph</span>
                                    </span>
                                    <span className="inline-flex items-center gap-1 text-[10px] uppercase font-bold text-emerald-700 dark:text-emerald-300 bg-emerald-100 dark:bg-emerald-900/60 px-2 py-0.5 rounded-full shrink-0 group-hover:translate-x-0.5 transition-transform">
                                      <span>Open Graph</span>
                                      <ArrowRight className="w-2.5 h-2.5" />
                                    </span>
                                  </button>
                                );
                              }

                              return (
                                <div
                                  key={idx}
                                  className="flex items-center justify-between gap-2 p-2.5 rounded-lg bg-white/90 dark:bg-slate-900/90 border border-slate-200 dark:border-slate-800 text-xs text-slate-800 dark:text-slate-200"
                                >
                                  <div className="flex items-start gap-2">
                                    <CheckCircle2 className="w-3.5 h-3.5 text-primary-500 shrink-0 mt-0.5" />
                                    <span className="leading-snug">{cleanAct}</span>
                                  </div>
                                  <button
                                    type="button"
                                    onClick={() => handleAsk(`How should we address: ${cleanAct}`)}
                                    disabled={loading}
                                    className="text-[10px] font-semibold text-primary-600 dark:text-primary-400 hover:underline shrink-0 px-2 py-1 rounded hover:bg-primary-50 dark:hover:bg-primary-950/40 border border-transparent hover:border-primary-200 dark:hover:border-primary-800 transition disabled:opacity-50"
                                  >
                                    Ask Copilot →
                                  </button>
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      )}

                      {/* Citations */}
                      {msg.data.citations && msg.data.citations.length > 0 && (
                        <div className="pt-2 border-t border-slate-100 dark:border-slate-800 space-y-1.5">
                          <span className="text-[11px] font-bold text-slate-500 uppercase tracking-wider block">
                            Evidence & Citations ({msg.data.citations.length})
                          </span>
                          <div className="flex flex-wrap gap-1.5">
                            {msg.data.citations.map((cite) => {
                              const isJira = cite.type === 'jira';
                              const isGithub = cite.type === 'github';
                              const isSrs = cite.type === 'srs';

                              const badgeColor = isJira
                                ? 'bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-950/40 dark:text-blue-300 dark:border-blue-800'
                                : isGithub
                                ? 'bg-slate-100 text-slate-800 border-slate-300 dark:bg-slate-800 dark:text-slate-200 dark:border-slate-700'
                                : isSrs
                                ? 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-300 dark:border-emerald-800'
                                : 'bg-purple-50 text-purple-700 border-purple-200 dark:bg-purple-950/40 dark:text-purple-300 dark:border-purple-800';

                              return cite.url ? (
                                <a
                                  key={cite.id}
                                  href={cite.url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] font-medium border transition-all hover:scale-[1.02] shadow-2xs ${badgeColor}`}
                                  title={`Open citation: ${cite.title}`}
                                >
                                  {isJira && <Trello className="w-3 h-3 text-blue-500" />}
                                  {isGithub && <Github className="w-3 h-3" />}
                                  {isSrs && <FileSearch className="w-3 h-3 text-emerald-500" />}
                                  <span className="truncate max-w-[220px]">{cite.title}</span>
                                  <ExternalLink className="w-2.5 h-2.5 shrink-0 opacity-60" />
                                </a>
                              ) : (
                                <span
                                  key={cite.id}
                                  className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] font-medium border ${badgeColor}`}
                                >
                                  {isSrs && <FileSearch className="w-3 h-3 text-emerald-500" />}
                                  <span className="truncate max-w-[220px]">{cite.title}</span>
                                </span>
                              );
                            })}
                          </div>
                        </div>
                      )}

                      {/* Follow-up Prompts */}
                      <div className="pt-2 flex items-center gap-2 flex-wrap">
                        <span className="text-[10px] font-semibold text-slate-400">
                          Follow-up:
                        </span>
                        {FOLLOW_UPS.map((follow) => (
                          <button
                            key={follow}
                            type="button"
                            onClick={() => handleAsk(follow)}
                            className="text-[11px] px-2 py-0.5 rounded border border-slate-200 dark:border-slate-800 text-primary-600 dark:text-primary-400 hover:bg-primary-50 dark:hover:bg-primary-950/30 transition"
                          >
                            {follow}
                          </button>
                        ))}
                      </div>
                    </>
                  )}

                  {/* Error Card */}
                  {msg.sender === 'assistant' && msg.error && (
                    <div className="text-xs text-red-600 dark:text-red-400 flex items-start gap-2">
                      <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                      <span>{msg.error}</span>
                    </div>
                  )}
                </div>

                {/* User Avatar */}
                {msg.sender === 'user' && (
                  <div className="w-8 h-8 rounded-xl bg-slate-200 dark:bg-slate-700 text-slate-700 dark:text-slate-200 flex items-center justify-center shrink-0 mt-1">
                    <User className="w-4 h-4" />
                  </div>
                )}
              </div>
            ))}

            {/* In-Flight Thinking */}
            {loading && (
              <div className="flex items-center gap-3 text-xs text-slate-500 p-3 rounded-xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 w-fit">
                <LoadingSpinner />
                <span>Grounding evidence across Jira, GitHub, and Risk Analysis...</span>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          {/* Sticky Query Input Bar */}
          <form
            onSubmit={(e) => {
              e.preventDefault();
              handleAsk();
            }}
            className="sticky bottom-4 flex items-center gap-2 p-2 rounded-2xl border border-slate-300 dark:border-slate-700 bg-white/95 dark:bg-slate-900/95 backdrop-blur-md shadow-lg"
          >
            <input
              type="text"
              value={inputQuestion}
              onChange={(e) => setInputQuestion(e.target.value)}
              placeholder="Ask Copilot about risks, architecture, sprint priorities, or SRS..."
              className="flex-1 px-4 py-2.5 text-sm bg-transparent text-slate-900 dark:text-white placeholder-slate-400 outline-none"
              disabled={loading}
            />
            <button
              type="submit"
              disabled={loading || inputQuestion.trim().length < 3}
              className="px-4 py-2.5 rounded-xl bg-primary-600 hover:bg-primary-700 text-white font-semibold text-xs inline-flex items-center gap-1.5 transition disabled:opacity-40 disabled:cursor-not-allowed shadow-xs"
              title="Submit question to Engineering Copilot"
            >
              <span>Ask</span>
              <Send className="w-3.5 h-3.5" />
            </button>
          </form>
        </div>
      )}

      {/* ========================================================================= */}
      {/* TAB 2: JIRA DEPENDENCY GRAPH (DARK & LIGHT MODE VISIBLE)                   */}
      {/* ========================================================================= */}
      {activeTab === 'graph' && (
        <div className="space-y-4">
          <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-xs flex flex-col md:flex-row md:items-center justify-between gap-3">
            <div>
              <h2 className="text-sm font-bold text-slate-900 dark:text-white flex items-center gap-2">
                <GitFork className="w-4 h-4 text-primary-500" />
                <span>Jira Issue Dependency & Delivery Hierarchy Graph</span>
              </h2>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                Displays real Jira links (blocks, blocked-by) and parent-child epic hierarchies. Strictly zero inferred edges.
              </p>
            </div>

            {/* Filter and Refresh Controls */}
            <div className="flex items-center gap-2 flex-wrap">
              <div className="inline-flex rounded-lg border border-slate-200 dark:border-slate-700 p-0.5 text-xs bg-slate-50 dark:bg-slate-800/60">
                <button
                  type="button"
                  onClick={() => setGraphFilter('all')}
                  className={`px-2.5 py-1 rounded font-semibold transition ${
                    graphFilter === 'all'
                      ? 'bg-slate-900 text-white dark:bg-white dark:text-slate-900 shadow-xs'
                      : 'text-slate-600 dark:text-slate-400'
                  }`}
                >
                  All Issues ({graph?.nodes?.length || 0})
                </button>
                <button
                  type="button"
                  onClick={() => setGraphFilter('blocked')}
                  className={`px-2.5 py-1 rounded font-semibold transition ${
                    graphFilter === 'blocked'
                      ? 'bg-red-600 text-white shadow-xs'
                      : 'text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/30'
                  }`}
                >
                  Blocked Work
                </button>
                <button
                  type="button"
                  onClick={() => setGraphFilter('risk')}
                  className={`px-2.5 py-1 rounded font-semibold transition ${
                    graphFilter === 'risk'
                      ? 'bg-amber-600 text-white shadow-xs'
                      : 'text-amber-600 dark:text-amber-400 hover:bg-amber-50 dark:hover:bg-amber-950/30'
                  }`}
                >
                  At Risk
                </button>
              </div>

              <button
                type="button"
                onClick={loadGraph}
                disabled={graphLoading}
                className="px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 text-xs font-semibold text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition inline-flex items-center gap-1.5"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${graphLoading ? 'animate-spin' : ''}`} />
                <span>Refresh</span>
              </button>
            </div>
          </div>

          {/* Graph Impact Summary */}
          {graph?.impact && (
            <div className="p-3 rounded-lg bg-primary-50 dark:bg-primary-950/30 border border-primary-200 dark:border-primary-900/40 text-xs text-primary-800 dark:text-primary-200 flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-primary-600 shrink-0" />
              <span>{graph.impact}</span>
            </div>
          )}

          {/* Canvas Container */}
          <div className="h-[640px] rounded-2xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950 overflow-hidden shadow-xs relative">
            {graphLoading && (
              <div className="absolute inset-0 bg-white/70 dark:bg-slate-950/70 z-10 flex items-center justify-center">
                <LoadingSpinner />
              </div>
            )}

            {graphError && (
              <div className="p-8 text-center text-sm text-red-600 dark:text-red-400">
                {graphError}
              </div>
            )}

            {!graphLoading && !graphError && graphNodes.length === 0 && (
              <div className="p-16 text-center text-sm text-slate-500">
                No Jira issues match the selected filter criteria.
              </div>
            )}

            {graphNodes.length > 0 && (
              <ReactFlow
                nodes={graphNodes}
                edges={graphEdges}
                fitView
                colorMode={isDark ? 'dark' : 'light'}
              >
                <Background color={isDark ? '#334155' : '#cbd5e1'} gap={24} size={1} />
                <Controls />
                <MiniMap
                  nodeColor={(n: any) =>
                    n.data?.isBlocked ? '#ef4444' : n.data?.isRisk ? '#f59e0b' : '#3b82f6'
                  }
                  maskColor={isDark ? 'rgba(15, 23, 42, 0.75)' : 'rgba(240, 240, 240, 0.75)'}
                  className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900"
                />
              </ReactFlow>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default AIInsights;
