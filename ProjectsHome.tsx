import React, { useEffect, useState } from 'react';
import { Plus, FolderKanban, Calendar, ArrowRight } from 'lucide-react';
import { Link } from 'react-router-dom';
import { projectService, Project } from '../services/projectService';
import { CreateProjectModal } from './CreateProjectModal';

export const ProjectsHome: React.FC = () => {
  const [projects, setProjects] = useState<Project[]>([]);
  const [isModalOpen, setIsModalOpen] = useState(false);

  const loadProjects = async () => {
    try {
      const data = await projectService.getProjects();
      setProjects(data);
    } catch (err) {
      console.error('Failed to load projects', err);
    }
  };

  useEffect(() => {
    loadProjects();
  }, []);

  const formatDate = (isoString: string) => {
    try {
      const cleanIsoString = isoString.endsWith('Z') || isoString.includes('+')
        ? isoString 
        : `${isoString}Z`;
      const date = new Date(cleanIsoString);
      return date.toLocaleDateString(undefined, {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
      });
    } catch (e) {
      return 'N/A';
    }
  };

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      {/* Header section */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Your Projects</h1>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
            Manage and view your software engineering workspaces.
          </p>
        </div>
        
        {projects.length > 0 && (
          <button
            onClick={() => setIsModalOpen(true)}
            className="flex items-center space-x-2 bg-primary-600 hover:bg-primary-500 text-white text-sm font-semibold px-4 py-2.5 rounded-lg shadow-sm transition"
          >
            <Plus className="w-4 h-4" />
            <span>Create New Project</span>
          </button>
        )}
      </div>

      {/* Projects list / Cards */}
      {projects.length > 0 ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {projects.map((project) => (
            <div
              key={project.id}
              className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800/80 rounded-xl p-6 shadow-sm flex flex-col justify-between hover:shadow-md transition duration-150 group"
            >
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <div className="p-2 bg-primary-50 dark:bg-primary-950/20 text-primary-600 dark:text-primary-400 rounded-lg">
                    <FolderKanban className="w-5 h-5" />
                  </div>
                  <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded ${
                    project.status === 'Active'
                      ? 'bg-emerald-50 dark:bg-emerald-950/20 text-emerald-600 dark:text-emerald-400 border border-emerald-100 dark:border-emerald-900/30'
                      : 'bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400'
                  }`}>
                    {project.status}
                  </span>
                </div>

                <div className="space-y-1">
                  <h3 className="font-bold text-lg text-slate-900 dark:text-white group-hover:text-primary-600 dark:group-hover:text-primary-400 transition truncate">
                    {project.name}
                  </h3>
                  <p className="text-sm text-slate-500 dark:text-slate-400 line-clamp-2 min-h-[40px]">
                    {project.description || 'No description provided.'}
                  </p>
                </div>
              </div>

              <div className="pt-6 mt-4 border-t border-slate-100 dark:border-slate-800/60 flex items-center justify-between text-xs text-slate-400 dark:text-slate-500">
                <div className="flex items-center space-x-1">
                  <Calendar className="w-3.5 h-3.5" />
                  <span>Updated {formatDate(project.updatedAt)}</span>
                </div>

                <Link
                  to={`/projects/${project.id}/overview`}
                  className="flex items-center space-x-1 text-primary-600 dark:text-primary-400 hover:text-primary-500 dark:hover:text-primary-300 font-semibold transition"
                >
                  <span>Open Project</span>
                  <ArrowRight className="w-3.5 h-3.5 transition group-hover:translate-x-0.5" />
                </Link>
              </div>
            </div>
          ))}
        </div>
      ) : (
        /* Empty State */
        <div className="flex flex-col items-center justify-center border border-dashed border-slate-300 dark:border-slate-800 rounded-2xl p-16 text-center bg-white/40 dark:bg-slate-900/20">
          <div className="p-4 bg-slate-100 dark:bg-slate-800/80 text-slate-400 rounded-2xl mb-6">
            <FolderKanban className="w-10 h-10" />
          </div>
          <h2 className="text-xl font-bold text-slate-900 dark:text-white mb-2">No projects yet</h2>
          <p className="text-sm text-slate-500 dark:text-slate-400 max-w-sm mb-8 leading-relaxed">
            Create a project to start analyzing your software engineering workspace.
          </p>
          <button
            onClick={() => setIsModalOpen(true)}
            className="flex items-center space-x-2 bg-primary-600 hover:bg-primary-500 text-white text-sm font-semibold px-5 py-3 rounded-lg shadow-sm transition"
          >
            <Plus className="w-4.5 h-4.5" />
            <span>Create Your First Project</span>
          </button>
        </div>
      )}

      {/* Creation Modal */}
      <CreateProjectModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        onProjectCreated={loadProjects}
      />
    </div>
  );
};
export default ProjectsHome;
