import React, { useEffect, useState } from 'react';
import { Link, Outlet, useLocation, useParams, useNavigate } from 'react-router-dom';
import { useOktaAuth } from '@okta/okta-react';
import { UserClaims } from '@okta/okta-auth-js';
import { useTheme } from '../context/ThemeContext';
import { projectService, Project } from '../services/projectService';
import {
  FolderKanban,
  Cpu,
  BarChart3,
  Calendar,
  GitBranch,
  Github,
  Trello,
  ShieldAlert,
  Brain,
  Settings,
  LogOut,
  Sun,
  Moon,
  User,
  ChevronRight,
} from 'lucide-react';
import { LoadingSpinner } from './LoadingSpinner';

export const AppLayout: React.FC = () => {
  const { authState, oktaAuth } = useOktaAuth();
  const { theme, toggleTheme } = useTheme();
  const { projectId } = useParams<{ projectId?: string }>();
  const location = useLocation();
  const navigate = useNavigate();

  const [userInfo, setUserInfo] = useState<UserClaims | null>(null);
  const [activeProject, setActiveProject] = useState<Project | null>(null);

  // Fetch Okta user details
  useEffect(() => {
    let active = true;
    if (authState?.isAuthenticated) {
      oktaAuth.getUser()
        .then((info) => {
          if (active) setUserInfo(info);
        })
        .catch((err) => console.error('Failed to get user claims', err));
    }
    return () => {
      active = false;
    };
  }, [authState, oktaAuth]);

  // Load project details if projectId is present in the route
  useEffect(() => {
    let active = true;
    if (projectId) {
      projectService.getProjectById(projectId)
        .then((proj) => {
          if (active) {
            setActiveProject(proj || null);
          }
        })
        .catch((err) => {
          console.error('Failed to fetch active project details', err);
          if (active) {
            setActiveProject(null);
          }
        });
    } else {
      setActiveProject(null);
    }
    return () => {
      active = false;
    };
  }, [projectId, location.pathname]);

  const handleLogout = async () => {
    try {
      await oktaAuth.signOut();
    } catch (err) {
      console.error('Logout error', err);
    }
  };

  const navItems = [
    { name: 'Overview', path: 'overview', icon: Cpu },
    { name: 'Architecture', path: 'architecture', icon: GitBranch },
    { name: 'Repositories', path: 'repositories', icon: Github },
    { name: 'Backlog', path: 'backlog', icon: Trello },
    { name: 'Jira Timeline', path: 'analytics', icon: Calendar },
    { name: 'Risk Analysis', path: 'risk', icon: ShieldAlert },
    { name: 'AI Insights', path: 'ai-insights', icon: Brain },
  ];

  if (!authState) {
    return <LoadingSpinner />;
  }

  return (
    <div className="flex h-screen bg-slate-50 dark:bg-[#0B0F19] text-slate-900 dark:text-slate-100 transition-colors duration-150">
      
      {/* 1. Left Sidebar */}
      <aside className="w-64 border-r border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900/60 flex flex-col justify-between shrink-0 z-20">
        
        {/* Top Branding Section */}
        <div className="p-6 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between">
          <Link to="/projects" className="flex items-center space-x-2.5">
            <div className="p-1.5 bg-primary-600 rounded-lg text-white">
              <Cpu className="w-5 h-5" />
            </div>
            <span className="font-bold text-lg tracking-tight bg-gradient-to-r from-primary-600 to-indigo-500 dark:from-primary-400 dark:to-indigo-300 bg-clip-text text-transparent">
              SEER AI
            </span>
          </Link>
        </div>

        {/* Navigation Middle Area */}
        <div className="flex-1 py-4 overflow-y-auto px-4 space-y-6">
          {/* Main platform routes */}
          <div className="space-y-1">
            <Link
              to="/projects"
              className={`flex items-center space-x-3 px-3.5 py-2.5 rounded-lg text-sm font-semibold transition ${
                location.pathname === '/projects'
                  ? 'bg-primary-50 dark:bg-primary-950/30 text-primary-600 dark:text-primary-400'
                  : 'text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800/50 hover:text-slate-900 dark:hover:text-slate-200'
              }`}
            >
              <FolderKanban className="w-4 h-4" />
              <span>Projects</span>
            </Link>
          </div>

          {/* Active project context options */}
          {activeProject && (
            <div className="space-y-2 pt-2 border-t border-slate-200 dark:border-slate-800/80">
              <div className="px-3 text-[10px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-widest truncate">
                Current Project: {activeProject.name}
              </div>
              <div className="space-y-0.5">
                {navItems.map((item) => {
                  const itemPath = `/projects/${projectId}/${item.path}`;
                  const isActive = location.pathname === itemPath;
                  const Icon = item.icon;

                  return (
                    <Link
                      key={item.name}
                      to={itemPath}
                      className={`flex items-center space-x-3 px-3.5 py-2.5 rounded-lg text-sm font-semibold transition ${
                        isActive
                          ? 'bg-primary-50 dark:bg-primary-950/30 text-primary-600 dark:text-primary-400'
                          : 'text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800/50 hover:text-slate-900 dark:hover:text-slate-200'
                      }`}
                    >
                      <Icon className="w-4 h-4" />
                      <span>{item.name}</span>
                    </Link>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        {/* Sidebar Footer (Settings, User, Logout) */}
        <div className="p-4 border-t border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-900/20">
          <div className="space-y-1 mb-4">
            <Link
              to={activeProject ? `/projects/${activeProject.id}/settings` : '/projects'}
              className={`flex items-center space-x-3 px-3 py-2 rounded-lg text-xs font-semibold transition ${
                location.pathname.endsWith('/settings')
                  ? 'text-primary-600 dark:text-primary-400'
                  : 'text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200'
              }`}
            >
              <Settings className="w-4 h-4" />
              <span>Settings</span>
            </Link>
          </div>

          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-2.5 min-w-0 flex-1 mr-2">
              <div className="w-8 h-8 rounded-full bg-slate-200 dark:bg-slate-800 text-slate-700 dark:text-slate-300 flex items-center justify-center font-bold text-xs shrink-0 border border-slate-300 dark:border-slate-700">
                {userInfo?.name ? userInfo.name.substring(0, 2).toUpperCase() : <User className="w-4 h-4" />}
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-xs font-bold text-slate-800 dark:text-slate-200 truncate">
                  {userInfo?.name || 'Developer'}
                </p>
                <p className="text-[10px] text-slate-400 dark:text-slate-500 truncate">
                  {userInfo?.email || 'authenticated'}
                </p>
              </div>
            </div>

            <button
              onClick={handleLogout}
              title="Logout"
              className="p-1.5 text-slate-400 hover:text-red-500 dark:hover:text-red-400 rounded-lg hover:bg-slate-200 dark:hover:bg-slate-800 transition"
            >
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        </div>

      </aside>

      {/* 2. Main content container */}
      <div className="flex-1 flex flex-col min-w-0">
        
        {/* Top Header */}
        <header className="h-16 border-b border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900/60 backdrop-blur-md flex items-center justify-between px-8 z-10">
          
          {/* Breadcrumbs / Page Context */}
          <div className="flex items-center space-x-2 text-sm font-medium text-slate-500 dark:text-slate-400">
            <Link to="/projects" className="hover:text-slate-900 dark:hover:text-white transition">
              Projects
            </Link>
            {activeProject && (
              <>
                <ChevronRight className="w-3.5 h-3.5 text-slate-300 dark:text-slate-700" />
                <span className="text-slate-800 dark:text-white font-bold">{activeProject.name}</span>
              </>
            )}
            {activeProject && location.pathname.split('/').length > 3 && (
              <>
                <ChevronRight className="w-3.5 h-3.5 text-slate-300 dark:text-slate-700" />
                <span className="capitalize text-slate-800 dark:text-slate-300">
                  {location.pathname.split('/').pop()?.replace('-', ' ')}
                </span>
              </>
            )}
          </div>

          {/* Theme Toggler */}
          <div className="flex items-center space-x-4">
            <button
              onClick={toggleTheme}
              className="p-2 text-slate-500 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800/80 border border-slate-200 dark:border-slate-800 transition duration-150"
              title={theme === 'light' ? 'Switch to Dark Mode' : 'Switch to Light Mode'}
            >
              {theme === 'light' ? <Moon className="w-4 h-4" /> : <Sun className="w-4 h-4" />}
            </button>
          </div>

        </header>

        {/* Content Outlet View */}
        <main className="flex-1 overflow-y-auto bg-slate-50 dark:bg-[#0B0F19] transition-colors duration-150">
          <Outlet />
        </main>

      </div>
    </div>
  );
};
