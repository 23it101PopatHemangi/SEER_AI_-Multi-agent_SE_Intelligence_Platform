import React, { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useOktaAuth } from '@okta/okta-react';
import { 
  Plus, 
  Github, 
  GitBranch, 
  Star, 
  GitFork, 
  AlertCircle, 
  Calendar, 
  Search, 
  Grid, 
  List as ListIcon, 
  ChevronLeft, 
  ChevronRight,
  SlidersHorizontal,
  Clock
} from 'lucide-react';
import { repositoryService, Repository } from '../services/repositoryService';
import { githubService, GitHubStatusResponse } from '../services/githubService';
import { ConnectRepoModal } from './ConnectRepoModal';
import { SelectJiraProjectModal } from './SelectJiraProjectModal';
import { LoadingSpinner } from './LoadingSpinner';

export const Repositories: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>();
  const { authState, oktaAuth } = useOktaAuth();

  const [repositories, setRepositories] = useState<Repository[]>([]);
  const [loading, setLoading] = useState(true);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [jiraMappingRepo, setJiraMappingRepo] = useState<Repository | null>(null);
  const [error, setError] = useState<string | null>(null);

  // GitHub Account Integration states
  const [userEmail, setUserEmail] = useState<string>('');
  const [githubStatus, setGithubStatus] = useState<GitHubStatusResponse | null>(null);
  const [selectedRepoUrl, setSelectedRepoUrl] = useState<string>('');
  const [importing, setImporting] = useState<boolean>(false);

  const handleRepositoryConnected = async (repository: Repository) => {
    await loadRepositories();
    setJiraMappingRepo(repository);
  };

  // Search, Filter, Sort, View, Pagination states
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'analyzed' | 'analyzing' | 'not-analyzed'>('all');
  const [sortBy, setSortBy] = useState<'updated' | 'name' | 'stars' | 'added'>('updated');
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid');
  const [currentPage, setCurrentPage] = useState<number>(1);
  const itemsPerPage = 8;

  // 1. Fetch project repositories from database
  const loadRepositories = async () => {
    if (!projectId) return;
    try {
      const data = await repositoryService.getRepositories(projectId);
      setRepositories(data);
    } catch (err: any) {
      console.error('Failed to load project repositories', err);
      setError('Failed to load connected repositories.');
    }
  };

  // 2. Fetch GitHub OAuth connection status
  const loadGithubStatus = async (email: string) => {
    if (!email) return;
    try {
      const status = await githubService.getConnectionStatus(email);
      setGithubStatus(status);
    } catch (err) {
      console.error('Failed to check GitHub integration status', err);
    }
  };

  // Resolve user session email
  useEffect(() => {
    let active = true;
    if (authState?.isAuthenticated) {
      oktaAuth.getUser().then((user) => {
        if (active && user.email) {
          setUserEmail(user.email);
        }
      }).catch(err => console.error('Error fetching user info', err));
    }
    return () => {
      active = false;
    };
  }, [authState, oktaAuth]);

  // Load both states
  useEffect(() => {
    const init = async () => {
      setLoading(true);
      setError(null);
      await loadRepositories();
      if (userEmail) {
        await loadGithubStatus(userEmail);
      }
      setLoading(false);
    };
    if (projectId) {
      init();
    }
  }, [projectId, userEmail]);

  // Reset pagination when filter or search changes
  useEffect(() => {
    setCurrentPage(1);
  }, [searchQuery, statusFilter]);

  // Handle OAuth Redirect initiation
  const handleConnectGithub = async () => {
    if (!userEmail || !projectId) return;
    setError(null);
    try {
      const authUrl = await githubService.getAuthUrl(userEmail, projectId);
      window.location.href = authUrl; // Redirect browser to GitHub
    } catch (err: any) {
      setError(err.message || 'Failed to connect to GitHub. Verify Client configurations on the server.');
    }
  };

  // Handle Disconnect Account request — fully clears all GitHub state
  const handleDisconnectGithub = async () => {
    if (!userEmail) return;
    setError(null);
    try {
      await githubService.disconnectAccount(userEmail);
      // Clear ALL GitHub-related state completely
      setGithubStatus(null);
      setSelectedRepoUrl('');
      // Force the status check to treat this as truly disconnected
      // by setting connected: false explicitly
      setGithubStatus({ connected: false });
    } catch (err: any) {
      setError('Failed to revoke GitHub integration.');
    }
  };

  // Handle Importing selected repository from Account List
  const handleImportRepository = async () => {
    if (!selectedRepoUrl || !projectId) return;
    setImporting(true);
    setError(null);
    try {
      const repository = await repositoryService.connectRepository(projectId, selectedRepoUrl, userEmail);
      setSelectedRepoUrl('');
      // Reload listing
      await loadRepositories();
      setJiraMappingRepo(repository);
    } catch (err: any) {
      setError(err.message || 'Failed to import repository.');
    } finally {
      setImporting(false);
    }
  };

  const formatDate = (isoString: string) => {
    try {
      const date = new Date(isoString);
      return date.toLocaleDateString(undefined, {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
      });
    } catch (e) {
      return 'N/A';
    }
  };

  // 1. Filter logic
  const filteredRepos = repositories.filter((repo) => {
    const matchesSearch = 
      repo.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      repo.owner.toLowerCase().includes(searchQuery.toLowerCase());

    let matchesStatus = true;
    if (statusFilter === 'analyzed') {
      matchesStatus = repo.analysis_status === 'Analyzed';
    } else if (statusFilter === 'analyzing') {
      matchesStatus = false; // Analytics are computed on-demand, no background workers are running
    } else if (statusFilter === 'not-analyzed') {
      matchesStatus = repo.analysis_status === 'Not Analyzed';
    }

    return matchesSearch && matchesStatus;
  });

  // 2. Sorting logic
  const sortedRepos = [...filteredRepos].sort((a, b) => {
    if (sortBy === 'name') {
      return a.name.localeCompare(b.name);
    }
    if (sortBy === 'stars') {
      return b.stars - a.stars;
    }
    if (sortBy === 'added') {
      return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
    }
    // Default: 'updated'
    return new Date(b.last_pushed_at).getTime() - new Date(a.last_pushed_at).getTime();
  });

  // 3. Pagination slicing
  const totalPages = Math.ceil(sortedRepos.length / itemsPerPage);
  const paginatedRepos = sortedRepos.slice(
    (currentPage - 1) * itemsPerPage,
    currentPage * itemsPerPage
  );

  if (loading) {
    return <LoadingSpinner />;
  }

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8 relative">
      
      {/* Sticky top headers section */}
      <div className="sticky top-0 bg-slate-50 dark:bg-slate-950 z-20 py-4 space-y-4 border-b border-slate-200 dark:border-slate-900/60 shadow-sm transition-colors">
        
        {/* Title and connect button */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Repositories</h1>
            <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
              Connect and analyze the GitHub repositories associated with this project.
            </p>
          </div>

          <button
            onClick={() => setIsModalOpen(true)}
            className="flex items-center space-x-2 bg-primary-600 hover:bg-primary-500 text-white text-sm font-semibold px-4 py-2.5 rounded-lg shadow-sm transition"
          >
            <Plus className="w-4 h-4" />
            <span>Connect Repository Link</span>
          </button>
        </div>

        {/* GitHub Account Connection Panel */}
        {githubStatus?.connected ? (
          <div className="bg-emerald-50 dark:bg-emerald-950/10 border border-emerald-250 dark:border-emerald-900/40 rounded-xl p-5 flex flex-col md:flex-row md:items-center justify-between gap-5 transition duration-150">
            <div className="flex items-center space-x-3.5">
              <div className="p-2.5 bg-emerald-500/10 rounded-lg text-emerald-600 dark:text-emerald-400 shrink-0">
                <Github className="w-6 h-6" />
              </div>
              <div>
                <h3 className="font-bold text-sm text-slate-900 dark:text-white">GitHub Connected</h3>
                <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                  Authorized as <strong className="font-bold text-slate-700 dark:text-slate-200">@{githubStatus.github_username}</strong>
                </p>
              </div>
            </div>
            
            <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-4">
              <div className="flex items-center gap-2">
                <select
                  value={selectedRepoUrl}
                  onChange={(e) => setSelectedRepoUrl(e.target.value)}
                  disabled={importing}
                  className="text-xs px-3 py-2.5 border border-slate-300 dark:border-slate-800 bg-white dark:bg-slate-950 rounded-lg text-slate-700 dark:text-slate-300 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent w-full sm:w-64"
                >
                  <option value="">-- Select GitHub Repository --</option>
                  {githubStatus.repositories?.map((r) => (
                    <option key={r.html_url} value={r.html_url}>
                      {r.full_name}
                    </option>
                  ))}
                </select>
                <button
                  onClick={handleImportRepository}
                  disabled={!selectedRepoUrl || importing}
                  className="bg-primary-600 hover:bg-primary-500 text-white font-bold text-xs px-4 py-2.5 rounded-lg transition disabled:opacity-50 whitespace-nowrap"
                >
                  {importing ? 'Importing...' : 'Import'}
                </button>
              </div>
              
              <button
                onClick={handleDisconnectGithub}
                className="text-xs font-bold text-red-600 hover:text-red-500 px-2 transition text-left"
              >
                Disconnect
              </button>
            </div>
          </div>
        ) : (
          <div className="bg-slate-150/50 dark:bg-slate-900/30 border border-slate-200 dark:border-slate-850 rounded-xl p-5 flex flex-col md:flex-row md:items-center justify-between gap-4 transition duration-150">
            <div className="flex items-center space-x-3.5">
              <div className="p-2.5 bg-slate-200 dark:bg-slate-850 text-slate-500 rounded-lg shrink-0">
                <Github className="w-6 h-6" />
              </div>
              <div>
                <h3 className="font-bold text-sm text-slate-900 dark:text-white">GitHub Integration</h3>
                <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                  Link your GitHub account to import repositories directly without copying URLs.
                </p>
              </div>
            </div>
            
            <button
              onClick={handleConnectGithub}
              className="flex items-center justify-center space-x-2 bg-slate-900 hover:bg-slate-800 text-white dark:bg-slate-800 dark:hover:bg-slate-700 font-bold text-xs px-4.5 py-2.5 rounded-lg shadow-sm transition whitespace-nowrap"
            >
              <Github className="w-4 h-4" />
              <span>Connect GitHub Account</span>
            </button>
          </div>
        )}
      </div>

      {error && (
        <div className="flex items-center space-x-2 p-3 text-sm text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/20 border border-red-200 dark:border-red-800/50 rounded-lg">
          <AlertCircle className="w-4 h-4 text-red-500 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Advanced search, filters, sorts panel */}
      {repositories.length > 0 && (
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800/80 rounded-xl p-4 flex flex-col lg:flex-row lg:items-center justify-between gap-4 shadow-sm transition">
          
          {/* Left: Search input */}
          <div className="relative flex-1 max-w-md">
            <Search className="absolute left-3.5 top-2.5 w-4.5 h-4.5 text-slate-400" />
            <input
              type="text"
              placeholder="Search repositories by name or owner..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-10 pr-4 py-2 text-sm bg-slate-50 dark:bg-slate-950 border border-slate-205 dark:border-slate-800 text-slate-900 dark:text-slate-100 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent transition"
            />
          </div>

          {/* Right: Filters & sorts */}
          <div className="flex flex-wrap items-center gap-4 text-xs font-semibold">
            {/* Status tabs */}
            <div className="flex items-center space-x-1 bg-slate-100 dark:bg-slate-800/50 p-0.5 rounded-lg border border-slate-200 dark:border-slate-800/80">
              {(['all', 'analyzed', 'analyzing', 'not-analyzed'] as const).map((filter) => (
                <button
                  key={filter}
                  onClick={() => setStatusFilter(filter)}
                  className={`px-3 py-1.5 rounded-md capitalize transition whitespace-nowrap ${
                    statusFilter === filter
                      ? 'bg-white dark:bg-slate-900 text-primary-650 dark:text-primary-400 shadow-sm border border-slate-200/50 dark:border-slate-800/60'
                      : 'text-slate-500 hover:text-slate-850 dark:hover:text-slate-200'
                  }`}
                >
                  {filter.replace('-', ' ')}
                </button>
              ))}
            </div>

            {/* Sort selectors */}
            <div className="flex items-center space-x-2 bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-lg p-1.5">
              <SlidersHorizontal className="w-3.5 h-3.5 text-slate-450" />
              <select
                value={sortBy}
                onChange={(e: any) => setSortBy(e.target.value)}
                className="bg-transparent text-slate-700 dark:text-slate-350 focus:outline-none cursor-pointer pr-1"
              >
                <option value="updated">Recently Updated</option>
                <option value="name">Name A–Z</option>
                <option value="stars">Stars</option>
                <option value="added">Recently Added</option>
              </select>
            </div>

            {/* Grid / List Toggles */}
            <div className="flex items-center space-x-1 bg-slate-100 dark:bg-slate-800/50 p-0.5 rounded-lg border border-slate-200 dark:border-slate-800/80 shrink-0">
              <button
                onClick={() => setViewMode('grid')}
                className={`p-1.5 rounded-md transition ${
                  viewMode === 'grid'
                    ? 'bg-white dark:bg-slate-900 text-primary-600 dark:text-primary-400 shadow-sm'
                    : 'text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'
                }`}
                title="Grid view"
              >
                <Grid className="w-4 h-4" />
              </button>
              <button
                onClick={() => setViewMode('list')}
                className={`p-1.5 rounded-md transition ${
                  viewMode === 'list'
                    ? 'bg-white dark:bg-slate-900 text-primary-600 dark:text-primary-400 shadow-sm'
                    : 'text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'
                }`}
                title="List view"
              >
                <ListIcon className="w-4 h-4" />
              </button>
            </div>

          </div>
        </div>
      )}

      {/* Catalog listing section */}
      {repositories.length > 0 ? (
        <div className="space-y-6">
          
          {/* Metadata counts */}
          <div className="flex items-center justify-between text-xs text-slate-500 dark:text-slate-450 px-1">
            <span>
              Showing <strong className="font-bold text-slate-700 dark:text-slate-200">{filteredRepos.length}</strong> of {repositories.length} connected repositories
            </span>
          </div>

          {paginatedRepos.length > 0 ? (
            
            viewMode === 'grid' ? (
              /* A. Grid Card Layout */
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-2 gap-6">
                {paginatedRepos.map((repo) => (
                  <Link
                    key={repo.id}
                    to={`/projects/${projectId}/repositories/${repo.id}`}
                    className="bg-white dark:bg-slate-900 border border-slate-205 dark:border-slate-850 rounded-xl p-6 shadow-sm flex flex-col justify-between hover:shadow-md hover:border-slate-300 dark:hover:border-slate-700 transition duration-150 group"
                  >
                    <div className="space-y-4">
                      <div className="flex items-start justify-between gap-4">
                        <div className="flex items-center space-x-3 min-w-0">
                          <div className="p-2 bg-slate-100 dark:bg-slate-800 text-slate-650 dark:text-slate-400 rounded-lg shrink-0 font-bold">
                            <Github className="w-5 h-5" />
                          </div>
                          <div className="min-w-0">
                            <h3 className="font-bold text-base text-slate-900 dark:text-white truncate group-hover:text-primary-600 dark:group-hover:text-primary-400 transition">
                              {repo.name}
                            </h3>
                            <p className="text-xs text-slate-400 dark:text-slate-500 truncate">
                              Owner: {repo.owner}
                            </p>
                          </div>
                        </div>
                        
                        <span className={`text-[9px] font-bold uppercase tracking-wider px-2 py-0.5 rounded border ${
                          repo.analysis_status === 'Analyzed'
                            ? 'bg-emerald-50 dark:bg-emerald-950/20 text-emerald-600 dark:text-emerald-450 border-emerald-200 dark:border-emerald-800/40'
                            : 'bg-slate-50 dark:bg-slate-900 text-slate-500 dark:text-slate-400 border-slate-200 dark:border-slate-800'
                        }`}>
                          {repo.analysis_status === 'Analyzed' ? 'Analyzed' : 'Not Analyzed'}
                        </span>
                      </div>

                      <p className="text-sm text-slate-500 dark:text-slate-400 line-clamp-2 min-h-[40px]">
                        {repo.description || 'No description provided.'}
                      </p>

                      <div className="flex items-center space-x-4 text-xs text-slate-500 dark:text-slate-400 font-medium">
                        {repo.primary_language && (
                          <div className="flex items-center space-x-1.5">
                            <span className="w-2.5 h-2.5 rounded-full bg-primary-500" />
                            <span>{repo.primary_language}</span>
                          </div>
                        )}
                        <div className="flex items-center space-x-1" title="Stars">
                          <Star className="w-3.5 h-3.5 text-amber-500" />
                          <span>{repo.stars}</span>
                        </div>
                        <div className="flex items-center space-x-1" title="Forks">
                          <GitFork className="w-3.5 h-3.5" />
                          <span>{repo.forks}</span>
                        </div>
                        <div className="flex items-center space-x-1" title="Default branch">
                          <GitBranch className="w-3.5 h-3.5" />
                          <span>{repo.default_branch}</span>
                        </div>
                      </div>
                    </div>

                    <div className="pt-4 mt-4 border-t border-slate-100 dark:border-slate-800/60 flex items-center justify-between text-[10px] text-slate-400 dark:text-slate-500 font-bold uppercase tracking-wider">
                      <span className="flex items-center space-x-1">
                        <Calendar className="w-3.5 h-3.5" />
                        <span>Pushed {formatDate(repo.last_pushed_at)}</span>
                      </span>
                      <span className="text-primary-650 dark:text-primary-400 group-hover:underline transition">
                        Manage Workspace &rarr;
                      </span>
                    </div>
                  </Link>
                ))}
              </div>
            ) : (
              /* B. Compact List Table Layout */
              <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-805 rounded-xl overflow-hidden shadow-sm transition">
                <div className="overflow-x-auto">
                  <table className="w-full text-left border-collapse">
                    <thead>
                      <tr className="border-b border-slate-150 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-900/60 text-slate-450 dark:text-slate-500 text-[10px] font-bold uppercase tracking-wider">
                        <th className="px-6 py-4">Repository</th>
                        <th className="px-6 py-4">Language</th>
                        <th className="px-6 py-4">Stats</th>
                        <th className="px-6 py-4">Status</th>
                        <th className="px-6 py-4">Last Pushed</th>
                        <th className="px-6 py-4 text-right">Action</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100 dark:divide-slate-800/50 text-sm">
                      {paginatedRepos.map((repo) => (
                        <tr
                          key={repo.id}
                          className="hover:bg-slate-50/40 dark:hover:bg-slate-900/20 transition group"
                        >
                          <td className="px-6 py-4 max-w-xs">
                            <div className="flex items-center space-x-3">
                              <Github className="w-4 h-4 text-slate-400 shrink-0" />
                              <div className="min-w-0">
                                <Link
                                  to={`/projects/${projectId}/repositories/${repo.id}`}
                                  className="font-bold text-slate-800 dark:text-slate-100 group-hover:text-primary-600 dark:group-hover:text-primary-400 transition block truncate"
                                >
                                  {repo.name}
                                </Link>
                                <span className="text-xs text-slate-400 dark:text-slate-500 block truncate">
                                  by {repo.owner}
                                </span>
                              </div>
                            </div>
                          </td>
                          <td className="px-6 py-4 text-xs font-semibold text-slate-650 dark:text-slate-350">
                            {repo.primary_language ? (
                              <div className="flex items-center space-x-1.5">
                                <span className="w-2 h-2 rounded-full bg-primary-500" />
                                <span>{repo.primary_language}</span>
                              </div>
                            ) : (
                              <span className="text-slate-400 dark:text-slate-500 font-normal italic">None</span>
                            )}
                          </td>
                          <td className="px-6 py-4 text-xs text-slate-550 dark:text-slate-400">
                            <div className="flex items-center space-x-3.5">
                              <span className="flex items-center space-x-1" title={`${repo.stars} stars`}>
                                <Star className="w-3.5 h-3.5 text-amber-500" />
                                <span className="font-semibold">{repo.stars}</span>
                              </span>
                              <span className="flex items-center space-x-1" title={`${repo.forks} forks`}>
                                <GitFork className="w-3.5 h-3.5" />
                                <span className="font-semibold">{repo.forks}</span>
                              </span>
                            </div>
                          </td>
                          <td className="px-6 py-4">
                            <span className={`text-[9px] font-bold uppercase tracking-wider px-2 py-0.5 rounded border ${
                              repo.analysis_status === 'Analyzed'
                                ? 'bg-emerald-50 dark:bg-emerald-950/20 text-emerald-600 dark:text-emerald-450 border-emerald-250 dark:border-emerald-900/35'
                                : 'bg-slate-50 dark:bg-slate-900 text-slate-500 dark:text-slate-400 border-slate-205 dark:border-slate-805'
                            }`}>
                              {repo.analysis_status === 'Analyzed' ? 'Analyzed' : 'Not Analyzed'}
                            </span>
                          </td>
                          <td className="px-6 py-4 text-xs font-semibold text-slate-500 dark:text-slate-400">
                            <div className="flex items-center space-x-1.5">
                              <Clock className="w-3.5 h-3.5 text-slate-400" />
                              <span>{formatDate(repo.last_pushed_at)}</span>
                            </div>
                          </td>
                          <td className="px-6 py-4 text-right">
                            <Link
                              to={`/projects/${projectId}/repositories/${repo.id}`}
                              className="text-xs font-bold text-primary-650 dark:text-primary-400 hover:underline"
                            >
                              Manage Workspace &rarr;
                            </Link>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )

          ) : (
            /* Search / Filter empty state */
            <div className="flex flex-col items-center justify-center p-12 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl text-center shadow-sm">
              <Search className="w-8 h-8 text-slate-400 mb-3" />
              <h3 className="text-base font-bold text-slate-900 dark:text-white">No repositories found</h3>
              <p className="text-xs text-slate-500 dark:text-slate-450 max-w-sm mt-1">
                We couldn't find any repositories matching your search query or filters.
              </p>
              <button
                onClick={() => {
                  setSearchQuery('');
                  setStatusFilter('all');
                }}
                className="mt-4 text-xs font-bold text-primary-650 dark:text-primary-400 hover:underline"
              >
                Clear all filters
              </button>
            </div>
          )}

          {/* D. Pagination Controls */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between border-t border-slate-200 dark:border-slate-805 pt-4">
              <span className="text-xs text-slate-400 dark:text-slate-500">
                Page <strong className="font-bold text-slate-700 dark:text-slate-200">{currentPage}</strong> of {totalPages}
              </span>
              
              <div className="flex items-center space-x-2">
                <button
                  onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                  disabled={currentPage === 1}
                  className="p-1.5 rounded-lg border border-slate-200 dark:border-slate-800 text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 hover:text-slate-700 dark:hover:text-slate-200 disabled:opacity-50 transition"
                >
                  <ChevronLeft className="w-4.5 h-4.5" />
                </button>
                <button
                  onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                  disabled={currentPage === totalPages}
                  className="p-1.5 rounded-lg border border-slate-200 dark:border-slate-800 text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 hover:text-slate-700 dark:hover:text-slate-200 disabled:opacity-50 transition"
                >
                  <ChevronRight className="w-4.5 h-4.5" />
                </button>
              </div>
            </div>
          )}

        </div>
      ) : (
        /* Empty State */
        <div className="flex flex-col items-center justify-center border border-dashed border-slate-300 dark:border-slate-800 rounded-2xl p-16 text-center bg-white/40 dark:bg-slate-900/20 shadow-sm">
          <div className="p-4 bg-slate-100 dark:bg-slate-800/80 text-slate-400 rounded-2xl mb-6">
            <Github className="w-10 h-10" />
          </div>
          <h2 className="text-xl font-bold text-slate-900 dark:text-white mb-2">Connect your first GitHub repository</h2>
          <p className="text-sm text-slate-500 dark:text-slate-400 max-w-sm mb-8 leading-relaxed">
            Link and import repository codebases directly to build and analyze project workspaces.
          </p>
          <button
            onClick={() => setIsModalOpen(true)}
            className="flex items-center space-x-2 bg-primary-600 hover:bg-primary-500 text-white text-sm font-semibold px-5 py-3 rounded-lg shadow-sm transition"
          >
            <Plus className="w-4.5 h-4.5" />
            <span>Connect Your First Repository</span>
          </button>
        </div>
      )}

      {/* Connect Modal */}
      {projectId && (
        <ConnectRepoModal
          isOpen={isModalOpen}
          projectId={projectId}
          onClose={() => setIsModalOpen(false)}
          onRepoConnected={loadRepositories}
        />
      )}
      {projectId && jiraMappingRepo && (
        <SelectJiraProjectModal
          isOpen={Boolean(jiraMappingRepo)}
          projectId={projectId}
          repositoryId={jiraMappingRepo.id}
          userEmail={userEmail}
          onClose={() => setJiraMappingRepo(null)}
          onConnected={async () => {
            setJiraMappingRepo(null);
            await loadRepositories();
          }}
        />
      )}
    </div>
  );
};
export default Repositories;
