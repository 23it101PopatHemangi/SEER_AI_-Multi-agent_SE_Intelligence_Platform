import React, { useState, useEffect } from 'react';
import { X, Trello, AlertCircle, Check, RefreshCw } from 'lucide-react';
import { jiraService, JiraProjectOption } from '../services/jiraService';

interface SelectJiraProjectModalProps {
  isOpen: boolean;
  projectId: string;
  repositoryId?: string;
  userEmail: string;
  initialProjects?: JiraProjectOption[];
  onClose: () => void;
  onConnected: () => void;
}

export const SelectJiraProjectModal: React.FC<SelectJiraProjectModalProps> = ({
  isOpen,
  projectId,
  repositoryId,
  userEmail,
  initialProjects = [],
  onClose,
  onConnected,
}) => {
  const [projects, setProjects] = useState<JiraProjectOption[]>(initialProjects);
  const [selectedKey, setSelectedKey] = useState<string>('');
  const [loading, setLoading] = useState<boolean>(false);
  const [saving, setSaving] = useState<boolean>(false);
  const [statusText, setStatusText] = useState<string>('');
  const [error, setError] = useState<string | null>(null);

  // Manual key input fallback in case API returns empty
  const [manualKey, setManualKey] = useState<string>('');
  const [manualName, setManualName] = useState<string>('');
  const [showManualInput, setShowManualInput] = useState<boolean>(false);

  const fetchProjects = async () => {
    if (!userEmail) return;
    setLoading(true);
    setError(null);
    try {
      const projs = await jiraService.getAvailableProjects(userEmail);
      setProjects(projs);
      if (projs.length > 0 && !selectedKey) {
        setSelectedKey(projs[0].key);
      }
    } catch (err: any) {
      console.error('Error fetching Jira projects:', err);
      setError(err.message || 'Failed to fetch Jira projects from your Atlassian account.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      setError(null);
      if (initialProjects.length > 0) {
        setProjects(initialProjects);
        setSelectedKey(initialProjects[0].key);
      } else if (userEmail) {
        fetchProjects();
      }
    }
  }, [isOpen, userEmail, initialProjects]);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    let keyToConnect = selectedKey;
    let nameToConnect = '';
    let idToConnect: string | undefined = undefined;

    if (showManualInput || projects.length === 0) {
      if (!manualKey.trim()) {
        setError('Please enter a Jira project key (e.g. SEER).');
        return;
      }
      keyToConnect = manualKey.trim().toUpperCase();
      nameToConnect = manualName.trim() || keyToConnect;
    } else {
      const selected = projects.find((p) => p.key === selectedKey);
      if (!selected) {
        setError('Please select a Jira project from the list.');
        return;
      }
      keyToConnect = selected.key;
      nameToConnect = selected.name;
      idToConnect = selected.id;
    }

    setSaving(true);
    setStatusText('Connecting Jira project to SEER workspace...');

    try {
      const payload = {
        jira_project_key: keyToConnect,
        jira_project_name: nameToConnect,
        jira_project_id: idToConnect,
      };
      if (repositoryId) {
        await jiraService.connectRepository(projectId, repositoryId, payload, userEmail);
      } else {
        await jiraService.connectProject(projectId, payload, userEmail);
      }

      onConnected();
      onClose();
    } catch (err: any) {
      setError(err.message || 'Failed to connect Jira project.');
    } finally {
      setSaving(false);
      setStatusText('');
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/50 dark:bg-slate-950/70 backdrop-blur-sm">
      <div className="w-full max-w-lg bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl shadow-2xl overflow-hidden transition-colors duration-150">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-slate-800">
          <div className="flex items-center space-x-2">
            <div className="p-1.5 bg-blue-50 dark:bg-blue-950/30 text-blue-600 dark:text-blue-400 rounded-lg">
              <Trello className="w-5 h-5" />
            </div>
            <div>
              <h3 className="text-base font-bold text-slate-900 dark:text-white">
                {repositoryId ? 'Choose Jira Project for Repository' : 'Connect Jira Project'}
              </h3>
              <p className="text-[11px] text-slate-500 dark:text-slate-400">
                {repositoryId
                  ? 'Each repository must use its own Jira project.'
                  : 'Choose which Jira project to link to this SEER workspace'}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            disabled={saving}
            className="p-1 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition disabled:opacity-50"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Loading Spinner during Save */}
        {saving ? (
          <div className="p-12 flex flex-col items-center justify-center space-y-4">
            <div className="w-10 h-10 border-4 border-primary-500 border-t-transparent rounded-full animate-spin"></div>
            <p className="text-sm font-semibold text-slate-700 dark:text-slate-300 animate-pulse">
              {statusText}
            </p>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="p-6 space-y-5">
            {error && (
              <div className="flex items-start space-x-2.5 p-3 text-xs text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/20 border border-red-200 dark:border-red-800/50 rounded-lg">
                <AlertCircle className="w-4 h-4 shrink-0 text-red-500 mt-0.5" />
                <span>{error}</span>
              </div>
            )}

            {loading ? (
              <div className="py-8 flex flex-col items-center justify-center space-y-3">
                <RefreshCw className="w-6 h-6 text-primary-500 animate-spin" />
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  Fetching Jira projects from your Atlassian workspace...
                </p>
              </div>
            ) : !showManualInput && projects.length > 0 ? (
              <div className="space-y-3">
                <label className="text-xs font-bold uppercase tracking-wider text-slate-600 dark:text-slate-300">
                  Select Jira Project
                </label>
                <div className="max-h-56 overflow-y-auto space-y-2 pr-1">
                  {projects.map((proj) => {
                    const isSelected = selectedKey === proj.key;
                    return (
                      <div
                        key={proj.id || proj.key}
                        onClick={() => setSelectedKey(proj.key)}
                        className={`flex items-center justify-between p-3 rounded-lg border cursor-pointer transition ${
                          isSelected
                            ? 'border-primary-500 bg-primary-50/50 dark:bg-primary-950/20 text-slate-900 dark:text-white'
                            : 'border-slate-200 dark:border-slate-800 hover:border-slate-300 dark:hover:border-slate-700 text-slate-700 dark:text-slate-300'
                        }`}
                      >
                        <div className="flex items-center space-x-3 truncate">
                          {proj.avatar_url ? (
                            <img
                              src={proj.avatar_url}
                              alt=""
                              className="w-7 h-7 rounded object-cover shrink-0"
                            />
                          ) : (
                            <div className="w-7 h-7 bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 rounded flex items-center justify-center text-xs font-bold shrink-0">
                              {proj.key.substring(0, 2)}
                            </div>
                          )}
                          <div className="truncate">
                            <p className="text-xs font-bold truncate">{proj.name}</p>
                            <p className="text-[10px] text-slate-400 font-mono">
                              Key: {proj.key} &bull; Type: {proj.project_type_key || 'software'}
                            </p>
                          </div>
                        </div>

                        {isSelected && (
                          <div className="w-5 h-5 rounded-full bg-primary-600 text-white flex items-center justify-center shrink-0">
                            <Check className="w-3 h-3" />
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>

                <div className="pt-2 text-right">
                  <button
                    type="button"
                    onClick={() => setShowManualInput(true)}
                    className="text-[11px] font-semibold text-slate-500 dark:text-slate-400 hover:underline"
                  >
                    Enter custom project key manually &rarr;
                  </button>
                </div>
              </div>
            ) : (
              <div className="space-y-4">
                <div className="text-xs text-slate-500 dark:text-slate-400">
                  {projects.length === 0 && !loading
                    ? 'No Jira projects were found automatically on your connected site. You can enter your Jira project key directly:'
                    : 'Enter your Jira project details directly:'}
                </div>

                <div className="space-y-1.5">
                  <label className="text-xs font-bold text-slate-700 dark:text-slate-300">
                    Jira Project Key *
                  </label>
                  <input
                    type="text"
                    value={manualKey}
                    onChange={(e) => setManualKey(e.target.value.toUpperCase())}
                    placeholder="e.g. SEER, PROJ, DEV"
                    className="w-full px-3 py-2 text-xs font-mono bg-white dark:bg-slate-950 border border-slate-300 dark:border-slate-800 rounded-lg text-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
                    required
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="text-xs font-bold text-slate-700 dark:text-slate-300">
                    Project Display Name (Optional)
                  </label>
                  <input
                    type="text"
                    value={manualName}
                    onChange={(e) => setManualName(e.target.value)}
                    placeholder="e.g. SEER Core Development"
                    className="w-full px-3 py-2 text-xs bg-white dark:bg-slate-950 border border-slate-300 dark:border-slate-800 rounded-lg text-slate-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-primary-500"
                  />
                </div>

                {projects.length > 0 && (
                  <div className="pt-1">
                    <button
                      type="button"
                      onClick={() => setShowManualInput(false)}
                      className="text-[11px] font-semibold text-primary-600 dark:text-primary-400 hover:underline"
                    >
                      &larr; Back to project list
                    </button>
                  </div>
                )}
              </div>
            )}

            {/* Footer Buttons */}
            <div className="flex items-center justify-end space-x-3 pt-4 border-t border-slate-200 dark:border-slate-800">
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2 text-xs font-semibold text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg transition"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={loading || saving}
                className="px-4.5 py-2 text-xs font-bold text-white bg-primary-600 hover:bg-primary-500 rounded-lg shadow-sm transition disabled:opacity-50"
              >
                {repositoryId ? 'Connect Repository to Jira' : 'Connect Project'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
};

export default SelectJiraProjectModal;
